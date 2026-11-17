"""Index one record and answer one query from the current row."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client.http import models as qm

from kbindex.bm25 import Corpus
from kbindex.chunking import chunk_blocks
from kbindex.config import Settings
from kbindex.contract import Envelope, block_text, blocks_digest, content_rev, properties_of, request_digest, stored_bytes
from kbindex.db import (
    Database,
    bm25_rows,
    chunk_public_id,
    clear_postings,
    delete_chunks_for,
    generation_row,
    hydrate_chunks,
    insert_chunks,
    insert_postings,
    queue_records_with_text,
    rebuild_bm25,
    record_id_for,
    record_of_chunk,
    replace_graph,
    replace_groups,
    write_generation,
)
from kbindex.embed import Embedder
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.rrf import rrf_scores
from kbindex.tokenize import char_bigrams, sudachi_terms


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


def _terms(settings: Settings, name: str, text: str) -> list[str]:
    if name == "sudachi":
        return sudachi_terms(text, mode=settings.sudachi_mode, normalize=settings.sudachi_normalize)
    if name == "char_bigram":
        return char_bigrams(
            text,
            nfkc=settings.bigram_nfkc,
            casefold=settings.bigram_casefold,
            drop_space=settings.bigram_drop_space,
            drop_control=settings.bigram_drop_control,
            drop_punct=settings.bigram_drop_punct,
        )
    return []


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
        self.fingerprint = settings.index_fingerprint(hidden_size=embedder.dim, max_seq_length=embedder.max_seq_length)

    def fingerprint_mismatch(self) -> bool:
        with self.db.connect() as conn:
            row = generation_row(conn)
        if row is None:
            return False
        return row["fingerprint"] != self.fingerprint

    def ensure_generation(self) -> None:
        """Insert the current fingerprint when the table is empty. Leave a mismatch alone."""
        with self.db.connect() as conn:
            row = generation_row(conn)
            if row is None:
                write_generation(
                    conn,
                    fingerprint=self.fingerprint,
                    model=self.settings.model,
                    dimension=self.embedder.dim,
                    max_seq_length=self.embedder.max_seq_length,
                    keyword={"tokenizers": list(self.settings.tokenizers), "mode": self.settings.sudachi_mode, "normalize": self.settings.sudachi_normalize},
                    fusion={"method": self.settings.fusion_method, "k": self.settings.fusion_k},
                )
                conn.commit()
            elif row["fingerprint"] != self.fingerprint:
                try:
                    if self.vectors.count() > 0:
                        return
                    self.vectors.drop()
                except QdrantUnavailable:
                    return
                write_generation(
                    conn,
                    fingerprint=self.fingerprint,
                    model=self.settings.model,
                    dimension=self.embedder.dim,
                    max_seq_length=self.embedder.max_seq_length,
                    keyword={"tokenizers": list(self.settings.tokenizers), "mode": self.settings.sudachi_mode, "normalize": self.settings.sudachi_normalize},
                    fusion={"method": self.settings.fusion_method, "k": self.settings.fusion_k},
                )
                conn.commit()
        try:
            self.vectors.ensure(self.embedder.dim)
        except QdrantUnavailable:
            return

    def config_refused(self) -> bool:
        if not self.fingerprint_mismatch():
            return False
        return self.vectors.count() > 0

    def reindex(self) -> tuple[str, list]:
        self.vectors.drop()
        self.vectors.ensure(self.embedder.dim)
        with self.db.connect() as conn:
            clear_postings(conn)
            write_generation(
                conn,
                fingerprint=self.fingerprint,
                model=self.settings.model,
                dimension=self.embedder.dim,
                max_seq_length=self.embedder.max_seq_length,
                keyword={"tokenizers": list(self.settings.tokenizers), "mode": self.settings.sudachi_mode, "normalize": self.settings.sudachi_normalize},
                fusion={"method": self.settings.fusion_method, "k": self.settings.fusion_k},
            )
            rows = queue_records_with_text(conn)
            conn.commit()
        return self.fingerprint, rows

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
                update records set indexing_status = 'EMPTY', failure_reason = null, updated_at = now()
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
        token_docs: dict[str, dict[str, list[str]]] = {name: {} for name in self.settings.tokenizers}
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
            for name in self.settings.tokenizers:
                token_docs[name][cid] = _terms(self.settings, name, piece.text)
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
                self.vectors.upsert(points)
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
            for name, docs in token_docs.items():
                insert_postings(conn, name, docs)
            rebuild_bm25(conn)
            conn.execute(
                """
                update records set indexing_status = 'COMPLETED', failure_reason = null, updated_at = now()
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

    def search(self, query: str, *, limit: int, kb_ids: list[str] | None, max_per_record: int | None, bounds: dict) -> dict:
        # Each branch fetches limit*2 before fusion. PipesHub's Qdrant prefetch
        # does the same for one dense and one sparse leg (qdrant/utils.py
        # L280-L301 at acc3095). Keyword legs are Postgres BM25, one per tokenizer.
        depth = branch_depth(limit)
        dense_pairs = self.vectors.search(self.embedder.embed_query(query), limit=depth, kb_ids=kb_ids)
        keyword_pairs: dict[str, list[tuple[str, float]]] = {}
        for name in ("sudachi", "char_bigram"):
            if name in self.settings.tokenizers:
                keyword_pairs[name] = self._bm25(name, query, depth)
            else:
                keyword_pairs[name] = []
        lists = [[cid for cid, _score in dense_pairs]]
        for name in self.settings.tokenizers:
            lists.append([cid for cid, _score in keyword_pairs.get(name, [])])
        ranked = rrf_scores(lists, k=self.settings.fusion_k)
        fused = self._filter_fused(ranked, kb_ids, bounds)
        if max_per_record is not None:
            kept = []
            seen: Counter[str] = Counter()
            for cid, score, row in fused:
                record = record_of_chunk(cid)
                if seen[record] >= max_per_record:
                    continue
                seen[record] += 1
                kept.append((cid, score, row))
            fused = kept
        limited = fused[:limit]
        return {
            "chunks": [self._chunk_json(item) for item in limited],
            "dense": dense_pairs,
            "keyword": keyword_pairs,
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

    def _bm25(self, tokenizer: str, query: str, limit: int) -> list[tuple[str, float]]:
        terms = _terms(self.settings, tokenizer, query)
        if not terms:
            return []
        with self.db.connect() as conn:
            stats, df_rows, posts = bm25_rows(conn, tokenizer, list(set(terms)))
        if not stats or stats["doc_count"] == 0:
            return []
        corpus = Corpus(k1=self.settings.bm25_k1, b=self.settings.bm25_b)
        corpus.doc_count = int(stats["doc_count"])
        corpus.total_tokens = int(stats["total_tokens"])
        for row in df_rows:
            corpus.df[row["term"]] = int(row["df"])
        by_doc: dict[str, list] = {}
        for row in posts:
            by_doc.setdefault(row["chunk_id"], []).append(row)
        for cid, triples in by_doc.items():
            counts: Counter[str] = Counter()
            for row in triples:
                counts[row["term"]] = int(row["tf"])
            corpus.tf[cid] = counts
            corpus.lengths[cid] = int(triples[0]["doc_len"])
        return corpus.rank(terms)[:limit]


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
    """Hits each retriever returns before RRF. Mirrors PipesHub Prefetch `limit * 2`."""
    return limit * 2


def has_indexable_text(envelope: Envelope) -> bool:
    for block in envelope.blocks.blocks or []:
        if block_text(block).strip():
            return True
    return False
