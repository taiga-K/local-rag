"""Score an already indexed KB with the harness retrieve and ranx path.

standalone_bench.py is not modified. Its self-check waits until each
document's first 80 characters is inside the top 10. On dense-only that
wait never ends for JQaRA external id 4210070, whose 80-character probe
is outside the top 10. Query scoring uses the same client, repeats, and
ranx metrics as run_benchmark.
"""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

from bench.standalone_bench import (
    LIMIT,
    RANX_METRICS,
    REPEATS,
    SEED,
    CompatibleClient,
    _grades,
    _query_row,
    _write_jsonl,
    _write_summary,
    external_record_id,
    latency_summary,
    load_subset,
    ranx_mean,
)


def score(subset: str, kb: str, out: Path, cache: Path, base_url: str) -> dict:
    _documents, queries = load_subset(subset, cache)
    client = CompatibleClient(base_url, kb, timeout=120.0)
    for doc_id, _text in _documents:
        client.external_to_doc[external_record_id(doc_id)] = doc_id
    passes = []
    for pass_index in range(REPEATS):
        passes.append([_query_row(client, query_id, text, grades, pass_index) for query_id, text, grades in queries])
    quality = [row for row in passes[0] if row["status"] == "ok"]
    errors = [row for row in passes[0] if row["status"] != "ok"]
    stable = all(
        [[hit["doc_id"] for hit in row["hits"]] for row in later if row["status"] == "ok"]
        == [[hit["doc_id"] for hit in row["hits"]] for row in passes[0] if row["status"] == "ok"]
        for later in passes[1:]
    )
    scored = [
        (str(row["query_id"]), [(str(hit["doc_id"]), float(hit["score"])) for hit in row["hits"]], _grades(queries, str(row["query_id"])))
        for row in quality
    ]
    means = ranx_mean(scored) if scored else {name: None for name in RANX_METRICS}
    metrics = {key: {"value": value, "label": "measured", "n": len(quality)} for key, value in means.items()}
    metrics["recall@20"] = {
        "value": None,
        "label": "not_measurable",
        "reason": f"the run requests {LIMIT} hits, so Recall@20 is not computed",
    }
    label = "measured"
    if errors:
        label = "measured_with_errors"
    if not stable and label == "measured":
        label = "unstable"
    latency_passes = [[float(row["latency_ms"]) for row in rows if row["status"] == "ok"] for rows in passes]
    summary = {
        "label": label,
        "dataset": subset,
        "n_queries": len(queries),
        "n_documents": len(_documents),
        "n_errors": len(errors),
        "n_empty": sum(1 for row in quality if not row["hits"]),
        "requested_depth": LIMIT,
        "result_cap": 50,
        "rankings_stable_across_repeats": stable,
        "metrics": metrics,
        "latency_ms": latency_summary(latency_passes) if all(latency_passes) else None,
        "index_seconds": None,
        "sanity": {"passed": None, "note": "scored after indexing; the 80-character self-check was not required"},
        "conditions": {
            "python": sys.version,
            "platform": platform.platform(),
            "seed": SEED,
            "limit": LIMIT,
            "repeats": REPEATS,
            "metrics": "ranx " + ",".join(RANX_METRICS),
            "latency": "nearest-rank",
            "self_check": "skipped",
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "queries.jsonl", [row for rows in passes for row in rows])
    _write_summary(out, summary)
    print(label, out / "summary.json", flush=True)
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:43123")
    args = parser.parse_args()
    started = time.perf_counter()
    score(args.subset, args.kb, args.out, args.cache, args.base_url)
    print(f"score_seconds {time.perf_counter() - started:.1f}", flush=True)
