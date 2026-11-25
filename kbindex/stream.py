"""Redis stream `record-events`. The envelope matches the PipesHub producer.

One lane publishes to that stream. More than one lane publishes to
`record-events.N` and the consumer also drains the base stream, which is
what PipesHub does when `FAIR_SCHEDULING_LANE_COUNT` is above 1
(`lanes/hash_router.py` `lane_topics`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256

import redis

STREAM = "record-events"
GROUP = "indexing"


def stream_names(lanes: int) -> tuple[str, ...]:
    """Streams the consumer reads. The base name stays first so older events drain."""
    count = max(1, lanes)
    if count == 1:
        return (STREAM,)
    return (STREAM,) + tuple(f"{STREAM}.{lane}" for lane in range(count))


def publish_stream(record_id: str, lanes: int) -> str:
    """Stable lane for one record. SHA-256, same idea as PipesHub `stable_lane`."""
    count = max(1, lanes)
    if count == 1:
        return STREAM
    lane = int.from_bytes(sha256(record_id.encode("utf-8")).digest()[:8], "big") % count
    return f"{STREAM}.{lane}"


def ensure_group(client: redis.Redis, lanes: int = 1) -> None:
    for name in stream_names(lanes):
        try:
            client.xgroup_create(name, GROUP, id="0", mkstream=True)
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
    lanes: int = 1,
    crash_retries: int | None = None,
) -> tuple[str, str]:
    body = {
        "recordId": record_id,
        "kbId": kb_id,
        "externalRecordId": external_record_id,
        "version": version,
        "contentRev": content_rev,
    }
    if crash_retries is not None:
        body["crashRetries"] = crash_retries
    payload = json.dumps(body, ensure_ascii=False)
    stream = publish_stream(record_id, lanes)
    message_id = client.xadd(
        stream,
        {
            "eventType": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return stream, str(message_id)


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
    crash_retries = payload.get("crashRetries") or 0
    try:
        crash_retries = int(crash_retries)
    except (TypeError, ValueError):
        crash_retries = 0
    return {
        "eventType": fields.get("eventType") or "",
        "recordId": str(payload.get("recordId") or ""),
        "kbId": str(payload.get("kbId") or ""),
        "externalRecordId": str(payload.get("externalRecordId") or ""),
        "version": version,
        "contentRev": str(payload.get("contentRev") or ""),
        "crashRetries": crash_retries,
    }
