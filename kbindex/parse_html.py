"""HTML through selectolax. script and style are dropped. Nothing is fetched."""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser

from kbindex.blocks import document, row_block, row_sentence, section_group, table_group, text_block

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP = {"script", "style", "noscript"}


def parse_html(text: str) -> dict:
    tree = LexborHTMLParser(text)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    blocks: list[dict] = []
    groups: list[dict] = []
    root = tree.body or tree.root
    if root is not None:
        _walk(root, blocks, groups, inside_table=False)
    if not blocks:
        plain = tree.text(separator=" ", strip=True) if tree.root is not None else ""
        blocks.append(text_block(0, plain, "html", "paragraph"))
    _parents(blocks, groups)
    return document(blocks, groups)


def _walk(node, blocks: list[dict], groups: list[dict], *, inside_table: bool) -> None:
    child = node.child
    while child is not None:
        tag = (child.tag or "").lower()
        if tag in _SKIP or tag == "-text":
            child = child.next
            continue
        if tag == "table" and not inside_table:
            _table(child, blocks, groups)
        elif tag in _HEADINGS:
            value = child.text(separator=" ", strip=True)
            if value:
                blocks.append(text_block(len(blocks), value, "html", "heading"))
                groups.append(section_group(len(groups), value, [(len(blocks) - 1, len(blocks) - 1)]))
        elif tag == "p":
            value = child.text(separator=" ", strip=True)
            if value:
                blocks.append(text_block(len(blocks), value, "html", "paragraph"))
        elif tag == "li":
            value = child.text(separator=" ", strip=True)
            if value:
                blocks.append(text_block(len(blocks), value, "html", "list_item"))
        elif tag and not inside_table:
            _walk(child, blocks, groups, inside_table=False)
        child = child.next


def _table(node, blocks: list[dict], groups: list[dict]) -> None:
    columns: list[str] = []
    rows: list[list[str]] = []
    for row in node.css("tr"):
        cells = [cell.text(separator=" ", strip=True) for cell in row.css("th, td")]
        if not cells:
            continue
        if not columns and row.css("th"):
            columns = cells
            continue
        if any(cells):
            rows.append(cells)
    if not columns:
        width = max((len(row) for row in rows), default=0)
        columns = [f"col_{pos + 1}" for pos in range(width)]
    if not rows:
        return
    start = len(blocks)
    for row_index, cells in enumerate(rows, start=1):
        blocks.append(row_block(len(blocks), cells, row_sentence(columns, cells), row_number=row_index))
    groups.append(table_group(len(groups), start, len(blocks) - 1, columns))


def _parents(blocks: list[dict], groups: list[dict]) -> None:
    owner = [-1] * len(blocks)
    for pos, group in enumerate(groups):
        for item in group.get("children", {}).get("block_ranges", []):
            for index in range(item["start"], item["end"] + 1):
                if 0 <= index < len(owner):
                    owner[index] = pos
    for index, block in enumerate(blocks):
        if owner[index] >= 0:
            block["parent_index"] = owner[index]
