"""log and cfg keep the head and tail. A file over 50MiB is not read.

The cut follows PipesHub's capped text: each end stops on a character boundary
for the encoding the whole file uses, so a multibyte character is not split.
"""

from __future__ import annotations

import codecs

from kbindex.blocks import document, text_block
from kbindex.skip_reasons import ParseSkip
from kbindex.text_decode import decode_text

LOG_MAX_BYTES = 256 * 1024
LOG_HARD_LIMIT_BYTES = 50 * 1024 * 1024
_MARK = "\n[省略]\n"
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def parse_capped(content: bytes) -> dict:
    if len(content) > LOG_HARD_LIMIT_BYTES:
        raise ParseSkip("unreadable")
    if len(content) <= LOG_MAX_BYTES:
        text = decode_text(content)
    else:
        codec, bom = _codec(content)
        half = LOG_MAX_BYTES // 2
        head_end = _align(content, half, codec, bom, forward=False)
        tail_start = _align(content, len(content) - half, codec, bom, forward=True)
        text = _part(content[bom:head_end], codec) + _MARK + _part(content[tail_start:], codec)
    return document([text_block(0, text, "txt")], [])


def _codec(content: bytes) -> tuple[str, int]:
    for mark, encoding in _BOMS:
        if content.startswith(mark):
            return encoding, len(mark)
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        return "utf-8", 0
    try:
        content.decode("cp932")
    except UnicodeDecodeError:
        pass
    else:
        return "cp932", 0
    return "cp1252", 0


def _part(content: bytes, codec: str) -> str:
    errors = "replace" if codec == "cp1252" else "strict"
    return content.decode(codec, errors=errors)


def _align(content: bytes, position: int, codec: str, bom: int, *, forward: bool) -> int:
    unit = 4 if codec in {"utf-32-le", "utf-32-be"} else 2 if codec in {"utf-16-le", "utf-16-be"} else 1
    position = max(bom, min(position, len(content)))
    position -= (position - bom) % unit
    if codec == "utf-8":
        step = 1 if forward else -1
        for _ in range(3):
            if not bom < position < len(content) or not 0x80 <= content[position] <= 0xBF:
                break
            position += step
        return max(bom, min(position, len(content)))
    if codec == "cp932":
        return _align_cp932(content, position, forward)
    return position


def _align_cp932(content: bytes, position: int, forward: bool) -> int:
    sample = content[position:] if forward else content[:position]
    for _ in range(2):
        try:
            sample.decode("cp932")
            return position
        except UnicodeDecodeError:
            position += 1 if forward else -1
            if position < 0 or position > len(content):
                break
            sample = content[position:] if forward else content[:position]
    return max(0, min(position, len(content)))
