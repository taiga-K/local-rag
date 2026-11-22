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
    NAMESPACE,
    Database,
    bm25_rows,
    chunk_public_id,
    delete_chunks_for,
    delete_postings,
    app_settings_row,
    generation_row,
    hydrate_chunks,
    insert_chunks,
    insert_weighted_postings,
    queue_records_with_text,
    read_score_threshold,
    record_id_for,
    write_generation,
    write_postings,
    replace_graph,
    replace_groups,
)
from kbindex.embed import Embedder
from kbindex.fastembed_bm25 import document_weights, query_terms
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.retrieve_cut import finish_retrieve, leg_depth
from kbindex.rrf import rrf_scores
from kbindex.similarity import apply_score_threshold, cosine


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


_CITATION_KEYS = (
    "section_title",
    "page_number",
    "line_number",
    "paragraph_number",
    "sheet_name",
    "row_number",
    "column_number",
    "slide_number",
)


def texts_of_stored(payload: dict) -> list[tuple[int, str, str, dict | None]]:
    """`(index, type, indexable text, citation)` for each stored block. Images keep an empty text."""
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
        out.append((int(block.get("index") or 0), kind, text if isinstance(text, str) else "", _citation(block)))
    return out


def _citation(block: dict) -> dict | None:
    raw = block.get("citation_metadata")
    if not isinstance(raw, dict):
        return None
    kept = {key: raw[key] for key in _CITATION_KEYS if raw.get(key) is not None}
    return kept or None


