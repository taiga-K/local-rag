"""Outlook msg. Body first, then attachment names. Attachment bytes are not read."""

from __future__ import annotations

import io

from oxmsg import Message

from kbindex.blocks import text_block
from kbindex.parse_html import parse_html
from kbindex.skip_reasons import ParseSkip

_MAX_BYTES = 64 * 1024 * 1024


def parse_msg(content: bytes) -> dict:
    if len(content) > _MAX_BYTES:
        raise ParseSkip("unreadable")
    try:
        message = Message.load(io.BytesIO(content))
    except Exception as exc:
        raise ParseSkip("unreadable") from exc
    html = _body_html(message).strip()
    blocks: list[dict] = []
    groups: list[dict] = []
    if html:
        parsed = parse_html(html)
        blocks = [block for block in parsed["blocks"] if _visible(block)]
        groups = parsed.get("block_groups") or []
    header = _header(message).strip()
    if header:
        blocks.insert(0, text_block(0, header, "html", "paragraph"))
        for block in blocks[1:]:
            block["index"] += 1
        for group in groups:
            for item in group.get("children", {}).get("block_ranges", []):
                item["start"] += 1
                item["end"] += 1
    names = [name.strip("\x00") for name in _attachment_names(message) if name and name.strip("\x00")]
    if names:
        blocks.append(text_block(len(blocks), "添付: " + "、".join(names), "html", "paragraph"))
    blocks = [block for block in blocks if _visible(block)]
    if not blocks:
        raise ParseSkip("unreadable")
    for index, block in enumerate(blocks):
        block["index"] = index
    body: dict = {"blocks": blocks}
    if groups:
        body["block_groups"] = groups
    return body


def _visible(block: dict) -> bool:
    data = block.get("data")
    if isinstance(data, str):
        return bool(data.strip("\x00 \t\r\n"))
    if isinstance(data, dict):
        return bool(data.get("row_natural_language_text") or data.get("cells"))
    return data is not None


def _body_html(message) -> str:
    for attr in ("html_body", "body"):
        value = getattr(message, attr, None)
        if isinstance(value, bytes) and value.strip():
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _header(message) -> str:
    subject = getattr(message, "subject", None) or ""
    sender = getattr(message, "sender", None) or ""
    parts = []
    if subject:
        parts.append(f"件名: {subject}")
    if sender:
        parts.append(f"差出人: {sender}")
    return " ".join(parts)


def _attachment_names(message) -> list[str]:
    found = []
    attachments = getattr(message, "attachments", None) or []
    for item in attachments:
        name = getattr(item, "file_name", None) or getattr(item, "filename", None) or getattr(item, "name", None)
        if name:
            found.append(str(name))
    return found
