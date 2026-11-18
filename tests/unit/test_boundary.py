"""Header checks, retrieve body, and the index fingerprint.

Principle: boundary discipline. These are the values a caller can send and read back.
PipesHub: backend/python/app/connectors/sources/localKB/push/admission.py
and backend/python/tests/unit/api/routes/test_retrieve.py.
"""

import pytest

from kbindex.api import admit, parse_retrieve
from kbindex.config import Settings, load_settings
from kbindex.contract import MAX_BODY_BYTES, PushRefusal
from kbindex.stream import publish_stream, stream_names


def _settings(**over) -> Settings:
    base = dict(
        database_url="postgresql://kbindex@127.0.0.1/kbindex",
        redis_url="redis://127.0.0.1/0",
        qdrant_url="http://127.0.0.1:6333",
        data_dir="/data/records",
        model="cl-nagoya/ruri-v3-310m",
        device="cpu",
        backend="sentence-transformers",
        tokenizers=("sudachi", "char_bigram"),
        sudachi_mode="C",
        sudachi_normalize=True,
        fusion_method="rrf",
        fusion_k=60,
        bm25_k1=1.2,
        bm25_b=0.75,
        api_port=43123,
    )
    base.update(over)
    return Settings(**base)


def test_content_type_and_length():
    admit("application/json", None, b"{}")
    admit("application/blocks; charset=utf-8", "2", b"{}")
    with pytest.raises(PushRefusal) as plain:
        admit("text/plain", None, b"{}")
    assert (plain.value.status, plain.value.reason) == (415, "UNSUPPORTED_MEDIA_TYPE")
    with pytest.raises(PushRefusal) as bad:
        admit("application/json", "nope", b"{}")
    assert (bad.value.status, bad.value.reason) == (400, "INVALID_CONTENT_LENGTH")
    with pytest.raises(PushRefusal) as huge:
        admit("application/json", str(MAX_BODY_BYTES + 1), b"{}")
    assert huge.value.status == 413 and huge.value.extra["limitBytes"] == MAX_BODY_BYTES
    with pytest.raises(PushRefusal) as body:
        admit("application/json", None, b"x" * (MAX_BODY_BYTES + 1))
    assert body.value.status == 413


def test_retrieve_bounds():
    assert parse_retrieve({"query": "東京"})["limit"] == 10
    parsed = parse_retrieve({
        "query": "  東京  ",
        "limit": 1,
        "filters": {"kb": ["demo"], "allowedApps": ["x"]},
        "maxChunksPerRecord": 1,
    })
    assert parsed["query"] == "東京" and parsed["kb_ids"] == ["demo"] and parsed["max_per"] == 1
    with pytest.raises(PushRefusal) as empty:
        parse_retrieve({"query": "   "})
    assert empty.value.status == 400
    with pytest.raises(PushRefusal) as low:
        parse_retrieve({"query": "東京", "limit": 0})
    assert low.value.status == 422
    with pytest.raises(PushRefusal) as high:
        parse_retrieve({"query": "東京", "limit": 11})
    assert high.value.status == 422
    assert parse_retrieve({"query": "東京", "limit": 10})["limit"] == 10
    with pytest.raises(PushRefusal) as unknown:
        parse_retrieve({"query": "東京", "filters": {"kbId": "demo"}})
    assert unknown.value.status == 400
    with pytest.raises(PushRefusal) as rewrite:
        parse_retrieve({"query": "東京", "rewriteQuery": True})
    assert (rewrite.value.status, rewrite.value.reason) == (400, "REWRITE_DISABLED")
    with pytest.raises(PushRefusal) as date:
        parse_retrieve({"query": "東京", "createdAfter": "yesterday"})
    assert date.value.status == 400
    day = parse_retrieve({"query": "東京", "createdAfter": "2026-11-17", "modifiedBefore": "2026-11-17T00:00:00Z"})
    assert day["bounds"]["created_after"].tzinfo is not None
    assert day["bounds"]["modified_before"].tzinfo is not None


