"""Chunk boundaries, Japanese tokens, BM25, RRF.

Principle: behavior. Expected scores are computed from the formula, not from the function under test.
PipesHub gap 6: tests/unit/modules/parsers/test_text_splitting.py has no ja case.
PipesHub RRF: tests/unit/modules/retrieval/test_result_merging.py keeps the best rank.
We sum independent retrievers. Gap 3: table cells are not replaced by a summary.
"""

from kbindex.bm25 import Corpus
from kbindex.chunking import chunk_blocks
from kbindex.db import chunk_public_id
from kbindex.contract import block_text, parse_envelope
from kbindex.rrf import rrf_scores
from kbindex.tokenize import char_bigrams, sudachi_terms
import json


def test_short_block_is_one_piece():
    pieces = chunk_blocks([(0, "東京都の天気")], window=20)
    assert [p.text for p in pieces] == ["東京都の天気"]


def test_empty_block_yields_nothing():
    assert chunk_blocks([(0, "   ")], window=8) == []


def test_window_edges_rejoin_without_overlap():
    text = "あいうえお"
    exact = chunk_blocks([(0, text[:4])], window=4)
    over = chunk_blocks([(1, text)], window=4)
    assert len(exact) == 1 and exact[0].text == text[:4] and exact[0].token_count == 4
    assert [p.text for p in over] == ["あいうえ", "お"]
    assert "".join(p.text for p in over) == text
    assert over[0].text[-1] not in over[1].text


def test_public_id_adds_piece_only_after_the_first_slice():
    assert chunk_public_id("rec", 2, 0, 1) == "rec:2"
    assert chunk_public_id("rec", 2, 0, 3) == "rec:2"
    assert chunk_public_id("rec", 2, 1, 3) == "rec:2:1"


def test_two_blocks_only_the_long_one_grows_piece():
    pieces = chunk_blocks([(0, "短い"), (1, "あいうえおか")], window=3)
    assert [(p.block_index, p.piece) for p in pieces] == [(0, 0), (1, 0), (1, 1)]


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
    assert char_bigrams("ＡＢ") == ["AB"]
    assert char_bigrams("a\x00b") == ["ab"]


def test_bm25_prefers_the_document_that_contains_the_term():
    corpus = Corpus()
    corpus.add("yes", sudachi_terms("東京都の天気は晴れ", mode="C"))
    corpus.add("no", sudachi_terms("大阪の人口", mode="C"))
    ranked = corpus.rank(sudachi_terms("東京の天気", mode="C"))
    assert ranked[0][0] == "yes"
    assert ranked[0][1] > 0
    # k1 changes the score and not the term set.
    terms = sudachi_terms("東京都の天気は晴れ", mode="C")
    other_terms = sudachi_terms("大阪の人口", mode="C")
    other = Corpus(k1=2.0)
    other.add("yes", terms)
    other.add("no", other_terms)
    assert set(other.df) == set(corpus.df)
    assert other.score("yes", ["天気"]) != corpus.score("yes", ["天気"])


def test_rrf_hand_computed():
    fused = dict(rrf_scores([["a", "b"], ["b"]], k=60))
    assert fused["a"] == pytest_approx(1 / 61)
    assert fused["b"] == pytest_approx(1 / 62 + 1 / 61)
    assert list(dict(rrf_scores([["a"], []], k=60)))[0] == "a"


def test_rrf_tie_keeps_input_order():
    ranked = [chunk_id for chunk_id, _score in rrf_scores([["c", "a"], ["c", "b"]], k=60)]
    assert ranked == ["c", "a", "b"]
    assert dict(rrf_scores([["a"], []], k=60))["a"] == pytest_approx(1 / 61)
    assert dict(rrf_scores([["a"], ["a"]], k=60))["a"] == pytest_approx(2 / 61)


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
