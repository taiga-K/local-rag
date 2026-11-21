"""Cosine against the stored dense vector, after RRF and before the page cut.

Named levels take their numbers from ``THRESHOLD_LEVELS``. ``custom`` stores
the operator's own number in ``app_settings.score_threshold``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

DEFAULT_SCORE_THRESHOLD = 0.84
CUSTOM_LEVEL = "custom"

# Measured on cl-nagoya/ruri-v3-310m. The grid in
# cursor/sim-threshold-measure d526787 measure/out/fine.json runs from 0.80
# through 0.86. At 0.86 every dataset keeps under 95% of answers among the
# 50 candidates. 0.88 was not measured, so strong is 0.86.
THRESHOLD_LEVELS: dict[str, float | None] = {
    "off": None,
    "weak": 0.80,
    "standard": DEFAULT_SCORE_THRESHOLD,
    "strong": 0.86,
}


def nearest_threshold_level(number: float) -> str:
    """Map a stored number onto a level. A tie keeps the lower number."""
    named = [(name, value) for name, value in THRESHOLD_LEVELS.items() if value is not None]
    return min(named, key=lambda item: (abs(item[1] - number), item[1]))[0]


def custom_threshold(number: object) -> float | None:
    """A custom cutoff from 0 to 1 with at most two decimal places."""
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return None
    if not math.isfinite(float(number)):
        return None
    cents = round(float(number) * 100)
    if cents < 0 or cents > 100:
        return None
    if abs(float(number) * 100 - cents) > 1e-6:
        return None
    return cents / 100


def resolve_threshold_level(level: str | None, *, enabled: bool, stored: float | None) -> str:
    """A saved level wins. An older numeric row maps to the nearest level. Unset is off.

    ``custom`` stays custom only when its number is still a valid cutoff.
    A legacy number is never read as custom.
    """
    if level == CUSTOM_LEVEL:
        if custom_threshold(stored) is None:
            return "off"
        return CUSTOM_LEVEL
    if level in THRESHOLD_LEVELS:
        return str(level)
    if not enabled or stored is None:
        return "off"
    return nearest_threshold_level(float(stored))


def threshold_for_level(level: str, stored: float | None = None) -> tuple[bool, float]:
    if level == CUSTOM_LEVEL:
        number = custom_threshold(stored)
        if number is None:
            return False, float(THRESHOLD_LEVELS["standard"])
        return True, number
    value = THRESHOLD_LEVELS[level]
    if value is None:
        return False, float(THRESHOLD_LEVELS["standard"])
    return True, float(value)


def cosine(query: Sequence[float], stored: Sequence[float]) -> float | None:
    """Real cosine. None when the lengths differ. A zero vector is 0.

    Embeddings are stored normalized. Dividing by the norms still matches a
    vector that was not, and keeps a zero vector from dividing by zero.
    """
    if len(query) != len(stored) or not query:
        return None
    dot = 0.0
    query_sq = 0.0
    stored_sq = 0.0
    for left, right in zip(query, stored, strict=True):
        dot += left * right
        query_sq += left * left
        stored_sq += right * right
    query_norm = math.sqrt(query_sq)
    stored_norm = math.sqrt(stored_sq)
    if query_norm == 0.0 or stored_norm == 0.0:
        return 0.0
    return dot / (query_norm * stored_norm)


def apply_score_threshold(
    fused: Sequence[tuple],
    similarities: Mapping[str, float | None],
    *,
    enabled: bool,
    threshold: float,
) -> list[tuple]:
    """Keep RRF order. Drop only when the threshold is on.

    A candidate stays when its similarity is equal to the threshold. A missing
    vector is None and is dropped only while the threshold is on.
    """
    kept: list[tuple] = []
    for cid, score, row in fused:
        similarity = similarities.get(cid)
        if enabled and (similarity is None or similarity < threshold):
            continue
        kept.append((cid, score, row, similarity))
    return kept
