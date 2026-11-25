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


REAL_NAMES = [
    "2026-09 定例議事録.docx",
    "2026-08 定例議事録.docx",
    "営業週報_2026-09-12.docx",
    "顧客打合せ_B社_0918.docx",
    "API仕様 v2.docx",
    "導入手順_社内ポータル.pdf",
    "問い合わせ対応_2026-09.md",
    "採用面談メモ_新卒_09.docx",
    "予算資料_第2四半期.pdf",
    "振り返り_8月.md",
    "契約書ドラフト_2026-09.pdf",
    "リリースノート_1.4.md",
    "障害報告_2026-09-03.docx",
    "研修資料_情報セキュリティ.pdf",
    "出張報告_大阪_0915.docx",
    "製品要望_一覧_2026-09.xlsx",
    "週次1on1_メモ.docx",
    "利用規約_改定案.pdf",
    "サポート手順_初回対応.md",
    "会議アジェンダ_2026-09-26.docx",
]


def _realistic(index: int) -> str:
    base = REAL_NAMES[index % len(REAL_NAMES)]
    stem, ext = base.rsplit(".", 1)
    cycle = index // len(REAL_NAMES)
    if cycle == 0:
        return base
    return f"{stem}_{cycle + 1}.{ext}"


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
        notes.append(_record("notes", _realistic(index), "COMPLETED", None, 2000 + index))
    notes.append(_record("notes", "2026-11 営業会議 議事録.docx", "IN_PROGRESS", None, 10))
    notes.append(_record("notes", "2026年度 予算申請書.pdf", "FAILED", "QDRANT_UNAVAILABLE", 11))
    notes.append(_record("notes", "定例メモ 10月.one", "FAILED", "この形式（.one）には対応していません。OneNote から PDF か Word で書き出すと取り込めます。", 12))
    notes.append(_record("notes", "顧客打合せ_A社_0827.docx", "FAILED", "読み込みに時間がかかりすぎたため中断しました。しばらくしてから再試行してください。", 13))
    for index in range(346):
        notes.append(_record("notes", _realistic(index + 20), "QUEUED", None, 3000 + index))
    notes[134]["recordName"] = "品質会議 議事録 2026年9月.pdf"
    notes[135]["recordName"] = "顧客打合せ_C社_0904.docx"
    notes[136]["recordName"] = "部長会 メモ 2026-09-30.docx"
    specs = [_record("specs", f"仕様書_{index + 1}.md", "COMPLETED", None, 4000 + index) for index in range(4)]
    return {
        "local": {
            "folders": [r"C:\Users\taiga\Documents\議事録", r"C:\Users\taiga\Documents\仕様書"],
            "includeSubfolders": True,
            "autoIndex": True,
        },
        "retrieve": {"level": "off"},
        "embedding": {
            "model": "cl-nagoya/ruri-v3-310m",
            "device": "cpu",
            "requestedModel": None,
            "requestedDevice": None,
            "keyword": "fastembed",
            "keywordEnabled": True,
            "dimension": 768,
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


def _point_count() -> int:
    return sum(1 for rows in STATE["records"].values() for row in rows if row["indexingStatus"] != "EMPTY")


def _embedding_public() -> dict:
    return {**STATE["embedding"], "pointCount": _point_count()}


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
        empty = sum(1 for row in rows if row["indexingStatus"] == "EMPTY")
        held = sum(1 for row in rows if row["indexingStatus"] == "AUTO_INDEX_OFF")
        done = completed + empty
        folders.append({
            "id": kb_id,
            "name": name,
            "total": total,
            "failed": failed,
            "active": active,
            "queued": queued,
            "completed": completed,
            "empty": empty,
            "held": held,
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
        "held": sum(item["held"] for item in folders),
        "reindexCount": sum(1 for rows in STATE["records"].values() for row in rows if row["indexingStatus"] != "EMPTY"),
        "latestAt": "2026-11-20T23:30:00Z" if not any(item["active"] or item["queued"] for item in folders) else latest,
        "current": current,
        "etaText": "あと約20分" if sum(item["active"] for item in folders) or sum(item["queued"] for item in folders) else None,
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
                self._send(200, _embedding_public())
                return
            if path == "/api/v1/ingest/activity":
                events = [
                    ("2026-11-20T13:51:00Z", "議事録", "2026-11 定例議事録.pdf", "更新"),
                    ("2026-11-20T13:40:00Z", "議事録", "営業週報_2026-11-14.docx", "追加"),
                    ("2026-11-20T13:12:00Z", "仕様書", "API仕様 v3.docx", "追加"),
                    ("2026-11-20T12:58:00Z", "仕様書", "API仕様 v2（旧）.docx", "削除"),
                    ("2026-11-20T09:20:00Z", "議事録", "経営会議 議事録 2026年10月期.pdf", "更新"),
                    ("2026-11-20T04:05:00Z", "議事録", "顧客打合せ_B社_1118.docx", "追加"),
                    ("2026-11-20T00:41:00Z", "仕様書", "導入手順_社内ポータル.pdf", "更新"),
                    ("2026-11-20T00:12:00Z", "議事録", "採用面談メモ_中途_11月.docx", "追加"),
                ]
                limit = 50 if "limit=50" in self.path else 8
                self._send(200, {
                    "hasMore": False,
                    "events": [
                        {"at": at, "folder": folder, "name": name, "kind": kind, "text": kind}
                        for at, folder, name, kind in events[:limit]
                    ],
                })
                return
            if path.startswith("/api/v1/kb/") and path.endswith("/records"):
                kb_id = path.split("/")[4]
                rows = STATE["records"].get(kb_id, [])
                ordered = sorted(
                    rows,
                    key=lambda row: (
                        row["indexingStatus"] == "FAILED",
                        row["indexingStatus"] == "IN_PROGRESS",
                        row["updatedAt"] or "",
                        row["recordId"],
                    ),
                    reverse=True,
                )
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
                limit = int(params.get("limit", "200") or 200)
                offset = int(params.get("offset", "0") or 0)
                status = params.get("status")
                if status:
                    ordered = [row for row in ordered if row["indexingStatus"] == status]
                page = ordered[offset:offset + limit]
                self._send(200, {"records": [_public(row) for row in page]})
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
                chosen = payload.get("model")
                if chosen == STATE["embedding"]["model"]:
                    STATE["embedding"]["requestedModel"] = None
                    self._send(200, {**_embedding_public(), "restartRequired": False})
                    return
                if _point_count() > 0:
                    self._send(400, {"error": {"reason": "MODEL_CHANGE_REFUSED", "message": "The collection still has points."}})
                    return
                STATE["embedding"]["requestedModel"] = chosen
                if chosen not in STATE["embedding"]["models"]:
                    STATE["embedding"]["models"].append(chosen)
                self._send(200, {**_embedding_public(), "restartRequired": True})
                return
            if path == "/api/v1/engineer/keyword":
                STATE["embedding"]["keywordEnabled"] = bool(payload.get("enabled"))
                self._send(200, _embedding_public())
                return
            if path == "/api/v1/engineer/device":
                STATE["embedding"]["requestedDevice"] = payload["device"]
                self._send(200, {**_embedding_public(), "restartRequired": True})
                return
            if path == "/api/v1/ingest/pause":
                kind = payload.get("kind")
                raw_until = payload.get("until")
                if kind == "tomorrow" and isinstance(raw_until, str):
                    until = datetime.fromisoformat(raw_until.replace("Z", "+00:00"))
                else:
                    until = None if kind is None else pause_deadline(kind, now)
                STATE["pause"] = {"kind": kind, "until": until}
                self._send(200, _summary(now)["pause"])
                return
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
        with LOCK:
            if path == "/api/v1/retrieve":
                query = str(payload.get("query", "")).strip()
                kb_filter = ((payload.get("filters") or {}).get("kb") or [])
                rows = []
                for kb_id, records in STATE["records"].items():
                    if kb_filter and kb_id not in kb_filter:
                        continue
                    rows.extend((kb_id, row) for row in records if row["indexingStatus"] == "COMPLETED")
                chunks = []
                for index, (kb_id, row) in enumerate(rows[:8]):
                    text = f"{row['recordName']} に関する本文です。{query} への関連箇所として、取り込み済みチャンクの表示例を返します。"
                    chunks.append({
                        "id": f"demo-{index}",
                        "text": text,
                        "score": 0.5 / (index + 1),
                        "similarity": max(0.35, 0.92 - index * 0.06),
                        "record": {
                            "recordId": row["externalRecordId"],
                            "name": row["recordName"],
                            "connector": kb_id,
                            "updatedAt": row["sourceModifiedMs"],
                        },
                        "citation": {"url": None, "recordUrl": None, "pageNum": None, "blockIndex": 0},
                    })
                self._send(200, {"chunks": chunks[: int(payload.get("limit", 8) or 8)], "incomplete": False})
                return
            if path == "/__demo/settled":
                for rows in STATE["records"].values():
                    for row in rows:
                        if row["indexingStatus"] in {"QUEUED", "IN_PROGRESS"}:
                            row["indexingStatus"] = "COMPLETED"
                STATE["pause"] = {"kind": None, "until": None}
                STATE["advance"] = False
                self._send(200, {"ok": True})
                return
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
