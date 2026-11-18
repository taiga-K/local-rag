"""Retrieve cuts match PipesHub 426fc25, not the previous kbindex defaults."""

import os

from kbindex.retrieve_cut import (
    finish_retrieve,
    internal_limit,
    leg_depth,
    passages_per_record,
    typed_text_pattern,
)


def _row(chunk_id: str, score: float, record: str, text: str):
    return {"id": chunk_id, "score": score, "record": record, "text": text}


def _finish(rows, *, limit, query, max_per=None):
    return finish_retrieve(
        rows,
        page_limit=limit,
        query=query,
        max_per_record=max_per,
        record_of=lambda row: row["record"],
        text_of=lambda row: row["text"],
    )


def test_omitted_cap_keeps_four_from_one_record():
    rows = [_row(f"c{i}", 10 - i, "same", f"本文{i}") for i in range(5)]
    kept = _finish(rows, limit=10, query="質問")
    assert passages_per_record(10) == 4
    assert [row["id"] for row in kept] == ["c0", "c1", "c2", "c3"]


def test_fusion_window_is_limit_plus_two():
    rows = [_row(f"c{i}", 20 - i, f"r{i}", f"本文{i}") for i in range(8)]
    kept = _finish(rows, limit=2, query="質問")
    ids = [row["id"] for row in kept]
    assert ids == ["c0", "c1"]
    assert "c4" not in ids


def test_exact_query_string_is_kept_ahead_of_a_higher_score():
    rows = [
        _row("high", 5, "a", "別の文章"),
        _row("mid", 4, "b", "もう一つ"),
        _row("match", 1, "c", "ここに 赤い りんご がある"),
    ]
    kept = _finish(rows, limit=1, query="赤い りんご")
    assert [row["id"] for row in kept] == ["match"]
    pattern = typed_text_pattern("赤い りんご")
    assert pattern is not None and pattern.search("赤いりんご") is None
    assert pattern.search("赤い りんご") is not None


def test_specified_first_stage_cap_is_six():
    assert internal_limit(10, 10) == 40
    assert passages_per_record(40) == 6
    assert leg_depth(10, 1) == 80
    rows = [_row(f"c{i}", 20 - i, "same", f"本文{i}") for i in range(7)]
    kept = _finish(rows, limit=10, query="本文", max_per=10)
    assert [row["id"] for row in kept] == [f"c{i}" for i in range(6)]


def test_specified_path_does_not_promote_the_query_string():
    rows = [
        _row("high", 5, "a", "別の文章"),
        _row("match", 1, "b", "赤い りんご"),
    ]
    kept = _finish(rows, limit=1, query="赤い りんご", max_per=1)
    assert [row["id"] for row in kept] == ["high"]


def test_floor_env_changes_the_omitted_cap(monkeypatch):
    monkeypatch.setenv("SEARCH_PER_RECORD_FLOOR", "2")
    monkeypatch.setenv("SEARCH_PER_RECORD_DIVISOR", "6")
    assert passages_per_record(10) == 2
    os.environ.pop("SEARCH_PER_RECORD_FLOOR", None)
    os.environ.pop("SEARCH_PER_RECORD_DIVISOR", None)
