"""Added cost of one dense retrieve plus cosine, on an in-process Qdrant.

This is the test client (`QdrantClient(":memory:")`), not a network server.
Before is `Vectors.search` alone. After is that search, then one
`dense_vectors` retrieve of the hit ids, then cosine for each hit.
Added is that retrieve and cosine on the same hit ids, without a second search.
The threshold flag does not add another retrieve: the read runs either way.
"""

from __future__ import annotations

import math
import random
import time
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from kbindex.db import NAMESPACE
from kbindex.qdrant_store import Vectors
from kbindex.similarity import cosine

DIM = 768
POINTS = 1000
LIMIT = 64
WARMUP = 20
SAMPLES = 80


def _unit(rng: random.Random) -> list[float]:
    values = [rng.gauss(0.0, 1.0) for _ in range(DIM)]
    norm = math.sqrt(sum(item * item for item in values))
    return [item / norm for item in values]


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _ms(samples: list[float]) -> str:
    return f"p50 {_percentile(samples, 0.50) * 1000:.3f} ms  p95 {_percentile(samples, 0.95) * 1000:.3f} ms"


def main() -> None:
    rng = random.Random(0)
    client = QdrantClient(":memory:")
    store = Vectors.__new__(Vectors)
    store.client = client
    store.ensure(DIM)
    points = []
    for index in range(POINTS):
        cid = f"c{index}"
        points.append(
            qm.PointStruct(
                id=str(uuid.uuid5(NAMESPACE, cid)),
                vector={"dense": _unit(rng)},
                payload={"chunkId": cid},
            )
        )
    client.upsert(collection_name="chunks", points=points)
    query = _unit(rng)

    def before():
        return store.search(query, limit=LIMIT, kb_ids=None)

    def after():
        hits = store.search(query, limit=LIMIT, kb_ids=None)
        stored = store.dense_vectors([cid for cid, _score in hits])
        for cid, _score in hits:
            vector = stored.get(cid)
            if vector is not None:
                cosine(query, vector)
        return hits

    for _ in range(WARMUP):
        before()
        after()
    sample_ids = [cid for cid, _score in before()]

    def added():
        stored = store.dense_vectors(sample_ids)
        for cid in sample_ids:
            vector = stored.get(cid)
            if vector is not None:
                cosine(query, vector)

    for _ in range(WARMUP):
        added()
    before_times = []
    after_times = []
    added_times = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        before()
        before_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        after()
        after_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        added()
        added_times.append(time.perf_counter() - started)
    print(f"in-process Qdrant  dim={DIM}  points={POINTS}  limit={LIMIT}  hits={len(sample_ids)}  samples={SAMPLES}")
    print("local mode is exact search; search_params do not build an HNSW")
    print(f"before search only                 {_ms(before_times)}")
    print(f"after  search + retrieve + cosine  {_ms(after_times)}")
    print(f"added  retrieve + cosine only      {_ms(added_times)}")


if __name__ == "__main__":
    main()
