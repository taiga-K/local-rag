"""HTML encapsulated in an Outlook RTF body (MS-OXRTFEX, \\fromhtml1)."""

from __future__ import annotations

import codecs
import re

_TOKEN = re.compile(
    rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?"
    rb"|\\'([0-9a-fA-F]{2})"
    rb"|\\([^a-zA-Z'])"
    rb"|([{}])"
    rb"|([^\\{}\r\n]+)"
    rb"|[\r\n]+",
)
_SKIPPED = frozenset({
    b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"listtable",
    b"listoverridetable", b"rsidtbl", b"generator", b"themedata", b"datastore", b"latentstyles",
})
_CHARSET_CODEPAGES = {
    2: "cp1252", 77: "mac_roman", 128: "cp932", 129: "cp949", 130: "cp1361", 134: "cp936",
    136: "cp950", 161: "cp1253", 162: "cp1254", 163: "cp1258", 177: "cp1255", 178: "cp1256",
    186: "cp1257", 204: "cp1251", 222: "cp874", 238: "cp1250", 255: "cp437",
}


def is_encapsulated_html(rtf: bytes) -> bool:
    return b"\\fromhtml1" in rtf[:2048]


def fix_surrogates(text: str) -> str:
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def deencapsulate_html(rtf: bytes) -> str:
    match = re.search(rb"\\ansicpg(\d{1,5})", rtf[:4096])
    codepage = _codec(f"cp{match.group(1).decode()}", "cp1252") if match else "cp1252"
    fonts: dict[int, str] = {}
    defining: list[int | None] = [None]
    out: list[str] = []
    pending = bytearray()
    pending_codepage = codepage

    def current_codepage(group: _Group) -> str:
        if group.html_tag or group.font is None:
            return codepage
        return fonts.get(group.font, codepage)

    def flush() -> None:
        if pending:
            out.append(pending.decode(pending_codepage, errors="replace"))
            pending.clear()

    stack = [_Group(html_tag=False, skip=False, uc=1, font=None, fonttbl=False)]
    suppressed = False
    star = False
    skip_chars = 0
    for token in _TOKEN.finditer(rtf):
        word, param, hex_byte, symbol, brace, text = token.groups()
        group = stack[-1]
        if brace == b"{":
            flush()
            stack.append(_Group(
                html_tag=group.html_tag, skip=group.skip, uc=group.uc, font=group.font, fonttbl=group.fonttbl,
            ))
            star = False
            continue
        if brace == b"}":
            flush()
            if len(stack) > 1:
                stack.pop()
            star = False
            continue
        if symbol == b"*":
            star = True
            continue
        if word is not None and group.fonttbl:
            if word == b"f" and param is not None:
                defining[0] = int(param)
            elif word in (b"fcharset", b"cpg") and param is not None and defining[0] is not None:
                number = int(param)
                if word == b"cpg":
                    fonts[defining[0]] = _codec(f"cp{number}", codepage)
                elif number in _CHARSET_CODEPAGES:
                    fonts.setdefault(defining[0], _CHARSET_CODEPAGES[number])
            continue
        if word is not None:
            if word == b"fonttbl":
                group.fonttbl = group.skip = True
                star = False
                continue
            if word == b"f" and param is not None and not group.fonttbl:
                flush()
                group.font = int(param)
                continue
            if star or word in _SKIPPED:
                star = False
                if word.startswith(b"htmltag") or word == b"mhtmltag":
                    group.html_tag = True
                    group.skip = False
                elif word in _SKIPPED or group is not stack[0]:
                    group.skip = True
                continue
            if word == b"htmlrtf":
                suppressed = param != b"0"
                continue
            emitting = not group.skip and (group.html_tag or not suppressed)
            if word == b"uc" and param is not None:
                group.uc = max(0, int(param))
            elif word == b"u" and param is not None and emitting:
                flush()
                code_point = int(param) % 0x10000 if int(param) < 0 else min(int(param), 0x10FFFF)
                out.append(chr(code_point))
                skip_chars = group.uc
            elif emitting and word in (b"par", b"line"):
                flush()
                out.append("\r\n")
            elif emitting and word == b"tab":
                flush()
                out.append("\t")
            continue
        star = False
        emitting = not group.skip and (group.html_tag or not suppressed)
        if hex_byte is not None:
            if skip_chars:
                skip_chars -= 1
            elif emitting:
                if pending and pending_codepage != current_codepage(group):
                    flush()
                pending_codepage = current_codepage(group)
                pending.append(int(hex_byte, 16))
            continue
        if symbol is not None:
            if emitting and symbol in (b"\\", b"{", b"}"):
                flush()
                out.append(symbol.decode())
            elif emitting and symbol == b"~":
                flush()
                out.append("\u00a0")
            continue
        if text is not None and emitting:
            if skip_chars:
                dropped = min(skip_chars, len(text))
                text = text[dropped:]
                skip_chars -= dropped
            flush()
            out.append(text.decode(current_codepage(group), errors="replace"))
    flush()
    return fix_surrogates("".join(out))


class _Group:
    __slots__ = ("font", "fonttbl", "html_tag", "skip", "uc")

    def __init__(self, *, html_tag: bool, skip: bool, uc: int, font: int | None, fonttbl: bool) -> None:
        self.html_tag = html_tag
        self.skip = skip
        self.uc = uc
        self.font = font
        self.fonttbl = fonttbl


def _codec(name: str, fallback: str) -> str:
    try:
        return codecs.lookup(name).name
    except LookupError:
        return fallback
