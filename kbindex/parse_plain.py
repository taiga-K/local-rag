"""log and cfg keep the head and tail. A file over 50MiB is not read."""

from __future__ import annotations

from kbindex.blocks import document, text_block
from kbindex.skip_reasons import ParseSkip
from kbindex.text_decode import decode_text

LOG_MAX_BYTES = 256 * 1024
LOG_HARD_LIMIT_BYTES = 50 * 1024 * 1024
_MARK = "\n[省略]\n"


def parse_capped(content: bytes) -> dict:
    if len(content) > LOG_HARD_LIMIT_BYTES:
        raise ParseSkip("unreadable")
    if len(content) <= LOG_MAX_BYTES:
        text = decode_text(content)
    else:
        half = LOG_MAX_BYTES // 2
        text = decode_text(content[:half]) + _MARK + decode_text(content[-half:])
    return document([text_block(0, text, "txt")], [])
