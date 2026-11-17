"""Qdrant collection `records`. Dense only. Settings follow PipesHub defaults."""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

COLLECTION = "records"


class Vectors:
    def __init__(self, url: str) -> None:
        self.client = QdrantClient(url=url, timeout=30)

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def ensure(self, dim: int) -> None:
        names = {item.name for item in self.client.get_collections().collections}
        if COLLECTION in names:
            return
        self.client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE, on_disk=True),
            hnsw_config=qm.HnswConfigDiff(ef_construct=256, on_disk=True),
            quantization_config=qm.ScalarQuantization(
                scalar=qm.ScalarQuantizationConfig(type=qm.ScalarType.INT8, quantile=0.95, always_ram=False)
            ),
            optimizers_config=qm.OptimizersConfigDiff(default_segment_number=8),
        )

    def count(self) -> int:
        names = {item.name for item in self.client.get_collections().collections}
        if COLLECTION not in names:
            return 0
        return int(self.client.count(COLLECTION, exact=True).count)

    def drop(self) -> None:
        names = {item.name for item in self.client.get_collections().collections}
        if COLLECTION in names:
            self.client.delete_collection(COLLECTION)

    def delete_record(self, record_id: str) -> None:
        if self.count() == 0 and COLLECTION not in {item.name for item in self.client.get_collections().collections}:
            return
        self.client.delete(
            collection_name=COLLECTION,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(must=[qm.FieldCondition(key="recordId", match=qm.MatchValue(value=record_id))])
            ),
        )

    def upsert(self, points: list[qm.PointStruct]) -> None:
        if points:
            self.client.upsert(collection_name=COLLECTION, points=points)

    def search(self, vector: list[float], *, limit: int, kb_id: str | None) -> list[tuple[str, float]]:
        must = []
        if kb_id:
            must.append(qm.FieldCondition(key="kbId", match=qm.MatchValue(value=kb_id)))
        query = qm.Filter(must=must) if must else None
        hits = self.client.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=limit,
            query_filter=query,
            search_params=qm.SearchParams(hnsw_ef=256, quantization=qm.QuantizationSearchParams(oversampling=1.5, rescore=True)),
            with_payload=True,
        ).points
        out = []
        for hit in hits:
            payload = hit.payload or {}
            out.append((str(payload.get("chunkId") or hit.id), float(hit.score or 0)))
        return out
