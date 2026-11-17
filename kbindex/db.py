"""Postgres for records, the block graph, and BM25 postings."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any

import psycopg
from psycopg.rows import dict_row

NAMESPACE = uuid.UUID("c3a1e5b0-7d2e-4b1a-9f60-4a0b1c2d3e4f")

SCHEMA = """
create table if not exists knowledge_bases (
  id text primary key,
  name text not null,
  created_at timestamptz not null default now()
);
create table if not exists schemas (
  kb_id text not null,
  schema_id text not null,
  properties jsonb not null,
  primary key (kb_id, schema_id)
);
create table if not exists records (
  record_id uuid primary key,
  kb_id text not null,
  external_record_id text not null,
  version bigint not null,
  revision_id text,
  content_rev text,
  blocks_sha text,
  record_name text not null,
  source_modified_ms bigint,
  indexing_status text not null,
  failure_reason text,
  raw_path text,
  stored_path text,
  embed_done int,
  embed_total int,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (kb_id, external_record_id)
);
create table if not exists blocks (
  block_id uuid primary key,
  record_id uuid not null references records(record_id) on delete cascade,
  position int not null,
  parent_position int,
  group_position int,
  type text not null,
  text text not null
);
create table if not exists block_groups (
  record_id uuid not null references records(record_id) on delete cascade,
  position int not null,
  parent_position int,
  type text not null,
  name text,
  primary key (record_id, position)
);
create table if not exists chunks (
  chunk_id text primary key,
  record_id uuid not null references records(record_id) on delete cascade,
  block_id uuid,
  block_index int not null,
  piece int not null,
  text text not null,
  token_count int not null
);
create table if not exists index_generation (
  id int primary key default 1,
  fingerprint text not null,
  model text not null,
  dimension int,
  max_seq_length int,
  keyword_json jsonb,
  fusion_json jsonb,
  ready boolean not null default true,
  check (id = 1)
);
create table if not exists bm25_stats (
  generation int not null,
  tokenizer text not null,
  doc_count int not null,
  avgdl double precision not null default 0,
  total_tokens int not null,
  primary key (generation, tokenizer)
);
create table if not exists bm25_terms (
  generation int not null,
  tokenizer text not null,
  term text not null,
  df int not null,
  primary key (generation, tokenizer, term)
);
create table if not exists bm25_postings (
  generation int not null,
  tokenizer text not null,
  term text not null,
  chunk_id text not null,
  tf int not null,
  doc_len int not null,
  primary key (generation, tokenizer, term, chunk_id)
);
"""

ALTERS = (
    "alter table blocks add column if not exists parent_position int",
    "alter table blocks add column if not exists group_position int",
    "alter table chunks add column if not exists block_id uuid",
    "alter table index_generation add column if not exists dimension int",
    "alter table index_generation add column if not exists max_seq_length int",
    "alter table index_generation add column if not exists keyword_json jsonb",
    "alter table index_generation add column if not exists fusion_json jsonb",
    "alter table bm25_stats add column if not exists avgdl double precision not null default 0",
    "alter table records add column if not exists embed_done int",
    "alter table records add column if not exists embed_total int",
)


def record_id_for(kb_id: str, external_record_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kb_id}\x1f{external_record_id}")


def block_id_for(record_id: uuid.UUID, position: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{record_id}\x1f{position}")


def chunk_public_id(record_id: str, block_index: int, piece: int, piece_count: int = 1) -> str:
    """Caller-visible id. One piece omits the suffix. Later pieces of a split block add it."""
    base = f"{record_id}:{block_index}"
    if piece_count <= 1 or piece == 0:
        return base
    return f"{base}:{piece}"


def record_of_chunk(chunk_id: str) -> str:
    return chunk_id.rsplit(":", 2)[0]


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(SCHEMA)
            for statement in ALTERS:
                conn.execute(statement)
            conn.commit()

    def ping(self) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("select 1")
            return True
        except Exception:
            return False


def kb_row(conn, kb_id: str):
    return conn.execute("select id, name from knowledge_bases where id = %s", (kb_id,)).fetchone()


def schema_row(conn, kb_id: str, schema_id: str | None):
    if schema_id:
        return conn.execute(
            "select schema_id, properties from schemas where kb_id = %s and schema_id = %s",
            (kb_id, schema_id),
        ).fetchone()
    return conn.execute(
        "select schema_id, properties from schemas where kb_id = %s order by schema_id limit 1",
        (kb_id,),
    ).fetchone()


def schema_exists(conn, kb_id: str, schema_id: str) -> bool:
    return schema_row(conn, kb_id, schema_id) is not None


def record_row(conn, record_id):
    return conn.execute("select * from records where record_id = %s", (record_id,)).fetchone()


def lock_record(conn, record_id):
    return conn.execute("select * from records where record_id = %s for update", (record_id,)).fetchone()


def counts_for(conn, kb_id: str) -> dict[str, int]:
    names = ("QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY")
    out = {name: 0 for name in names}
    rows = conn.execute(
        "select indexing_status, count(*) as n from records where kb_id = %s group by indexing_status",
        (kb_id,),
    ).fetchall()
    for row in rows:
        if row["indexing_status"] in out:
            out[row["indexing_status"]] = int(row["n"])
    return out


def generation_row(conn):
    return conn.execute("select * from index_generation where id = 1").fetchone()


def write_generation(conn, *, fingerprint: str, model: str, dimension: int, max_seq_length: int, keyword: dict, fusion: dict) -> None:
    conn.execute(
        """
        insert into index_generation (id, fingerprint, model, dimension, max_seq_length, keyword_json, fusion_json, ready)
        values (1, %s, %s, %s, %s, %s::jsonb, %s::jsonb, true)
        on conflict (id) do update set
          fingerprint = excluded.fingerprint,
          model = excluded.model,
          dimension = excluded.dimension,
          max_seq_length = excluded.max_seq_length,
          keyword_json = excluded.keyword_json,
          fusion_json = excluded.fusion_json,
          ready = true
        """,
        (fingerprint, model, dimension, max_seq_length, json.dumps(keyword), json.dumps(fusion)),
    )


def recover_in_progress(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        update records
        set indexing_status = 'QUEUED', failure_reason = null, updated_at = now()
        where indexing_status = 'IN_PROGRESS'
        returning record_id, kb_id, external_record_id, version, content_rev
        """
    ).fetchall()
    return list(rows)


