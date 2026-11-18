"""Local settings and engineer-only controls over HTTP.

Principle: behavior. The settings app can read folders, auto-index, and
status. Embedding model, upload limit, and vector-store cleanup are the
engineer routes and are not required by the settings screens.

PipesHub: local folder and manual indexing are
backend/python/app/connectors/sources/local_fs/connector.py (personal, not
admin). Labs file size and vector-store cleanup are adminOnly
(gui_settings_scope.md). No PipesHub test covers a desktop settings screen.
test_viewpoints.md has no settings-GUI case.
"""

from __future__ import annotations

import json
import os
import urllib.error
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
        headers={"content-type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


def test_desktop_origin_is_reflected():
    request = urllib.request.Request(
        API + "/api/v1/settings/local",
        headers={"Origin": "http://127.0.0.1:43124"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:43124"


def test_local_settings_round_trip_and_manual_hold():
    try:
        status, saved = call("PUT", "/api/v1/settings/local", {
            "folders": ["/data/notes"],
            "includeSubfolders": False,
            "autoIndex": False,
        })
        assert status == 200
        assert saved == {"folders": ["/data/notes"], "includeSubfolders": False, "autoIndex": False}
        status, again = call("GET", "/api/v1/settings/local")
        assert status == 200 and again == saved
        kb = "set" + uuid.uuid4().hex[:8]
        status, _kb = call("POST", "/api/v1/kb", {"id": kb, "name": kb})
        assert status == 201
        status, pushed = call("POST", f"/api/v1/kb/{kb}/records", {
            "recordName": "保留",
            "mimeType": "application/blocks",
            "externalRecordId": "held",
            "version": 1,
            "blocksFormat": 1,
            "blocks": {"blocks": [{"index": 0, "type": "text", "data": "まだ索引しない。"}]},
        })
        assert status == 201 and pushed["indexingStatus"] == "AUTO_INDEX_OFF"
        status, listed = call("GET", f"/api/v1/kb/{kb}/records")
        assert listed["records"][0]["indexingStatus"] == "AUTO_INDEX_OFF"
        status, queued = call("POST", f"/api/v1/connectors/{kb}/reindex")
        assert status == 202 and queued["queued"] == 1
    finally:
        call("PUT", "/api/v1/settings/local", {"folders": [], "includeSubfolders": True, "autoIndex": True})


def test_engineer_limit_and_embedding_refusal():
    status, before = call("GET", "/api/v1/engineer/upload-limit")
    assert status == 200 and before["maxBytes"] >= 1
    try:
        status, updated = call("PUT", "/api/v1/engineer/upload-limit", {"maxBytes": 32})
        assert status == 200 and updated == {"maxBytes": 32}
        kb = "lim" + uuid.uuid4().hex[:8]
        call("POST", "/api/v1/kb", {"id": kb, "name": kb})
        status, refused = call("POST", f"/api/v1/kb/{kb}/records", {
            "recordName": "大",
            "mimeType": "application/blocks",
            "externalRecordId": "big",
            "version": 1,
            "blocksFormat": 1,
            "blocks": {"blocks": [{"index": 0, "type": "text", "data": "x" * 40}]},
        })
        assert status == 413 and refused["error"]["reason"] == "PAYLOAD_TOO_LARGE"
        assert refused["error"]["limitBytes"] == 32
    finally:
        call("PUT", "/api/v1/engineer/upload-limit", {"maxBytes": before["maxBytes"]})
    status, current = call("GET", "/api/v1/engineer/embedding")
    assert status == 200 and current["model"]
    status, blocked = call("PUT", "/api/v1/engineer/embedding", {"model": "other/model"})
    assert status == 400 and blocked["error"]["reason"] == "INDEX_CONFIG_MISMATCH"
