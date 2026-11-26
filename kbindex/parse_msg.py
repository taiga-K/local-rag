"""Outlook msg as one HTML page. Attachment bytes are not read."""

from __future__ import annotations

import datetime as dt
import html
import multiprocessing
import time
from typing import Callable

import compressed_rtf
from bs4 import BeautifulSoup
from oxmsg import Message
from striprtf.striprtf import rtf_to_text

from kbindex.blocks import text_block
from kbindex.parse_html import parse_html
from kbindex.rtf_html import deencapsulate_html, fix_surrogates, is_encapsulated_html
from kbindex.skip_reasons import ParseSkip

_MAX_BYTES = 64 * 1024 * 1024
_TEXT_CAP = 1 << 20
MSG_PARSE_TIMEOUT_SECONDS = 60
_PID_RTF_COMPRESSED = 0x1009
_PID_RECIPIENT_TYPE = 0x0C15
_PID_DISPLAY_TO = 0x0E04
_PID_DISPLAY_CC = 0x0E03
_PID_ATTACH_FILENAME = 0x3704
_PID_ATTACH_SIZE = 0x0E20
_TO, _CC = 1, 2
_NO_DATE_YEAR = 1601
_REMOTE_ATTRIBUTES = ("src", "srcset", "href", "xlink:href", "poster", "background")
_DROPPED_TAGS = (
    "script", "style", "head", "title", "meta", "link", "base", "iframe", "frame", "frameset",
    "object", "embed", "applet",
)
_IMAGE_TAGS = ("img", "picture", "source", "image", "input", "video", "audio", "body", "table", "td")


def parse_msg(content: bytes) -> dict:
    if len(content) > _MAX_BYTES:
        raise ParseSkip("unreadable")
    parts = _run_bounded(_parts_of, content, MSG_PARSE_TIMEOUT_SECONDS)
    return _assemble(parts)


def _run_bounded(fn: Callable[[bytes], object], content: bytes, seconds: float):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(fn, content, child))
    proc.start()
    child.close()
    deadline = time.monotonic() + seconds
    kind = None
    payload = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if parent.poll(min(remaining, 0.2)):
                kind, payload = parent.recv()
                break
            if not proc.is_alive():
                if parent.poll(0):
                    kind, payload = parent.recv()
                break
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(5)
        parent.close()
    if kind == "ok":
        return payload
    if kind == "skip":
        raise ParseSkip(payload)
    raise ParseSkip("unreadable")


def _child(fn: Callable[[bytes], str], content: bytes, conn) -> None:
    try:
        conn.send(("ok", fn(content)))
    except ParseSkip as exc:
        conn.send(("skip", exc.reason))
    except Exception:
        conn.send(("error", ""))
    finally:
        conn.close()


def _parts_of(content: bytes) -> dict:
    try:
        message = Message.load(bytes(content))
    except Exception as exc:
        raise ParseSkip("unreadable") from exc
    sent: dt.datetime | None = message.sent_date
    to, cc = _addresses(message)
    return {
        "subject": _clean(message.subject or ""),
        "from": _clean(message.sender),
        "to": _clean("; ".join(to)),
        "cc": _clean("; ".join(cc)),
        "date": sent.astimezone(dt.UTC).isoformat() if sent and sent.year > _NO_DATE_YEAR else None,
        "body": _clean(_body(message)) or "",
        "attachments": [_clean(line) or "" for line in _attachment_lines(message)],
    }


def _assemble(parts: dict) -> dict:
    headers: list[dict] = []
    if parts["subject"]:
        headers.append(text_block(0, parts["subject"], "html", "heading"))
    for label, key in (("From", "from"), ("To", "to"), ("Cc", "cc"), ("Date", "date")):
        value = parts.get(key)
        if value:
            headers.append(text_block(len(headers), f"{label}: {value}", "html", "paragraph"))
    parsed = parse_html(parts["body"]) if str(parts["body"]).strip() else {"blocks": []}
    body_blocks = _fit_text([block for block in parsed.get("blocks") or [] if _visible(block)], parsed.get("block_groups") or [])
    footers = [text_block(0, line, "html", "list_item") for line in parts["attachments"]]
    blocks = headers + body_blocks + footers
    if not blocks:
        raise ParseSkip("unreadable")
    offset = len(headers)
    for index, block in enumerate(blocks):
        block["index"] = index
    groups = parsed.get("block_groups") or []
    for group in groups:
        for item in group.get("children", {}).get("block_ranges", []):
            item["start"] += offset
            item["end"] += offset
    body: dict = {"blocks": blocks}
    if groups:
        body["block_groups"] = groups
    return body


