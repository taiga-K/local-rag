"""HTTP push, index, retrieve against the compose stack.

Fills PipesHub gaps 1, 2, and 4 from test_viewpoints.md:
no retrieve e2e, no push-to-search test, and only one real-Qdrant hybrid test.
Principle: behavior. Assert status codes and chunk text, not private helpers.
PipesHub reference: integration-tests/retrieval/test_search_quality.py ranks documents
and does not threshold scores. It calls /api/v1/search, not /retrieve.
"""

import json
import os
import time
import urllib.request
import uuid

import pytest

pytestmark = pytest.mark.integration

API = os.environ.get("KBINDEX_API", "http://127.0.0.1:43123")


def _json(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"content-type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}


def test_push_index_retrieve_and_debug():
    kb = "it" + uuid.uuid4().hex[:8]
    _json("POST", "/api/v1/kb", {"id": kb, "name": kb})
    status, created = _json("POST", f"/api/v1/kb/{kb}/records", {
        "recordName": "天気",
        "mimeType": "application/blocks",
        "externalRecordId": "weather",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "data": "東京都の天気は晴れです。"}]},
    })
    assert status == 201 and created["status"] == "created"
    status, again = _json("POST", f"/api/v1/kb/{kb}/records", {
        "recordName": "天気",
        "mimeType": "application/blocks",
        "externalRecordId": "weather",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "data": "東京都の天気は晴れです。"}]},
    })
    assert status == 200 and again["status"] == "unchanged"
    deadline = time.time() + 180
    while time.time() < deadline:
        _code, counts = _json("GET", f"/api/v1/kb/{kb}/indexing/counts")
        if counts.get("QUEUED") == 0 and counts.get("IN_PROGRESS") == 0 and counts.get("COMPLETED", 0) >= 1:
            break
        time.sleep(1)
    else:
        pytest.fail(f"not indexed: {counts}")
    _code, found = _json("POST", "/api/v1/retrieve", {"query": "東京の天気", "limit": 10, "filters": {"kb": [kb]}})
    assert found["chunks"]
    assert "晴れ" in found["chunks"][0]["text"]
    _code, debug = _json("POST", "/api/v1/debug/retrieve", {"query": "東京の天気", "limit": 10, "filters": {"kb": [kb]}})
    assert debug["breakdown"][0]["rrf"] >= debug["breakdown"][-1]["rrf"]
    assert "dense" in debug["breakdown"][0]
