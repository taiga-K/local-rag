"""Header checks, retrieve body, and the index fingerprint.

Principle: boundary discipline. These are the values a caller can send and read back.
PipesHub: backend/python/app/connectors/sources/localKB/push/admission.py
and backend/python/tests/unit/api/routes/test_retrieve.py.
"""

import json

import pytest

from kbindex.api import admit, parse_retrieve
from kbindex.config import Settings, load_settings
from kbindex.contract import MAX_BODY_BYTES, PushRefusal
from kbindex.stream import publish, publish_stream, read_event, stream_names


def _settings(**over) -> Settings:
    base = dict(
        database_url="postgresql://kbindex@127.0.0.1/kbindex",
        redis_url="redis://127.0.0.1/0",
        qdrant_url="http://127.0.0.1:6333",
        data_dir="/data/records",
        model="cl-nagoya/ruri-v3-310m",
        device="cpu",
        backend="sentence-transformers",
        api_port=43123,
    )
    base.update(over)
    return Settings(**base)


def test_upload_limit_is_the_configured_cap():
    admit("application/json", "4", b"{}", limit=8)
    with pytest.raises(PushRefusal) as huge:
        admit("application/json", "9", b"123456789", limit=8)
    assert huge.value.status == 413 and huge.value.extra["limitBytes"] == 8


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
    assert parse_retrieve({"query": "東京"})["limit"] == 8
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
        parse_retrieve({"query": "東京", "limit": 51})
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


def test_redis_lanes_are_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("redis:\n  lanes: 8\n", encoding="utf-8")
    assert load_settings(str(path)).redis_lanes == 8
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


def test_crash_retry_generation_round_trips_and_defaults_to_zero():
    written = []

    class Redis:
        def xadd(self, _stream, fields):
            written.append(fields)
            return "1-0"

    client = Redis()
    publish(
        client,
        "reindexRecord",
        record_id="rec",
        kb_id="kb",
        external_record_id="doc",
        version=1,
        content_rev="rev",
        crash_retries=1,
    )
    publish(
        client,
        "newRecord",
        record_id="rec",
        kb_id="kb",
        external_record_id="doc",
        version=1,
        content_rev="rev",
    )

    assert read_event(written[0])["crashRetries"] == 1
    assert json.loads(written[0]["payload"])["crashRetries"] == 1
    assert read_event(written[1])["crashRetries"] == 0
    assert "crashRetries" not in json.loads(written[1]["payload"])


def test_retrieve_limit_defaults_to_eight_and_rejects_51():
    assert parse_retrieve({"query": "首都"})["limit"] == 8
    assert parse_retrieve({"query": "首都", "limit": 50})["limit"] == 50
    assert parse_retrieve({"query": "首都", "limit": 1})["limit"] == 1
    with pytest.raises(PushRefusal) as high:
        parse_retrieve({"query": "首都", "limit": 51})
    assert high.value.status == 422


def test_query_and_document_are_the_same_string():
    from kbindex.embed import FakeEmbedder

    embedder = FakeEmbedder()
    text = "東京都の天気"
    assert embedder.embed_query(text) == embedder.embed_documents([text])[0]


def test_shipped_config_is_the_embedding_example():
    loaded = load_settings("config.yaml")
    assert loaded.model == "cl-nagoya/ruri-v3-310m"
    assert loaded.device == "cpu"