def test_tuning_defaults_are_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "bm25:\n  k1: 1.5\n  b: 0.4\nkeyword:\n  char_bigram:\n    casefold: true\n    drop_punct: true\nredis:\n  lanes: 8\n",
        encoding="utf-8",
    )
    loaded = load_settings(str(path))
    assert (loaded.bm25_k1, loaded.bm25_b, loaded.bigram_casefold, loaded.bigram_drop_punct, loaded.redis_lanes) == (
        1.5,
        0.4,
        True,
        True,
        8,
    )
    path.write_text("redis:\n  lanes: 0\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_settings(str(path))


def test_lane_names_follow_pipeshub():
    assert stream_names(1) == ("record-events",)
    assert publish_stream("rec", 1) == "record-events"
    names = stream_names(8)
    assert names[0] == "record-events"
    assert names[1:] == tuple(f"record-events.{lane}" for lane in range(8))
    placed = publish_stream("same-record", 8)
    assert placed == publish_stream("same-record", 8)
    assert placed in names[1:]


def test_fusion_k_is_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("fusion:\n  method: rrf\n  k: 2\n", encoding="utf-8")
    assert load_settings(str(path)).fusion_k == 2
    path.write_text("fusion:\n  method: dbsf\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_settings(str(path))


def test_query_and_document_are_the_same_string():
    from kbindex.embed import FakeEmbedder

    embedder = FakeEmbedder()
    text = "東京都の天気"
    assert embedder.embed_query(text) == embedder.embed_documents([text])[0]


def test_legs_selects_named_retrievers():
    parsed = parse_retrieve({"query": "首都", "legs": ["dense", "sudachi"]})
    assert parsed["legs"] == ("dense", "sudachi")
    parsed = parse_retrieve({"query": "首都", "legs": ["dense", "fastembed"]})
    assert parsed["legs"] == ("dense", "fastembed")
    with pytest.raises(PushRefusal) as unknown:
        parse_retrieve({"query": "首都", "legs": ["sparse"]})
    assert unknown.value.status == 400


def test_shipped_config_loads_tokenizer_flags_into_the_fingerprint():
    import yaml
    from dataclasses import replace
    from pathlib import Path

    raw = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    loaded = load_settings("config.yaml")
    sudachi = raw["keyword"]["sudachi"]
    bigram = raw["keyword"]["char_bigram"]
    assert loaded.sudachi_mode == sudachi["mode"]
    assert loaded.sudachi_normalize is sudachi["normalize"]
    assert loaded.bigram_nfkc is bigram["nfkc"]
    assert loaded.bigram_casefold is bigram["casefold"]
    assert loaded.bigram_drop_space is bigram["drop_space"]
    assert loaded.bigram_drop_control is bigram["drop_control"]
    assert loaded.bigram_drop_punct is bigram["drop_punct"]
    base = loaded.index_fingerprint(hidden_size=768, max_seq_length=8192)
    flipped = replace(loaded, bigram_drop_punct=not loaded.bigram_drop_punct)
    assert flipped.index_fingerprint(hidden_size=768, max_seq_length=8192) != base


def test_fingerprint_ignores_device_and_bm25():
    cpu = _settings(device="cpu", bm25_k1=1.2)
    cuda = _settings(device="cuda", bm25_k1=2.0)
    assert cpu.index_fingerprint(hidden_size=768, max_seq_length=8192) == cuda.index_fingerprint(
        hidden_size=768, max_seq_length=8192
    )
    renamed = _settings(model="other")
    assert cpu.index_fingerprint(hidden_size=768, max_seq_length=8192) != renamed.index_fingerprint(
        hidden_size=768, max_seq_length=8192
    )
    assert cpu.index_fingerprint(hidden_size=768, max_seq_length=8192) == _settings(fusion_k=2).index_fingerprint(
        hidden_size=768, max_seq_length=8192
    )
    assert cpu.index_fingerprint(hidden_size=768, max_seq_length=8192) != _settings(fusion_method="other").index_fingerprint(
        hidden_size=768, max_seq_length=8192
    )
    punct = _settings(bigram_drop_punct=True)
    assert cpu.index_fingerprint(hidden_size=768, max_seq_length=8192) != punct.index_fingerprint(
        hidden_size=768, max_seq_length=8192
    )
    assert cpu.index_fingerprint(hidden_size=768, max_seq_length=8192) == _settings(redis_lanes=8, bm25_b=0.5).index_fingerprint(
        hidden_size=768, max_seq_length=8192
    )
