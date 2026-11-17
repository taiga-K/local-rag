"""Reciprocal rank fusion. Ranks are 1-based. Missing lists contribute 0."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def rrf_scores(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse independent retrievers by summing 1/(k+rank).

    PipesHub's cross-collection merger keeps the best rank instead of the sum
    (`result_merging.py`). These lists are different retrievers, so the
    contributions add.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[str, float] = {}
    order: list[str] = []
    for ranking in rankings:
        for index, chunk_id in enumerate(ranking, start=1):
            if chunk_id not in scores:
                order.append(chunk_id)
                scores[chunk_id] = 0.0
            scores[chunk_id] += 1.0 / (k + index)
    ranked = sorted(order, key=lambda cid: (-scores[cid], order.index(cid)))
    return [(cid, scores[cid]) for cid in ranked]


def ranks_of(ranking: Sequence[str]) -> dict[str, int]:
    return {chunk_id: index for index, chunk_id in enumerate(ranking, start=1)}


def breakdown_row(
    chunk_id: str,
    *,
    dense: Sequence[tuple[str, float]],
    keywords: Mapping[str, Sequence[tuple[str, float]]],
    fused: float,
) -> dict[str, object]:
    def leg(pairs: Sequence[tuple[str, float]]) -> dict[str, float | int] | None:
        for rank, (cid, score) in enumerate(pairs, start=1):
            if cid == chunk_id:
                return {"rank": rank, "score": score}
        return None

    return {
        "chunkId": chunk_id,
        "dense": leg(dense),
        "keyword": {name: leg(pairs) for name, pairs in keywords.items()},
        "rrf": fused,
    }