def build_pieces(record_id: str, payload: dict, embedder: Embedder) -> list:
    pairs = [(index, text) for index, _kind, text, _cite in texts_of_stored(payload)]
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

    def capture_index(self) -> dict:
        """Copy vectors, chunks, postings, and statuses before a full rebuild."""
        points = self.vectors.scroll_all()
        with self.db.connect() as conn:
            chunks = [
                dict(row)
                for row in conn.execute(
                    "select chunk_id, record_id, block_id, block_index, piece, text, token_count from chunks"
                ).fetchall()
            ]
            postings = [
                dict(row)
                for row in conn.execute(
                    "select generation, tokenizer, term, chunk_id, tf, doc_len from bm25_postings"
                ).fetchall()
            ]
            statuses = [
                dict(row)
                for row in conn.execute("select record_id, indexing_status, failure_reason from records").fetchall()
            ]
            generation = generation_row(conn)
        return {
            "points": points,
            "chunks": chunks,
            "postings": postings,
            "statuses": statuses,
            "generation": dict(generation) if generation else None,
        }

    def restore_index(self, snap: dict) -> None:
        """Put a capture_index snapshot back after a rebuild that could not be published."""
        generation = snap.get("generation")
        dim = int(generation["dimension"]) if generation and generation.get("dimension") else self.embedder.dim
        self.vectors.drop()
        self.vectors.ensure(dim)
        self.vectors.restore_points(snap["points"])
        with self.db.connect() as conn:
            delete_postings(conn, "true")
            conn.execute("delete from chunks")
            for row in snap["chunks"]:
                conn.execute(
                    """
                    insert into chunks (chunk_id, record_id, block_id, block_index, piece, text, token_count)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["chunk_id"], row["record_id"], row["block_id"], row["block_index"],
                        row["piece"], row["text"], row["token_count"],
                    ),
                )
            write_postings(
                conn,
                [
                    (row["generation"], row["tokenizer"], row["term"], row["chunk_id"], row["tf"], row["doc_len"])
                    for row in snap["postings"]
                ],
            )
            for row in snap["statuses"]:
                conn.execute(
                    """
                    update records set indexing_status = %s, failure_reason = %s, updated_at = now()
                    where record_id = %s
                    """,
                    (row["indexing_status"], row["failure_reason"], row["record_id"]),
                )
            if generation:
                write_generation(
                    conn,
                    fingerprint=generation["fingerprint"],
                    model=generation["model"],
                    dimension=_optional_int(generation.get("dimension")),
                    max_seq_length=_optional_int(generation.get("max_seq_length")),
                    keyword=_json_map(generation.get("keyword_json")),
                    fusion=_json_map(generation.get("fusion_json")),
                )
            conn.commit()

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
                  and indexing_status in ('QUEUED', 'IN_PROGRESS', 'FAILED', 'COMPLETED', 'EMPTY', 'AUTO_INDEX_OFF')
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
            self._fail(rid, event_version, event_rev, _stored_error(exc))
            return "FAILED"

    def _finish_empty(self, rid, event_version: int, event_rev: str) -> str:
        with self.db.connect() as conn:
            row = conn.execute(
                "select version, content_rev, indexing_status from records where record_id = %s for update",
                (rid,),
            ).fetchone()
            if (
                row is None
                or row["version"] != event_version
                or row["content_rev"] != event_rev
                or row["indexing_status"] != "IN_PROGRESS"
            ):
                conn.rollback()
                return "stale"
            delete_chunks_for(conn, rid)
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
                    id=str(uuid.uuid5(NAMESPACE, cid)),
                    vector={"dense": vector},
                    payload=payload_out,
                )
            )
            sparse_docs[cid] = document_weights(piece.text)
        with self.db.connect() as conn:
            row = conn.execute(
                "select version, content_rev, indexing_status from records where record_id = %s for update",
                (rid,),
            ).fetchone()
            if row is None:
                conn.rollback()
                try:
                    self.vectors.delete_record(str(rid))
                except QdrantUnavailable:
                    pass
                return "gone"
            if row["version"] != event_version or row["content_rev"] != event_rev or row["indexing_status"] != "IN_PROGRESS":
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
            graph = [(index, parent_of(payload, index), kind, text, cite) for index, kind, text, cite in listed]
            replace_graph(conn, rid, graph)
            replace_groups(conn, rid, groups_of(payload))
            delete_chunks_for(conn, rid)
            insert_chunks(conn, rid, chunk_rows)
            insert_weighted_postings(conn, "fastembed", sparse_docs, length_from_weight=False)
            conn.execute(
                """
                update records set indexing_status = 'COMPLETED', has_indexed_copy = true,
                  failure_reason = null, updated_at = now()
                where record_id = %s and version = %s and indexing_status = 'IN_PROGRESS'
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
        query_vector = self.embedder.embed_query(query)
        dense_pairs = self.vectors.search(query_vector, limit=depth, kb_ids=kb_ids)
        sparse_pairs = [] if not self._keyword_enabled() else self._fastembed(query, depth, kb_ids)
        ranked = rrf_scores(
            [[cid for cid, _score in dense_pairs], [cid for cid, _score in sparse_pairs]],
            k=1,
        )
        fused, enabled, threshold = self._filter_fused(ranked, kb_ids, bounds)
        # Threshold runs on the whole fused list, then finish_retrieve cuts to limit.
        scored = apply_score_threshold(
            fused,
            self._similarities(query_vector, [cid for cid, _score, _row in fused], enabled=enabled),
            enabled=enabled,
            threshold=threshold,
        )
        limited = finish_retrieve(
            scored,
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
            enabled, threshold = read_score_threshold(conn)
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
        return kept, enabled, threshold

    def _similarities(self, query_vector: list[float], chunk_ids: list[str], *, enabled: bool) -> dict[str, float | None]:
        """Cosine for every fused candidate, including BM25-only hits.

        One retrieve covers the whole list. While the threshold is off, a
        Qdrant failure leaves similarity null and still returns today's hits.
        While it is on, that failure is the same 503 as a failed dense search,
        because the filter cannot be decided.
        """
        if not chunk_ids:
            return {}
        try:
            stored = self.vectors.dense_vectors(chunk_ids)
        except QdrantUnavailable:
            if enabled:
                raise
            return {cid: None for cid in chunk_ids}
        return {cid: cosine(query_vector, stored[cid]) if cid in stored else None for cid in chunk_ids}

    def _chunk_json(self, item) -> dict:
        cid, score, row, similarity = item
        updated = row["source_modified_ms"]
        if updated is None and row["updated_at"] is not None:
            updated = int(row["updated_at"].timestamp() * 1000)
        return {
            "id": cid,
            "text": row["text"],
            "score": score,
            "similarity": similarity,
            "record": {
                "recordId": row["external_record_id"],
                "name": row["record_name"],
                "connector": row["kb_id"],
                "mimeType": "application/blocks",
                "updatedAt": updated,
            },
            "citation": _result_citation(row),
        }

    def _keyword_enabled(self) -> bool:
        with self.db.connect() as conn:
            row = app_settings_row(conn)
        return bool(row.get("keyword_enabled", True))

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


def _result_citation(row) -> dict:
    raw = row.get("citation") or {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raw = {}
    return {
        "url": None,
        "recordUrl": None,
        "pageNum": raw.get("page_number"),
        "blockIndex": row["block_index"],
        "sectionTitle": raw.get("section_title"),
        "lineNumber": raw.get("line_number"),
        "paragraphNumber": raw.get("paragraph_number"),
        "sheetName": raw.get("sheet_name"),
        "rowNumber": raw.get("row_number"),
        "columnNumber": raw.get("column_number"),
        "slideNumber": raw.get("slide_number"),
    }


def _stored_error(exc: BaseException) -> str:
    """Keep the exception text the process already has. Do not classify it."""
    detail = " ".join(str(exc).split())
    text = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    return text[:200]


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


def branch_depth(limit: int) -> int:
    """Hits each retriever returns before RRF.

    PipesHub prefetches ``limit * 2``. A keyword-only hit whose dense rank is
    just outside that window scores as if dense never saw it. At k=60 that
    drops a rank-1 keyword passage out of the top 10. The floor of 64 keeps
    those near misses in the fusion.
    """
    return max(limit * 2, 64)


def _optional_int(value: object) -> int | None:
    """Keep a nullable generation column null. int(None) would abort the restore."""
    if value is None:
        return None
    return int(value)


def _json_map(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    return {}


def has_indexable_text(envelope: Envelope) -> bool:
    for block in envelope.blocks.blocks or []:
        if block_text(block).strip():
            return True
    return False
