"""Record indexing states. One status, the transitions in DESIGN.md."""

from __future__ import annotations

from dataclasses import dataclass

STATUSES = ("QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY")


@dataclass(frozen=True)
class Transition:
    status: str
    failure_reason: str | None
    refused: str | None = None


def apply(status: str | None, event: str, *, has_text: bool = True, ok: bool = True, reason: str | None = None) -> Transition:
    """Return the next status a caller can read back.

    `event` is push, claim, succeed, fail, reprocess, or delete.
    `delete` is represented by refused RECORD_GONE rather than a status.
    """
    if event == "delete":
        return Transition("", None, "RECORD_GONE")
    if event == "push":
        if status is None:
            return Transition("QUEUED" if has_text else "EMPTY", None)
        return Transition("QUEUED" if has_text else "EMPTY", None)
    if event == "claim":
        if status != "QUEUED":
            return Transition(status or "", None, "NOT_QUEUED")
        return Transition("IN_PROGRESS", None)
    if event == "succeed":
        if status != "IN_PROGRESS":
            return Transition(status or "", None, "NOT_IN_PROGRESS")
        if not has_text:
            return Transition("EMPTY", None)
        return Transition("COMPLETED", None)
    if event == "fail":
        if status != "IN_PROGRESS":
            return Transition(status or "", None, "NOT_IN_PROGRESS")
        return Transition("FAILED", reason or "INDEX_FAILED")
    if event == "reprocess":
        if status == "IN_PROGRESS":
            return Transition(status, None, "IN_PROGRESS")
        if status not in STATUSES:
            return Transition(status or "", None, "UNKNOWN")
        return Transition("QUEUED", None)
    raise ValueError(f"unknown event {event}")
