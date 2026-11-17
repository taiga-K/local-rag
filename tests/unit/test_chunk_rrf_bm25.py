"""Chunk boundaries, Japanese tokens, BM25, RRF.

Principle: behavior. Expected scores are computed from the formula, not from the function under test.
PipesHub gap 6: tests/unit/modules/parsers/test_text_splitting.py has no ja case.
PipesHub RRF: tests/unit/modules/retrieval/test_result_merging.py keeps the best rank.
We sum independent retrievers. Gap 3: table cells are not replaced by a summary.
"""

import json

from kbindex.bm25 import Corpus
from kbindex.chunking import chunk_blocks
from kbindex.config import Settings
from kbindex.contract import block_text, parse_envelope
from kbindex.db import chunk_public_id
from kbindex.embed import FakeEmbedder
from kbindex.pipeline import Engine
from kbindex.rrf import rrf_scores
from kbindex.tokenize import char_bigrams, sudachi_terms


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
    assert char_bigrams("Ab") == ["Ab"]
    assert char_bigrams("Ab", casefold=True) == ["ab"]
    assert char_bigrams("a.b", drop_punct=True) == ["ab"]
    assert char_bigrams("a.b") == ["a.", ".b"]


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


def test_each_branch_fetches_twice_the_retrieve_limit():
    """Candidate depth is the request limit times 2, then RRF uses fusion.k.

    PipesHub: backend/python/app/services/vector_db/qdrant/utils.py L280-L309
    at acc3095. One dense prefetch and one sparse prefetch, each limit*2,
    fused with Fusion.RRF and no k (Qdrant default 2). The approved k here is 60.
    """
    class Vectors:
        def __init__(self) -> None:
            self.limits: list[int] = []

        def search(self, vector, *, limit, kb_ids):
            self.limits.append(limit)
            return [("c1", 0.9), ("c2", 0.4)]

    def row(chunk_id: str) -> dict:
        return {
            "chunk_id": chunk_id,
            "text": chunk_id,
            "external_record_id": "ext",
            "record_name": "n",
            "kb_id": "kb",
            "block_index": 0,
            "source_modified_ms": None,
            "updated_at": None,
        }

    def run(k: int) -> tuple[dict, list[int]]:
        vectors = Vectors()
        engine = Engine(_fusion_settings(k), db=None, vectors=vectors, embedder=FakeEmbedder())
        seen: dict[str, int] = {}

        def bm25(tokenizer: str, query: str, limit: int):
            seen[tokenizer] = limit
            if tokenizer == "sudachi":
                return [("c1", 3.0)]
            return []

        engine._bm25 = bm25
        engine._filter_fused = lambda fused, kb_ids, bounds: [(cid, score, row(cid)) for cid, score in fused]
        found = engine.search("晴れ", limit=4, kb_ids=None, max_per_record=None, bounds={})
        return found, [vectors.limits[0], seen["sudachi"], seen["char_bigram"]]

    found, depths = run(60)
    assert depths == [8, 8, 8]
    assert found["chunks"][0]["score"] == pytest_approx(2 / 61)
    found_k2, depths_k2 = run(2)
    assert depths_k2 == [8, 8, 8]
    assert found_k2["chunks"][0]["score"] == pytest_approx(2 / 3)


def _fusion_settings(k: int):
    return Settings(
        database_url="postgresql://kbindex@127.0.0.1/kbindex",
        redis_url="redis://127.0.0.1/0",
        qdrant_url="http://127.0.0.1:6333",
        data_dir="/data/records",
        model="cl-nagoya/ruri-v3-310m",
        device="cpu",
        backend="fake",
        tokenizers=("sudachi", "char_bigram"),
        sudachi_mode="C",
        sudachi_normalize=True,
        fusion_method="rrf",
        fusion_k=k,
        bm25_k1=1.2,
        bm25_b=0.75,
        api_port=43123,
    )


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
