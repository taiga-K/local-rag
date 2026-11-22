"""Outlook msg. Body first, then attachment names. Attachment bytes are not read."""

from __future__ import annotations

import io

from oxmsg import Message

from kbindex.blocks import document, text_block
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
    html = _body_html(message)
    parsed = parse_html(html) if html else document([], [])
    blocks = list(parsed["blocks"])
    header = _header(message)
    if header:
        blocks.insert(0, text_block(0, header, "html", "paragraph"))
        for block in blocks[1:]:
            block["index"] = block["index"] + 1
            if block.get("parent_index") is not None:
                pass
        groups = parsed.get("block_groups") or []
        for group in groups:
            for item in group.get("children", {}).get("block_ranges", []):
                item["start"] += 1
                item["end"] += 1
    else:
        groups = parsed.get("block_groups") or []
    names = _attachment_names(message)
    if names:
        blocks.append(text_block(len(blocks), "添付: " + "、".join(names), "html", "paragraph"))
    if not blocks:
        raise ParseSkip("unreadable")
    body = document(blocks, groups)
    return body


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
