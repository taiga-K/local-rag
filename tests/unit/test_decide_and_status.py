"""Version table and indexingStatus transitions.

Principle: test behavior, not helpers. Callers observe the action and the next status.
PipesHub: tests/integration/graph_db/test_kb_push_real_backends.py
and the missing transition table noted in test_viewpoints.md gap 7.
"""

import pytest

from kbindex.decide import decide
from kbindex.status import apply


@pytest.mark.parametrize(
    "stored,digest,version,incoming,action,http,reason",
    [
        (None, None, 1, "a", "create", 201, None),
        (1, "a", 1, "a", "unchanged", 200, None),
        (1, "a", 1, "b", "conflict", 409, "VERSION_CONFLICT"),
        (2, "a", 1, "b", "stale", 409, "STALE_VERSION"),
        (1, "a", 2, "a", "metadata", 200, None),
        (1, "a", 2, "b", "content", 200, None),
        (0, "a", 0, "a", "unchanged", 200, None),
    ],
)
def test_version_table(stored, digest, version, incoming, action, http, reason):
    got = decide(
        stored_version=stored,
        stored_blocks_sha=digest,
        stored_request_digest=digest,
        version=version,
        blocks_sha=incoming,
        request_digest=incoming,
    )
    assert (got.action, got.http_status, got.reason) == (action, http, reason)
    if reason:
        assert got.current_version == stored


def test_same_blocks_different_request_digest():
    conflict = decide(
        stored_version=1,
        stored_blocks_sha="blocks",
        stored_request_digest="req-a",
        version=1,
        blocks_sha="blocks",
        request_digest="req-b",
    )
    assert (conflict.action, conflict.reason, conflict.current_version) == ("conflict", "VERSION_CONFLICT", 1)
    metadata = decide(
        stored_version=1,
        stored_blocks_sha="blocks",
        stored_request_digest="req-a",
        version=2,
        blocks_sha="blocks",
        request_digest="req-b",
    )
    assert metadata.action == "metadata" and metadata.http_status == 200


def test_reprocess_and_lifecycle():
    assert apply(None, "push").status == "QUEUED"
    assert apply(None, "push", has_text=False).status == "EMPTY"
    assert apply("QUEUED", "claim").status == "IN_PROGRESS"
    assert apply("IN_PROGRESS", "succeed").status == "COMPLETED"
    assert apply("IN_PROGRESS", "succeed", has_text=False).status == "EMPTY"
    failed = apply("IN_PROGRESS", "fail", reason="QDRANT_UNAVAILABLE")
    assert (failed.status, failed.failure_reason) == ("FAILED", "QDRANT_UNAVAILABLE")
    assert apply("FAILED", "reprocess").status == "QUEUED"
    assert apply("COMPLETED", "reprocess").status == "QUEUED"
    assert apply("EMPTY", "reprocess").status == "QUEUED"
    assert apply("QUEUED", "reprocess").status == "QUEUED"
    refused = apply("IN_PROGRESS", "reprocess")
    assert refused.refused == "IN_PROGRESS" and refused.status == "IN_PROGRESS"
    assert apply("COMPLETED", "delete").refused == "RECORD_GONE"


def test_claim_only_from_queued():
    assert apply("COMPLETED", "claim").refused == "NOT_QUEUED"


def test_content_update_queues_and_metadata_keeps_status():
    assert apply("COMPLETED", "push").status == "QUEUED"
    assert apply("FAILED", "push", has_text=False).status == "QUEUED"
    kept = apply("FAILED", "metadata", reason="QDRANT_UNAVAILABLE")
    assert (kept.status, kept.failure_reason) == ("FAILED", "QDRANT_UNAVAILABLE")
