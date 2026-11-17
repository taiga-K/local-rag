"""Redis Streams consumer. Re-reads the row and converges."""

from __future__ import annotations

import json
import time

import redis

from kbindex.api import GROUP, STREAM
from kbindex.db import Database
from kbindex.embed import load_embedder
from kbindex.pipeline import Engine
from kbindex.qdrant_store import Vectors
from kbindex.settings import load_settings


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_url)
    db.migrate()
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    vectors = Vectors(settings.qdrant_url)
    embedder = load_embedder(settings.backend, settings.model, settings.device)
    engine = Engine(settings, db, vectors, embedder)
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    with db.connect() as conn:
        conn.execute("update records set indexing_status = 'QUEUED' where indexing_status = 'IN_PROGRESS'")
        conn.commit()
    if not engine.model_change_blocked():
        engine.ensure_generation()
    while True:
        found = client.xreadgroup(GROUP, "worker", {STREAM: ">"}, count=4, block=2000)
        if not found:
            continue
        for _stream, messages in found:
            for message_id, fields in messages:
                _handle(engine, client, message_id, fields)


def _handle(engine: Engine, client, message_id: str, fields: dict) -> None:
    if engine.model_change_blocked():
        return
    payload = json.loads(fields.get("payload") or "{}")
    event = fields.get("eventType")
    if event == "deleteRecord":
        engine.vectors.delete_record(payload.get("recordId", ""))
        client.xack(STREAM, GROUP, message_id)
        return
    kb_id = payload.get("kbId")
    external = payload.get("externalRecordId")
    if not kb_id or not external:
        client.xack(STREAM, GROUP, message_id)
        return
    with engine.db.connect() as conn:
        row = conn.execute(
            "select version from records where kb_id = %s and external_record_id = %s",
            (kb_id, external),
        ).fetchone()
    if row is None:
        client.xack(STREAM, GROUP, message_id)
        return
    if int(payload.get("version") or 0) < int(row["version"]) and event != "reindexRecord":
        client.xack(STREAM, GROUP, message_id)
        return
    engine.index_record(kb_id, external)
    client.xack(STREAM, GROUP, message_id)


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception:
            time.sleep(2)
            raise
