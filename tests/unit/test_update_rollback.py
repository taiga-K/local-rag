"""A Redis failure after a committed content update puts the old index back.

Principle: failure. A higher version with different blocks that cannot be
published must leave the previous version, chunk text, block graph, BM25
posting, and Qdrant point in place.
"""

from dataclasses import replace
from datetime import datetime, timezone

import redis
from fastapi.testclient import TestClient
from qdrant_client.http import models as qm

from kbindex.api import create_app
from kbindex.config import load_settings
from kbindex.db import record_id_for
from kbindex.qdrant_store import Vectors


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
            return _Result([{"id": 1, "auto_index": True, "max_upload_bytes": 8_000_000}])
        if "from knowledge_bases" in text:
            return _Result([{"id": params[0], "name": "kb"}])
        if "from records where record_id" in text and text.startswith("select"):
            row = store["records"].get(params[0])
            return _Result([row] if row else [])
        if "from chunks where record_id" in text and text.startswith("select"):
            return _Result([row for row in store["chunks"] if row["record_id"] == params[0]])
        if "from bm25_postings where chunk_id = any" in text:
            wanted = set(params[0])
            return _Result([row for row in store["postings"] if row["chunk_id"] in wanted])
        if "from blocks where record_id" in text and text.startswith("select"):
            return _Result([row for row in store["blocks"] if row["record_id"] == params[0]])
        if "from block_groups where record_id" in text and text.startswith("select"):
            return _Result([row for row in store["groups"] if row["record_id"] == params[0]])
        if "delete from bm25_postings" in text and "chunk_id in" in text:
            ids = {row["chunk_id"] for row in store["chunks"] if row["record_id"] == params[0]}
            store["postings"] = [row for row in store["postings"] if row["chunk_id"] not in ids]
            return _Result([])
        if text.startswith("delete from chunks where record_id"):
            store["chunks"] = [row for row in store["chunks"] if row["record_id"] != params[0]]
            return _Result([])
        if text.startswith("delete from blocks"):
            store["blocks"] = [row for row in store["blocks"] if row["record_id"] != params[0]]
            return _Result([])
        if text.startswith("delete from block_groups"):
            store["groups"] = [row for row in store["groups"] if row["record_id"] != params[0]]
            return _Result([])
        if text.startswith("delete from bm25_terms") or text.startswith("delete from bm25_stats"):
            return _Result([])
        if text.startswith("insert into bm25_terms") or text.startswith("insert into bm25_stats"):
            return _Result([])
        if text.startswith("update records set version") and "failure_reason = null" in text:
            names = (
                "version", "revision_id", "content_rev", "blocks_sha", "record_name",
                "source_modified_ms", "indexing_status", "raw_path", "stored_path",
            )
            row = store["records"][params[-1]]
            for name, value in zip(names, params[:-1], strict=True):
                row[name] = value
            row["failure_reason"] = None
            return _Result([])
        if text.startswith("update records set version"):
            names = (
                "version", "revision_id", "content_rev", "blocks_sha", "record_name",
                "source_modified_ms", "indexing_status", "failure_reason", "raw_path",
                "stored_path", "updated_at",
            )
            row = store["records"][params[-1]]
            for name, value in zip(names, params[:-1], strict=True):
                row[name] = value
            return _Result([])
        if text.startswith("insert into chunks"):
            keys = ("chunk_id", "record_id", "block_id", "block_index", "piece", "text", "token_count")
            store["chunks"].append(dict(zip(keys, params, strict=True)))
            return _Result([])
        if "unnest" in text and "insert into bm25_postings" in text:
            generations, tokenizers, terms, chunk_ids, tfs, doc_lens = params
            for generation, tokenizer, term, chunk_id, tf, doc_len in zip(
                generations, tokenizers, terms, chunk_ids, tfs, doc_lens, strict=True
            ):
                row = {
                    "generation": generation,
                    "tokenizer": tokenizer,
                    "term": term,
                    "chunk_id": chunk_id,
                    "tf": tf,
                    "doc_len": doc_len,
                }
                store["postings"] = [
                    item for item in store["postings"]
                    if not (
                        item["generation"] == row["generation"]
                        and item["tokenizer"] == row["tokenizer"]
                        and item["term"] == row["term"]
                        and item["chunk_id"] == row["chunk_id"]
                    )
                ]
                store["postings"].append(row)
            return _Result([])
        if text.startswith("insert into bm25_postings"):
            keys = ("generation", "tokenizer", "term", "chunk_id", "tf", "doc_len")
            row = dict(zip(keys, params, strict=True))
            store["postings"] = [
                item for item in store["postings"]
                if not (
                    item["generation"] == row["generation"]
                    and item["tokenizer"] == row["tokenizer"]
                    and item["term"] == row["term"]
                    and item["chunk_id"] == row["chunk_id"]
                )
            ]
            store["postings"].append(row)
            return _Result([])
        if text.startswith("insert into blocks"):
            keys = ("block_id", "record_id", "position", "parent_position", "group_position", "type", "text")
            store["blocks"].append(dict(zip(keys, params, strict=True)))
            return _Result([])
        if text.startswith("insert into block_groups"):
            keys = ("record_id", "position", "parent_position", "type", "name")
            store["groups"].append(dict(zip(keys, params, strict=True)))
            return _Result([])
        raise AssertionError(f"unhandled sql: {text} params={params!r}")

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


class _RedisPublishFails:
    def ping(self):
        return True

    def xadd(self, *_args, **_kwargs):
        raise redis.RedisError("down")


class _Engine:
    def fingerprint_mismatch(self):
        return False


class _Point:
    def __init__(self, point_id, record_id):
        self.id = point_id
        self.vector = {"dense": [0.1, 0.2]}
        self.payload = {"recordId": record_id}


