"""Closed reasons for a file the ingest tool did not push.

The confirmation screen prints `message` and does not invent a cause.
`models_missing` names the condition from the requirements. The exact sentence
was not specified there.
"""

from __future__ import annotations

SKIP_MESSAGES = {
    "unsupported": "読めない形式",
    "unreadable": "ファイルを読めませんでした",
    "feature_required": "追加機能が必要です",
    "models_missing": "モデルが未取得です",
    "scanned_pdf": "スキャンPDFのため読めません",
    "password": "パスワードがかかっているため読めません",
}


class ParseSkip(Exception):
    def __init__(self, reason: str) -> None:
        if reason not in SKIP_MESSAGES:
            raise ValueError(reason)
        super().__init__(reason)
        self.reason = reason


def skip_message(reason: str) -> str:
    try:
        return SKIP_MESSAGES[reason]
    except KeyError:
        raise ValueError(reason) from None
