"""Outlook msg as one HTML page. Attachment bytes are not read."""

from __future__ import annotations

import datetime as dt
import html
import multiprocessing
from typing import Callable

import compressed_rtf
from bs4 import BeautifulSoup
from oxmsg import Message
from striprtf.striprtf import rtf_to_text

from kbindex.parse_html import parse_html
from kbindex.rtf_html import deencapsulate_html, fix_surrogates, is_encapsulated_html
from kbindex.skip_reasons import ParseSkip

_MAX_BYTES = 64 * 1024 * 1024
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
    page = _run_bounded(_page_of, content, MSG_PARSE_TIMEOUT_SECONDS)
    parsed = parse_html(page)
    if not any(_visible(block) for block in parsed["blocks"]):
        raise ParseSkip("unreadable")
    return parsed


def _run_bounded(fn: Callable[[bytes], str], content: bytes, seconds: float) -> str:
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(fn, content, child))
    proc.start()
    child.close()
    proc.join(seconds)
    if proc.is_alive():
        proc.kill()
        proc.join(5)
        parent.close()
        raise ParseSkip("unreadable")
    try:
        kind, payload = parent.recv()
    except EOFError:
        raise ParseSkip("unreadable") from None
    finally:
        parent.close()
        proc.join(1)
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


def _page_of(content: bytes) -> str:
    try:
        message = Message.load(bytes(content))
        return _page(message)
    except Exception as exc:
        raise ParseSkip("unreadable") from exc


def _page(message: Message) -> str:
    subject = message.subject or ""
    sent: dt.datetime | None = message.sent_date
    to, cc = _addresses(message)
    attachments = _attachments(message)
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        f"<title>{html.escape(subject)}</title></head><body>",
        f"<h1>{html.escape(subject)}</h1>" if subject else "",
        _header("From", message.sender),
        _header("To", "; ".join(to)),
        _header("Cc", "; ".join(cc)),
        _header("Date", sent.astimezone(dt.UTC).isoformat() if sent and sent.year > _NO_DATE_YEAR else None),
        "<hr/>",
        _body(message),
    ]
    if attachments:
        parts += ["<h2>Attachments</h2><ul>", *attachments, "</ul>"]
    parts.append("</body></html>")
    return fix_surrogates("".join(parts))


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


def _attachments(message: Message) -> list[str]:
    listed = []
    for attachment in message.attachments:
        props = attachment.properties
        name = attachment.file_name or props.str_prop_value(_PID_ATTACH_FILENAME) or "attachment"
        size = props.int_prop_value(_PID_ATTACH_SIZE)
        detail = attachment.mime_type or "application/octet-stream"
        if size:
            detail = f"{detail}, {size:,} bytes"
        listed.append(f"<li>{html.escape(name)} ({html.escape(detail)})</li>")
    return listed


def _header(label: str, value: str | None) -> str:
    return f"<p><strong>{label}:</strong> {html.escape(value)}</p>" if value else ""


def _visible(block: dict) -> bool:
    data = block.get("data")
    if isinstance(data, str):
        return bool(data.strip("\x00 \t\r\n"))
    if isinstance(data, dict):
        return bool(data.get("row_natural_language_text") or data.get("cells"))
    return data is not None
