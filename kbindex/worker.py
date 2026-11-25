"""Redis Streams consumer. A redelivery reads the current row and ends in the same state."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import psycopg
import redis

from kbindex.config import load_settings
from kbindex.db import Database, app_settings_row, delete_postings, record_id_for, record_row, recover_in_progress
from kbindex.ingest_ui import pause_is_active
from kbindex.embed import load_embedder
from kbindex.pipeline import Engine
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.stream import GROUP, ensure_group, publish, read_event, stream_names

CONSUMER = "worker"


def main() -> None:
    while True:
        try:
            _run()
        except (redis.RedisError, psycopg.OperationalError, OSError):
            time.sleep(2)


def _run() -> None:
    settings = load_settings()
    db = Database(settings.database_url)
    db.migrate()
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    vectors = Vectors(settings.qdrant_url)
    embedder = load_embedder(settings.backend, settings.model, settings.device)
    engine = Engine(settings, db, vectors, embedder)
    ensure_group(client, settings.redis_lanes)
    engine.ensure_generation()
    _recover(db, client, settings.redis_lanes)
    streams = stream_names(settings.redis_lanes)
    while True:
        for cursor in ("0", ">"):
            found = client.xreadgroup(
                GROUP,
                CONSUMER,
                {name: cursor for name in streams},
                count=8,
                block=2000 if cursor == ">" else 1,
            )
            if not found:
                continue
            for stream_name, messages in found:
                for message_id, fields in messages:
                    _handle(engine, db, client, stream_name, message_id, fields)


def _recover(db: Database, client, lanes: int) -> None:
    with db.connect() as conn:
        rows = recover_in_progress(conn)
        conn.commit()
    for row in rows:
        publish(
            client,
            "reindexRecord",
            record_id=str(row["record_id"]),
            kb_id=row["kb_id"],
            external_record_id=row["external_record_id"],
            version=int(row["version"]),
            content_rev=row["content_rev"] or "",
            lanes=lanes,
            crash_retries=int(row["crash_retries"]),
        )


def _ingest_paused(db: Database) -> bool:
    with db.connect() as conn:
        row = app_settings_row(conn)
    return pause_is_active(row.get("pause_kind"), row.get("pause_until"), datetime.now(timezone.utc))


def _handle(engine: Engine, db: Database, client, stream_name: str, message_id: str, fields: dict) -> None:
    event = read_event(fields)
    if event["eventType"] == "deleteRecord":
        _delete(engine, db, event)
        client.xack(stream_name, GROUP, message_id)
        return
    if _ingest_paused(db):
        time.sleep(1)
        return
    if not event["kbId"] or not event["externalRecordId"]:
        client.xack(stream_name, GROUP, message_id)
        return
    with db.connect() as conn:
        row = conn.execute(
            "select version, content_rev from records where kb_id = %s and external_record_id = %s",
            (event["kbId"], event["externalRecordId"]),
        ).fetchone()
    if row is None:
        _delete_points(engine, db, event["recordId"])
        client.xack(stream_name, GROUP, message_id)
        return
    if event["version"] < int(row["version"]):
        client.xack(stream_name, GROUP, message_id)
        return
    try:
        engine.index_record(
            event["kbId"],
            event["externalRecordId"],
            event_version=event["version"],
            event_rev=event["contentRev"] or row["content_rev"],
            event_crash_retries=event["crashRetries"],
        )
    except psycopg.OperationalError:
        time.sleep(1)
        return
    except QdrantUnavailable:
        engine._fail(
            record_id_for(event["kbId"], event["externalRecordId"]),
            event["version"],
            event["contentRev"] or row["content_rev"],
            "QDRANT_UNAVAILABLE",
        )
    client.xack(stream_name, GROUP, message_id)


def _delete(engine: Engine, db: Database, event: dict) -> None:
    with db.connect() as conn:
        row = record_row(conn, event["recordId"]) if event["recordId"] else None
        if row is not None and int(row["version"]) > event["version"]:
            return
        if row is not None:
            return
    _delete_points(engine, db, event["recordId"])


def _delete_points(engine: Engine, db: Database, record_id: str) -> None:
    if not record_id:
        return
    try:
        engine.vectors.delete_record(record_id)
    except QdrantUnavailable:
        return
    with db.connect() as conn:
        delete_postings(conn, "chunk_id like %s", (record_id + ":%",))
        conn.commit()
