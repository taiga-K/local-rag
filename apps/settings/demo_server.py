"""Stand-in API for the settings screens. Same paths as kbindex, with scripted rows.

The numbers on screen are this process's record list, not hard-coded captions.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kbindex.ingest_ui import activity_sentence, failure_fields, pause_deadline, pause_is_active

LOCK = threading.Lock()
NOW = datetime(2026, 11, 20, 23, 8, tzinfo=timezone.utc)


def _record(kb: str, name: str, status: str, reason: str | None, index: int) -> dict:
    return {
        "recordId": f"{kb}-{index}",
        "externalRecordId": f"ext-{index}",
        "recordName": name,
        "indexingStatus": status,
        "failureReason": reason,
        "sourceModifiedMs": int(NOW.timestamp() * 1000) - index * 60_000,
        "updatedAt": (NOW - timedelta(minutes=index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": 1,
        "kbId": kb,
    }


def _seed() -> dict:
    named = [
        "2026-11 定例議事録.pdf",
        "2026-10 定例議事録.pdf",
        "経営会議 議事録 2026年10月期.pdf",
        "採用面談メモ_中途_10月.docx",
        "プロジェクト振り返り_第3四半期.md",
    ]
    notes = []
    for index, name in enumerate(named):
        notes.append(_record("notes", name, "COMPLETED", None, 1000 + index))
    for index in range(125):
        notes.append(_record("notes", f"取り込み済み {index + 1}.docx", "COMPLETED", None, 2000 + index))
    notes.append(_record("notes", "2026-11 営業会議 議事録.docx", "IN_PROGRESS", None, 10))
    notes.append(_record("notes", "2026年度 予算申請書.pdf", "FAILED", "QDRANT_UNAVAILABLE", 11))
    notes.append(_record("notes", "定例メモ 10月.one", "FAILED", "INDEX_FAILED", 12))
    for index in range(347):
        notes.append(_record("notes", f"待ち {index + 1}.docx", "QUEUED", None, 3000 + index))
    specs = [_record("specs", f"仕様 {index + 1}.md", "COMPLETED", None, 4000 + index) for index in range(4)]
    return {
        "local": {"folders": [r"C:\Users\taiga\Documents\議事録"], "includeSubfolders": True, "autoIndex": True},
        "retrieve": {"scoreThresholdEnabled": False, "scoreThreshold": 0.5},
        "embedding": {
            "model": "cl-nagoya/ruri-v3-310m",
            "device": "cpu",
            "requestedModel": None,
            "requestedDevice": None,
            "keyword": "fastembed",
            "models": ["cl-nagoya/ruri-v3-310m", "cl-nagoya/ruri-v3-130m"],
            "devices": ["cpu", "cuda"],
        },
        "pause": {"kind": None, "until": None},
        "folders": {"notes": "議事録", "specs": "仕様書"},
        "records": {"notes": notes, "specs": specs},
        "advance": False,
        "ticks": 0,
    }


STATE = _seed()


def _public(row: dict) -> dict:
    fields = failure_fields(row["indexingStatus"], row["failureReason"])
    return {
        "recordId": row["recordId"],
        "externalRecordId": row["externalRecordId"],
        "recordName": row["recordName"],
        "indexingStatus": row["indexingStatus"],
        "failureReason": None if row["indexingStatus"] in {"COMPLETED", "EMPTY"} else row["failureReason"],
        "failureClassified": fields["failureClassified"],
        "failureMessage": fields["failureMessage"],
        "sourceModifiedMs": row["sourceModifiedMs"],
        "updatedAt": row["updatedAt"],
        "version": row["version"],
    }


def _summary(now: datetime) -> dict:
    folders = []
    current = None
    latest = None
    for kb_id, name in STATE["folders"].items():
        rows = STATE["records"][kb_id]
        total = len(rows)
        failed = sum(1 for row in rows if row["indexingStatus"] == "FAILED")
        active = sum(1 for row in rows if row["indexingStatus"] == "IN_PROGRESS")
        queued = sum(1 for row in rows if row["indexingStatus"] == "QUEUED")
        completed = sum(1 for row in rows if row["indexingStatus"] == "COMPLETED")
        done = sum(1 for row in rows if row["indexingStatus"] in {"COMPLETED", "EMPTY", "FAILED"})
        folders.append({
            "id": kb_id,
            "name": name,
            "total": total,
            "failed": failed,
            "active": active,
            "queued": queued,
            "completed": completed,
            "done": done,
        })
        for row in rows:
            if row["indexingStatus"] == "IN_PROGRESS" and current is None:
                current = {"recordName": row["recordName"], "kbId": kb_id, "kbName": name}
            if latest is None or (row["updatedAt"] or "") > latest:
                latest = row["updatedAt"]
    pause = STATE["pause"]
    until = pause["until"]
    active = pause_is_active(pause["kind"], until, now)
    return {
        "total": sum(item["total"] for item in folders),
        "done": sum(item["done"] for item in folders),
        "active": sum(item["active"] for item in folders),
        "queued": sum(item["queued"] for item in folders),
        "failed": sum(item["failed"] for item in folders),
        "reindexCount": sum(1 for rows in STATE["records"].values() for row in rows if row["indexingStatus"] != "EMPTY"),
        "latestAt": latest,
        "current": current,
        "pause": {"active": active, "kind": pause["kind"], "until": None if until is None else until.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "folders": [{key: value for key, value in item.items() if key != "done"} for item in folders],
    }


def _advance(now: datetime) -> None:
    if not STATE["advance"] or pause_is_active(STATE["pause"]["kind"], STATE["pause"]["until"], now):
        return
    STATE["ticks"] += 1
    if STATE["ticks"] % 3:
        return
    rows = STATE["records"]["notes"]
    current = next((row for row in rows if row["indexingStatus"] == "IN_PROGRESS"), None)
    nxt = next((row for row in rows if row["indexingStatus"] == "QUEUED"), None)
    names = ["2026-11 営業会議 議事録.docx", "API仕様 v2.docx", "顧客打合せ_A社_0827.docx"]
    if current is not None:
        current["indexingStatus"] = "COMPLETED"
        current["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if nxt is not None:
        nxt["indexingStatus"] = "IN_PROGRESS"
        nxt["recordName"] = names[(STATE["ticks"] // 3) % len(names)]
        nxt["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        with LOCK:
            now = datetime.now(timezone.utc)
            if path == "/api/v1/ingest/summary":
                _advance(now)
                self._send(200, _summary(now))
                return
            if path == "/api/v1/settings/local":
                self._send(200, STATE["local"])
                return
            if path == "/api/v1/settings/retrieve":
                self._send(200, STATE["retrieve"])
                return
            if path == "/api/v1/engineer/embedding":
                self._send(200, STATE["embedding"])
                return
            if path == "/api/v1/ingest/activity":
                events = []
                for kb_id, rows in STATE["records"].items():
                    for row in rows:
                        if row["indexingStatus"] in {"QUEUED"}:
                            continue
                        events.append((row["updatedAt"], STATE["folders"][kb_id], activity_sentence(row["recordName"], row["indexingStatus"])))
                events.sort(reverse=True)
                limit = 50 if "limit=50" in self.path else 8
                self._send(200, {
                    "hasMore": len(events) > limit,
                    "events": [{"at": at, "folder": folder, "text": text} for at, folder, text in events[:limit]],
                })
                return
            if path.startswith("/api/v1/kb/") and path.endswith("/records"):
                kb_id = path.split("/")[4]
                rows = STATE["records"].get(kb_id, [])
                ordered = sorted(rows, key=lambda row: (row["indexingStatus"] != "FAILED", row["indexingStatus"] != "IN_PROGRESS", row["updatedAt"]), reverse=False)
                self._send(200, {"records": [_public(row) for row in ordered[:100]]})
                return
        self._send(404, {"error": {"message": "not found"}})

    def do_PUT(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?", 1)[0]
        with LOCK:
            now = datetime.now(timezone.utc)
            if path == "/api/v1/settings/local":
                STATE["local"] = payload
                self._send(200, STATE["local"])
                return
            if path == "/api/v1/settings/retrieve":
                STATE["retrieve"] = payload
                self._send(200, STATE["retrieve"])
                return
            if path == "/api/v1/engineer/embedding":
                STATE["embedding"]["model"] = payload["model"]
                STATE["embedding"]["requestedModel"] = payload["model"]
                self._send(200, STATE["embedding"])
                return
            if path == "/api/v1/engineer/device":
                STATE["embedding"]["requestedDevice"] = payload["device"]
                self._send(200, {**STATE["embedding"], "restartRequired": True})
                return
            if path == "/api/v1/ingest/pause":
                kind = payload.get("kind")
                until = None if kind is None else pause_deadline(kind, now)
                STATE["pause"] = {"kind": kind, "until": until}
                self._send(200, _summary(now)["pause"])
                return
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        with LOCK:
            if path == "/__demo/idle":
                for rows in STATE["records"].values():
                    for row in rows:
                        row["indexingStatus"] = "COMPLETED"
                        row["failureReason"] = None
                STATE["pause"] = {"kind": None, "until": None}
                STATE["advance"] = False
                self._send(200, {"ok": True})
                return
            if path == "/__demo/advance":
                STATE["advance"] = True
                self._send(200, {"ok": True})
                return
            if path == "/__demo/running":
                STATE.clear()
                STATE.update(_seed())
                self._send(200, {"ok": True})
                return
            if path == "/api/v1/ingest/retry-failed":
                queued = 0
                for rows in STATE["records"].values():
                    for row in rows:
                        if row["indexingStatus"] == "FAILED":
                            row["indexingStatus"] = "QUEUED"
                            row["failureReason"] = None
                            queued += 1
                self._send(200, {"queued": queued})
                return
            if "/records/" in path and path.endswith("/reprocess"):
                parts = path.split("/")
                kb_id = parts[4]
                external = parts[6]
                for row in STATE["records"].get(kb_id, []):
                    if row["externalRecordId"] == external:
                        row["indexingStatus"] = "QUEUED"
                        row["failureReason"] = None
                        self._send(200, {"queued": True})
                        return
            if path.endswith("/detach"):
                kb_id = path.split("/")[4]
                count = len(STATE["records"].get(kb_id, []))
                STATE["records"][kb_id] = []
                self._send(200, {"deleted": count})
                return
        self._send(404, {"error": {"message": "not found"}})

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 43123), Handler).serve_forever()
