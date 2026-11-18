"""Index one record and answer one query from the current row."""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client.http import models as qm

from kbindex.chunking import chunk_blocks
from kbindex.config import Settings
from kbindex.contract import Envelope, block_text, blocks_digest, content_rev, properties_of, request_digest, stored_bytes
from kbindex.db import (
    Database,
    bm25_rows,
    chunk_public_id,
    delete_chunks_for,
    hydrate_chunks,
    insert_chunks,
    insert_weighted_postings,
    queue_records_with_text,
    rebuild_bm25,
    record_id_for,
    replace_graph,
    replace_groups,
)
from kbindex.embed import Embedder
from kbindex.fastembed_bm25 import document_weights, query_terms
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.retrieve_cut import finish_retrieve, leg_depth
from kbindex.rrf import rrf_scores


@dataclass(frozen=True)
class Prepared:
    blocks_sha: str
    request_digest: str
    stored: bytes
    content_rev: str
    revision: str


def prepare(envelope: Envelope) -> Prepared:
    props = properties_of(envelope)
    blocks_sha = blocks_digest(envelope.blocks)
    digest = request_digest(blocks_sha, props)
    stored = stored_bytes(envelope.blocks, props)
    rev = content_rev(stored)
    return Prepared(blocks_sha, digest, stored, rev, f"pb1:{digest}:{rev}")


def write_payload(directory: Path, kb_id: str, record_id: str, raw: bytes, stored: bytes) -> tuple[str, str]:
    folder = directory / kb_id
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / f"{record_id}.raw.json"
    stored_path = folder / f"{record_id}.stored.json"
    tmp_raw = folder / f"{record_id}.raw.json.tmp"
    tmp_stored = folder / f"{record_id}.stored.json.tmp"
    tmp_raw.write_bytes(raw)
    tmp_stored.write_bytes(stored)
    os.replace(tmp_raw, raw_path)
    os.replace(tmp_stored, stored_path)
    return str(raw_path), str(stored_path)


def texts_of_stored(payload: dict) -> list[tuple[int, str, str]]:
    """`(index, type, indexable text)` for each stored block. Images keep an empty text."""
    out = []
    for block in payload.get("blocks") or []:
        kind = block.get("type") or ""
        if kind == "text":
            text = block.get("data") or ""
        elif kind == "table_row":
            data = block.get("data") or {}
            if data.get("cells"):
                text = "\t".join(data["cells"])
            else:
                text = data.get("row_natural_language_text") or ""
        else:
            text = ""
        out.append((int(block.get("index") or 0), kind, text if isinstance(text, str) else ""))
    return out


def build_pieces(record_id: str, payload: dict, embedder: Embedder) -> list:
    pairs = [(index, text) for index, _kind, text in texts_of_stored(payload)]
    return chunk_blocks(pairs, window=embedder.split_limit(), spans=embedder.token_spans)


