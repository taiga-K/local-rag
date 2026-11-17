"""Redis Streams consumer. A redelivery reads the current row and ends in the same state."""

from __future__ import annotations

import time

import psycopg
import redis

from kbindex.config import load_settings
from kbindex.db import Database, rebuild_bm25, record_id_for, record_row, recover_in_progress
from kbindex.embed import load_embedder
from kbindex.pipeline import Engine
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.stream import GROUP, STREAM, ensure_group, publish, read_event

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
    ensure_group(client)
    engine.ensure_generation()
    _recover(db, client)
    while True:
        for cursor in ("0", ">"):
            found = client.xreadgroup(GROUP, CONSUMER, {STREAM: cursor}, count=8, block=2000 if cursor == ">" else 1)
            if not found:
                continue
            for _stream, messages in found:
                for message_id, fields in messages:
                    _handle(engine, db, client, message_id, fields)


def _recover(db: Database, client) -> None:
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
        )


def _handle(engine: Engine, db: Database, client, message_id: str, fields: dict) -> None:
    event = read_event(fields)
    if event["eventType"] == "deleteRecord":
        _delete(engine, db, event)
        client.xack(STREAM, GROUP, message_id)
        return
    if not event["kbId"] or not event["externalRecordId"]:
        client.xack(STREAM, GROUP, message_id)
        return
    if engine.fingerprint_mismatch():
        client.xack(STREAM, GROUP, message_id)
        return
    with db.connect() as conn:
        row = conn.execute(
            "select version, content_rev from records where kb_id = %s and external_record_id = %s",
            (event["kbId"], event["externalRecordId"]),
        ).fetchone()
    if row is None:
        _delete_points(engine, db, event["recordId"])
        client.xack(STREAM, GROUP, message_id)
        return
    if event["version"] < int(row["version"]):
        client.xack(STREAM, GROUP, message_id)
        return
    try:
        engine.index_record(
            event["kbId"],
            event["externalRecordId"],
            event_version=event["version"],
            event_rev=event["contentRev"] or row["content_rev"],
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
    client.xack(STREAM, GROUP, message_id)


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
        conn.execute("delete from bm25_postings where chunk_id like %s", (record_id + ":%",))
        rebuild_bm25(conn)
        conn.commit()