def queue_records_with_text(conn) -> list[dict[str, Any]]:
    conn.execute(
        """
        update records
        set indexing_status = 'QUEUED', failure_reason = null, updated_at = now()
        where indexing_status <> 'EMPTY'
        """
    )
    return list(
        conn.execute(
            """
            select record_id, kb_id, external_record_id, version, content_rev
            from records where indexing_status = 'QUEUED'
            """
        ).fetchall()
    )


def clear_postings(conn) -> None:
    conn.execute("delete from bm25_postings")
    conn.execute("delete from bm25_terms")
    conn.execute("delete from bm25_stats")
    conn.execute("delete from chunks")


def replace_graph(conn, record_id, blocks: list[tuple[int, int | None, str, str]]) -> None:
    conn.execute("delete from blocks where record_id = %s", (record_id,))
    conn.execute("delete from block_groups where record_id = %s", (record_id,))
    for position, parent, kind, text in blocks:
        conn.execute(
            """
            insert into blocks (block_id, record_id, position, parent_position, group_position, type, text)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (block_id_for(record_id, position), record_id, position, parent, parent, kind, text),
        )


def replace_groups(conn, record_id, groups: list[tuple[int, int | None, str, str | None]]) -> None:
    for position, parent, kind, name in groups:
        conn.execute(
            """
            insert into block_groups (record_id, position, parent_position, type, name)
            values (%s, %s, %s, %s, %s)
            """,
            (record_id, position, parent, kind, name),
        )


def delete_chunks_for(conn, record_id) -> None:
    conn.execute(
        "delete from bm25_postings where chunk_id in (select chunk_id from chunks where record_id = %s)",
        (record_id,),
    )
    conn.execute("delete from chunks where record_id = %s", (record_id,))


def insert_chunks(conn, record_id, rows: list[tuple[str, int, int, str, int]]) -> None:
    for chunk_id, block_index, piece, text, token_count in rows:
        conn.execute(
            """
            insert into chunks (chunk_id, record_id, block_id, block_index, piece, text, token_count)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (chunk_id, record_id, block_id_for(record_id, block_index), block_index, piece, text, token_count),
        )


def insert_postings(conn, tokenizer: str, docs: dict[str, list[str]]) -> None:
    for chunk_id, terms in docs.items():
        counts = Counter(terms)
        doc_len = sum(counts.values())
        for term, tf in counts.items():
            conn.execute(
                """
                insert into bm25_postings (generation, tokenizer, term, chunk_id, tf, doc_len)
                values (1, %s, %s, %s, %s, %s)
                on conflict (generation, tokenizer, term, chunk_id)
                do update set tf = excluded.tf, doc_len = excluded.doc_len
                """,
                (tokenizer, term, chunk_id, tf, doc_len),
            )


def rebuild_bm25(conn) -> None:
    conn.execute("delete from bm25_terms where generation = 1")
    conn.execute(
        """
        insert into bm25_terms (generation, tokenizer, term, df)
        select generation, tokenizer, term, count(*)
        from bm25_postings
        where generation = 1
        group by generation, tokenizer, term
        """
    )
    conn.execute("delete from bm25_stats where generation = 1")
    conn.execute(
        """
        insert into bm25_stats (generation, tokenizer, doc_count, avgdl, total_tokens)
        select 1, tokenizer, count(*),
               case when count(*) = 0 then 0 else sum(dl)::float8 / count(*) end,
               coalesce(sum(dl), 0)
        from (
          select tokenizer, chunk_id, max(doc_len) as dl
          from bm25_postings
          where generation = 1
          group by tokenizer, chunk_id
        ) lengths
        group by tokenizer
        """
    )


def bm25_rows(conn, tokenizer: str, terms: list[str]):
    stats = conn.execute(
        "select doc_count, total_tokens, avgdl from bm25_stats where generation = 1 and tokenizer = %s",
        (tokenizer,),
    ).fetchone()
    if not terms:
        return stats, [], []
    df_rows = conn.execute(
        "select term, df from bm25_terms where generation = 1 and tokenizer = %s and term = any(%s)",
        (tokenizer, terms),
    ).fetchall()
    posts = conn.execute(
        """
        select term, chunk_id, tf, doc_len
        from bm25_postings
        where generation = 1 and tokenizer = %s and term = any(%s)
        """,
        (tokenizer, terms),
    ).fetchall()
    return stats, df_rows, posts


def hydrate_chunks(conn, chunk_ids: list[str]):
    if not chunk_ids:
        return []
    return conn.execute(
        """
        select c.chunk_id, c.text, c.block_index, c.piece, c.token_count,
               r.record_id, r.record_name, r.kb_id, r.source_modified_ms, r.created_at, r.updated_at
        from chunks c
        join records r on r.record_id = c.record_id
        where c.chunk_id = any(%s)
        """,
        (chunk_ids,),
    ).fetchall()
