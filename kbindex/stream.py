"""Redis stream `record-events`. The envelope matches the PipesHub producer."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import redis

STREAM = "record-events"
GROUP = "indexing"


def ensure_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def publish(
    client: redis.Redis,
    event_type: str,
    *,
    record_id: str,
    kb_id: str,
    external_record_id: str,
    version: int,
    content_rev: str,
) -> None:
    payload = json.dumps(
        {
            "recordId": record_id,
            "kbId": kb_id,
            "externalRecordId": external_record_id,
            "version": version,
            "contentRev": content_rev,
        },
        ensure_ascii=False,
    )
    client.xadd(
        STREAM,
        {
            "eventType": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )


def read_event(fields: dict) -> dict:
    try:
        payload = json.loads(fields.get("payload") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    version = payload.get("version") or 0
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = 0
    return {
        "eventType": fields.get("eventType") or "",
        "recordId": str(payload.get("recordId") or ""),
        "kbId": str(payload.get("kbId") or ""),
        "externalRecordId": str(payload.get("externalRecordId") or ""),
        "version": version,
        "contentRev": str(payload.get("contentRev") or ""),
    }
