"""EPUB is a zip of HTML chapters, read in spine order, then parsed as HTML."""

from __future__ import annotations

import io
import posixpath
import zipfile
from xml.etree import ElementTree

from kbindex.blocks import document
from kbindex.parse_html import parse_html
from kbindex.skip_reasons import ParseSkip

_MAX_FILES = 10_000
_MAX_UNCOMPRESSED = 512 * 1024 * 1024
_MAX_CHAPTER = 64 * 1024 * 1024


def parse_epub(content: bytes) -> dict:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ParseSkip("unreadable") from exc
    infos = archive.infolist()
    if len(infos) > _MAX_FILES:
        raise ParseSkip("unreadable")
    total = sum(info.file_size for info in infos)
    if total > _MAX_UNCOMPRESSED:
        raise ParseSkip("unreadable")
    names = {info.filename for info in infos}
    chapters = _spine(archive, names)
    blocks: list[dict] = []
    groups: list[dict] = []
    for name in chapters:
        info = archive.getinfo(name)
        if info.file_size > _MAX_CHAPTER:
            raise ParseSkip("unreadable")
        html = archive.read(name).decode("utf-8", errors="replace")
        parsed = parse_html(html)
        shift_blocks = len(blocks)
        shift_groups = len(groups)
        for block in parsed["blocks"]:
            block = dict(block)
            block["index"] = shift_blocks + block["index"]
            if block.get("parent_index") is not None:
                block["parent_index"] = shift_groups + block["parent_index"]
            blocks.append(block)
        for group in parsed.get("block_groups") or []:
            group = dict(group)
            group["index"] = shift_groups + group["index"]
            children = group.get("children") or {}
            ranges = []
            for item in children.get("block_ranges") or []:
                ranges.append({"start": shift_blocks + item["start"], "end": shift_blocks + item["end"]})
            group["children"] = {"block_ranges": ranges}
            groups.append(group)
    return document(blocks, groups)


def _spine(archive: zipfile.ZipFile, names: set[str]) -> list[str]:
    root = "META-INF/container.xml"
    if root not in names:
        raise ParseSkip("unreadable")
    container = ElementTree.fromstring(archive.read(root))
    opf_name = ""
    for node in container.iter():
        if node.tag.endswith("rootfile"):
            opf_name = node.attrib.get("full-path", "")
            break
    if not opf_name or opf_name not in names:
        raise ParseSkip("unreadable")
    opf = ElementTree.fromstring(archive.read(opf_name))
    base = posixpath.dirname(opf_name)
    manifest: dict[str, str] = {}
    spine: list[str] = []
    for node in opf.iter():
        if node.tag.endswith("item") and node.attrib.get("id"):
            href = node.attrib.get("href", "")
            manifest[node.attrib["id"]] = posixpath.normpath(posixpath.join(base, href))
        if node.tag.endswith("itemref"):
            spine.append(node.attrib.get("idref", ""))
    chapters = [manifest[item] for item in spine if manifest.get(item) in names]
    if not chapters:
        raise ParseSkip("unreadable")
    return chapters
