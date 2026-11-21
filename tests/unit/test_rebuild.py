"""Model change and vector-store rebuild follow PipesHub, not a fingerprint."""

import os

import pytest
import redis
from fastapi.testclient import TestClient

from kbindex.api import create_app
from kbindex.chunking import Piece
from kbindex.config import load_settings
from kbindex.embed import FakeEmbedder
from kbindex.pipeline import Engine
from kbindex.qdrant_store import QdrantUnavailable


class _Vectors:
    def __init__(self, count: int = 0, fail_count: bool = False, fail_ensure: bool = False):
        self.count_value = count
        self.fail_count = fail_count
        self.fail_ensure = fail_ensure
        self.dropped = 0
        self.ensured: list[int] = []
        self.points = count

    def count(self):
        if self.fail_count:
            raise QdrantUnavailable("down")
        return self.count_value

    def drop(self):
        self.dropped += 1
        self.points = 0
        self.count_value = 0

    def ensure(self, dim: int):
        if self.fail_ensure:
            raise QdrantUnavailable("create failed")
        self.ensured.append(dim)
        self.points = 0

    def ping(self):
        return True

    def search(self, *_args, **_kwargs):
        return []


class _Conn:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        if "from app_settings" in text:
            settings = self.store.setdefault("settings", {"id": 1, "requested_model": None})
            return _Result([settings])
        if text.startswith("update app_settings set requested_model"):
            self.store.setdefault("settings", {"id": 1})["requested_model"] = params[0]
            return _Result([])
        if text.startswith("select 1 from records where indexing_status"):
            blocked = bool(self.store.get("busy")) or (bool(self.store.get("queued_block")) and "QUEUED" in text)
            return _Result([{"one": 1}] if blocked else [])
        if text.startswith("update records set indexing_status = 'NOT_STARTED'"):
            self.store["status"] = "NOT_STARTED"
            if "has_indexed_copy" in text:
                self.store["has_indexed_copy"] = False
            return _Result([])
        if "delete from bm25_postings" in text:
            self.store["postings"] = []
            return _Result([])
        if text.startswith("delete from bm25_terms") or text.startswith("delete from bm25_stats"):
            return _Result([])
        if text.startswith("delete from chunks"):
            self.store["chunks"] = []
            return _Result([])
        if text.startswith("update records") and "QUEUED" in text:
            return _Result([])
        if "from records where indexing_status = 'QUEUED'" in text:
            return _Result(self.store["queued"])
        return _Result([])

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, store):
        self.store = store

    def ping(self):
        return True

    def connect(self):
        return _Conn(self.store)


class _Redis:
    def __init__(self, held=False):
        self.held = held
        self.deleted = 0

    def ping(self):
        return True

    def set(self, *_args, **_kwargs):
        if self.held:
            return False
        self.held = True
        return True

    def delete(self, *_args):
        self.deleted += 1
        self.held = False
        return 1

    def xadd(self, *_args, **_kwargs):
        return "1-0"


class _Engine:
    def __init__(self, rows):
        self.rows = rows
        self.dim = 32

    def queue_reindex(self):
        return self.rows


def _app(vectors, store, redis_client, monkeypatch, enabled="true"):
    monkeypatch.setenv("ENABLE_VECTOR_STORE_REBUILD", enabled)
    app = create_app()
    app.router.on_startup.clear()
    app.state.db = _DB(store)
    app.state.redis = redis_client
    app.state.vectors = vectors
    app.state.embedder = _Engine([])
    app.state.embedder.dim = 32
    app.state.engine = _Engine(store["queued"])
    return TestClient(app)


def test_model_change_is_refused_while_points_remain(monkeypatch):
    vectors = _Vectors(count=3)
    with _app(vectors, {"busy": False, "queued": []}, _Redis(), monkeypatch) as client:
        response = client.put("/api/v1/engineer/embedding", json={"model": "other", "dimension": 64})
    assert response.status_code == 400
    assert vectors.dropped == 0


def test_model_change_recreates_an_empty_collection(monkeypatch):
    vectors = _Vectors(count=0)
    with _app(vectors, {"busy": False, "queued": []}, _Redis(), monkeypatch) as client:
        response = client.put("/api/v1/engineer/embedding", json={"model": "other", "dimension": 64})
    assert response.status_code == 200, response.text
    assert vectors.dropped == 1
    assert vectors.ensured == [64]
    assert response.json()["restartRequired"] is True


