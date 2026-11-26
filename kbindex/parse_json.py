"""JSON and YAML flattened without an LLM. Object arrays become table rows."""

from __future__ import annotations

import json

import yaml

from kbindex.blocks import document, row_block, row_sentence, table_group, text_block
from kbindex.skip_reasons import ParseSkip


def parse_json(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseSkip("unreadable") from exc
    return _flatten(value)


def parse_yaml(text: str) -> dict:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseSkip("unreadable") from exc
    return _flatten(value)


def _flatten(value) -> dict:
    blocks: list[dict] = []
    groups: list[dict] = []
    _walk(value, "$", blocks, groups)
    return document(blocks, groups)


def _walk(value, path: str, blocks: list[dict], groups: list[dict]) -> None:
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        columns: list[str] = []
        for item in value:
            for key in item:
                if key not in columns:
                    columns.append(str(key))
        start = len(blocks)
        for item in value:
            cells = [_cell(item.get(key)) for key in columns]
            if not any(cells):
                continue
            blocks.append(row_block(
                len(blocks),
                cells,
                row_sentence(columns, cells),
                citation={"section_title": path[:1024]},
            ))
        if len(blocks) > start:
            groups.append(table_group(len(groups), start, len(blocks) - 1, columns))
            for index in range(start, len(blocks)):
                blocks[index]["parent_index"] = groups[-1]["index"]
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _walk(item, f"{path}.{key}", blocks, groups)
        return
    if isinstance(value, list):
        for pos, item in enumerate(value):
            _walk(item, f"{path}[{pos}]", blocks, groups)
        return
    rendered = _cell(value)
    if rendered:
        blocks.append(text_block(len(blocks), rendered, "json", "paragraph", citation={"section_title": path[:1024]}))


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)
