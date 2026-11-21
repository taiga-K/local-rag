"""Push txt, md, and html files, and delete files that disappeared."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup


def main() -> None:
    parser = argparse.ArgumentParser(prog="kbindex-ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--kb", required=True)
    sync.add_argument("--root", required=True)
    sync.add_argument("--api", default="http://127.0.0.1:43123")
    load = sub.add_parser("load")
    load.add_argument("--kb", required=True)
    load.add_argument("--jsonl", required=True)
    load.add_argument("--api", default="http://127.0.0.1:43123")
    args = parser.parse_args()
    if args.cmd == "sync":
        sync_tree(args.api, args.kb, Path(args.root))
    else:
        load_jsonl(args.api, args.kb, Path(args.jsonl))


def sync_tree(api: str, kb: str, root: Path) -> None:
    _ensure_kb(api, kb)
    ledger_path = root / ".kbindex-sync.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    seen: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".html"}:
            continue
        rel = path.relative_to(root).as_posix()
        external = _external_id(rel)
        seen.add(external)
        previous = int(ledger.get(external, {}).get("version", 0))
        version = _file_version(path, previous)
        body = _blocks(path)
        status = _push(api, kb, external, path.name, version, body)
        print(f"{status} {external}")
        ledger[external] = {"version": version, "path": rel}
    for external in list(ledger):
        if external not in seen:
            _delete(api, kb, external)
            print(f"deleted {external}")
            del ledger[external]
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))


def load_jsonl(api: str, kb: str, path: Path) -> None:
    _ensure_kb(api, kb)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        blocks = {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": item["text"]}]}
        status = _push(api, kb, item["externalRecordId"], item.get("recordName") or item["externalRecordId"], int(item.get("version") or 1), blocks)
        print(f"{status} {item['externalRecordId']}")


def _blocks(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".txt":
        return {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": text}]}
    if path.suffix.lower() == ".md":
        return _markdown(text)
    return _html(text)


_MAX_VERSION = 2**53 - 1


def _file_version(path: Path, previous: int) -> int:
    # Epoch nanoseconds do not fit in a version. Microseconds do.
    version = path.stat().st_mtime_ns // 1000
    if version > _MAX_VERSION:
        version = _MAX_VERSION
    if previous and version < previous:
        version = min(previous + 1, _MAX_VERSION)
    return version


def _markdown(text: str) -> dict:
    items: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        value = "\n".join(buffer).strip()
        buffer.clear()
        if value:
            items.append(("p", value))

    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(\S.*)$", line)
        if heading:
            flush()
            items.append(("h", heading.group(1).strip()))
        elif not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()
    blocks = []
    starts = []
    for kind, value in items:
        if kind == "h":
            starts.append(len(blocks))
        blocks.append({
            "index": len(blocks),
            "type": "text",
            "format": "markdown",
            "sub_type": "heading" if kind == "h" else "paragraph",
            "data": value,
        })
    groups = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] - 1 if pos + 1 < len(starts) else len(blocks) - 1
        groups.append({
            "index": pos,
            "type": "text_section",
            "name": blocks[start]["data"][:1024],
            "children": {"block_ranges": [{"start": start, "end": end}]},
        })
        for index in range(start, end + 1):
            blocks[index]["parent_index"] = pos
    if not blocks:
        blocks = [{"index": 0, "type": "text", "format": "markdown", "data": ""}]
    body: dict = {"blocks": blocks}
    if groups:
        body["block_groups"] = groups
    return body


def _html(text: str) -> dict:
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    blocks = []
    for node in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        value = node.get_text(" ", strip=True)
        if not value:
            continue
        kind = "heading" if node.name.startswith("h") else "list_item" if node.name == "li" else "paragraph"
        blocks.append({"index": len(blocks), "type": "text", "format": "html", "data": value, "sub_type": kind})
    if not blocks:
        blocks = [{"index": 0, "type": "text", "format": "html", "data": soup.get_text(" ", strip=True)}]
    return {"blocks": blocks}


def _external_id(rel: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._~:-]", "_", rel)
    if not cleaned or not cleaned[0].isalnum():
        cleaned = "f" + cleaned
    return cleaned[:256]


def _ensure_kb(api: str, kb: str) -> None:
    _request("POST", f"{api}/api/v1/kb", {"id": kb, "name": kb})


def _push(api: str, kb: str, external: str, name: str, version: int, blocks: dict) -> int:
    body = {
        "recordName": name[:255] or "doc",
        "mimeType": "application/blocks",
        "externalRecordId": external,
        "version": version,
        "blocksFormat": 1,
        "blocks": blocks,
    }
    status, _payload = _request("POST", f"{api}/api/v1/kb/{kb}/records", body)
    return status


def _delete(api: str, kb: str, external: str) -> None:
    _request("DELETE", f"{api}/api/v1/kb/{kb}/records/{external}?source=sync", None)


def _request(method: str, url: str, body) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"content-type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"{method} {url} -> {exc.code} {detail}") from exc


if __name__ == "__main__":
    main()
