"""One table from extension to reader. The ingest command looks nowhere else."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kbindex.parse_csv import parse_csv
from kbindex.parse_epub import parse_epub
from kbindex.parse_html import parse_html
from kbindex.parse_json import parse_json, parse_yaml
from kbindex.parse_md import parse_markdown, parse_mdx
from kbindex.parse_msg import parse_msg
from kbindex.parse_plain import parse_capped
from kbindex.skip_reasons import ParseSkip
from kbindex.text_decode import decode_text

LEDGER_NAME = ".kbindex-sync.json"


def _text(path: Path, reader, *, html: bool = False):
    return reader(decode_text(path.read_bytes(), html=html))


FORMATS: dict[str, tuple] = {
    ".txt": lambda path: _text(path, lambda text: parse_markdown(text, fmt="txt")),
    ".md": lambda path: _text(path, parse_markdown),
    ".mdx": lambda path: _text(path, parse_mdx),
    ".log": lambda path: parse_capped(path.read_bytes()),
    ".cfg": lambda path: parse_capped(path.read_bytes()),
    ".html": lambda path: _text(path, parse_html, html=True),
    ".htm": lambda path: _text(path, parse_html, html=True),
    ".json": lambda path: _text(path, parse_json),
    ".yaml": lambda path: _text(path, parse_yaml),
    ".yml": lambda path: _text(path, parse_yaml),
    ".csv": lambda path: _text(path, lambda text: parse_csv(text, delimiter=",")),
    ".tsv": lambda path: _text(path, lambda text: parse_csv(text, delimiter="\t")),
    ".epub": lambda path: parse_epub(path.read_bytes()),
    ".msg": lambda path: parse_msg(path.read_bytes()),
}


def read_file(path: Path) -> dict:
    """Return push blocks, or raise ParseSkip."""
    reader = FORMATS.get(path.suffix.lower())
    if reader is None:
        raise ParseSkip("unsupported")
    try:
        return reader(path)
    except ParseSkip:
        raise
    except Exception as exc:
        raise ParseSkip("unreadable") from exc


def blocks_sha(body: dict) -> str:
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
