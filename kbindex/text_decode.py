"""Byte order mark, then strict UTF-8, then an HTML charset, then CP932, then windows-1252.

The order is the local-rag rule. A charset guesser is not used. HTML declarations
are read only after UTF-8 has already failed, including stateful charsets.
"""

from __future__ import annotations

import codecs
import re

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

_DECLARED = re.compile(rb"""charset\s*=\s*["']?\s*([A-Za-z0-9._+-]+)""", re.IGNORECASE)

_LABELS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "shift_jis": "cp932",
    "shift-jis": "cp932",
    "sjis": "cp932",
    "csshiftjis": "cp932",
    "ms932": "cp932",
    "windows-31j": "cp932",
    "cp932": "cp932",
    "x-sjis": "cp932",
    "windows-1252": "cp1252",
    "cp1252": "cp1252",
    "iso-8859-1": "cp1252",
    "latin1": "cp1252",
    "iso-2022-jp": "iso2022_jp",
}


def decode_text(content: bytes, *, html: bool = False) -> str:
    """Decode one file. The last step is windows-1252, so this does not raise."""
    for mark, encoding in _BOMS:
        if content.startswith(mark):
            return content[len(mark):].decode(encoding, errors="replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if html:
        declared = _declared_codec(content)
        if declared:
            try:
                return content.decode(declared)
            except UnicodeDecodeError:
                pass
    try:
        return content.decode("cp932")
    except UnicodeDecodeError:
        pass
    return content.decode("cp1252", errors="replace")


def _declared_codec(content: bytes) -> str | None:
    found = _DECLARED.search(content[:8192])
    if not found:
        return None
    label = found.group(1).decode("ascii", errors="ignore").strip().lower()
    name = _LABELS.get(label, label)
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None
