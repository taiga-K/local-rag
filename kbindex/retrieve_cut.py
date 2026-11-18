"""Retrieve cuts copied from PipesHub 426fc25.

Omitted maxChunksPerRecord: each leg already fetched ``limit * 2``. Fusion
keeps ``limit + 2`` and the page is cut to ``limit``. A record keeps
``max(SEARCH_PER_RECORD_FLOOR, limit // SEARCH_PER_RECORD_DIVISOR)`` passages
(record_cut.py L146-L150, defaults 4 and 6). When more than ``limit`` remain,
a chunk whose text matches the query with ``(?<!\\w)...(?!\\w)`` is kept
first (search.py ``_typed_text_pattern`` / ``_apply_result_limit``).

Specified maxChunksPerRecord: the internal limit is ``min(limit * 4, 200)``.
That page is capped at ``passages_per_record(internal)`` (6 when limit is 10),
then by the caller's value, then cut to ``limit``. No string priority.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

PER_RECORD_FLOOR_ENV = "SEARCH_PER_RECORD_FLOOR"
PER_RECORD_DIVISOR_ENV = "SEARCH_PER_RECORD_DIVISOR"
DEFAULT_FLOOR = 4
DEFAULT_DIVISOR = 6
TIE_MARGIN = 2
SPECIFIED_OVERFETCH = 4
SPECIFIED_CAP = 200


def internal_limit(limit: int, max_per_record: int | None) -> int:
    if max_per_record is None:
        return limit
    return min(limit * SPECIFIED_OVERFETCH, SPECIFIED_CAP)


def leg_depth(limit: int, max_per_record: int | None) -> int:
    return internal_limit(limit, max_per_record) * 2


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def passages_per_record(limit: int) -> int:
    floor = _env_int(PER_RECORD_FLOOR_ENV, DEFAULT_FLOOR)
    divisor = _env_int(PER_RECORD_DIVISOR_ENV, DEFAULT_DIVISOR)
    if divisor <= 0:
        divisor = DEFAULT_DIVISOR
    return max(floor, limit // divisor)


def typed_text_pattern(typed: str) -> re.Pattern[str] | None:
    words = typed.split()
    if not words:
        return None
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)", re.IGNORECASE)


def cap_per_record(items: Sequence[T], per_record: int, record_of: Callable[[T], str | None]) -> list[T]:
    """Keep the first ``per_record`` hits of each record. Input is best-first."""
    per_record = max(per_record, 1)
    seen: dict[str, int] = {}
    kept: list[T] = []
    for item in items:
        record = record_of(item)
        if record is None:
            kept.append(item)
            continue
        if seen.get(record, 0) >= per_record:
            continue
        seen[record] = seen.get(record, 0) + 1
        kept.append(item)
    return kept


def apply_string_priority(
    items: Sequence[T],
    limit: int,
    query: str,
    text_of: Callable[[T], str],
) -> list[T]:
    """When more than ``limit`` hits remain, exact query matches come first."""
    if len(items) <= limit:
        return list(items[:limit])
    pattern = typed_text_pattern(query)
    if pattern is None:
        return list(items[:limit])

    def holds(item: T) -> bool:
        text = text_of(item)
        return isinstance(text, str) and pattern.search(text) is not None

    promoted = [item for item in items if holds(item)]
    rest = [item for item in items if not holds(item)]
    return (promoted + rest)[:limit]


def finish_retrieve(
    fused: Sequence[T],
    *,
    page_limit: int,
    query: str,
    max_per_record: int | None,
    record_of: Callable[[T], str | None],
    text_of: Callable[[T], str],
) -> list[T]:
    """Cut a best-first fused list the way PipesHub retrieve does."""
    internal = internal_limit(page_limit, max_per_record)
    window = list(fused[: internal + TIE_MARGIN])
    if max_per_record is None:
        capped = cap_per_record(window, passages_per_record(page_limit), record_of)
        return apply_string_priority(capped, page_limit, query, text_of)
    staged = cap_per_record(window[:internal], passages_per_record(internal), record_of)
    filtered = cap_per_record(staged, max_per_record, record_of)
    return filtered[:page_limit]