def test_selecting_the_running_model_clears_a_pending_request(monkeypatch):
    vectors = _Vectors(count=0)
    store = {"busy": False, "queued": []}
    with _app(vectors, store, _Redis(), monkeypatch) as client:
        changed = client.put("/api/v1/engineer/embedding", json={"model": "other", "dimension": 64})
        assert changed.status_code == 200
        running = client.app.state.settings.model
        cleared = client.put("/api/v1/engineer/embedding", json={"model": running, "dimension": 32})
    assert cleared.status_code == 200
    assert cleared.json()["restartRequired"] is False
    assert store["settings"]["requested_model"] is None
    assert vectors.dropped == 2
    assert vectors.ensured == [64, 32]


def test_selecting_the_running_model_leaves_an_existing_collection(monkeypatch):
    vectors = _Vectors(count=3)
    with _app(vectors, {"busy": False, "queued": []}, _Redis(), monkeypatch) as client:
        response = client.put(
            "/api/v1/engineer/embedding",
            json={"model": client.app.state.settings.model, "dimension": 32},
        )
    assert response.status_code == 200
    assert vectors.dropped == 0


def test_model_change_is_not_saved_when_recreate_fails(monkeypatch):
    vectors = _Vectors(count=0, fail_ensure=True)
    with _app(vectors, {"busy": False, "queued": []}, _Redis(), monkeypatch) as client:
        response = client.put("/api/v1/engineer/embedding", json={"model": "other", "dimension": 64})
    assert response.status_code == 503
    assert not hasattr(client.app.state, "requested_model") or client.app.state.requested_model != "other"


def test_model_change_fails_closed_when_the_count_cannot_be_read(monkeypatch):
    vectors = _Vectors(fail_count=True)
    with _app(vectors, {"busy": False, "queued": []}, _Redis(), monkeypatch) as client:
        response = client.put("/api/v1/engineer/embedding", json={"model": "other", "dimension": 64})
    assert response.status_code == 503
    assert vectors.dropped == 0


def test_cleanup_is_disabled_when_the_flag_is_off(monkeypatch):
    with _app(_Vectors(), {"busy": False, "queued": []}, _Redis(), monkeypatch, enabled="false") as client:
        response = client.post("/api/v1/connectors/vector-store/cleanup")
    assert response.status_code == 403
    assert response.json()["error"]["reason"] == "REBUILD_DISABLED"


def test_cleanup_is_409_while_ingest_is_running(monkeypatch):
    with _app(_Vectors(), {"busy": True, "queued": []}, _Redis(), monkeypatch) as client:
        response = client.post("/api/v1/connectors/vector-store/cleanup")
    assert response.status_code == 409


def test_cleanup_drops_the_collection_and_marks_records_not_started(monkeypatch):
    store = {"busy": False, "queued": [], "status": "COMPLETED"}
    vectors = _Vectors(count=4)
    with _app(vectors, store, _Redis(), monkeypatch) as client:
        response = client.post("/api/v1/connectors/vector-store/cleanup")
    assert response.status_code == 202, response.text
    assert vectors.points == 0
    assert vectors.ensured == [32]
    assert store["status"] == "NOT_STARTED"
    assert vectors.search("q", limit=10, kb_ids=None) == []


def test_cleanup_drops_keyword_rows_and_the_indexed_copy(monkeypatch):
    store = {
        "busy": False,
        "queued": [],
        "status": "COMPLETED",
        "has_indexed_copy": True,
        "chunks": ["c1"],
        "postings": ["p1"],
    }
    with _app(_Vectors(count=2), store, _Redis(), monkeypatch) as client:
        response = client.post("/api/v1/connectors/vector-store/cleanup")
    assert response.status_code == 202, response.text
    assert store["chunks"] == []
    assert store["postings"] == []
    assert store["has_indexed_copy"] is False
    assert store["status"] == "NOT_STARTED"


def test_queued_rows_can_be_wiped_or_republished(monkeypatch):
    """QUEUED with no running rebuild is a stuck queue, not a live sync."""
    store = {"busy": False, "queued_block": True, "queued": [], "status": "QUEUED"}
    vectors = _Vectors(count=2)
    redis_client = _Redis()
    with _app(vectors, store, redis_client, monkeypatch) as client:
        cleanup = client.post("/api/v1/connectors/vector-store/cleanup")
        reindex = client.post("/api/v1/connectors/vector-store/reindex")
    assert cleanup.status_code == 202, cleanup.text
    assert vectors.dropped == 1
    assert reindex.status_code == 202, reindex.text


