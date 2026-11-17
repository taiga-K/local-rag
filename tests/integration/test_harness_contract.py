"""Benchmark harness contract.

The harness pushes one text block and queries with rewriteQuery false,
maxChunksPerRecord 1, and filters.kb. record.recordId equals the pushed
externalRecordId. An unknown kb returns chunks [].

Principle: behavior the harness observes over HTTP.
PipesHub has no retrieve e2e (test_viewpoints.md gap 1). The closest file is
integration-tests/retrieval/test_search_quality.py, which calls /api/v1/search.
"""

import json
import os
import time
import urllib.request
import uuid

import pytest

pytestmark = pytest.mark.integration

API = os.environ.get("KBINDEX_API", "http://127.0.0.1:43123")


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        API + path,
        data=data,
        headers={"content-type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}


def wait_idle(kb: str) -> None:
    deadline = time.time() + 180
    last = {}
    while time.time() < deadline:
        _status, last = call("GET", f"/api/v1/kb/{kb}/indexing/counts")
        if last.get("QUEUED") == 0 and last.get("IN_PROGRESS") == 0 and last.get("FAILED") == 0 and last.get("COMPLETED", 0) >= 1:
            return
        time.sleep(0.5)
    pytest.fail(f"index did not finish: {last}")


def test_harness_push_and_retrieve_shape():
    kb = "h" + uuid.uuid4().hex[:8]
    other = "o" + uuid.uuid4().hex[:8]
    call("POST", "/api/v1/kb", {"id": kb, "name": kb})
    call("POST", "/api/v1/kb", {"id": other, "name": other})
    external = "doc.weather_1"
    status, pushed = call("POST", f"/api/v1/kb/{kb}/records", {
        "recordName": "天気",
        "mimeType": "application/blocks",
        "externalRecordId": external,
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [
            {"index": 0, "type": "text", "format": "txt", "data": "東京都の天気は晴れです。"},
            {"index": 1, "type": "text", "format": "txt", "data": "東京都の天気は翌日も晴れです。"},
        ]},
    })
    assert status == 201
    assert pushed["externalRecordId"] == external
    call("POST", f"/api/v1/kb/{other}/records", {
        "recordName": "図書館",
        "mimeType": "application/blocks",
        "externalRecordId": "doc.library_1",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "data": "市立図書館は水曜が休館です。"}]},
    })
    wait_idle(kb)
    wait_idle(other)
    _status, found = call("POST", "/api/v1/retrieve", {
        "query": "東京の天気",
        "limit": 10,
        "rewriteQuery": False,
        "maxChunksPerRecord": 1,
        "filters": {"kb": [kb]},
    })
    assert found["chunks"]
    ids = []
    for chunk in found["chunks"]:
        assert chunk["record"]["recordId"] == external
        assert "図書館" not in chunk["text"]
        ids.append(chunk["record"]["recordId"])
    assert len(ids) == len(set(ids))
    _status, empty = call("POST", "/api/v1/retrieve", {
        "query": "東京の天気",
        "limit": 10,
        "rewriteQuery": False,
        "maxChunksPerRecord": 1,
        "filters": {"kb": ["missingkb"]},
    })
    assert empty == {"chunks": [], "incomplete": False}
