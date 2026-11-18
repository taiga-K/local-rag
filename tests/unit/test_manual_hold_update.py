"""Manual hold is for a new text record. A content update stays QUEUED.

Principle: state. autoIndex off must not turn an already indexed record into
AUTO_INDEX_OFF after the push deletes its chunks, or the worker never puts
the text back.
"""

from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from kbindex.api import create_app
from kbindex.config import load_settings
from kbindex.db import record_id_for


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return [dict(row) for row in self._rows]

    def fetchone(self):
        if not self._rows:
            return None
        return dict(self._rows[0])


class _Conn:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        params = params or ()
        store = self.store
        if text.startswith("select pg_advisory"):
            return _Result([])
        if "from app_settings" in text:
            return _Result([store["settings"]])
        if "from knowledge_bases" in text:
            return _Result([{"id": params[0], "name": "kb"}])
        if "from records where record_id" in text and text.startswith("select"):
            row = store["records"].get(params[0])
            return _Result([row] if row else [])
        if "from chunks where record_id" in text and text.startswith("select"):
            return _Result([row for row in store["chunks"] if row["record_id"] == params[0]])
        if "from bm25_postings where chunk_id = any" in text:
            return _Result(store.get("postings") or [])
        if "from blocks where record_id" in text and text.startswith("select"):
            return _Result([])
        if "from block_groups where record_id" in text and text.startswith("select"):
            return _Result([])
        if text.startswith("insert into records"):
            keys = (
                "record_id", "kb_id", "external_record_id", "version", "revision_id",
                "content_rev", "blocks_sha", "record_name", "source_modified_ms",
                "indexing_status", "raw_path", "stored_path",
            )
            row = dict(zip(keys, params, strict=True))
            row["failure_reason"] = None
            store["records"][row["record_id"]] = row
            return _Result([])
        if text.startswith("update records set version") and "indexing_status = %s" in text:
            names = (
                "version", "revision_id", "content_rev", "blocks_sha", "record_name",
                "source_modified_ms", "indexing_status", "raw_path", "stored_path",
            )
            row = store["records"][params[-1]]
            for name, value in zip(names, params[:-1], strict=True):
                row[name] = value
            row["failure_reason"] = None
            return _Result([])
        if text.startswith("delete from bm25_postings"):
            ids = {row["chunk_id"] for row in store["chunks"] if row["record_id"] == params[0]}
            store["postings"] = [row for row in store["postings"] if row["chunk_id"] not in ids]
            return _Result([])
        if text.startswith("delete from chunks"):
            store["chunks"] = [row for row in store["chunks"] if row["record_id"] != params[0]]
            return _Result([])
        if text.startswith("delete from blocks") or text.startswith("delete from block_groups"):
            return _Result([])
        if text.startswith("delete from bm25_terms") or text.startswith("delete from bm25_stats"):
            return _Result([])
        if text.startswith("insert into bm25_terms") or text.startswith("insert into bm25_stats"):
            return _Result([])
        if text.startswith("insert into blocks") or text.startswith("insert into block_groups"):
            return _Result([])
        raise AssertionError(f"unhandled sql: {text}")

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DB:
    def __init__(self, store):
        self.store = store

    def ping(self):
        return True

    def connect(self):
        return _Conn(self.store)


class _Redis:
    def __init__(self):
        self.events: list[str] = []

    def ping(self):
        return True

    def xadd(self, _stream, fields):
        self.events.append(fields["eventType"])
        return "1-0"


class _Engine:
    def fingerprint_mismatch(self):
        return False


class _Vectors:
    def delete_record(self, _record_id):
        return None

    def scroll_record(self, _record_id):
        return []


def _settings_row():
    return {"id": 1, "auto_index": False, "max_upload_bytes": 8_000_000, "include_subfolders": True, "folders": []}


def _record(record_id):
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    return {
        "record_id": record_id,
        "kb_id": "kb",
        "external_record_id": "doc-1",
        "version": 1,
        "revision_id": "v1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:1",
        "content_rev": "c1",
        "blocks_sha": "b1",
        "record_name": "doc-1",
        "source_modified_ms": None,
        "indexing_status": "COMPLETED",
        "failure_reason": None,
        "raw_path": None,
        "stored_path": None,
        "created_at": now,
        "updated_at": now,
    }


def _app(tmp_path, store, redis):
    settings = replace(load_settings(), data_dir=str(tmp_path))
    app = create_app(settings)
    app.router.on_startup.clear()
    app.state.db = _DB(store)
    app.state.redis = redis
    app.state.vectors = _Vectors()
    app.state.engine = _Engine()
    return app


def test_content_update_stays_queued_when_auto_index_is_off(tmp_path):
    record_id = record_id_for("kb", "doc-1")
    redis = _Redis()
    store = {
        "settings": _settings_row(),
        "records": {record_id: _record(record_id)},
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "record_id": record_id,
                "text": "本文",
            }
        ],
        "postings": [],
    }
    body = {
        "recordName": "doc-1",
        "mimeType": "application/blocks",
        "externalRecordId": "doc-1",
        "version": 2,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": "新しい本文"}]},
    }
    with TestClient(_app(tmp_path, store, redis)) as client:
        response = client.post("/api/v1/kb/kb/records", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["indexingStatus"] == "QUEUED"
    assert response.json()["event"] == "updateRecord"
    assert redis.events == ["updateRecord"]
    assert store["records"][record_id]["indexing_status"] == "QUEUED"


def test_new_text_record_stays_on_manual_hold(tmp_path):
    redis = _Redis()
    store = {"settings": _settings_row(), "records": {}, "chunks": [], "postings": []}
    body = {
        "recordName": "保留",
        "mimeType": "application/blocks",
        "externalRecordId": "held",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": "まだ索引しない。"}]},
    }
    with TestClient(_app(tmp_path, store, redis)) as client:
        response = client.post("/api/v1/kb/kb/records", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["indexingStatus"] == "AUTO_INDEX_OFF"
    assert response.json()["event"] is None
    assert redis.events == []