def test_reindex_holds_the_lock_so_cleanup_cannot_start(monkeypatch):
    redis = _Redis()
    store = {
        "busy": False,
        "queued": [{
            "record_id": "r1",
            "kb_id": "kb",
            "external_record_id": "doc",
            "version": 1,
            "content_rev": "c",
        }],
        "status": "COMPLETED",
    }
    vectors = _Vectors(count=1)
    with _app(vectors, store, redis, monkeypatch) as client:
        started = client.post("/api/v1/connectors/vector-store/reindex")
        assert started.status_code == 202, started.text
        cleanup = client.post("/api/v1/connectors/vector-store/cleanup")
    assert redis.deleted == 0
    assert cleanup.status_code == 409
    assert cleanup.json()["error"]["reason"] == "REBUILD_RUNNING"
    assert vectors.dropped == 0


def test_publish_failure_does_not_stick_the_rebuild_lock(monkeypatch):
    class _RedisFailsOnce(_Redis):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def xadd(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise redis.RedisError("down")
            return "1-0"

    redis_client = _RedisFailsOnce()
    store = {
        "busy": False,
        "queued": [{
            "record_id": "r1",
            "kb_id": "kb",
            "external_record_id": "doc",
            "version": 1,
            "content_rev": "c",
        }],
        "status": "QUEUED",
    }
    with _app(_Vectors(), store, redis_client, monkeypatch) as client:
        failed = client.post("/api/v1/connectors/vector-store/reindex")
        assert failed.status_code == 503, failed.text
        assert failed.json()["error"]["reason"] == "REDIS_UNAVAILABLE"
        store["queued_block"] = True
        retried = client.post("/api/v1/connectors/vector-store/reindex")
    assert retried.status_code == 202, retried.text


def test_worker_does_not_claim_a_not_started_record():
    seen: list[str] = []

    class Conn:
        def execute(self, sql, _params=None):
            seen.append(" ".join(sql.split()))

            class Rows:
                def fetchone(self):
                    return None

            return Rows()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class DB:
        def connect(self):
            return Conn()

    engine = Engine(load_settings(), DB(), None, FakeEmbedder())
    assert engine.index_record("kb", "doc-1", event_version=1, event_rev="rev") == "stale"
    assert "NOT_STARTED" not in seen[0]


def test_finish_does_not_refill_a_collection_after_cleanup(monkeypatch):
    """A QUEUED event that finishes after cleanup must not write points or COMPLETED."""
    monkeypatch.setattr("kbindex.pipeline.document_weights", lambda _text: [("1", 1.0)])
    upserts: list = []

    class Vectors:
        def delete_record(self, _record_id):
            return None

        def ensure(self, _dim):
            return None

        def upsert(self, points, expected_dim=None):
            upserts.append(points)

    class Result:
        def __init__(self, row):
            self._row = row
            self.rowcount = 1

        def fetchone(self):
            return self._row

    class Conn:
        def __init__(self):
            self.completed = False

        def execute(self, sql, _params=None):
            text = " ".join(sql.split())
            if text.startswith("select") and "from records" in text:
                return Result({"version": 1, "content_rev": "rev", "indexing_status": "NOT_STARTED"})
            if "indexing_status = 'COMPLETED'" in text:
                self.completed = True
            return Result(None)

        def commit(self):
            return None

        def rollback(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    conn = Conn()

    class DB:
        def connect(self):
            return conn

    engine = Engine(load_settings(), DB(), Vectors(), FakeEmbedder())
    engine.embedder.dim = 2
    result = engine._finish_chunks(
        "rid",
        "kb",
        {"record_name": "doc", "source_modified_ms": None},
        [Piece(0, 0, "本文", 2)],
        [[0.1, 0.2]],
        1,
        "rev",
        {"blocks": []},
    )
    assert result == "stale"
    assert upserts == []
    assert conn.completed is False


def test_upsert_rejects_a_vector_of_the_wrong_dimension():
    from kbindex.qdrant_store import Vectors
    from qdrant_client.http import models as qm

    vectors = Vectors.__new__(Vectors)
    point = qm.PointStruct(id="p", vector={"dense": [0.1, 0.2]}, payload={})
    with pytest.raises(QdrantUnavailable):
        vectors.upsert([point], expected_dim=3)
