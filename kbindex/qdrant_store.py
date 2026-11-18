"""Qdrant collection `chunks`. Dense vector name `dense`. No sparse vectors."""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

COLLECTION = "chunks"


class QdrantUnavailable(Exception):
    pass


class Vectors:
    def __init__(self, url: str) -> None:
        self.client = QdrantClient(url=url, timeout=30, check_compatibility=False)

    def _call(self, fn):
        try:
            return fn()
        except QdrantUnavailable:
            raise
        except Exception as exc:
            raise QdrantUnavailable(str(exc)) from exc

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def _names(self) -> set[str]:
        found = self._call(lambda: self.client.get_collections())
        return {item.name for item in found.collections}

    def ensure(self, dim: int) -> None:
        def create() -> None:
            names = self._names()
            if COLLECTION in names:
                return
            self.client.create_collection(
                collection_name=COLLECTION,
                vectors_config={
                    "dense": qm.VectorParams(size=dim, distance=qm.Distance.COSINE, on_disk=True),
                },
                hnsw_config=qm.HnswConfigDiff(on_disk=True, ef_construct=256),
                quantization_config=qm.ScalarQuantization(
                    scalar=qm.ScalarQuantizationConfig(
                        type=qm.ScalarType.INT8,
                        quantile=0.95,
                        always_ram=False,
                    )
                ),
                optimizers_config=qm.OptimizersConfigDiff(default_segment_number=8),
            )

        self._call(create)

    def count(self) -> int:
        def run() -> int:
            if COLLECTION not in self._names():
                return 0
            return int(self.client.count(COLLECTION, exact=True).count)

        return self._call(run)

    def drop(self) -> None:
        def remove() -> None:
            if COLLECTION in self._names():
                self.client.delete_collection(COLLECTION)

        self._call(remove)

    def delete_record(self, record_id: str) -> None:
        def remove() -> None:
            if COLLECTION not in self._names():
                return
            self.client.delete(
                collection_name=COLLECTION,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(must=[qm.FieldCondition(key="recordId", match=qm.MatchValue(value=record_id))])
                ),
            )

        self._call(remove)

    def upsert(self, points: list[qm.PointStruct]) -> None:
        if not points:
            return
        self._call(lambda: self.client.upsert(collection_name=COLLECTION, points=points))

    def scroll_all(self) -> list:
        """Every point in the collection, including vectors. Empty when it is missing."""

        def run() -> list:
            if COLLECTION not in self._names():
                return []
            found: list = []
            offset = None
            while True:
                batch, offset = self.client.scroll(
                    collection_name=COLLECTION,
                    limit=128,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                found.extend(batch)
                if offset is None:
                    break
            return found

        return self._call(run)

    def restore_points(self, points: list) -> None:
        """Upsert scrolled points. A named vector dict keeps the dense list."""
        structs: list[qm.PointStruct] = []
        for point in points:
            vector = point.vector
            if isinstance(vector, dict):
                vector = vector["dense"]
            structs.append(qm.PointStruct(id=point.id, vector={"dense": list(vector)}, payload=dict(point.payload or {})))
        self.upsert(structs)

    def search(self, vector: list[float], *, limit: int, kb_ids: list[str] | None) -> list[tuple[str, float]]:
        def run() -> list[tuple[str, float]]:
            if COLLECTION not in self._names():
                return []
            must = []
            if kb_ids:
                if len(kb_ids) == 1:
                    must.append(qm.FieldCondition(key="kbId", match=qm.MatchValue(value=kb_ids[0])))
                else:
                    must.append(qm.FieldCondition(key="kbId", match=qm.MatchAny(any=kb_ids)))
            query = qm.Filter(must=must) if must else None
            hits = self.client.query_points(
                collection_name=COLLECTION,
                query=vector,
                using="dense",
                limit=limit,
                query_filter=query,
                search_params=qm.SearchParams(
                    hnsw_ef=256,
                    quantization=qm.QuantizationSearchParams(oversampling=1.5, rescore=True),
                ),
                with_payload=True,
            ).points
            out = []
            for hit in hits:
                payload = hit.payload or {}
                out.append((str(payload.get("chunkId") or hit.id), float(hit.score or 0.0)))
            return out

        return self._call(run)
