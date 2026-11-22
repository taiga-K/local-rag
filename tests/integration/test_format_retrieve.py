"""Sync a folder of made-up Japanese files and retrieve each unique sentence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

API = os.environ.get("KBINDEX_API", "http://127.0.0.1:43123")


def test_sync_reads_shift_jis_and_records_the_skip(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "引き継ぎ.txt").write_bytes("夜勤の引き継ぎは第三倉庫の鍵を使う".encode("cp932"))
    (root / "在庫.csv").write_bytes("品番,在庫\r\n品番 A-102 の在庫は 7 個,7\r\n".encode("cp932"))
    (root / "束ね.zip").write_bytes(b"PK\x03\x04not-a-document")
    kb = "fmt" + uuid.uuid4().hex[:8]
    _json("POST", "/api/v1/kb", {"id": kb, "name": kb})
    subprocess.run(
        [sys.executable, "-m", "kbindex.cli", "sync", "--kb", kb, "--root", str(root), "--api", API],
        check=True,
    )
    _wait_idle(kb)
    txt = _retrieve(kb, "夜勤の引き継ぎは第三倉庫の鍵を使う")
    csv = _retrieve(kb, "品番 A-102 の在庫は 7 個")
    assert any(row["record"]["name"] == "引き継ぎ.txt" for row in txt["chunks"][:10])
    assert any(row["record"]["name"] == "在庫.csv" for row in csv["chunks"][:10])
    status, unread = _json("GET", f"/api/v1/kb/{kb}/unreadable")
    assert status == 200
    assert unread["files"][0]["relativePath"] == "束ね.zip"
    assert unread["files"][0]["message"] == "読めない形式"


def _retrieve(kb: str, query: str) -> dict:
    status, body = _json("POST", "/api/v1/retrieve", {"query": query, "limit": 10, "filters": {"kb": [kb]}})
    assert status == 200
    return body


def _wait_idle(kb: str) -> None:
    for _ in range(40):
        status, body = _json("GET", f"/api/v1/kb/{kb}/indexing/counts")
        if status == 200 and body.get("QUEUED", 0) == 0 and body.get("IN_PROGRESS", 0) == 0:
            return
        time.sleep(0.5)
    raise AssertionError("indexing did not finish")


def _json(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
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
