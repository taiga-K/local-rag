"""Small builders for the push contract. Indices match list positions."""

from __future__ import annotations


def text_block(
    index: int,
    data: str,
    fmt: str,
    sub_type: str | None = None,
    *,
    parent: int | None = None,
    citation: dict | None = None,
) -> dict:
    block: dict = {"index": index, "type": "text", "format": fmt, "data": data}
    if sub_type:
        block["sub_type"] = sub_type
    if parent is not None:
        block["parent_index"] = parent
    if citation:
        block["citation_metadata"] = citation
    return block


def row_block(
    index: int,
    cells: list[str],
    sentence: str,
    *,
    parent: int | None = None,
    citation: dict | None = None,
    row_number: int | None = None,
) -> dict:
    data: dict = {"cells": cells or None, "row_natural_language_text": sentence or None}
    if row_number is not None:
        data["row_number"] = row_number
    block: dict = {"index": index, "type": "table_row", "data": {key: value for key, value in data.items() if value is not None}}
    if parent is not None:
        block["parent_index"] = parent
    if citation:
        block["citation_metadata"] = citation
    return block


def section_group(index: int, name: str, ranges: list[tuple[int, int]]) -> dict:
    return {
        "index": index,
        "type": "text_section",
        "name": name[:1024],
        "children": {"block_ranges": [{"start": start, "end": end} for start, end in ranges]},
    }


def table_group(index: int, start: int, end: int, columns: list[str]) -> dict:
    return {
        "index": index,
        "type": "table",
        "data": {"table_summary": ""},
        "table_metadata": {"num_of_rows": end - start + 1, "num_of_cols": len(columns), "has_header": True, "column_names": columns},
        "children": {"block_ranges": [{"start": start, "end": end}]},
    }


def document(blocks: list[dict], groups: list[dict]) -> dict:
    if not blocks:
        blocks = [text_block(0, "", "txt")]
    body: dict = {"blocks": blocks}
    if groups:
        body["block_groups"] = groups
    return body


def row_sentence(columns: list[str], cells: list[str]) -> str:
    parts = []
    for pos, cell in enumerate(cells):
        name = columns[pos] if pos < len(columns) and columns[pos] else f"col_{pos + 1}"
        parts.append(f"{name}: {cell}")
    return ", ".join(parts)
