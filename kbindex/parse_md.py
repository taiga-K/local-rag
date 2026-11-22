"""Markdown and MDX through markdown-it. Tables, lists, and fences become blocks."""

from __future__ import annotations

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

from kbindex.blocks import document, row_block, row_sentence, section_group, table_group, text_block

_MD = MarkdownIt("commonmark").enable("table").use(front_matter_plugin)


def parse_markdown(text: str, *, fmt: str = "markdown") -> dict:
    tokens = _MD.parse(text)
    blocks: list[dict] = []
    groups: list[dict] = []
    section_name = ""
    section_ranges: list[tuple[int, int]] = []
    section_open: int | None = None

    def close_section() -> None:
        nonlocal section_open
        if section_open is None:
            return
        end = len(blocks) - 1
        if end >= section_open:
            section_ranges.append((section_open, end))
        section_open = None

    def add_text(data: str, sub_type: str) -> None:
        nonlocal section_open
        if section_open is None and section_name:
            section_open = len(blocks)
        blocks.append(text_block(len(blocks), data, fmt, sub_type))

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            close_section()
            if section_ranges:
                groups.append(section_group(len(groups), section_name or "section", section_ranges))
                section_ranges = []
            inline = tokens[index + 1]
            section_name = inline.content.strip()
            add_text(section_name, "heading")
            index += 3
            continue
        if token.type == "paragraph_open":
            inline = tokens[index + 1]
            value = inline.content.strip()
            if value:
                add_text(value, "paragraph")
            index += 3
            continue
        if token.type == "fence":
            add_text(token.content.rstrip("\n"), "code")
            index += 1
            continue
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            index += 1
            while index < len(tokens) and tokens[index].type != token.type.replace("_open", "_close"):
                if tokens[index].type == "inline" and tokens[index].content.strip():
                    add_text(tokens[index].content.strip(), "list_item")
                index += 1
            index += 1
            continue
        if token.type == "table_open":
            close_section()
            columns, rows = _table(tokens, index)
            start = len(blocks)
            for row_index, cells in enumerate(rows, start=1):
                blocks.append(row_block(len(blocks), cells, row_sentence(columns, cells), row_number=row_index))
            if rows:
                groups.append(table_group(len(groups), start, len(blocks) - 1, columns))
            while index < len(tokens) and tokens[index].type != "table_close":
                index += 1
            index += 1
            continue
        index += 1
    close_section()
    if section_ranges:
        groups.append(section_group(len(groups), section_name or "section", section_ranges))
    _assign_parents(blocks, groups)
    return document(blocks, groups)


def parse_mdx(text: str) -> dict:
    return parse_markdown(text)


def _table(tokens, start: int) -> tuple[list[str], list[list[str]]]:
    columns: list[str] = []
    rows: list[list[str]] = []
    current: list[str] = []
    header = False
    index = start
    while index < len(tokens) and tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "thead_open":
            header = True
        elif token.type == "tbody_open":
            header = False
        elif token.type == "tr_open":
            current = []
        elif token.type == "inline":
            current.append(token.content.strip())
        elif token.type == "tr_close":
            if header and not columns:
                columns = current
            elif current and any(cell for cell in current):
                rows.append(current)
        index += 1
    if not columns:
        columns = [f"col_{pos + 1}" for pos in range(max((len(row) for row in rows), default=0))]
    return columns, rows


def _assign_parents(blocks: list[dict], groups: list[dict]) -> None:
    owner = [-1] * len(blocks)
    for pos, group in enumerate(groups):
        for item in group.get("children", {}).get("block_ranges", []):
            for index in range(item["start"], item["end"] + 1):
                owner[index] = pos
    for index, block in enumerate(blocks):
        if owner[index] >= 0:
            block["parent_index"] = owner[index]
