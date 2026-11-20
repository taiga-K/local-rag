"""Similarity is attached after RRF. The threshold drops hits before the page cut."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from kbindex.api import create_app
from kbindex.config import load_settings
from kbindex.db import ALTERS, NAMESPACE, score_threshold_payload
from kbindex.pipeline import Engine
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.similarity import DEFAULT_SCORE_THRESHOLD, apply_score_threshold, cosine


def test_cosine_divides_by_the_norms():
    assert cosine([1.0, 0.0], [0.6, 0.8]) == pytest.approx(0.6)
    assert cosine([2.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 0.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0]) is None


def test_threshold_keeps_the_boundary_and_rrf_order():
    fused = [("a", 0.5, {"id": "a"}), ("b", 0.4, {"id": "b"}), ("c", 0.3, {"id": "c"})]
    sims = {"a": 0.5, "b": 0.49, "c": None}
    assert [item[0] for item in apply_score_threshold(fused, sims, enabled=False, threshold=0.5)] == ["a", "b", "c"]
    kept = apply_score_threshold(fused, sims, enabled=True, threshold=0.5)
    assert [item[0] for item in kept] == ["a"]
    assert kept[0][1] == 0.5
    assert kept[0][3] == 0.5


def test_default_threshold_is_the_single_constant():
    assert DEFAULT_SCORE_THRESHOLD == 0.84
    assert "0.84" not in "\n".join(ALTERS)


def test_null_column_follows_the_constant(monkeypatch):
    monkeypatch.setattr("kbindex.db.DEFAULT_SCORE_THRESHOLD", 0.25)
    body = score_threshold_payload({"score_threshold_enabled": False, "score_threshold": None})
    assert body == {"scoreThresholdEnabled": False, "scoreThreshold": 0.25}


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DB:
    def connect(self):
        return _Conn()


class _Embed:
    def __init__(self):
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [1.0, 0.0]


class _Vectors:
    def __init__(self, stored: dict[str, list[float]], *, fail: bool = False):
        self.stored = stored
        self.fail = fail
        self.batches: list[list[str]] = []
        self.queries: list[list[float]] = []

    def search(self, vector, *, limit, kb_ids):
        self.queries.append(list(vector))
        return [("low", 0.2), ("high", 0.9), ("gone", 0.1)]

    def dense_vectors(self, chunk_ids):
        self.batches.append(list(chunk_ids))
        if self.fail:
            raise QdrantUnavailable("down")
        return {cid: self.stored[cid] for cid in chunk_ids if cid in self.stored}


def _rows(chunk_ids: list[str]):
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    return [
        {
            "chunk_id": cid,
            "text": "本文",
            "block_index": 0,
            "piece": 0,
            "token_count": 1,
            "record_id": "11111111-1111-1111-1111-111111111111",
            "external_record_id": cid,
            "record_name": cid,
            "kb_id": "kb",
            "indexing_status": "COMPLETED",
            "has_indexed_copy": True,
            "source_modified_ms": None,
            "created_at": now,
            "updated_at": now,
        }
        for cid in chunk_ids
    ]


def _search(monkeypatch, *, enabled: bool, threshold: float, stored: dict, limit: int = 10, fail: bool = False):
    monkeypatch.setattr("kbindex.pipeline.query_terms", lambda _query: ["語"])
    monkeypatch.setattr(
        "kbindex.pipeline.bm25_rows",
        lambda _conn, tokenizer, _terms, kb_ids=None: (
            {"doc_count": 3},
            [{"term": "語", "df": 1}],
            [{"term": "語", "chunk_id": "only", "tf": 1.0}],
        ),
    )
    monkeypatch.setattr("kbindex.pipeline.hydrate_chunks", lambda _conn, ids: _rows(ids))
    monkeypatch.setattr("kbindex.pipeline.read_score_threshold", lambda _conn: (enabled, threshold))
    embed = _Embed()
    vectors = _Vectors(stored, fail=fail)
    engine = Engine(load_settings(), _DB(), vectors, embed)
    found = engine.search("質問", limit=limit, kb_ids=None, max_per_record=None, bounds={})
    return found, embed, vectors


_STORED = {
    "low": [0.0, 1.0],
    "only": [0.6, 0.8],
    "high": [1.0, 0.0],
}


def test_disabled_keeps_rrf_order_and_attaches_similarity(monkeypatch):
    found, embed, vectors = _search(monkeypatch, enabled=False, threshold=0.5, stored=_STORED)
    assert embed.queries == ["質問"]
    assert vectors.queries == [[1.0, 0.0]]
    assert vectors.batches == [["low", "only", "high", "gone"]]
    assert [chunk["id"] for chunk in found["chunks"]] == ["low", "only", "high", "gone"]
    assert [chunk["score"] for chunk in found["chunks"]] == pytest.approx([0.5, 0.5, 1 / 3, 0.25])
    assert found["chunks"][0]["similarity"] == pytest.approx(0.0)
    assert found["chunks"][1]["similarity"] == pytest.approx(0.6)
    assert found["chunks"][2]["similarity"] == pytest.approx(1.0)
    assert found["chunks"][3]["similarity"] is None
    assert "only" not in {cid for cid, _score in found["dense"]}


def test_enabled_drops_low_and_missing_vectors_before_the_limit(monkeypatch):
    found, _embed, _vectors = _search(monkeypatch, enabled=True, threshold=0.5, stored=_STORED, limit=1)
    assert [chunk["id"] for chunk in found["chunks"]] == ["only"]
    assert found["chunks"][0]["score"] == pytest.approx(0.5)
    assert found["chunks"][0]["similarity"] == pytest.approx(0.6)


def test_enabled_returns_empty_when_every_candidate_is_below(monkeypatch):
    stored = {"low": [0.0, 1.0], "only": [0.0, 1.0], "high": [0.0, 1.0]}
    found, _embed, _vectors = _search(monkeypatch, enabled=True, threshold=0.5, stored=stored)
    assert found["chunks"] == []


def test_disabled_survives_a_vector_read_failure(monkeypatch):
    found, _embed, _vectors = _search(monkeypatch, enabled=False, threshold=0.5, stored=_STORED, fail=True)
    assert [chunk["id"] for chunk in found["chunks"]] == ["low", "only", "high", "gone"]
    assert [chunk["similarity"] for chunk in found["chunks"]] == [None, None, None, None]


def test_enabled_vector_read_failure_is_unavailable(monkeypatch):
    with pytest.raises(QdrantUnavailable):
        _search(monkeypatch, enabled=True, threshold=0.5, stored=_STORED, fail=True)


def test_dense_vectors_reads_one_batch_by_chunk_uuid():
    client = QdrantClient(":memory:")
    store = Vectors.__new__(Vectors)
    store.client = client
    store.ensure(4)
    cid = "rec:0"
    point_id = str(uuid.uuid5(NAMESPACE, cid))
    client.upsert(
        collection_name="chunks",
        points=[qm.PointStruct(id=point_id, vector={"dense": [1.0, 0.0, 0.0, 0.0]}, payload={"chunkId": cid})],
    )
    calls = {"n": 0}
    original = client.retrieve

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        assert kwargs["with_vectors"] == ["dense"]
        assert kwargs["ids"] == [point_id, str(uuid.uuid5(NAMESPACE, "missing"))]
        return original(*args, **kwargs)

    client.retrieve = wrapped
    found = store.dense_vectors([cid, "missing"])
    assert calls["n"] == 1
    assert found == {cid: [1.0, 0.0, 0.0, 0.0]}
    assert store.dense_vectors([]) == {}
    assert calls["n"] == 1


class _SettingsCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return None if self.row is None else dict(self.row)


class _SettingsConn:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        if text.startswith("update app_settings"):
            self.row["score_threshold_enabled"] = params[0]
            self.row["score_threshold"] = params[1]
        return _SettingsCursor(self.row)

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _SettingsDB:
    def __init__(self, row):
        self.conn = _SettingsConn(row)

    def connect(self):
        return self.conn


def _settings_client(row):
    app = create_app()
    app.router.on_startup.clear()
    app.state.db = _SettingsDB(row)
    return TestClient(app)


def test_retrieve_settings_round_trip_and_local_body_stays_put():
    row = {
        "id": 1,
        "folders": ["/data/notes"],
        "include_subfolders": True,
        "auto_index": True,
        "max_upload_bytes": 16,
        "requested_model": None,
        "score_threshold_enabled": False,
        "score_threshold": None,
    }
    with _settings_client(row) as client:
        got = client.get("/api/v1/settings/retrieve")
        assert got.status_code == 200
        assert got.json() == {"scoreThresholdEnabled": False, "scoreThreshold": 0.84}
        local = client.get("/api/v1/settings/local")
        assert local.json() == {"folders": ["/data/notes"], "includeSubfolders": True, "autoIndex": True}
        saved = client.put(
            "/api/v1/settings/retrieve",
            json={"scoreThresholdEnabled": True, "scoreThreshold": 1},
        )
        assert saved.status_code == 200
        assert saved.json() == {"scoreThresholdEnabled": True, "scoreThreshold": 1.0}
        assert client.get("/api/v1/settings/retrieve").json() == saved.json()


@pytest.mark.parametrize(
    "body",
    [
        {"scoreThresholdEnabled": True, "scoreThreshold": 1.1},
        {"scoreThresholdEnabled": True, "scoreThreshold": -1.1},
        {"scoreThresholdEnabled": True, "scoreThreshold": True},
        {"scoreThresholdEnabled": True, "scoreThreshold": "0.5"},
        {"scoreThresholdEnabled": True},
        {"scoreThresholdEnabled": True, "scoreThreshold": 0.5, "limit": 10},
    ],
)
def test_retrieve_settings_reject_a_bad_body(body):
    row = {"score_threshold_enabled": False, "score_threshold": None}
    with _settings_client(row) as client:
        response = client.put("/api/v1/settings/retrieve", json=body)
        assert response.status_code == 400
        assert response.json()["error"]["reason"] == "ENVELOPE_INVALID"
