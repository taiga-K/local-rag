"""Version decision for one pushed record. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["create", "unchanged", "conflict", "stale", "metadata", "content"]


@dataclass(frozen=True)
class Decision:
    action: Action
    http_status: int
    reason: str | None = None
    current_version: int | None = None


def decide(
    *,
    stored_version: int | None,
    stored_blocks_sha: str | None,
    stored_request_digest: str | None,
    version: int,
    blocks_sha: str,
    request_digest: str,
) -> Decision:
    """One row of the push table.

    Same version compares the request digest. A higher version reindexes only
    when the blocks digest changes. Name and metadata keep the current status.
    """
    if stored_version is None:
        return Decision("create", 201)
    if version < stored_version:
        return Decision("stale", 409, "STALE_VERSION", stored_version)
    if version == stored_version:
        if request_digest == stored_request_digest:
            return Decision("unchanged", 200)
        return Decision("conflict", 409, "VERSION_CONFLICT", stored_version)
    if blocks_sha == stored_blocks_sha:
        return Decision("metadata", 200)
    return Decision("content", 200)
