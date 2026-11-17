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
    stored_digest: str | None,
    version: int,
    digest: str,
) -> Decision:
    """Match PipesHub `_decide` without trash, org, or images.

    `stored_digest` is the blocks digest already stored. `digest` is the
    incoming blocks digest. Equal digests are the same content.
    """
    if stored_version is None:
        return Decision("create", 201)
    if version < stored_version:
        return Decision("stale", 409, "STALE_VERSION", stored_version)
    if version == stored_version:
        if digest == stored_digest:
            return Decision("unchanged", 200)
        return Decision("conflict", 409, "VERSION_CONFLICT", stored_version)
    if digest == stored_digest:
        return Decision("metadata", 200)
    return Decision("content", 200)
