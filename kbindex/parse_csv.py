"""CSV and TSV. Each blank-line-separated region is a table. No row cap."""

from __future__ import annotations

import csv
import io

from kbindex.blocks import document, row_block, row_sentence, table_group
from kbindex.skip_reasons import ParseSkip


def parse_csv(text: str, *, delimiter: str) -> dict:
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise ParseSkip("unreadable") from exc
    blocks: list[dict] = []
    groups: list[dict] = []
    line_no = 0
    region: list[tuple[int, list[str]]] = []

    def flush() -> None:
        nonlocal region
        data = [(line, cells) for line, cells in region if any(cell.strip() for cell in cells)]
        region = []
        if len(data) < 2:
            return
        columns = [cell.strip() or f"col_{pos + 1}" for pos, cell in enumerate(data[0][1])]
        start = len(blocks)
        for line, cells in data[1:]:
            values = [cell.strip() for cell in cells]
            blocks.append(row_block(
                len(blocks),
                values,
                row_sentence(columns, values),
                citation={"row_number": line},
                row_number=line,
            ))
        groups.append(table_group(len(groups), start, len(blocks) - 1, columns))
        for index in range(start, len(blocks)):
            blocks[index]["parent_index"] = groups[-1]["index"]

    for raw in rows:
        line_no += 1
        if not any(cell.strip() for cell in raw):
            flush()
            continue
        region.append((line_no, raw))
    flush()
    return document(blocks, groups)
