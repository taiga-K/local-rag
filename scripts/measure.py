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
import statistics
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:43123"
DOCS = 8
WARMUP = 1
MEASURED = 5


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
    _request("POST", "/api/v1/kb", {"id": "measure", "name": "measure"})
    started = time.perf_counter()
    for index in range(DOCS):
        _request(
            "POST",
            "/api/v1/kb/measure/records",
            {
                "recordName": f"m{index}",
                "mimeType": "application/blocks",
                "externalRecordId": f"m{index}",
                "version": 1,
                "blocksFormat": 1,
                "blocks": {"blocks": [{"index": 0, "type": "text", "data": f"計測文書{index}。東京都の天気は晴れです。"}]},
            },
        )
    deadline = time.perf_counter() + 600
    while time.perf_counter() < deadline:
        _status, counts = _request("GET", "/api/v1/kb/measure/indexing/counts")
        if counts.get("QUEUED", 1) == 0 and counts.get("IN_PROGRESS", 1) == 0:
            break
        time.sleep(0.5)
    else:
        print(f"index did not finish: {counts}", file=sys.stderr)
        raise SystemExit(2)
    indexed = time.perf_counter() - started
    tokens = 0
    for index in range(DOCS):
        _status, debug = _request("GET", f"/api/v1/debug/kb/measure/records/m{index}")
        tokens += sum(int(chunk["tokenCount"]) for chunk in debug.get("chunks", []))
    for _ in range(WARMUP):
        _request("POST", "/api/v1/retrieve", {"query": "東京の天気", "filters": {"kb": ["measure"]}})
    latencies = []
    for _ in range(MEASURED):
        began = time.perf_counter()
        _request("POST", "/api/v1/retrieve", {"query": "東京の天気", "filters": {"kb": ["measure"]}})
        latencies.append(time.perf_counter() - began)
    print(
        json.dumps(
            {
                "docs": DOCS,
                "token_count": tokens,
                "warmup": WARMUP,
                "measured": MEASURED,
                "index_seconds": indexed,
                "retrieve_seconds": {
                    "min": min(latencies),
                    "max": max(latencies),
                    "median": statistics.median(latencies),
                },
                "model_load": "excluded",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