class Engine:
    def __init__(self, settings: Settings, db: Database, vectors: Vectors, embedder: Embedder) -> None:
        self.settings = settings
        self.db = db
        self.vectors = vectors
        self.embedder = embedder

    def ensure_generation(self) -> None:
        """Create the collection at the loaded model's dimension. Do not rebuild it."""
        try:
            self.vectors.ensure(self.embedder.dim)
        except QdrantUnavailable:
            return

    def queue_reindex(self) -> list:
        """Re-embed stored records without dropping the collection. One row per record."""
        with self.db.connect() as conn:
            rows = queue_records_with_text(conn)
            conn.commit()
        return rows

    def index_record(self, kb_id: str, external_record_id: str, *, event_version: int, event_rev: str) -> str:
        rid = record_id_for(kb_id, external_record_id)
        with self.db.connect() as conn:
            updated = conn.execute(
                """
                update records
                set indexing_status = 'IN_PROGRESS', failure_reason = null, updated_at = now()
                where record_id = %s and version = %s and content_rev = %s
                  and indexing_status in ('QUEUED', 'IN_PROGRESS', 'FAILED', 'COMPLETED', 'EMPTY')
                returning stored_path, record_name, source_modified_ms, version, content_rev
                """,
                (rid, event_version, event_rev),
            ).fetchone()
            conn.commit()
        if updated is None:
            return "stale"
        try:
            payload = json.loads(Path(updated["stored_path"]).read_bytes())
            pieces = build_pieces(str(rid), payload, self.embedder)
            self._set_embed_progress(rid, event_version, 0, len(pieces))
            if not pieces:
                return self._finish_empty(rid, event_version, event_rev)
            vectors = self.embedder.embed_documents([piece.text for piece in pieces])
            return self._finish_chunks(rid, kb_id, updated, pieces, vectors, event_version, event_rev, payload)
        except QdrantUnavailable:
            self._fail(rid, event_version, event_rev, "QDRANT_UNAVAILABLE")
            return "FAILED"
        except Exception as exc:
            self._fail(rid, event_version, event_rev, type(exc).__name__[:200])
            return "FAILED"

    def _finish_empty(self, rid, event_version: int, event_rev: str) -> str:
        with self.db.connect() as conn:
            row = conn.execute("select version, content_rev from records where record_id = %s for update", (rid,)).fetchone()
            if row is None or row["version"] != event_version or row["content_rev"] != event_rev:
                conn.rollback()
                return "stale"
            delete_chunks_for(conn, rid)
            rebuild_bm25(conn)
            conn.execute(
                """
                update records set indexing_status = 'EMPTY', has_indexed_copy = false, failure_reason = null, updated_at = now()
                where record_id = %s and version = %s
                """,
                (rid, event_version),
            )
            conn.commit()
        try:
            self.vectors.delete_record(str(rid))
        except QdrantUnavailable:
            self._fail(rid, event_version, event_rev, "QDRANT_UNAVAILABLE")
            return "FAILED"
        return "EMPTY"

    def _finish_chunks(self, rid, kb_id, updated, pieces, vectors, event_version, event_rev, payload) -> str:
        chunk_rows = []
        points = []
        sparse_docs: dict[str, list[tuple[str, float]]] = {}
        counts: dict[int, int] = {}
        for piece in pieces:
            counts[piece.block_index] = counts.get(piece.block_index, 0) + 1
        listed = texts_of_stored(payload)
        for piece, vector in zip(pieces, vectors, strict=True):
            cid = chunk_public_id(str(rid), piece.block_index, piece.piece, counts[piece.block_index])
            chunk_rows.append((cid, piece.block_index, piece.piece, piece.text, piece.token_count))
            payload_out = {
                "chunkId": cid,
                "recordId": str(rid),
                "kbId": kb_id,
                "blockIndex": piece.block_index,
                "piece": piece.piece,
                "text": piece.text,
                "recordName": updated["record_name"],
                "mimeType": "application/blocks",
            }
            if updated["source_modified_ms"] is not None:
                payload_out["sourceModifiedMs"] = int(updated["source_modified_ms"])
            points.append(
                qm.PointStruct(
                    id=str(uuid.uuid5(uuid.UUID("c3a1e5b0-7d2e-4b1a-9f60-4a0b1c2d3e4f"), cid)),
                    vector={"dense": vector},
                    payload=payload_out,
                )
            )
            sparse_docs[cid] = document_weights(piece.text)
        with self.db.connect() as conn:
            row = conn.execute("select version, content_rev from records where record_id = %s for update", (rid,)).fetchone()
            if row is None:
                conn.rollback()
                try:
                    self.vectors.delete_record(str(rid))
                except QdrantUnavailable:
                    pass
                return "gone"
            if row["version"] != event_version or row["content_rev"] != event_rev:
                conn.rollback()
                return "stale"
            try:
                self.vectors.delete_record(str(rid))
                self.vectors.ensure(self.embedder.dim)
                self.vectors.upsert(points, expected_dim=self.embedder.dim)
            except QdrantUnavailable:
                conn.execute(
                    """
                    update records set indexing_status = 'FAILED', failure_reason = 'QDRANT_UNAVAILABLE', updated_at = now()
                    where record_id = %s and version = %s
                    """,
                    (rid, event_version),
                )
                conn.commit()
                return "FAILED"
            graph = [(index, parent_of(payload, index), kind, text) for index, kind, text in listed]
            replace_graph(conn, rid, graph)
            replace_groups(conn, rid, groups_of(payload))
            delete_chunks_for(conn, rid)
            insert_chunks(conn, rid, chunk_rows)
            insert_weighted_postings(conn, "fastembed", sparse_docs, length_from_weight=False)
            rebuild_bm25(conn)
            conn.execute(
                """
                update records set indexing_status = 'COMPLETED', has_indexed_copy = true,
                  failure_reason = null, updated_at = now()
                where record_id = %s and version = %s
                """,
                (rid, event_version),
            )
            conn.commit()
        return "COMPLETED"

    def _fail(self, rid, event_version: int, event_rev: str, reason: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                update records set indexing_status = 'FAILED', failure_reason = %s, updated_at = now()
                where record_id = %s and version = %s and content_rev = %s
                """,
                (reason, rid, event_version, event_rev),
            )
            conn.commit()

    def _set_embed_progress(self, rid, event_version: int, done: int, total: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                update records set embed_done = %s, embed_total = %s
                where record_id = %s and version = %s and indexing_status = 'IN_PROGRESS'
                """,
                (done, total, rid, event_version),
            )
            conn.commit()

    def search(
        self,
        query: str,
        *,
        limit: int,
        kb_ids: list[str] | None,
        max_per_record: int | None,
        bounds: dict,
    ) -> dict:
        depth = leg_depth(limit, max_per_record)
        dense_pairs = self.vectors.search(self.embedder.embed_query(query), limit=depth, kb_ids=kb_ids)
        sparse_pairs = self._fastembed(query, depth, kb_ids)
        ranked = rrf_scores(
            [[cid for cid, _score in dense_pairs], [cid for cid, _score in sparse_pairs]],
            k=1,
        )
        fused = self._filter_fused(ranked, kb_ids, bounds)
        limited = finish_retrieve(
            fused,
            page_limit=limit,
            query=query,
            max_per_record=max_per_record,
            record_of=lambda item: str(item[2]["record_id"]),
            text_of=lambda item: item[2]["text"],
        )
        return {
            "chunks": [self._chunk_json(item) for item in limited],
            "dense": dense_pairs,
            "keyword": {"fastembed": sparse_pairs},
            "fused": fused,
            "incomplete": False,
        }

    def _filter_fused(self, fused, kb_ids: list[str] | None, bounds: dict):
        ids = [cid for cid, _score in fused]
        with self.db.connect() as conn:
            rows = hydrate_chunks(conn, ids)
        by_id = {row["chunk_id"]: row for row in rows}
        kept = []
        for cid, score in fused:
            row = by_id.get(cid)
            if row is None:
                continue
            if kb_ids and row["kb_id"] not in kb_ids:
                continue
            visible = row["indexing_status"] == "COMPLETED" or bool(row.get("has_indexed_copy"))
            if not visible:
                continue
            if not _in_bounds(row, bounds):
                continue
            kept.append((cid, score, row))
        return kept

    def _chunk_json(self, item) -> dict:
        cid, score, row = item
        updated = row["source_modified_ms"]
        if updated is None and row["updated_at"] is not None:
            updated = int(row["updated_at"].timestamp() * 1000)
        return {
            "id": cid,
            "text": row["text"],
            "score": score,
            "record": {
                "recordId": row["external_record_id"],
                "name": row["record_name"],
                "connector": row["kb_id"],
                "mimeType": "application/blocks",
                "updatedAt": updated,
            },
            "citation": {
                "url": None,
                "recordUrl": None,
                "pageNum": None,
                "blockIndex": row["block_index"],
            },
        }

    def _fastembed(self, query: str, limit: int, kb_ids: list[str] | None) -> list[tuple[str, float]]:
        """fastembed document weight times the recompute IDF. Not Okapi."""
        terms = query_terms(query)
        if not terms:
            return []
        with self.db.connect() as conn:
            stats, df_rows, posts = bm25_rows(conn, "fastembed", terms, kb_ids)
        if not stats or int(stats["doc_count"]) == 0:
            return []
        n_docs = int(stats["doc_count"])
        df = {row["term"]: int(row["df"]) for row in df_rows}
        scores: dict[str, float] = {}
        for row in posts:
            n = df.get(row["term"], 0)
            idf = math.log((n_docs - n + 0.5) / (n + 0.5) + 1.0)
            scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + float(row["tf"]) * idf
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [(chunk_id, score) for chunk_id, score in ranked if score > 0][:limit]


