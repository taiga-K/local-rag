"""Qdrant collection `chunks`. Dense vector name `dense`. No sparse vectors."""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from kbindex.db import NAMESPACE

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

    def vector_size(self) -> int | None:
        def run() -> int | None:
            if COLLECTION not in self._names():
                return None
            info = self.client.get_collection(COLLECTION)
            params = info.config.params.vectors
            if isinstance(params, dict):
                dense = params.get("dense")
                return None if dense is None else int(dense.size)
            return int(params.size)

        return self._call(run)

    def upsert(self, points: list[qm.PointStruct], expected_dim: int | None = None) -> None:
        if expected_dim is not None:
            for point in points:
                vector = point.vector
                if isinstance(vector, dict):
                    vector = vector.get("dense")
                if vector is not None and len(list(vector)) != expected_dim:
                    raise QdrantUnavailable(
                        f"vector dimension {len(list(vector))} does not match collection {expected_dim}"
                    )
        if not points:
            return
        self._call(lambda: self.client.upsert(collection_name=COLLECTION, points=points))

    def scroll_all(self) -> list:
        """Every point in the collection, including vectors. Empty when it is missing."""
        return self._scroll(None)

    def scroll_record(self, record_id: str) -> list:
        """Points whose payload recordId matches, including vectors."""
        filt = qm.Filter(must=[qm.FieldCondition(key="recordId", match=qm.MatchValue(value=record_id))])
        return self._scroll(filt)

    def _scroll(self, filt: qm.Filter | None) -> list:
        def run() -> list:
            if COLLECTION not in self._names():
                return []
            found: list = []
            offset = None
            while True:
                kwargs: dict = {
                    "collection_name": COLLECTION,
                    "limit": 128,
                    "offset": offset,
                    "with_payload": True,
                    "with_vectors": True,
                }
                if filt is not None:
                    kwargs["scroll_filter"] = filt
                batch, offset = self.client.scroll(**kwargs)
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

    def dense_vectors(self, chunk_ids: list[str]) -> dict[str, list[float]]:
        """Stored ``dense`` vectors for these chunk ids, fetched in one retrieve.

        The point id is ``uuid5(NAMESPACE, chunkId)``, the same id written at
        index time. A chunk with no point is absent. Callers turn that into
        a null similarity.
        """
        if not chunk_ids:
            return {}

        def run() -> dict[str, list[float]]:
            if COLLECTION not in self._names():
                return {}
            by_point = {str(uuid.uuid5(NAMESPACE, cid)): cid for cid in chunk_ids}
            points = self.client.retrieve(
                collection_name=COLLECTION,
                ids=list(by_point),
                with_payload=False,
                with_vectors=["dense"],
            )
            found: dict[str, list[float]] = {}
            for point in points:
                cid = by_point.get(str(point.id))
                if cid is None:
                    continue
                values = _dense_values(point.vector)
                if values is not None:
                    found[cid] = values
            return found

        return self._call(run)

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


def _dense_values(vector: object) -> list[float] | None:
    raw = vector.get("dense") if isinstance(vector, dict) else vector
    if raw is None or isinstance(raw, (str, bytes)):
        return None
    try:
        values = [float(item) for item in raw]
    except (TypeError, ValueError):
        return None
    return values or None
