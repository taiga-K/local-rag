"""Index throughput and retrieve latency.

A successful run records the document count, the sum of chunk tokenCount,
one warmup retrieve that is left out of the stats, then 5 measured retrieves,
and the min, max, and median of those 5. Index time starts only after this
process sees the API answer, so model load is not included. The script prints
that exclusion before any timing.

Without --run, or when the API does not answer, the process exits 2 and
prints no timings. It does not invent numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:43123"
WARMUP = 1
MEASURED = 20
SAMPLES = Path("samples")


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"content-type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        print("no measurement run; refusing to invent timings", file=sys.stderr)
        raise SystemExit(2)
    try:
        _request("GET", "/api/v1/kb/measure")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            print("API did not answer; refusing to invent timings", file=sys.stderr)
            raise SystemExit(2) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print("API did not answer; refusing to invent timings", file=sys.stderr)
        raise SystemExit(2) from exc
    print("model load is excluded: this process does not start the server", flush=True)
    kb = "samples"
    _request("POST", "/api/v1/kb", {"id": kb, "name": kb})
    files = sorted(SAMPLES.glob("*"))
    files = [path for path in files if path.suffix.lower() in {".txt", ".md", ".html"}]
    if not files:
        print("no sample files", file=sys.stderr)
        raise SystemExit(2)
    started = time.perf_counter()
    for path in files:
        external = "s" + path.stem
        _request(
            "POST",
            f"/api/v1/kb/{kb}/records",
            {
                "recordName": path.name,
                "mimeType": "application/blocks",
                "externalRecordId": external,
                "version": int(time.time() * 1000),
                "blocksFormat": 1,
                "blocks": {"blocks": [{"index": 0, "type": "text", "data": path.read_text(encoding="utf-8")}]},
            },
        )
    deadline = time.perf_counter() + 600
    while time.perf_counter() < deadline:
        _status, counts = _request("GET", f"/api/v1/kb/{kb}/indexing/counts")
        if counts.get("QUEUED", 1) == 0 and counts.get("IN_PROGRESS", 1) == 0 and counts.get("FAILED", 1) == 0:
            break
        time.sleep(0.05)
    else:
        print(f"index did not finish: {counts}", file=sys.stderr)
        raise SystemExit(2)
    indexed = time.perf_counter() - started
    tokens = 0
    for path in files:
        _status, debug = _request("GET", f"/api/v1/debug/kb/{kb}/records/s{path.stem}")
        tokens += sum(int(chunk.get("tokenCount") or chunk.get("token_count") or 0) for chunk in debug.get("chunks", []))
    query = {"query": "東京の天気", "limit": 10, "rewriteQuery": False, "maxChunksPerRecord": 1, "filters": {"kb": [kb]}}
    for _ in range(WARMUP):
        _request("POST", "/api/v1/retrieve", query)
    latencies = []
    for _ in range(MEASURED):
        began = time.perf_counter()
        _request("POST", "/api/v1/retrieve", query)
        latencies.append(time.perf_counter() - began)
    ordered = sorted(latencies)
    def pct(p: float) -> float:
        rank = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
        return ordered[rank]
    print(
        json.dumps(
            {
                "docs": len(files),
                "files": [path.name for path in files],
                "token_count": tokens,
                "warmup": WARMUP,
                "measured": MEASURED,
                "index_seconds": indexed,
                "docs_per_second": len(files) / indexed if indexed else None,
                "retrieve_seconds": {
                    "p50": pct(0.50),
                    "p95": pct(0.95),
                    "min": ordered[0],
                    "max": ordered[-1],
                },
                "model_load": "excluded",
                "poll_seconds": 0.05,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