def parent_of(payload: dict, index: int) -> int | None:
    for block in payload.get("blocks") or []:
        if int(block.get("index") or 0) == index:
            parent = block.get("parent_index")
            return int(parent) if parent is not None else None
    return None


def groups_of(payload: dict) -> list[tuple[int, int | None, str, str | None]]:
    out = []
    for group in payload.get("block_groups") or []:
        parent = group.get("parent_index")
        out.append((int(group.get("index") or 0), int(parent) if parent is not None else None, group.get("type") or "", group.get("name")))
    return out


def _in_bounds(row, bounds: dict) -> bool:
    created = row["created_at"]
    if bounds.get("created_after") and created < bounds["created_after"]:
        return False
    if bounds.get("created_before") and created > bounds["created_before"]:
        return False
    modified = row["source_modified_ms"]
    if bounds.get("modified_after") or bounds.get("modified_before"):
        if modified is None:
            return False
        if bounds.get("modified_after") and modified < _ms(bounds["modified_after"]):
            return False
        if bounds.get("modified_before") and modified > _ms(bounds["modified_before"]):
            return False
    return True


def _ms(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def has_indexable_text(envelope: Envelope) -> bool:
    for block in envelope.blocks.blocks or []:
        if block_text(block).strip():
            return True
    return False
