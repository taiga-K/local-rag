"""Push supported files, record the ones that could not be read, and delete files that disappeared."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from kbindex.formats import LEDGER_NAME, blocks_sha, read_file
from kbindex.skip_reasons import ParseSkip


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
    present: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == LEDGER_NAME:
            continue
        rel = path.relative_to(root).as_posix()
        present.add(rel)
        external = _external_id(rel)
        try:
            body = read_file(path)
        except ParseSkip as exc:
            if external in ledger:
                _delete(api, kb, external)
                del ledger[external]
            _record_skip(api, kb, path.name, rel, exc.reason)
            print(f"skipped {rel} {exc.reason}")
            continue
        seen.add(external)
        _clear_skip(api, kb, rel)
        previous = int(ledger.get(external, {}).get("version", 0))
        version = _file_version(path, previous)
        digest = blocks_sha(body)
        if digest != ledger.get(external, {}).get("blocks") and version <= previous:
            version = min(previous + 1, _MAX_VERSION)
        status = _push(api, kb, external, path.name, version, body)
        print(f"{status} {external}")
        ledger[external] = {"version": version, "path": rel, "blocks": digest}
    for external in list(ledger):
        if external not in seen:
            recorded = ledger[external].get("path") if isinstance(ledger[external], dict) else None
            if recorded:
                _clear_skip(api, kb, recorded)
            _delete(api, kb, external)
            print(f"deleted {external}")
            del ledger[external]
    _drop_absent_skips(api, kb, present)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))


def unreadable_paths_to_drop(recorded: list[str], present: set[str]) -> list[str]:
    """Paths recorded as unreadable that this scan did not see."""
    return [path for path in recorded if path not in present]


def load_jsonl(api: str, kb: str, path: Path) -> None:
    _ensure_kb(api, kb)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        blocks = {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": item["text"]}]}
        status = _push(api, kb, item["externalRecordId"], item.get("recordName") or item["externalRecordId"], int(item.get("version") or 1), blocks)
        print(f"{status} {item['externalRecordId']}")


_MAX_VERSION = 2**53 - 1


def _file_version(path: Path, previous: int) -> int:
    # Epoch nanoseconds do not fit in a version. Microseconds do.
    version = path.stat().st_mtime_ns // 1000
    if version > _MAX_VERSION:
        version = _MAX_VERSION
    if previous and version < previous:
        version = min(previous + 1, _MAX_VERSION)
    return version


def _drop_absent_skips(api: str, kb: str, present: set[str]) -> None:
    _status, body = _request("GET", f"{api}/api/v1/kb/{kb}/unreadable", None)
    recorded = [item["relativePath"] for item in body.get("files") or []]
    for rel in unreadable_paths_to_drop(recorded, present):
        _clear_skip(api, kb, rel)
        print(f"cleared {rel}")


def _record_skip(api: str, kb: str, name: str, rel: str, reason: str) -> None:
    _request("PUT", f"{api}/api/v1/kb/{kb}/unreadable", {"fileName": name, "relativePath": rel, "reason": reason})


def _clear_skip(api: str, kb: str, rel: str) -> None:
    quoted = urllib.request.quote(rel, safe="")
    _request("DELETE", f"{api}/api/v1/kb/{kb}/unreadable?relativePath={quoted}", None)


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
