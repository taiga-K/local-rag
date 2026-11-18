"""Chunk text and RRF scores. Keyword legs are fastembed, not Sudachi."""

import json

from kbindex.contract import block_text, parse_envelope
from kbindex.retrieve_cut import leg_depth
from kbindex.rrf import rrf_scores


def test_rrf_is_one_over_rank_plus_one():
    """Qdrant RRF is 1/(position+2) with position starting at 0, which is k=1 here."""
    fused = dict(rrf_scores([["a", "b"], ["b"]], k=1))
    assert fused["a"] == pytest_approx(1 / 2)
    assert fused["b"] == pytest_approx(1 / 3 + 1 / 2)


def test_rrf_tie_breaks_by_id():
    ranked = [chunk_id for chunk_id, _score in rrf_scores([["c", "a"], ["c", "b"]], k=1)]
    assert ranked == ["c", "a", "b"]


def test_leg_depth_follows_the_retrieve_cap():
    assert leg_depth(10, None) == 20
    assert leg_depth(10, 1) == 80
    assert leg_depth(8, None) == 16


def test_rrf_rejects_non_positive_k():
    try:
        rrf_scores([["a"]], k=0)
    except ValueError:
        return
    raise AssertionError("k=0 must fail")


def test_table_cells_are_not_replaced():
    raw = json.dumps({
        "recordName": "表",
        "mimeType": "application/blocks",
        "externalRecordId": "t",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "table_row", "data": {"cells": ["気温", "二十度"]}}]},
    }).encode()
    text = block_text(parse_envelope(raw).blocks.blocks[0])
    assert text == "気温\t二十度"
    assert "要約" not in text


def pytest_approx(value: float):
    import pytest
    return pytest.approx(value)
