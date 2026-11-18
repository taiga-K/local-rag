"""Model change and vector-store rebuild follow PipesHub, not a fingerprint."""

import os

import pytest
from fastapi.testclient import TestClient

from kbindex.api import create_app
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
        if "indexing_status = 'IN_PROGRESS'" in text and text.startswith("select"):
            return _Result([{"one": 1}] if self.store["busy"] else [])
        if text.startswith("update records set indexing_status = 'NOT_STARTED'"):
            self.store["status"] = "NOT_STARTED"
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


def test_upsert_rejects_a_vector_of_the_wrong_dimension():
    from kbindex.qdrant_store import Vectors
    from qdrant_client.http import models as qm

    vectors = Vectors.__new__(Vectors)
    point = qm.PointStruct(id="p", vector={"dense": [0.1, 0.2]}, payload={})
    with pytest.raises(QdrantUnavailable):
        vectors.upsert([point], expected_dim=3)
