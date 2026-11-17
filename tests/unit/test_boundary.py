"""Header checks, retrieve body, and the index fingerprint.

Principle: boundary discipline. These are the values a caller can send and read back.
PipesHub: backend/python/app/connectors/sources/localKB/push/admission.py
and backend/python/tests/unit/api/routes/test_retrieve.py.
"""

import pytest

from kbindex.api import admit, parse_retrieve
from kbindex.config import Settings
from kbindex.contract import MAX_BODY_BYTES, PushRefusal


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


def test_query_and_document_prefixes_differ():
    from kbindex.embed import FakeEmbedder

    embedder = FakeEmbedder()
    text = "東京都の天気"
    assert embedder.embed_query(text) != embedder.embed_documents([text])[0]


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
