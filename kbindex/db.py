"""Postgres for records, graph edges, and BM25 postings."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

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
  type text not null,
  text text not null
);
create table if not exists chunks (
  chunk_id text primary key,
  record_id uuid not null references records(record_id) on delete cascade,
  block_index int not null,
  piece int not null,
  text text not null,
  token_count int not null
);
create table if not exists index_generation (
  id int primary key default 1,
  fingerprint text not null,
  model text not null,
  ready boolean not null default true,
  check (id = 1)
);
create table if not exists bm25_stats (
  generation int not null,
  tokenizer text not null,
  doc_count int not null,
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


def record_id_for(kb_id: str, external_record_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kb_id}\x1f{external_record_id}")


@dataclass
class Database:
    dsn: str

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(SCHEMA)
            conn.commit()

    def ping(self) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("select 1")
            return True
        except Exception:
            return False
