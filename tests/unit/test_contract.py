"""Push envelope equivalence classes and boundaries.

Principle: behavior. The refusal status and reason are what the HTTP layer returns.
PipesHub: tests/unit/connectors/sources/localKB/push/test_contract.py
"""

import json

import pytest

from kbindex.contract import PushRefusal, blocks_digest, parse_envelope


def envelope(**over) -> bytes:
    body = {
        "recordName": "案内",
        "mimeType": "application/blocks",
        "externalRecordId": "doc-1",
        "version": 1,
        "blocksFormat": 1,
        "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": "こんにちは。"}]},
    }
    body.update(over)
    return json.dumps(body).encode()


def refusal(raw: bytes) -> PushRefusal:
    with pytest.raises(PushRefusal) as caught:
        parse_envelope(raw)
    return caught.value


def test_equivalent_json_has_one_digest():
    forms = [
        envelope(),
        json.dumps(json.loads(envelope()), sort_keys=True).encode(),
    ]
    assert len({blocks_digest(parse_envelope(raw).blocks) for raw in forms}) == 1


def test_changed_text_changes_digest():
    a = blocks_digest(parse_envelope(envelope()).blocks)
    b = blocks_digest(parse_envelope(envelope(blocks={"blocks": [{"index": 0, "type": "text", "data": "別"}]})).blocks)
    assert a != b


@pytest.mark.parametrize("version", [0, 2**53 - 1])
def test_version_bounds(version):
    assert parse_envelope(envelope(version=version)).version == version


@pytest.mark.parametrize("version", [-1, 2**53, "1", 1.0, True])
def test_version_refused(version):
    body = json.loads(envelope())
    body["version"] = version
    assert refusal(json.dumps(body).encode()).reason == "ENVELOPE_INVALID"


@pytest.mark.parametrize("ext", ["a", "A1", "k.v~w:x-y_z", "x" * 256])
def test_external_id_accepted(ext):
    assert parse_envelope(envelope(externalRecordId=ext)).externalRecordId == ext


@pytest.mark.parametrize("ext", ["", "x" * 257, "-lead", "a/b", "ok\n", "é"])
def test_external_id_refused(ext):
    got = refusal(envelope(externalRecordId=ext))
    assert (got.status, got.reason, got.location) == (400, "ENVELOPE_INVALID", "externalRecordId")


@pytest.mark.parametrize("name", ["", "   ", "x" * 256, "<b>x</b>", "a %s"])
def test_record_name_refused(name):
    assert refusal(envelope(recordName=name)).status == 400


def test_record_name_trimmed():
    assert parse_envelope(envelope(recordName="  hi  ")).recordName == "hi"


def test_unknown_key_and_strict_index():
    body = json.loads(envelope())
    body["extra"] = 1
    assert refusal(json.dumps(body).encode()).status == 400
    body = json.loads(envelope())
    body["blocks"]["blocks"][0]["index"] = "0"
    got = refusal(json.dumps(body).encode())
    assert (got.status, got.reason) == (422, "BLOCKS_INVALID")
    assert "index" in (got.location or "")


def test_empty_text_is_allowed():
    parsed = parse_envelope(envelope(blocks={"blocks": [{"index": 0, "type": "text", "data": ""}]}))
    assert parsed.blocks.blocks[0].data == ""


def test_malformed_json():
    assert refusal(b"{").reason == "INVALID_JSON"
    assert refusal(b"").status == 400


def test_index_must_match_position_and_depth():
    assert refusal(envelope(blocks={"blocks": [{"index": 1, "type": "text", "data": "a"}]})).status == 422
    groups = [{"index": i, "type": "list", **({"parent_index": i - 1} if i else {})} for i in range(64)]
    parse_envelope(envelope(blocks={"block_groups": groups}))
    groups.append({"index": 64, "type": "list", "parent_index": 63})
    assert refusal(envelope(blocks={"block_groups": groups})).status == 422


def test_pipeline_id_refused():
    body = json.loads(envelope())
    body["blocks"]["blocks"][0]["id"] = "b1"
    assert refusal(json.dumps(body).encode()).reason == "BLOCKS_INVALID"


def test_table_row_kept():
    blocks = {"blocks": [{"index": 0, "type": "table_row", "data": {"cells": ["気温", "20度"]}}]}
    parsed = parse_envelope(envelope(blocks=blocks))
    assert parsed.blocks.blocks[0].data.cells == ["気温", "20度"]
