"""A Redis failure around a full reindex must not leave the index empty.

Principle: failure. If Redis is already down, reindex does not run. If the
wipe runs and publish then fails, points, chunks, postings, and the previous
statuses come back, and the response is 503.
"""

import redis
from fastapi.testclient import TestClient
from qdrant_client.http import models as qm

from kbindex.api import create_app
from kbindex.config import load_settings
from kbindex.embed import FakeEmbedder
from kbindex.pipeline import Engine
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
        if text.startswith("update records") and "indexing_status = 'QUEUED'" in text:
            for row in store["records"]:
                if row["indexing_status"] != "EMPTY":
                    row["indexing_status"] = "QUEUED"
                    row["failure_reason"] = None
            return _Result([])
        if text.startswith("update records") and "indexing_status = %s" in text:
            status, reason, record_id = params
            for row in store["records"]:
                if row["record_id"] == record_id:
                    row["indexing_status"] = status
                    row["failure_reason"] = reason
            return _Result([])
        if "delete from bm25_postings" in text:
            store["postings"] = []
            return _Result([])
        if text.startswith("delete from chunks"):
            store["chunks"] = []
            return _Result([])
        if text.startswith("delete from bm25_terms") or text.startswith("delete from bm25_stats"):
            return _Result([])
        if text.startswith("insert into bm25_terms") or text.startswith("insert into bm25_stats"):
            return _Result([])
        if text.startswith("insert into index_generation"):
            fingerprint, model, dimension, max_seq, keyword_json, fusion_json = params
            store["generation"] = {
                "fingerprint": fingerprint,
                "model": model,
                "dimension": dimension,
                "max_seq_length": max_seq,
                "keyword_json": keyword_json,
                "fusion_json": fusion_json,
            }
            return _Result([])
        if "from index_generation" in text:
            row = store.get("generation")
            return _Result([row] if row else [])
        if text.startswith("insert into chunks"):
            keys = ("chunk_id", "record_id", "block_id", "block_index", "piece", "text", "token_count")
            store["chunks"].append(dict(zip(keys, params, strict=True)))
            return _Result([])
        if text.startswith("insert into bm25_postings"):
            keys = ("generation", "tokenizer", "term", "chunk_id", "tf", "doc_len")
            store["postings"].append(dict(zip(keys, params, strict=True)))
            return _Result([])
        if text.startswith("select") and "from records where indexing_status = 'QUEUED'" in text:
            return _Result([row for row in store["records"] if row["indexing_status"] == "QUEUED"])
        if text.startswith("select") and "from records" in text:
            return _Result(store["records"])
        if text.startswith("select") and "from chunks" in text:
            return _Result(store["chunks"])
        if text.startswith("select") and "from bm25_postings" in text:
            return _Result(store["postings"])
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


class _RedisDown:
    def ping(self):
        raise redis.RedisError("down")


class _RedisPublishFails:
    def ping(self):
        return True

    def xadd(self, *_args, **_kwargs):
        raise redis.RedisError("down")


class _Point:
    def __init__(self, point_id, record_id):
        self.id = point_id
        self.vector = {"dense": [0.1, 0.2]}
        self.payload = {"recordId": record_id}


class _Vectors:
    def __init__(self, points):
        self.points = list(points)

    def drop(self):
        self.drops = getattr(self, "drops", 0) + 1
        self.points = []

    def ensure(self, dim):
        self.ensured = getattr(self, "ensured", [])
        self.ensured.append(dim)

    def count(self):
        return len(self.points)

    def scroll_all(self):
        return list(self.points)

    def restore_points(self, points):
        self.points.extend(points)


def test_old_full_reindex_route_is_gone():
    """Config A replaced POST /api/v1/index/reindex with the flag-gated vector-store routes."""
    app = create_app()
    app.router.on_startup.clear()
    app.state.db = _DB({"records": [], "chunks": [], "postings": []})
    app.state.redis = _RedisDown()
    with TestClient(app) as client:
        response = client.post("/api/v1/index/reindex")
    assert response.status_code == 404, response.text


def test_restore_index_accepts_a_generation_with_null_dimension():
    """Nullable dimension and max_seq_length must not abort rollback after the drop."""
    settings = load_settings()
    store = {
        "records": [
            {"record_id": "r1", "indexing_status": "QUEUED", "failure_reason": "wiped"},
        ],
        "chunks": [],
        "postings": [],
        "generation": None,
    }
    vectors = _Vectors([])
    engine = Engine(settings, _DB(store), vectors, FakeEmbedder())
    engine.embedder.dim = 8
    chunk = {
        "chunk_id": "chunk-1",
        "record_id": "r1",
        "block_id": None,
        "block_index": 0,
        "piece": 0,
        "text": "本文",
        "token_count": 2,
    }
    engine.restore_index(
        {
            "points": [_Point("p1", "r1")],
            "chunks": [chunk],
            "postings": [],
            "statuses": [{"record_id": "r1", "indexing_status": "COMPLETED", "failure_reason": None}],
            "generation": {
                "fingerprint": "old-fp",
                "model": "cl-nagoya/ruri-v3-310m",
                "dimension": None,
                "max_seq_length": None,
                "keyword_json": {"tokenizers": ["sudachi"]},
                "fusion_json": {"method": "rrf", "k": 60},
            },
        }
    )
    assert store["generation"]["fingerprint"] == "old-fp"
    assert store["generation"]["dimension"] is None
    assert store["generation"]["max_seq_length"] is None
    assert [row["text"] for row in store["chunks"]] == ["本文"]
    assert store["records"][0]["indexing_status"] == "COMPLETED"
    assert store["records"][0]["failure_reason"] is None
    assert [point.id for point in vectors.points] == ["p1"]
    assert vectors.ensured == [8]


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
