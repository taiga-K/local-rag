"""Push one subset and its sanity docs. Readiness is COMPLETED in Postgres.

The harness self-check is a separate step. This only fills the index.
"""

from __future__ import annotations

import time
from pathlib import Path

from bench.standalone_bench import SANITY_DOCS, CompatibleClient, load_subset


def push(subset: str, kb: str, sanity_kb: str, cache: Path, base_url: str) -> None:
    documents, _queries = load_subset(subset, cache)
    sanity = CompatibleClient(base_url, sanity_kb, timeout=120.0)
    for doc_id, text in SANITY_DOCS:
        sanity.push(doc_id, text)
    client = CompatibleClient(base_url, kb, timeout=120.0)
    started = time.perf_counter()
    for doc_id, text in documents:
        client.push(doc_id, text)
    print(f"pushed {len(documents)} in {time.perf_counter() - started:.1f}s", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--sanity-kb", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:43123")
    args = parser.parse_args()
    push(args.subset, args.kb, args.sanity_kb, args.cache, args.base_url)