def _fit_text(blocks: list[dict], groups: list[dict]) -> list[dict]:
    if groups or len(blocks) != 1:
        _reject_over_cap(blocks)
        return blocks
    data = blocks[0].get("data")
    if not isinstance(data, str) or len(data) <= _TEXT_CAP:
        return blocks
    return [
        text_block(0, data[start:start + _TEXT_CAP], "html", blocks[0].get("sub_type") or "paragraph")
        for start in range(0, len(data), _TEXT_CAP)
    ]


def _reject_over_cap(blocks: list[dict]) -> None:
    for block in blocks:
        data = block.get("data")
        if isinstance(data, str) and len(data) > _TEXT_CAP:
            raise ParseSkip("unreadable")
        if isinstance(data, dict):
            text = data.get("row_natural_language_text") or ""
            cells = data.get("cells") or []
            if len(text) > _TEXT_CAP or any(len(cell) > _TEXT_CAP for cell in cells):
                raise ParseSkip("unreadable")


def _body(message: Message) -> str:
    if html_body := message.html_body:
        return _body_html(html_body)
    rtf = _rtf(message)
    if rtf and is_encapsulated_html(rtf):
        return _body_html(deencapsulate_html(rtf))
    if plain := message.body:
        return _text_html(plain)
    if rtf:
        return _text_html(rtf_to_text(rtf.decode("latin-1"), errors="ignore"))
    return ""


def _rtf(message: Message) -> bytes | None:
    compressed = message.properties.binary_prop_value(_PID_RTF_COMPRESSED)
    if not compressed:
        return None
    return compressed_rtf.decompress(compressed)


def _body_html(fragment: str) -> str:
    soup = BeautifulSoup(fragment, "html.parser")
    _strip_remote(soup)
    for tag in soup.find_all(_DROPPED_TAGS):
        tag.decompose()
    for tag in soup.find_all(style=True):
        if "url(" in str(tag["style"]).lower().replace(" ", ""):
            del tag["style"]
    body = soup.find("body")
    return body.decode_contents() if body is not None else str(soup)


def _strip_remote(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_IMAGE_TAGS):
        for attribute in _REMOTE_ATTRIBUTES:
            value = tag.get(attribute)
            if isinstance(value, str) and (tag.name != "body" or attribute == "background") and _remote(value):
                del tag[attribute]


def _remote(value: str) -> bool:
    return not value.strip().lower().startswith("data:")


def _text_html(text: str) -> str:
    paragraphs = [p for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>" for p in paragraphs)


def _addresses(message: Message) -> tuple[list[str], list[str]]:
    to: list[str] = []
    cc: list[str] = []
    for recipient in message.recipients:
        kind = recipient.properties.int_prop_value(_PID_RECIPIENT_TYPE)
        name, address = recipient.name, recipient.email_address
        shown = f"{name} <{address}>" if name and address and name != address else (address or name)
        if not shown:
            continue
        if kind == _TO:
            to.append(shown)
        elif kind == _CC:
            cc.append(shown)
    if not to and not cc:
        props = message.properties
        to = [props.str_prop_value(_PID_DISPLAY_TO) or ""]
        cc = [props.str_prop_value(_PID_DISPLAY_CC) or ""]
    return [item for item in to if item], [item for item in cc if item]


def _attachment_lines(message: Message) -> list[str]:
    listed = []
    for attachment in message.attachments:
        props = attachment.properties
        name = attachment.file_name or props.str_prop_value(_PID_ATTACH_FILENAME) or "attachment"
        size = props.int_prop_value(_PID_ATTACH_SIZE)
        detail = attachment.mime_type or "application/octet-stream"
        if size:
            detail = f"{detail}, {size:,} bytes"
        listed.append(f"{name} ({detail})")
    return listed


def _clean(value: str | None) -> str | None:
    if not value:
        return value
    return fix_surrogates(value)


def _visible(block: dict) -> bool:
    data = block.get("data")
    if isinstance(data, str):
        return bool(data.strip("\x00 \t\r\n"))
    if isinstance(data, dict):
        return bool(data.get("row_natural_language_text") or data.get("cells"))
    return data is not None
