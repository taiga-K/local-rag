"""Chunk boundaries, Japanese tokens, BM25, RRF.

Principle: behavior. Expected scores are computed from the formula, not from the function under test.
PipesHub gap 6: tests/unit/modules/parsers/test_text_splitting.py has no ja case.
PipesHub RRF: tests/unit/modules/retrieval/test_result_merging.py keeps the best rank.
We sum independent retrievers. Gap 3: table cells are not replaced by a summary.
"""

from kbindex.bm25 import Corpus
from kbindex.chunking import chunk_blocks
from kbindex.contract import block_text, parse_envelope
from kbindex.rrf import rrf_scores
from kbindex.tokenize import char_bigrams, sudachi_terms
import json


def test_short_block_is_one_piece():
    pieces = chunk_blocks([(0, "東京都の天気")], window=20)
    assert [p.text for p in pieces] == ["東京都の天気"]


def test_empty_block_yields_nothing():
    assert chunk_blocks([(0, "   ")], window=8) == []


def test_split_has_no_overlap_and_rejoins():
    text = "あいうえおかきくけこ"
    pieces = chunk_blocks([(3, text)], window=4)
    assert len(pieces) == 3
    assert "".join(p.text for p in pieces) == text
    assert pieces[0].block_index == 3 and [p.piece for p in pieces] == [0, 1, 2]
    # No shared character between neighbors.
    assert pieces[0].text[-1] != pieces[1].text[0]


def test_period_does_not_split_under_policy_b():
    text = "今日は晴れ。明日は雨。"
    pieces = chunk_blocks([(0, text)], window=50)
    assert len(pieces) == 1 and pieces[0].text == text


def test_japanese_boundary_character_stays_whole():
    pieces = chunk_blocks([(0, "漢字")], window=1)
    assert [p.text for p in pieces] == ["漢", "字"]
    assert "".join(p.text for p in pieces) == "漢字"


def test_sudachi_mode_c_keeps_tokyo():
    # Mode C does not split 東京都. Mode A does.
    assert "東京都" in sudachi_terms("東京都の天気", mode="C", normalize=True)
    assert "東京" in sudachi_terms("東京都", mode="A", normalize=True)


def test_normalize_form_for_verb():
    surface = sudachi_terms("走った", mode="C", normalize=False)
    normalized = sudachi_terms("走った", mode="C", normalize=True)
    assert surface != normalized
    assert normalized[0] == "走る"


def test_char_bigram_provisional():
    assert char_bigrams("ab c") == ["ab", "bc"]
    assert char_bigrams("") == []
    assert char_bigrams("あ") == []
    assert char_bigrams("あい") == ["あい"]
    assert char_bigrams("あいう") == ["あい", "いう"]
    assert char_bigrams("ＡＢ") == ["ab"]


def test_bm25_prefers_the_document_that_contains_the_term():
    corpus = Corpus()
    corpus.add("yes", sudachi_terms("東京都の天気は晴れ", mode="C"))
    corpus.add("no", sudachi_terms("大阪の人口", mode="C"))
    ranked = corpus.rank(sudachi_terms("東京の天気", mode="C"))
    assert ranked[0][0] == "yes"
    assert ranked[0][1] > 0
    # k1 changes the score and not the term set.
    other = Corpus(k1=2.0)
    other.add("yes", sudachi_terms("東京都の天気は晴れ", mode="C"))
    assert other.score("yes", ["天気"]) != corpus.score("yes", ["天気"])


def test_rrf_hand_computed():
    fused = dict(rrf_scores([["a", "b"], ["b"]], k=60))
    assert fused["a"] == pytest_approx(1 / 61)
    assert fused["b"] == pytest_approx(1 / 62 + 1 / 61)
    assert list(dict(rrf_scores([["a"], []], k=60)))[0] == "a"


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
