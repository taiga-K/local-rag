"""Words and pause rules for the settings app.

Failure sentences exist only for reasons this process actually writes.
Anything else stays unclassified. The screen must not invent a cause.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

NO_STORED_FAILURE = "原因が記録されていません。再試行しても失敗する場合はファイルを開けるか確かめてください。"
BLANK_FAILURES = {"", "INDEX_FAILED"}
FAILURE_LIMIT = 160

PAUSE_KINDS = ("30m", "1h", "tomorrow", "resume")


def failure_fields(status: str, reason: str | None) -> dict[str, bool | str | None]:
    """Show the stored error as written. Do not invent a cause."""
    if status != "FAILED":
        return {"failureClassified": False, "failureMessage": None}
    text = (reason or "").strip()
    if text in BLANK_FAILURES:
        return {"failureClassified": False, "failureMessage": NO_STORED_FAILURE}
    if len(text) > FAILURE_LIMIT:
        text = text[: FAILURE_LIMIT - 1] + "…"
    return {"failureClassified": True, "failureMessage": text}


def activity_sentence(name: str, status: str) -> str:
    quoted = f"「{name}」"
    if status == "COMPLETED":
        return f"{quoted}を取り込みました"
    if status == "EMPTY":
        return f"{quoted}は取り込む本文がありませんでした"
    if status == "FAILED":
        return f"{quoted}を取り込めませんでした"
    if status == "IN_PROGRESS":
        return f"{quoted}を取り込んでいます"
    if status == "QUEUED":
        return f"{quoted}を取り込み待ちにしました"
    if status == "AUTO_INDEX_OFF":
        return f"{quoted}は自動取り込みを止めています"
    if status == "NOT_STARTED":
        return f"{quoted}はまだ取り込んでいません"
    return f"{quoted}の状態は分類できません"


def pause_deadline(kind: str, now: datetime) -> datetime | None:
    if kind not in PAUSE_KINDS:
        raise ValueError(kind)
    if kind == "30m":
        return now + timedelta(minutes=30)
    if kind == "1h":
        return now + timedelta(hours=1)
    if kind == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def pause_is_active(kind: str | None, until: datetime | None, now: datetime) -> bool:
    if not kind:
        return False
    if kind == "resume":
        return True
    if until is None:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return until > now
