"""HTTP behavior against the compose stack.

Principle: behavior callers observe. Status, error.reason, later GET, and
retrieved text. Not private helpers.

PipesHub references, commit 7aff0de unless noted:
- backend/python/tests/integration/graph_db/test_kb_push_real_backends.py
- backend/python/tests/integration/graph_db/test_kb_push_concurrency_real_backends.py
  (test_race_two_services)
- backend/python/tests/unit/connectors/sources/localKB/push/test_contract.py
- backend/python/tests/unit/connectors/sources/localKB/push/test_structure.py
- backend/python/tests/unit/api/routes/test_retrieve.py
- tests/integration/vector_db/test_qdrant_integration.py (test_hybrid_sparse_dense_query)
- integration-tests/resilience/test_reindex_failed_records.py
- integration-tests/resilience/test_vector_store_rebuild.py
- integration-tests/response-validation/knowledgebase/integration_test_knowledgebase_records_crud.py
- integration-tests/response-validation/connector/integration_test_connector_sync_lifecycle.py

No PipesHub test drops Postgres, Redis, or Qdrant and reads the HTTP status.
Those cases follow DESIGN.md.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

API = os.environ.get("KBINDEX_API", "http://127.0.0.1:43123")
DSN = os.environ.get("DATABASE_URL", "postgresql://kbindex:kbindex@127.0.0.1:54329/kbindex")
ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["sudo", "docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
_CODES = {
    400: "HTTP_BAD_REQUEST",
    404: "HTTP_NOT_FOUND",
    409: "HTTP_CONFLICT",
    422: "HTTP_UNPROCESSABLE_ENTITY",
    503: "HTTP_SERVICE_UNAVAILABLE",
}


def _call(method: str, path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"content-type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, _body(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _body(exc.read())


def _body(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"reason": "NON_JSON", "message": raw[:300].decode("utf-8", "replace")}}
    return parsed if isinstance(parsed, dict) else {}


def _kb() -> str:
    kb = "h" + uuid.uuid4().hex[:10]
    status, _body = _call("POST", "/api/v1/kb", {"id": kb, "name": kb})
    assert status == 201
    return kb


def _doc(ext: str, text: str, version: int, name: str = "記録") -> dict:
    return {
        "recordName": name,
        "mimeType": "application/blocks",
        "externalRecordId": ext,
        "version": version,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "data": text}]},
    }


def _push(kb: str, body: dict) -> tuple[int, dict]:
    return _call("POST", f"/api/v1/kb/{kb}/records", body)


def _reason(body: dict) -> str:
    return body["error"]["reason"]


def _assert_error(status: int, body: dict, reason: str) -> None:
    assert status in _CODES
    assert body["error"]["code"] == _CODES[status]
    assert body["error"]["reason"] == reason


def _wait_status(kb: str, ext: str, wanted: set[str], timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        code, last = _call("GET", f"/api/v1/kb/{kb}/records/{ext}")
        if code == 200 and last.get("indexingStatus") in wanted:
            return last
        time.sleep(0.4)
    pytest.fail(f"status did not reach {wanted}: {last}")


def _compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], check=True, cwd=ROOT, timeout=90)


def _wait_port(port: int, timeout: float = 40) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 1):
                return
        except OSError:
            time.sleep(0.3)
    pytest.fail(f"127.0.0.1:{port} did not open")


class _stopped:
    def __init__(self, service: str, port: int) -> None:
        self.service = service
        self.port = port

    def __enter__(self) -> None:
        _compose("stop", self.service)

    def __exit__(self, *exc: object) -> None:
        _compose("start", self.service)
        _wait_port(self.port)
        if self.service == "postgres":
            _wait_postgres()


def _wait_postgres() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with psycopg.connect(DSN, connect_timeout=3) as conn:
                conn.execute("select 1")
            return
        except psycopg.Error:
            time.sleep(0.4)
    pytest.fail("postgres did not accept queries")


def test_push_dto_rejections():
    kb = _kb()
    base = _doc("doc", "東京", 1)
    unknown = dict(base)
    unknown["extra"] = 1
    status, body = _push(kb, unknown)
    _assert_error(status, body, "ENVELOPE_INVALID")
    assert status == 400

    strict = json.loads(json.dumps(base))
    strict["blocks"]["blocks"][0]["index"] = "0"
    status, body = _push(kb, strict)
    _assert_error(status, body, "BLOCKS_INVALID")
    assert status == 422

    missing_name = dict(base)
    del missing_name["recordName"]
    status, body = _push(kb, missing_name)
    _assert_error(status, body, "ENVELOPE_INVALID")
    assert status == 400

    missing_blocks = dict(base)
    del missing_blocks["blocks"]
    status, body = _push(kb, missing_blocks)
    _assert_error(status, body, "BLOCKS_INVALID")
    assert status == 422

    paragraph = json.loads(json.dumps(base))
    paragraph["blocks"]["blocks"][0]["type"] = "paragraph"
    status, body = _push(kb, paragraph)
    _assert_error(status, body, "BLOCKS_INVALID")
    assert status == 422

    sheet = json.loads(json.dumps(base))
    sheet["blocks"]["block_groups"] = [{"index": 0, "type": "sheet"}]
    status, body = _push(kb, sheet)
    _assert_error(status, body, "BLOCKS_INVALID")
    assert status == 422

    status, body = _push(kb, {})
    _assert_error(status, body, "ENVELOPE_INVALID")
    assert status == 400

    huge = json.loads(json.dumps(base))
    huge["externalRecordId"] = "huge"
    huge["blocks"]["blocks"][0]["data"] = "あ" * ((1 << 20) + 1)
    status, body = _push(kb, huge)
    _assert_error(status, body, "BLOCKS_INVALID")
    assert status == 422


def test_version_semantics_delete_repush():
    kb = _kb()
    ext = "weather"
    original = "東京都の天気は晴れです。"
    status, created = _push(kb, _doc(ext, original, 1, "天気"))
    assert status == 201 and created["status"] == "created" and created["contentChanged"] is True
    status, same = _push(kb, _doc(ext, original, 1, "天気"))
    assert status == 200 and same["status"] == "unchanged" and same["contentChanged"] is False
    status, renamed = _push(kb, _doc(ext, original, 2, "別名"))
    assert status == 200 and renamed["status"] == "updated" and renamed["contentChanged"] is False
    status, conflict = _push(kb, _doc(ext, "本文を変える", 2))
    _assert_error(status, conflict, "VERSION_CONFLICT")
    assert status == 409 and conflict["error"]["currentVersion"] == 2
    status, stale = _push(kb, _doc(ext, original, 1))
    _assert_error(status, stale, "STALE_VERSION")
    assert status == 409 and stale["error"]["currentVersion"] == 2
    _code, debug = _call("GET", f"/api/v1/debug/kb/{kb}/records/{ext}")
    assert debug["blocks"][0]["text"] == original
    updated = "翌日は曇りです。"
    status, changed = _push(kb, _doc(ext, updated, 3, "天気"))
    assert status == 200 and changed["status"] == "updated" and changed["contentChanged"] is True
    row = _wait_status(kb, ext, {"COMPLETED"})
    assert row["failureReason"] is None
    _code, found = _call("POST", "/api/v1/retrieve", {"query": "翌日の天気", "limit": 10, "filters": {"kb": [kb]}})
    assert found["chunks"] and "曇り" in found["chunks"][0]["text"]
    status, deleted = _call("DELETE", f"/api/v1/kb/{kb}/records/{ext}")
    assert status == 200 and deleted["deleted"] is True
    status, missing = _call("GET", f"/api/v1/kb/{kb}/records/{ext}")
    _assert_error(status, missing, "RECORD_NOT_FOUND")
    assert status == 404
    again = "削除のあと戻した晴れです。"
    status, recreated = _push(kb, _doc(ext, again, 1))
    assert status == 201 and recreated["status"] == "created"
    _wait_status(kb, ext, {"COMPLETED"})
    _code, found = _call("POST", "/api/v1/retrieve", {"query": "戻した晴れ", "limit": 10, "filters": {"kb": [kb]}})
    assert found["chunks"] and "戻した" in found["chunks"][0]["text"]
    assert all("曇り" not in chunk["text"] for chunk in found["chunks"])


def test_concurrent_push_same_key():
    kb = _kb()
    ext = "race"

    def one(version: int) -> tuple[int, dict]:
        return _push(kb, _doc(ext, f"版{version}の本文です。", version))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(1, 9)))
    statuses = {status for status, _body in results}
    assert statuses <= {200, 201, 409}
    assert sum(1 for status, _body in results if status == 201) == 1
    winners = [body["version"] for status, body in results if status in {200, 201}]
    assert max(winners) == 8
    _code, debug = _call("GET", f"/api/v1/debug/kb/{kb}/records/{ext}")
    assert debug["raw"]["version"] == 8
    assert "版8" in debug["blocks"][0]["text"]


def test_inspection_paths():
    kb = _kb()
    status, created = _push(kb, _doc("seen", "観測対象です。", 1))
    assert status == 201
    record_id = created["recordId"]
    seen = []
    for path in (f"/api/v1/records/{record_id}", f"/api/v1/knowledgeBase/record/{record_id}"):
        code, body = _call("GET", path)
        assert code == 200
        assert body["record"]["id"] == record_id
        assert body["record"]["externalRecordId"] == "seen"
        assert body["knowledgeBase"]["id"] == kb
        assert body["record"]["indexingStatus"]
        seen.append(body["record"]["indexingStatus"])
    assert seen[0] == seen[1]
    code, missing = _call("GET", f"/api/v1/records/{uuid.uuid4()}")
    _assert_error(code, missing, "RECORD_NOT_FOUND")
    code, stats = _call("GET", f"/api/v1/connectors/{kb}/stats")
    assert code == 200 and stats["success"] is True
    counts = stats["data"]["stats"]["indexingStatus"]
    assert stats["data"]["connectorId"] == kb
    assert stats["data"]["origin"] == "COLLECTION"
    assert set(counts) == {"QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY", "NOT_STARTED"}
    assert stats["data"]["stats"]["total"] == sum(counts.values()) == 1
    code, unknown = _call("GET", "/api/v1/connectors/missingkb/stats")
    _assert_error(code, unknown, "KB_NOT_FOUND")
    code, queued = _call("POST", f"/api/v1/knowledgeBase/reindex/record/{record_id}", {})
    assert code == 202 and queued["indexingStatus"] == "QUEUED"


def test_indexing_status_and_qdrant():
    kb = _kb()
    status, _created = _push(kb, _doc("main", "東京都の天気は晴れです。", 1))
    assert status == 201
    _wait_status(kb, "main", {"COMPLETED"})
    _code, counts = _call("GET", f"/api/v1/kb/{kb}/indexing/counts")
    assert set(counts) == {"QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY", "NOT_STARTED"}
    assert counts["COMPLETED"] == 1
    assert sum(counts.values()) == 1
    with psycopg.connect(DSN, connect_timeout=3) as conn:
        conn.execute(
            "update records set indexing_status = 'IN_PROGRESS' where kb_id = %s and external_record_id = %s",
            (kb, "main"),
        )
        conn.commit()
    code, busy = _call("POST", f"/api/v1/kb/{kb}/records/main/reprocess")
    _assert_error(code, busy, "IN_PROGRESS")
    assert code == 409
    with psycopg.connect(DSN, connect_timeout=3) as conn:
        conn.execute(
            "update records set indexing_status = 'COMPLETED' where kb_id = %s and external_record_id = %s",
            (kb, "main"),
        )
        conn.commit()
    status, empty = _push(kb, {
        "recordName": "空",
        "mimeType": "application/blocks",
        "externalRecordId": "blank",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {},
    })
    assert status == 201
    _wait_status(kb, "blank", {"EMPTY"})
    _code, counts = _call("GET", f"/api/v1/kb/{kb}/indexing/counts")
    assert counts["EMPTY"] == 1 and counts["COMPLETED"] == 1
    assert sum(counts.values()) == 2
    with _stopped("qdrant", 46333):
        code, down = _call(
            "POST",
            "/api/v1/retrieve",
            {"query": "天気", "limit": 1, "filters": {"kb": [kb]}},
            timeout=45,
        )
        _assert_error(code, down, "QDRANT_UNAVAILABLE")
        assert code == 503
        status, accepted = _push(kb, _doc("later", "索引できない本文です。", 1))
        assert status == 201
        failed = _wait_status(kb, "later", {"FAILED"}, timeout=90)
        assert failed["failureReason"] == "QDRANT_UNAVAILABLE"
    _code, counts = _call("GET", f"/api/v1/connectors/{kb}/stats")
    assert counts["data"]["stats"]["indexingStatus"]["FAILED"] == 1
    code, again = _call("POST", f"/api/v1/records/{accepted['recordId']}/reindex", {})
    assert code == 202
    _wait_status(kb, "later", {"COMPLETED"})
    code, found = _call("POST", "/api/v1/retrieve", {"query": "索引できない", "limit": 5, "filters": {"kb": [kb]}})
    assert code == 200 and found["chunks"]
    assert "索引できない" in found["chunks"][0]["text"]


def test_redis_unavailable_then_push():
    kb = _kb()
    body = _doc("redisdoc", "redis の本文です。", 1)
    with _stopped("redis", 63799):
        status, refused = _push(kb, body)
        _assert_error(status, refused, "REDIS_UNAVAILABLE")
        assert status == 503
    status, missing = _call("GET", f"/api/v1/kb/{kb}/records/redisdoc")
    assert status == 404
    deadline = time.time() + 30
    status = 0
    while time.time() < deadline:
        status, created = _push(kb, body)
        if status == 201:
            break
        time.sleep(0.5)
    assert status == 201 and created["status"] == "created"
    _wait_status(kb, "redisdoc", {"COMPLETED"})


def test_postgres_unavailable_then_push():
    kb = _kb()
    body = _doc("pgdoc", "postgres の本文です。", 1)
    with _stopped("postgres", 54329):
        status, refused = _push(kb, body)
        _assert_error(status, refused, "POSTGRES_UNAVAILABLE")
        assert status == 503
    deadline = time.time() + 30
    status = 0
    while time.time() < deadline:
        status, _missing = _call("GET", f"/api/v1/kb/{kb}/records/pgdoc")
        if status == 404:
            break
        time.sleep(0.5)
    assert status == 404
    created: dict = {}
    deadline = time.time() + 30
    while time.time() < deadline:
        status, created = _push(kb, body)
        if status == 201:
            break
        time.sleep(0.5)
    assert status == 201 and created["status"] == "created"


def test_retrieve_boundaries():
    kb = _kb()
    blocks = {
        "recordName": "二つ",
        "mimeType": "application/blocks",
        "externalRecordId": "two",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [
            {"index": 0, "type": "text", "data": "東京の空は晴れです。"},
            {"index": 1, "type": "text", "data": "東京の夜も晴れです。"},
        ]},
    }
    status, _created = _push(kb, blocks)
    assert status == 201
    _wait_status(kb, "two", {"COMPLETED"})
    query = {"query": "晴れ", "filters": {"kb": [kb]}}
    status, zero = _call("POST", "/api/v1/retrieve", {**query, "limit": 0})
    _assert_error(status, zero, "LIMIT_OUT_OF_RANGE")
    assert status == 422
    status, high = _call("POST", "/api/v1/retrieve", {**query, "limit": 51})
    _assert_error(status, high, "LIMIT_OUT_OF_RANGE")
    assert status == 422
    status, one = _call("POST", "/api/v1/retrieve", {**query, "limit": 1})
    assert status == 200 and len(one["chunks"]) == 1
    status, ten = _call("POST", "/api/v1/retrieve", {**query, "limit": 10})
    assert status == 200 and 1 < len(ten["chunks"]) <= 10
    status, empty = _call("POST", "/api/v1/retrieve", {"query": "   ", "limit": 10})
    _assert_error(status, empty, "INVALID_QUERY")
    assert status == 400
    status, unknown_kb = _call("POST", "/api/v1/retrieve", {"query": "晴れ", "limit": 10, "filters": {"kb": ["missingkb"]}})
    assert status == 200 and unknown_kb["chunks"] == []
    status, bad_filter = _call("POST", "/api/v1/retrieve", {"query": "晴れ", "filters": {"kbId": kb}})
    _assert_error(status, bad_filter, "INVALID_FILTER")
    assert status == 400
    status, capped = _call("POST", "/api/v1/retrieve", {**query, "limit": 10, "maxChunksPerRecord": 1})
    assert status == 200
    assert len(capped["chunks"]) == 1
    assert capped["chunks"][0]["record"]["recordId"] == "two"


def test_debug_japanese_bm25_and_dense():
    kb = _kb()
    status, _body = _push(kb, _doc("weather", "東京都の天気は晴れです。", 1, "天気"))
    assert status == 201
    status, _body = _push(kb, _doc("library", "図書館の休館日は月曜日です。", 1, "図書館"))
    assert status == 201
    _wait_status(kb, "weather", {"COMPLETED"})
    _wait_status(kb, "library", {"COMPLETED"})
    _code, lexical = _call("POST", "/api/v1/debug/retrieve", {
        "query": "晴れ",
        "limit": 10,
        "filters": {"kb": [kb]},
    })
    hit = next(row for row in lexical["breakdown"] if "晴れ" in _text_of(lexical, row["chunkId"]))
    assert hit["fastembed"] is not None
    assert hit["dense"] is not None
    _code, dense_only = _call("POST", "/api/v1/debug/retrieve", {
        "query": "琵琶湖水深測定",
        "limit": 10,
        "filters": {"kb": [kb]},
    })
    assert dense_only["breakdown"]
    for row in dense_only["breakdown"]:
        assert row["dense"] is not None
        assert row["fastembed"] is not None


def _text_of(payload: dict, chunk_id: str) -> str:
    for chunk in payload["chunks"]:
        if chunk["id"] == chunk_id:
            return chunk["text"]
    return ""


def test_index_config_mismatch_then_reindex():
    kb = _kb()
    status, _created = _push(kb, _doc("kept", "再索引の対象です。", 1))
    assert status == 201
    _wait_status(kb, "kept", {"COMPLETED"})
    query = {"query": "再索引", "limit": 5, "filters": {"kb": [kb]}}
    try:
        with psycopg.connect(DSN, connect_timeout=3) as conn:
            conn.execute("update index_generation set fingerprint = %s where id = 1", ("0" * 64,))
            conn.commit()
        status, refused = _call("POST", "/api/v1/retrieve", query)
        _assert_error(status, refused, "INDEX_CONFIG_MISMATCH")
        assert status == 400
        assert "POST /api/v1/index/reindex" in refused["error"]["message"]
        status, started = _call("POST", "/api/v1/index/reindex", {})
        assert status == 202 and started["queued"] >= 1
        _wait_status(kb, "kept", {"COMPLETED"}, timeout=300)
        status, found = _call("POST", "/api/v1/retrieve", query)
        assert status == 200 and found["chunks"]
        assert "再索引" in found["chunks"][0]["text"]
    finally:
        status, body = _call("POST", "/api/v1/retrieve", {"query": "再索引", "limit": 1})
        if status == 400 and body.get("error", {}).get("reason") == "INDEX_CONFIG_MISMATCH":
            _call("POST", "/api/v1/index/reindex", {})
