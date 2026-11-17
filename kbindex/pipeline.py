"""Index one record and answer one query. Idempotent given the current row."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from pathlib import Path

from qdrant_client.http import models as qm

from kbindex.bm25 import Corpus
from kbindex.chunking import chunk_blocks
from kbindex.contract import Envelope, block_text, blocks_digest, content_rev
from kbindex.db import Database, record_id_for
from kbindex.embed import Embedder
from kbindex.qdrant_store import COLLECTION, Vectors
from kbindex.rrf import rrf_scores
from kbindex.settings import Settings
from kbindex.tokenize import char_bigrams, sudachi_terms


def chunk_public_id(record_id: str, block_index: int, piece: int, piece_count: int) -> str:
    base = f"{record_id}:{block_index}"
    if piece_count == 1 or piece == 0:
        return base
    return f"{base}:{piece}"


class Engine:
    def __init__(self, settings: Settings, db: Database, vectors: Vectors, embedder: Embedder) -> None:
        self.settings = settings
        self.db = db
        self.vectors = vectors
        self.embedder = embedder

    def model_change_blocked(self) -> bool:
        with self.db.connect() as conn:
            row = conn.execute("select fingerprint from index_generation where id = 1").fetchone()
        if row is None or row["fingerprint"] == self.settings.fingerprint:
            return False
        return self.vectors.count() > 0

    def ensure_generation(self) -> None:
        if self.model_change_blocked():
            return
        self.vectors.ensure(self.embedder.dim)
        with self.db.connect() as conn:
            conn.execute(
                """
                insert into index_generation (id, fingerprint, model, ready)
                values (1, %s, %s, true)
                on conflict (id) do update set fingerprint = excluded.fingerprint, model = excluded.model, ready = true
                """,
                (self.settings.fingerprint, self.settings.model),
            )
            conn.commit()

    def index_record(self, kb_id: str, external_record_id: str) -> str:
        rid = record_id_for(kb_id, external_record_id)
        with self.db.connect() as conn:
            row = conn.execute("select * from records where record_id = %s", (rid,)).fetchone()
            if row is None:
                return "gone"
            conn.execute(
                "update records set indexing_status = 'IN_PROGRESS', failure_reason = null, embed_done = 0, embed_total = null, updated_at = now() where record_id = %s",
                (rid,),
            )
            conn.commit()
        try:
            stored = json.loads(Path(row["stored_path"]).read_text(encoding="utf-8"))
            blocks = stored.get("blocks") or []
            texts = []
            for block in blocks:
                if block.get("type") == "text":
                    texts.append((block["index"], block.get("data") or ""))
                elif block.get("type") == "table_row":
                    data = block.get("data") or {}
                    if data.get("cells"):
                        texts.append((block["index"], "\t".join(data["cells"])))
                    else:
                        texts.append((block["index"], data.get("row_natural_language_text") or ""))
            window = max(8, self.embedder.max_seq_length - 8)
            pieces = chunk_blocks(texts, window=window)
            by_block: dict[int, int] = Counter(p.block_index for p in pieces)
            # piece_count per block for ids
            counts: dict[int, int] = {}
            for piece in pieces:
                counts[piece.block_index] = counts.get(piece.block_index, 0) + 1
            if not pieces:
                self._replace_children(rid, [], [])
                self.vectors.delete_record(str(rid))
                self._set_status(rid, "EMPTY", None, 0, 0)
                return "EMPTY"
            vectors = self.embedder.embed_documents([p.text for p in pieces])
            chunk_rows = []
            points = []
            token_docs: dict[str, dict[str, list[str]]] = {name: {} for name in self.settings.tokenizers}
            for piece, vector in zip(pieces, vectors, strict=True):
                cid = chunk_public_id(str(rid), piece.block_index, piece.piece, counts[piece.block_index])
                chunk_rows.append((cid, piece.block_index, piece.piece, piece.text, piece.token_count))
                points.append(qm.PointStruct(
                    id=str(uuid.uuid5(uuid.UUID("c3a1e5b0-7d2e-4b1a-9f60-4a0b1c2d3e4f"), cid)),
                    vector=vector,
                    payload={
                        "chunkId": cid,
                        "recordId": str(rid),
                        "kbId": kb_id,
                        "blockIndex": piece.block_index,
                        "piece": piece.piece,
                        "text": piece.text,
                        "recordName": row["record_name"],
                        "mimeType": "application/blocks",
                        "sourceModifiedMs": row["source_modified_ms"],
                    },
                ))
                for name in self.settings.tokenizers:
                    token_docs[name][cid] = self._terms(name, piece.text)
            self.vectors.delete_record(str(rid))
            self.vectors.ensure(self.embedder.dim)
            self.vectors.upsert(points)
            self._replace_children(rid, [(block["index"], block.get("type"), block_plain(block)) for block in blocks], chunk_rows)
            self._write_bm25(str(rid), token_docs)
            self._set_status(rid, "COMPLETED", None, len(pieces), len(pieces))
            return "COMPLETED"
        except Exception as exc:
            self._set_status(rid, "FAILED", type(exc).__name__, None, None)
            return "FAILED"

    def _terms(self, name: str, text: str) -> list[str]:
        if name == "sudachi":
            return sudachi_terms(text, mode=self.settings.sudachi_mode, normalize=self.settings.sudachi_normalize)
        if name == "char_bigram":
            return char_bigrams(text)
        return []

    def _set_status(self, rid, status: str, reason: str | None, done, total) -> None:
        with self.db.connect() as conn:
            still = conn.execute("select 1 from records where record_id = %s", (rid,)).fetchone()
            if still is None:
                self.vectors.delete_record(str(rid))
                return
            conn.execute(
                """
                update records set indexing_status = %s, failure_reason = %s, embed_done = %s, embed_total = %s, updated_at = now()
                where record_id = %s
                """,
                (status, reason, done, total, rid),
            )
            conn.commit()

    def _replace_children(self, rid, blocks, chunks) -> None:
        with self.db.connect() as conn:
            conn.execute("delete from chunks where record_id = %s", (rid,))
            conn.execute("delete from blocks where record_id = %s", (rid,))
            for position, kind, text in blocks:
                conn.execute(
                    "insert into blocks (block_id, record_id, position, type, text) values (%s, %s, %s, %s, %s)",
                    (uuid.uuid4(), rid, position, kind, text),
                )
            for cid, block_index, piece, text, tokens in chunks:
                conn.execute(
                    "insert into chunks (chunk_id, record_id, block_index, piece, text, token_count) values (%s, %s, %s, %s, %s, %s)",
                    (cid, rid, block_index, piece, text, tokens),
                )
            conn.commit()

    def _write_bm25(self, record_id: str, token_docs: dict[str, dict[str, list[str]]]) -> None:
        with self.db.connect() as conn:
            old = conn.execute("select chunk_id from chunks where record_id = %s", (record_id,)).fetchall()
            # chunks were just replaced, so delete postings for this record's previous chunk ids by prefix
            conn.execute("delete from bm25_postings where chunk_id like %s", (record_id + ":%",))
            for tokenizer, docs in token_docs.items():
                for cid, terms in docs.items():
                    counts = Counter(terms)
                    doc_len = sum(counts.values())
                    for term, tf in counts.items():
                        conn.execute(
                            """
                            insert into bm25_postings (generation, tokenizer, term, chunk_id, tf, doc_len)
                            values (1, %s, %s, %s, %s, %s)
                            on conflict (generation, tokenizer, term, chunk_id) do update set tf = excluded.tf, doc_len = excluded.doc_len
                            """,
                            (tokenizer, term, cid, tf, doc_len),
                        )
            conn.execute(
                """
                insert into bm25_terms (generation, tokenizer, term, df)
                select generation, tokenizer, term, count(distinct chunk_id)
                from bm25_postings group by generation, tokenizer, term
                on conflict (generation, tokenizer, term) do update set df = excluded.df
                """
            )
            conn.execute("delete from bm25_terms where df = 0")
            conn.execute(
                """
                insert into bm25_stats (generation, tokenizer, doc_count, total_tokens)
                select 1, tokenizer, count(distinct chunk_id), coalesce(sum(doc_len), 0)
                from (
                  select tokenizer, chunk_id, max(doc_len) as doc_len from bm25_postings group by tokenizer, chunk_id
                ) s group by tokenizer
                on conflict (generation, tokenizer) do update set doc_count = excluded.doc_count, total_tokens = excluded.total_tokens
                """
            )
            conn.commit()
        del old

    def search(self, query: str, *, limit: int, kb_id: str | None, max_per_record: int | None) -> dict:
        if self.model_change_blocked():
            return {"blocked": True}
        dense_pairs = self.vectors.search(self.embedder.embed_query(query), limit=50, kb_id=kb_id)
        keyword_pairs: dict[str, list[tuple[str, float]]] = {}
        for name in self.settings.tokenizers:
            keyword_pairs[name] = self._bm25(name, query, kb_id)
        lists = [[cid for cid, _ in dense_pairs]]
        lists.extend([cid for cid, _ in pairs] for pairs in keyword_pairs.values())
        fused = rrf_scores(lists, k=self.settings.fusion_k)
        if kb_id:
            fused = [(cid, score) for cid, score in fused if self._chunk_kb(cid) == kb_id]
        if max_per_record is not None:
            kept = []
            seen: Counter[str] = Counter()
            for cid, score in fused:
                rec = cid.split(":")[0]
                if seen[rec] >= max_per_record:
                    continue
                seen[rec] += 1
                kept.append((cid, score))
            fused = kept
        fused = fused[:limit]
        chunks = [self._chunk_json(cid, score) for cid, score in fused]
        return {"chunks": chunks, "incomplete": False, "dense": dense_pairs, "keyword": keyword_pairs, "fused": fused}

    def _bm25(self, tokenizer: str, query: str, kb_id: str | None) -> list[tuple[str, float]]:
        terms = self._terms(tokenizer, query)
        if not terms:
            return []
        with self.db.connect() as conn:
            stats = conn.execute(
                "select doc_count, total_tokens from bm25_stats where generation = 1 and tokenizer = %s",
                (tokenizer,),
            ).fetchone()
            if not stats or stats["doc_count"] == 0:
                return []
            corpus = Corpus(k1=self.settings.bm25_k1, b=self.settings.bm25_b)
            corpus.doc_count = stats["doc_count"]
            corpus.total_tokens = stats["total_tokens"]
            rows = conn.execute(
                "select term, df from bm25_terms where generation = 1 and tokenizer = %s and term = any(%s)",
                (tokenizer, list(set(terms))),
            ).fetchall()
            for row in rows:
                corpus.df[row["term"]] = row["df"]
            posts = conn.execute(
                "select term, chunk_id, tf, doc_len from bm25_postings where generation = 1 and tokenizer = %s and term = any(%s)",
                (tokenizer, list(set(terms))),
            ).fetchall()
        by_doc: dict[str, list[tuple[str, int, int]]] = {}
        for row in posts:
            by_doc.setdefault(row["chunk_id"], []).append((row["term"], row["tf"], row["doc_len"]))
        for cid, triples in by_doc.items():
            if kb_id and self._chunk_kb(cid) != kb_id:
                continue
            counts: Counter[str] = Counter()
            doc_len = triples[0][2]
            for term, tf, _ in triples:
                counts[term] = tf
            corpus.tf[cid] = counts
            corpus.lengths[cid] = doc_len
        return corpus.rank(terms)

    def _chunk_kb(self, chunk_id: str) -> str | None:
        record = chunk_id.split(":")[0]
        with self.db.connect() as conn:
            row = conn.execute("select kb_id from records where record_id = %s", (record,)).fetchone()
        return row["kb_id"] if row else None

    def _chunk_json(self, chunk_id: str, score: float) -> dict:
        record = chunk_id.split(":")[0]
        with self.db.connect() as conn:
            row = conn.execute(
                """
                select c.text, c.block_index, r.record_id, r.record_name, r.kb_id, r.source_modified_ms
                from chunks c join records r on r.record_id = c.record_id
                where c.chunk_id = %s
                """,
                (chunk_id,),
            ).fetchone()
        if row is None:
            return {"id": chunk_id, "text": "", "score": score, "record": {}, "citation": {"url": None, "recordUrl": None, "pageNum": None, "blockIndex": None}}
        return {
            "id": chunk_id,
            "text": row["text"],
            "score": score,
            "record": {
                "recordId": str(row["record_id"]),
                "name": row["record_name"],
                "connector": row["kb_id"],
                "mimeType": "application/blocks",
                "updatedAt": row["source_modified_ms"],
            },
            "citation": {"url": None, "recordUrl": None, "pageNum": None, "blockIndex": row["block_index"]},
        }


def block_plain(block: dict) -> str:
    if block.get("type") == "text":
        return block.get("data") or ""
    if block.get("type") == "table_row":
        data = block.get("data") or {}
        if data.get("cells"):
            return "\t".join(data["cells"])
        return data.get("row_natural_language_text") or ""
    return ""


def write_payload(directory: Path, kb_id: str, record_id: str, raw: bytes, stored: dict) -> tuple[str, str]:
    folder = directory / kb_id
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / f"{record_id}.raw.json"
    stored_path = folder / f"{record_id}.stored.json"
    tmp_raw = folder / f"{record_id}.raw.json.tmp"
    tmp_stored = folder / f"{record_id}.stored.json.tmp"
    tmp_raw.write_bytes(raw)
    tmp_stored.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_raw, raw_path)
    os.replace(tmp_stored, stored_path)
    return str(raw_path), str(stored_path)


def stored_from(envelope: Envelope) -> dict:
    blocks = []
    for block in envelope.blocks.blocks or []:
        item = block.model_dump(exclude_none=True)
        blocks.append(item)
    return {"blocks": blocks, "push_format": 1}


def digest_of(envelope: Envelope) -> str:
    return blocks_digest(envelope.blocks)


def rev_of(stored: dict) -> str:
    return content_rev(json.dumps(stored, ensure_ascii=False).encode())
