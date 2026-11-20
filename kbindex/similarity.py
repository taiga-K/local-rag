"""Cosine against the stored dense vector, after RRF and before the page cut.

The threshold number lives only in ``DEFAULT_SCORE_THRESHOLD``. A null
``app_settings.score_threshold`` means that constant. Swap the constant to
change the default; stored values stay as the operator set them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

DEFAULT_SCORE_THRESHOLD = 0.5


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
