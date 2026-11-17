"""Measure indexing throughput and retrieve latency. Prints only what this process observed."""

from __future__ import annotations

import json
import statistics
import time
import urllib.request
import uuid

API = "http://127.0.0.1:43123"


def post(path: str, body: dict) -> tuple[int, dict, float]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers={"content-type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = json.loads(response.read().decode())
        return response.status, payload, time.perf_counter() - started


def main() -> None:
    post("/api/v1/kb", {"id": "measure", "name": "measure"})
    docs = 8
    run = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    for i in range(docs):
        post("/api/v1/kb/measure/records", {
            "recordName": f"m{i}",
            "mimeType": "application/blocks",
            "externalRecordId": f"m{run}{i}",
            "version": 1,
            "blocksFormat": 1,
            "blocks": {"blocks": [{"index": 0, "type": "text", "data": f"計測文書{i}。東京都の天気は晴れです。"}]},
        })
    pushed = time.perf_counter() - started
    deadline = time.perf_counter() + 600
    while time.perf_counter() < deadline:
        req = urllib.request.Request(API + "/api/v1/kb/measure/indexing/counts")
        with urllib.request.urlopen(req) as response:
            counts = json.loads(response.read().decode())
        if counts.get("QUEUED", 1) == 0 and counts.get("IN_PROGRESS", 1) == 0:
            break
        time.sleep(0.05)
    else:
        raise SystemExit(f"index did not finish: {counts}")
    indexed = time.perf_counter() - started
    latencies = []
    for _ in range(5):
        _status, _payload, elapsed = post("/api/v1/retrieve", {"query": "東京の天気", "limit": 10, "filters": {"kb": ["measure"]}})
        latencies.append(elapsed)
    print(json.dumps({
        "docs": docs,
        "push_seconds": round(pushed, 4),
        "index_seconds_including_push": round(indexed, 4),
        "docs_per_second_until_counts_idle": round(docs / indexed, 4),
        "retrieve_seconds": {
            "n": len(latencies),
            "min": round(min(latencies), 4),
            "median": round(statistics.median(latencies), 4),
            "max": round(max(latencies), 4),
        },
        "note": "index_seconds includes push HTTP and waiting until QUEUED and IN_PROGRESS are 0. Model load is excluded if the worker was already up. Device is the server config, expected cpu.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
