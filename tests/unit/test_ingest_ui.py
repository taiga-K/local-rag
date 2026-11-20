"""Failure copy stays inside reasons the indexer actually records."""

from datetime import datetime, timedelta, timezone

from kbindex.ingest_ui import activity_sentence, failure_fields, pause_deadline, pause_is_active


def test_only_qdrant_has_a_classified_sentence():
    shown = failure_fields("FAILED", "QDRANT_UNAVAILABLE")
    assert shown == {"failureClassified": True, "failureMessage": "QDRANT_UNAVAILABLE"}
    hidden = failure_fields("FAILED", "INDEX_FAILED")
    assert hidden["failureClassified"] is False
    assert "原因が記録されていません" in str(hidden["failureMessage"])
    long = failure_fields("FAILED", "x" * 180)
    assert long["failureClassified"] is True
    assert str(long["failureMessage"]).endswith("…")
    assert len(str(long["failureMessage"])) == 160
    assert failure_fields("FAILED", "ValueError: bad block")["failureMessage"] == "ValueError: bad block"
    assert failure_fields("COMPLETED", "QDRANT_UNAVAILABLE")["failureMessage"] is None


def test_activity_lines_follow_the_status():
    assert activity_sentence("議事録", "COMPLETED") == "「議事録」を取り込みました"
    assert activity_sentence("議事録", "FAILED") == "「議事録」を取り込めませんでした"
    assert "分類できません" in activity_sentence("議事録", "SOMETHING_ELSE")


def test_pause_until_resume_stays_until_cleared():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert pause_deadline("resume", now) is None
    assert pause_is_active("resume", None, now) is True
    until = pause_deadline("30m", now)
    assert until == now + timedelta(minutes=30)
    assert pause_is_active("30m", until, now) is True
    assert pause_is_active("30m", until, until) is False
    assert pause_is_active(None, None, now) is False