class _Vectors:
    def __init__(self, points):
        self.points = list(points)

    def scroll_record(self, record_id):
        return [point for point in self.points if point.payload["recordId"] == record_id]

    def delete_record(self, record_id):
        self.points = [point for point in self.points if point.payload["recordId"] != record_id]

    def restore_points(self, points):
        self.points.extend(points)


def _store(record_id):
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    return {
        "records": {
            record_id: {
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
        },
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "record_id": record_id,
                "block_id": None,
                "block_index": 0,
                "piece": 0,
                "text": "本文",
                "token_count": 2,
            }
        ],
        "postings": [
            {
                "generation": 1,
                "tokenizer": "sudachi",
                "term": "本文",
                "chunk_id": "chunk-1",
                "tf": 1,
                "doc_len": 2,
            }
        ],
        "blocks": [
            {
                "block_id": "blk-1",
                "record_id": record_id,
                "position": 0,
                "parent_position": None,
                "group_position": None,
                "type": "text",
                "text": "旧",
            }
        ],
        "groups": [],
    }


def test_content_update_restores_chunks_and_points_when_publish_fails(tmp_path):
    record_id = record_id_for("kb", "doc-1")
    store = _store(record_id)
    vectors = _Vectors([_Point("p1", str(record_id))])
    settings = replace(load_settings(), data_dir=str(tmp_path))
    app = create_app(settings)
    app.router.on_startup.clear()
    app.state.db = _DB(store)
    app.state.redis = _RedisPublishFails()
    app.state.vectors = vectors
    app.state.engine = _Engine()
    body = {
        "recordName": "doc-1",
        "mimeType": "application/blocks",
        "externalRecordId": "doc-1",
        "version": 2,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": "新しい本文"}]},
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/kb/kb/records", json=body)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["reason"] == "REDIS_UNAVAILABLE"
    assert store["records"][record_id]["version"] == 1
    assert store["records"][record_id]["indexing_status"] == "COMPLETED"
    assert [row["text"] for row in store["chunks"]] == ["本文"]
    assert [row["term"] for row in store["postings"]] == ["本文"]
    assert [row["text"] for row in store["blocks"]] == ["旧"]
    assert [point.id for point in vectors.points] == ["p1"]


def test_content_update_stops_before_deleting_points_when_the_snapshot_fails(tmp_path):
    from kbindex.qdrant_store import QdrantUnavailable

    record_id = record_id_for("kb", "doc-1")
    store = _store(record_id)
    vectors = _Vectors([_Point("p1", str(record_id))])

    def boom(_record_id):
        raise QdrantUnavailable("scroll failed")

    vectors.scroll_record = boom
    settings = replace(load_settings(), data_dir=str(tmp_path))
    app = create_app(settings)
    app.router.on_startup.clear()
    app.state.db = _DB(store)
    app.state.redis = _RedisPublishFails()
    app.state.vectors = vectors
    app.state.engine = _Engine()
    body = {
        "recordName": "doc-1",
        "mimeType": "application/blocks",
        "externalRecordId": "doc-1",
        "version": 2,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": "新しい本文"}]},
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/kb/kb/records", json=body)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["reason"] == "QDRANT_UNAVAILABLE"
    assert store["records"][record_id]["version"] == 1
    assert [row["text"] for row in store["chunks"]] == ["本文"]
    assert [point.id for point in vectors.points] == ["p1"]


def test_snapshot_failure_puts_the_previous_payload_files_back(tmp_path):
    record_id = record_id_for("kb", "doc-1")
    folder = tmp_path / "kb"
    folder.mkdir()
    raw_path = folder / f"{record_id}.raw.json"
    stored_path = folder / f"{record_id}.stored.json"
    raw_path.write_bytes(b'{"version":1,"blocks":"old"}')
    stored_path.write_bytes(b'{"blocks":[{"data":"old"}]}')
    store = _store(record_id)
    store["records"][record_id]["raw_path"] = str(raw_path)
    store["records"][record_id]["stored_path"] = str(stored_path)
    vectors = _Vectors([_Point("p1", str(record_id))])

    def boom(_record_id):
        from kbindex.qdrant_store import QdrantUnavailable

        raise QdrantUnavailable("scroll failed")

    vectors.scroll_record = boom
    settings = replace(load_settings(), data_dir=str(tmp_path))
    app = create_app(settings)
    app.router.on_startup.clear()
    app.state.db = _DB(store)
    app.state.redis = _RedisPublishFails()
    app.state.vectors = vectors
    app.state.engine = _Engine()
    body = {
        "recordName": "doc-1",
        "mimeType": "application/blocks",
        "externalRecordId": "doc-1",
        "version": 2,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": "新しい本文"}]},
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/kb/kb/records", json=body)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["reason"] == "QDRANT_UNAVAILABLE"
    assert raw_path.read_bytes() == b'{"version":1,"blocks":"old"}'
    assert stored_path.read_bytes() == b'{"blocks":[{"data":"old"}]}'
    assert store["records"][record_id]["version"] == 1
    assert [row["text"] for row in store["chunks"]] == ["本文"]


def test_restore_points_upserts_a_dense_named_vector():
    saved = []

    class Client:
        def upsert(self, *, collection_name, points):
            saved.append((collection_name, points))

    vectors = Vectors.__new__(Vectors)
    vectors.client = Client()
    point = _Point("p1", "r")
    point.vector = {"dense": [0.25, 0.5]}
    vectors.restore_points([point])
    assert saved[0][0] == "chunks"
    got = saved[0][1][0]
    assert isinstance(got, qm.PointStruct)
    assert got.vector == {"dense": [0.25, 0.5]}
