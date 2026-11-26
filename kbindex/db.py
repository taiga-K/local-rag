"""Postgres for records, the block graph, and BM25 postings."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any

import psycopg
from psycopg.rows import dict_row

from kbindex.similarity import custom_threshold, resolve_threshold_level, threshold_for_level

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
  tf double precision not null,
  doc_len int not null,
  primary key (generation, tokenizer, term, chunk_id)
);
create index if not exists bm25_postings_chunk
  on bm25_postings (generation, tokenizer, chunk_id);
create table if not exists bm25_term_delta (
  seq bigint generated always as identity primary key,
  generation int not null,
  tokenizer text not null,
  term text not null,
  d int not null
);
create index if not exists bm25_term_delta_term
  on bm25_term_delta (generation, tokenizer, term) include (d);
create table if not exists bm25_count_delta (
  seq bigint generated always as identity primary key,
  generation int not null,
  tokenizer text not null,
  d int not null
);
create index if not exists bm25_count_delta_tok
  on bm25_count_delta (generation, tokenizer) include (d);
create table if not exists bm25_df_pending (
  generation int not null,
  tokenizer text not null,
  primary key (generation, tokenizer)
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
    "alter table bm25_stats drop column if exists avgdl",
    "alter table bm25_stats drop column if exists total_tokens",
    "alter table records add column if not exists embed_done int",
    "alter table records add column if not exists embed_total int",
    """
    create table if not exists app_settings (
      id int primary key,
      folders jsonb not null default '[]'::jsonb,
      include_subfolders boolean not null default true,
      auto_index boolean not null default true,
      max_upload_bytes bigint not null default 16777216,
      requested_model text,
      score_threshold_enabled boolean not null default false,
      score_threshold double precision,
      pause_until timestamptz,
      pause_kind text,
      requested_device text
    )
    """,
    "insert into app_settings (id) values (1) on conflict (id) do nothing",
    "alter table app_settings add column if not exists score_threshold_enabled boolean not null default false",
    "alter table app_settings add column if not exists score_threshold double precision",
    "alter table app_settings add column if not exists pause_until timestamptz",
    "alter table app_settings add column if not exists pause_kind text",
    "alter table app_settings add column if not exists requested_device text",
    "alter table app_settings add column if not exists score_threshold_level text",
    "alter table app_settings add column if not exists score_threshold_custom double precision",
    "alter table app_settings add column if not exists keyword_enabled boolean not null default true",
    """
    create table if not exists record_activity (
      id bigserial primary key,
      happened_at timestamptz not null default now(),
      kb_name text not null,
      record_name text not null,
      kind text not null
    )
    """,
    "alter table records add column if not exists has_indexed_copy boolean not null default false",
    "alter table blocks add column if not exists citation jsonb",
    """
    create table if not exists unreadable_files (
      kb_id text not null,
      relative_path text not null,
      file_name text not null,
      reason text not null,
      recorded_at timestamptz not null default now(),
      primary key (kb_id, relative_path)
    )
    """,
    "alter table bm25_postings alter column tf type double precision using tf::double precision",
)

# Statement triggers record DF. There is no restore role that reloads exported frequencies, so every
# posting write is counted. enable_nestloop is off for the same reason as PipesHub: a transition table
# has no statistics.
_BM25_CAPTURE = """
create or replace function bm25_postings_df_capture() returns trigger
language plpgsql
set enable_nestloop = off
set jit = off
as $fn$
begin
  if tg_op = 'INSERT' then
    insert into bm25_term_delta (generation, tokenizer, term, d)
      select n.generation, n.tokenizer, n.term, count(*)::int from newtab n group by 1, 2, 3;
  elsif tg_op = 'DELETE' then
    insert into bm25_term_delta (generation, tokenizer, term, d)
      select o.generation, o.tokenizer, o.term, -count(*)::int from oldtab o group by 1, 2, 3;
  else
    insert into bm25_term_delta (generation, tokenizer, term, d)
      select x.generation, x.tokenizer, x.term, sum(x.d)::int from (
        select n.generation, n.tokenizer, n.term, 1 as d from newtab n
        union all
        select o.generation, o.tokenizer, o.term, -1 from oldtab o) x
      group by 1, 2, 3 having sum(x.d) <> 0;
  end if;
  return null;
end
$fn$
"""

_BM25_TRIGGER_INSERT = """
create or replace trigger bm25_postings_df_insert
after insert on bm25_postings
referencing new table as newtab
for each statement execute function bm25_postings_df_capture()
"""

_BM25_TRIGGER_DELETE = """
create or replace trigger bm25_postings_df_delete
after delete on bm25_postings
referencing old table as oldtab
for each statement execute function bm25_postings_df_capture()
"""

_BM25_TRIGGER_UPDATE = """
create or replace trigger bm25_postings_df_update
after update on bm25_postings
referencing old table as oldtab new table as newtab
for each statement execute function bm25_postings_df_capture()
"""

# One statement, so folded values and deltas share the caller's snapshot.
# While bm25_df_pending is set, only per-term df is counted from postings.
# Document count is always bm25_stats plus bm25_count_delta (PipesHub search_sparse).
_BM25_READ = """
create or replace function bm25_read(p_tokenizer text, p_terms text[], p_kb text[])
returns table (doc_count int, term text, df int, chunk_id text, tf double precision, doc_len int)
language sql
stable
as $fn$
with pending as (
  select exists (
    select 1 from bm25_df_pending x
    where x.generation = 1 and x.tokenizer = p_tokenizer
  ) as pending
),
n as (
  select (
    coalesce((select s.doc_count from bm25_stats s
              where s.generation = 1 and s.tokenizer = p_tokenizer), 0)
    + coalesce((select sum(d.d) from bm25_count_delta d
                where d.generation = 1 and d.tokenizer = p_tokenizer), 0)
  )::int as doc_count
),
df as (
  select q.term,
    case when (select pending from pending) then (
      select count(*)::int from bm25_postings p
      where p.generation = 1 and p.tokenizer = p_tokenizer and p.term = q.term
    ) else (
      coalesce((select f.df from bm25_terms f
                where f.generation = 1 and f.tokenizer = p_tokenizer and f.term = q.term), 0)
      + coalesce((select sum(t.d) from bm25_term_delta t
                  where t.generation = 1 and t.tokenizer = p_tokenizer and t.term = q.term), 0)
    )::int end as df
  from (select distinct t.term from unnest(coalesce(p_terms, '{}'::text[])) as t(term)) q
),
posts as (
  select p.term, p.chunk_id, p.tf, p.doc_len
  from bm25_postings p
  where p.generation = 1 and p.tokenizer = p_tokenizer
    and p.term = any(coalesce(p_terms, '{}'::text[]))
    and (
      p_kb is null
      or exists (
        select 1 from chunks c
        join records r on r.record_id = c.record_id
        where c.chunk_id = p.chunk_id and r.kb_id = any(p_kb)
      )
    )
)
select n.doc_count, df.term, df.df, posts.chunk_id, posts.tf, posts.doc_len
from n
left join df on true
left join posts on posts.term = df.term
$fn$
"""

BM25_INCREMENTAL = (
    _BM25_CAPTURE,
    _BM25_TRIGGER_INSERT,
    _BM25_TRIGGER_DELETE,
    _BM25_TRIGGER_UPDATE,
    _BM25_READ,
)

_WRITE_POSTINGS = """
with incoming as (
  select * from unnest(%s::int[], %s::text[], %s::text[], %s::text[], %s::float8[], %s::int[])
    as t(generation, tokenizer, term, chunk_id, tf, doc_len)
),
fresh as materialized (
  select distinct t.generation, t.tokenizer, t.chunk_id
  from incoming t
  where not exists (
    select 1 from bm25_postings p
    where p.generation = t.generation and p.tokenizer = t.tokenizer and p.chunk_id = t.chunk_id
  )
),
ins as (
  insert into bm25_postings (generation, tokenizer, term, chunk_id, tf, doc_len)
  select generation, tokenizer, term, chunk_id, tf, doc_len
  from incoming
  order by generation, tokenizer, term, chunk_id
  on conflict (generation, tokenizer, term, chunk_id)
  do update set tf = excluded.tf, doc_len = excluded.doc_len
  returning 1
),
cnt as (
  insert into bm25_count_delta (generation, tokenizer, d)
  select f.generation, f.tokenizer, count(*)::int
  from fresh f
  group by f.generation, f.tokenizer
  having count(*) > 0
  returning 1
)
select count(*) from ins
"""


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
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=3)

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(SCHEMA)
            for statement in ALTERS:
                conn.execute(statement)
            first_triggers = conn.execute(
                "select 1 from pg_trigger where tgname = 'bm25_postings_df_insert'"
            ).fetchone() is None
            for statement in BM25_INCREMENTAL:
                conn.execute(statement)
            if first_triggers:
                # Pre-trigger collections stay pending until an operator runs
                # kbindex-maintain recount. Search counts their df from postings until then.
                conn.execute(
                    """
                    insert into bm25_df_pending (generation, tokenizer)
                    select generation, tokenizer from bm25_stats
                    union
                    select distinct generation, tokenizer from bm25_postings
                    on conflict do nothing
                    """
                )
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
    names = ("QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY", "AUTO_INDEX_OFF", "NOT_STARTED")
    out = {name: 0 for name in names}
    rows = conn.execute(
        "select indexing_status, count(*) as n from records where kb_id = %s group by indexing_status",
        (kb_id,),
    ).fetchall()
    for row in rows:
        if row["indexing_status"] in out:
            out[row["indexing_status"]] = int(row["n"])
    return out


def app_settings_row(conn) -> dict[str, Any]:
    row = conn.execute("select * from app_settings where id = 1").fetchone()
    if row is None:
        conn.execute("insert into app_settings (id) values (1) on conflict (id) do nothing")
        row = conn.execute("select * from app_settings where id = 1").fetchone()
    return dict(row)


def save_local_settings(conn, *, folders: list[str], include_subfolders: bool, auto_index: bool) -> dict[str, Any]:
    conn.execute(
        """
        update app_settings
        set folders = %s::jsonb, include_subfolders = %s, auto_index = %s
        where id = 1
        """,
        (json.dumps(folders), include_subfolders, auto_index),
    )
    return app_settings_row(conn)


def save_upload_limit(conn, max_upload_bytes: int) -> dict[str, Any]:
    conn.execute("update app_settings set max_upload_bytes = %s where id = 1", (max_upload_bytes,))
    return app_settings_row(conn)


def save_requested_model(conn, model: str | None) -> dict[str, Any]:
    conn.execute("update app_settings set requested_model = %s where id = 1", (model,))
    return app_settings_row(conn)


def score_threshold_payload(row: dict[str, Any]) -> dict[str, Any]:
    """The saved level. Named numbers come from the level constants.

    Custom also returns the stored cutoff. Older numeric rows stay on the
    nearest named level and do not become custom.
    """
    stored = None if row.get("score_threshold") is None else float(row["score_threshold"])
    level = resolve_threshold_level(
        row.get("score_threshold_level"),
        enabled=bool(row.get("score_threshold_enabled")),
        stored=stored,
    )
    body: dict[str, Any] = {"level": level}
    if level == "custom":
        body["value"] = custom_threshold(stored)
    remembered = custom_threshold(row.get("score_threshold_custom"))
    if remembered is not None:
        body["customValue"] = remembered
    return body


def read_score_threshold(conn) -> tuple[bool, float]:
    row = app_settings_row(conn)
    stored = None if row.get("score_threshold") is None else float(row["score_threshold"])
    level = resolve_threshold_level(
        row.get("score_threshold_level"),
        enabled=bool(row.get("score_threshold_enabled")),
        stored=stored,
    )
    return threshold_for_level(level, stored)


def save_score_level(conn, level: str, value: float | None = None) -> dict[str, Any]:
    if level == "custom":
        number = custom_threshold(value)
        if number is None:
            raise ValueError("custom threshold is invalid")
        enabled, stored = True, number
    else:
        enabled, number = threshold_for_level(level)
        stored = None if level == "off" else number
    conn.execute(
        """
        update app_settings
        set score_threshold_level = %s,
            score_threshold_enabled = %s,
            score_threshold = %s,
            score_threshold_custom = case when %s = 'custom' then %s else score_threshold_custom end
        where id = 1
        """,
        (level, enabled, stored, level, stored if level == "custom" else None),
    )
    return app_settings_row(conn)


def save_pause(conn, *, kind: str | None, until) -> dict[str, Any]:
    conn.execute(
        "update app_settings set pause_kind = %s, pause_until = %s where id = 1",
        (kind, until),
    )
    return app_settings_row(conn)


def save_keyword_enabled(conn, enabled: bool) -> dict[str, Any]:
    conn.execute("update app_settings set keyword_enabled = %s where id = 1", (enabled,))
    return app_settings_row(conn)


def save_requested_device(conn, device: str) -> dict[str, Any]:
    conn.execute("update app_settings set requested_device = %s where id = 1", (device,))
    return app_settings_row(conn)


def list_kbs(conn) -> list[dict[str, Any]]:
    return list(conn.execute("select id, name from knowledge_bases order by id").fetchall())


def list_record_status(
    conn,
    kb_id: str,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
) -> list[dict[str, Any]]:
    where = "where kb_id = %s"
    params: list[Any] = [kb_id]
    if status is not None:
        where += " and indexing_status = %s"
        params.append(status)
    params.extend([limit, offset])
    return list(
        conn.execute(
            f"""
            select record_id, external_record_id, record_name, indexing_status, failure_reason, version,
                   source_modified_ms, updated_at
            from records {where}
            order by (indexing_status = 'FAILED') desc,
                     (indexing_status = 'IN_PROGRESS') desc,
                     updated_at desc,
                     record_id
            limit %s offset %s
            """,
            params,
        ).fetchall()
    )


def list_external_ids(conn, kb_id: str) -> list[str]:
    rows = conn.execute(
        "select external_record_id from records where kb_id = %s order by external_record_id",
        (kb_id,),
    ).fetchall()
    return [row["external_record_id"] for row in rows]


def ingest_folder_counts(conn) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            """
            select r.kb_id, k.name,
                   count(*) as total,
                   count(*) filter (where r.indexing_status = 'FAILED') as failed,
                   count(*) filter (where r.indexing_status = 'IN_PROGRESS') as active,
                   count(*) filter (where r.indexing_status = 'QUEUED') as queued,
                   count(*) filter (where r.indexing_status = 'COMPLETED') as completed,
                   count(*) filter (where r.indexing_status = 'EMPTY') as empty,
                   count(*) filter (where r.indexing_status = 'AUTO_INDEX_OFF') as held,
                   count(*) filter (where r.indexing_status in ('COMPLETED', 'EMPTY')) as done
            from records r
            join knowledge_bases k on k.id = r.kb_id
            group by r.kb_id, k.name
            order by k.name
            """
        ).fetchall()
    )


def current_ingest_record(conn) -> dict[str, Any] | None:
    return conn.execute(
        """
        select r.record_name, r.kb_id, k.name as kb_name
        from records r
        join knowledge_bases k on k.id = r.kb_id
        where r.indexing_status = 'IN_PROGRESS'
        order by r.updated_at desc
        limit 1
        """
    ).fetchone()


def latest_record_update(conn):
    return conn.execute("select max(updated_at) as updated_at from records").fetchone()


def note_indexed_removal(conn, *, kb_id: str, record_name: str) -> None:
    """A searchable document left the folder and the index. Counts drop with the row."""
    conn.execute(
        """
        insert into record_activity (kb_name, record_name, kind)
        select coalesce(k.name, %s), %s, '削除'
        from (select %s::text as id) wanted
        left join knowledge_bases k on k.id = wanted.id
        """,
        (kb_id, record_name, kb_id),
    )


def recent_record_events(conn, limit: int) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            """
            select record_name, kb_name, updated_at, kind from (
              select r.record_name, k.name as kb_name, r.updated_at,
                     case when r.version > 1 then '更新' else '追加' end as kind
              from records r
              join knowledge_bases k on k.id = r.kb_id
              where r.indexing_status in ('COMPLETED', 'EMPTY')
              union all
              select record_name, kb_name, happened_at, kind
              from record_activity
            ) events
            order by updated_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()
    )


def count_reindexable(conn) -> int:
    row = conn.execute("select count(*) as n from records where indexing_status <> 'EMPTY'").fetchone()
    return int(row["n"])


def queue_failed_records(conn, kb_id: str | None) -> list[dict[str, Any]]:
    if kb_id is None:
        return list(
            conn.execute(
                """
                update records
                set indexing_status = 'QUEUED', failure_reason = null, updated_at = now()
                where indexing_status = 'FAILED'
                returning record_id, kb_id, external_record_id, version, content_rev
                """
            ).fetchall()
        )
    return list(
        conn.execute(
            """
            update records
            set indexing_status = 'QUEUED', failure_reason = null, updated_at = now()
            where indexing_status = 'FAILED' and kb_id = %s
            returning record_id, kb_id, external_record_id, version, content_rev
            """,
            (kb_id,),
        ).fetchall()
    )


def queue_kb_records(conn, kb_id: str) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            """
            update records
            set indexing_status = 'QUEUED', failure_reason = null, updated_at = now()
            where kb_id = %s and indexing_status <> 'EMPTY'
            returning record_id, kb_id, external_record_id, version, content_rev
            """,
            (kb_id,),
        ).fetchall()
    )


def generation_row(conn):
    return conn.execute("select * from index_generation where id = 1").fetchone()


def write_generation(conn, *, fingerprint: str, model: str, dimension: int | None, max_seq_length: int | None, keyword: dict, fusion: dict) -> None:
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
    """Wipe postings. Each touched stats row stays, with doc_count 0.

    Document frequency is global per tokenizer, so every KB shares one delta table.
    The rows removed are only the stale deltas of the tokenizers whose postings this
    wipe deleted: deltas already visible to that delete, plus the negative deltas this
    transaction just wrote. A delta another transaction commits after the delete
    (another KB ingesting the same tokenizer) is left alone.
    Pending rows stay until recount.
    """
    touched = _wipe_postings(conn)
    _drop_wiped_deltas(conn, touched)
    conn.execute(
        """
        delete from chunks c
        where not exists (
          select 1 from bm25_postings p where p.chunk_id = c.chunk_id
        )
        """
    )


def _wipe_postings(conn) -> list[dict]:
    """Delete every posting and return one row per tokenizer, with the pre-delete delta watermarks."""
    return list(
        conn.execute(
            """
            with mark as materialized (
              -- Fence the read on the statement snapshot. Inlining it after the
              -- delete lets max(seq) include this statement's own deltas, and the
              -- later delete then drops a concurrent ingest that committed during it.
              select
                coalesce((select max(seq) from bm25_term_delta), 0) as term_seq,
                coalesce((select max(seq) from bm25_count_delta), 0) as count_seq
            ),
            gone as (
              delete from bm25_postings
              returning generation, tokenizer, chunk_id
            ),
            cnt as (
              insert into bm25_count_delta (generation, tokenizer, d)
              select generation, tokenizer, -count(distinct chunk_id)::int
              from gone
              group by generation, tokenizer
              having count(*) > 0
              returning 1
            )
            select distinct g.generation, g.tokenizer, m.term_seq, m.count_seq
            from gone g
            cross join mark m
            """
        ).fetchall()
    )


def _drop_wiped_deltas(conn, touched: list[dict]) -> None:
    if not touched:
        return
    generations = [int(row["generation"]) for row in touched]
    tokenizers = [row["tokenizer"] for row in touched]
    term_seq = int(touched[0]["term_seq"])
    count_seq = int(touched[0]["count_seq"])
    scope = (generations, tokenizers)
    conn.execute(
        """
        update bm25_stats s
        set doc_count = 0
        where (s.generation, s.tokenizer) in (
          select * from unnest(%s::int[], %s::text[]) as u(generation, tokenizer)
        )
        """,
        scope,
    )
    conn.execute(
        """
        delete from bm25_terms f
        where (f.generation, f.tokenizer) in (
          select * from unnest(%s::int[], %s::text[]) as u(generation, tokenizer)
        )
        """,
        scope,
    )
    own = "d.xmin = pg_current_xact_id()::xid"
    conn.execute(
        f"""
        delete from bm25_term_delta d
        where (d.generation, d.tokenizer) in (
          select * from unnest(%s::int[], %s::text[]) as u(generation, tokenizer)
        )
        and (d.seq <= %s or {own})
        """,
        (*scope, term_seq),
    )
    conn.execute(
        f"""
        delete from bm25_count_delta d
        where (d.generation, d.tokenizer) in (
          select * from unnest(%s::int[], %s::text[]) as u(generation, tokenizer)
        )
        and (d.seq <= %s or {own})
        """,
        (*scope, count_seq),
    )


def _json_text(value: Any) -> str | None:
    """JSON text for a jsonb column. A string is already encoded."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def replace_graph(conn, record_id, blocks: list[tuple]) -> None:
    conn.execute("delete from blocks where record_id = %s", (record_id,))
    conn.execute("delete from block_groups where record_id = %s", (record_id,))
    for row in blocks:
        position, parent, kind, text = row[0], row[1], row[2], row[3]
        citation = row[4] if len(row) > 4 else None
        conn.execute(
            """
            insert into blocks (block_id, record_id, position, parent_position, group_position, type, text, citation)
            values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                block_id_for(record_id, position), record_id, position, parent, parent, kind, text,
                _json_text(citation),
            ),
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


def read_record_index(conn, record_id) -> dict:
    """Copy chunks, postings, and the block graph before they are deleted."""
    chunks = [
        dict(row)
        for row in conn.execute(
            """
            select chunk_id, record_id, block_id, block_index, piece, text, token_count
            from chunks where record_id = %s
            """,
            (record_id,),
        ).fetchall()
    ]
    chunk_ids = [row["chunk_id"] for row in chunks]
    postings: list[dict[str, Any]] = []
    if chunk_ids:
        postings = [
            dict(row)
            for row in conn.execute(
                """
                select generation, tokenizer, term, chunk_id, tf, doc_len
                from bm25_postings where chunk_id = any(%s)
                """,
                (chunk_ids,),
            ).fetchall()
        ]
    blocks = [
        dict(row)
        for row in conn.execute(
            """
            select block_id, record_id, position, parent_position, group_position, type, text, citation
            from blocks where record_id = %s
            """,
            (record_id,),
        ).fetchall()
    ]
    groups = [
        dict(row)
        for row in conn.execute(
            """
            select record_id, position, parent_position, type, name
            from block_groups where record_id = %s
            """,
            (record_id,),
        ).fetchall()
    ]
    return {"chunks": chunks, "postings": postings, "blocks": blocks, "groups": groups}


def write_record_index(conn, record_id, snap: dict) -> None:
    """Put a read_record_index snapshot back. Posting triggers and the count delta keep BM25."""
    conn.execute("delete from blocks where record_id = %s", (record_id,))
    conn.execute("delete from block_groups where record_id = %s", (record_id,))
    for row in snap["blocks"]:
        conn.execute(
            """
            insert into blocks (block_id, record_id, position, parent_position, group_position, type, text, citation)
            values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                row["block_id"], record_id, row["position"], row["parent_position"],
                row["group_position"], row["type"], row["text"],
                _json_text(row.get("citation")),
            ),
        )
    for row in snap["groups"]:
        conn.execute(
            """
            insert into block_groups (record_id, position, parent_position, type, name)
            values (%s, %s, %s, %s, %s)
            """,
            (record_id, row["position"], row["parent_position"], row["type"], row["name"]),
        )
    for row in snap["chunks"]:
        conn.execute(
            """
            insert into chunks (chunk_id, record_id, block_id, block_index, piece, text, token_count)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (chunk_id) do nothing
            """,
            (
                row["chunk_id"], record_id, row["block_id"], row["block_index"],
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


def delete_postings(conn, where_sql: str, params: tuple = ()) -> None:
    """Delete postings and append the doc-count delta for chunks that lost every posting.

    where_sql is a trusted SQL fragment, not user input. Callers delete every posting of each
    chunk they touch (one record, a record prefix, or the whole table).
    """
    conn.execute(
        f"""
        with gone as (
          delete from bm25_postings
          where {where_sql}
          returning generation, tokenizer, chunk_id
        ),
        cnt as (
          insert into bm25_count_delta (generation, tokenizer, d)
          select generation, tokenizer, -count(distinct chunk_id)::int
          from gone
          group by generation, tokenizer
          having count(*) > 0
          returning 1
        )
        select count(*) from gone
        """,
        params,
    )


def delete_chunks_for(conn, record_id) -> None:
    delete_postings(
        conn,
        "chunk_id in (select chunk_id from chunks where record_id = %s)",
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
    weighted = {
        chunk_id: [(term, float(tf)) for term, tf in Counter(terms).items()]
        for chunk_id, terms in docs.items()
    }
    insert_weighted_postings(conn, tokenizer, weighted, length_from_weight=True)


def write_postings(conn, rows: list[tuple]) -> None:
    """Insert or replace postings in one statement, and append a doc-count delta for new chunks.

    A repeated (generation, tokenizer, term, chunk_id) keeps the last weight. doc_len is the
    caller's value (the length before that de-duplication).
    """
    chosen: dict[tuple, tuple[float, int]] = {}
    for generation, tokenizer, term, chunk_id, tf, doc_len in rows:
        chosen[(int(generation), str(tokenizer), str(term), str(chunk_id))] = (float(tf), int(doc_len))
    if not chosen:
        return
    generations: list[int] = []
    tokenizers: list[str] = []
    terms: list[str] = []
    chunk_ids: list[str] = []
    tfs: list[float] = []
    doc_lens: list[int] = []
    for (generation, tokenizer, term, chunk_id), (tf, doc_len) in chosen.items():
        generations.append(generation)
        tokenizers.append(tokenizer)
        terms.append(term)
        chunk_ids.append(chunk_id)
        tfs.append(tf)
        doc_lens.append(doc_len)
    conn.execute(_WRITE_POSTINGS, (generations, tokenizers, terms, chunk_ids, tfs, doc_lens))


def insert_weighted_postings(
    conn,
    tokenizer: str,
    docs: dict[str, list[tuple[str, float]]],
    *,
    length_from_weight: bool,
) -> None:
    rows: list[tuple] = []
    for chunk_id, pairs in docs.items():
        doc_len = int(sum(weight for _term, weight in pairs)) if length_from_weight else len(pairs)
        weights: dict[str, float] = {}
        for term, weight in pairs:
            weights[term] = float(weight)
        for term, weight in weights.items():
            rows.append((1, tokenizer, term, chunk_id, weight, doc_len))
    write_postings(conn, rows)


def bm25_rows(conn, tokenizer: str, terms: list[str], kb_ids: list[str] | None = None):
    rows = conn.execute(
        "select doc_count, term, df, chunk_id, tf, doc_len from bm25_read(%s, %s, %s)",
        (tokenizer, terms, kb_ids if kb_ids else None),
    ).fetchall()
    if not rows:
        return {"doc_count": 0}, [], []
    stats = {"doc_count": int(rows[0]["doc_count"])}
    seen: set[str] = set()
    df_rows = []
    posts = []
    for row in rows:
        term = row["term"]
        if term is not None and term not in seen:
            seen.add(term)
            df_rows.append({"term": term, "df": int(row["df"])})
        if row["chunk_id"] is not None:
            posts.append(row)
    return stats, df_rows, posts


def upsert_unreadable(conn, kb_id: str, relative_path: str, file_name: str, reason: str) -> None:
    conn.execute(
        """
        insert into unreadable_files (kb_id, relative_path, file_name, reason, recorded_at)
        values (%s, %s, %s, %s, now())
        on conflict (kb_id, relative_path) do update
        set file_name = excluded.file_name, reason = excluded.reason, recorded_at = now()
        """,
        (kb_id, relative_path, file_name, reason),
    )


def delete_unreadable(conn, kb_id: str, relative_path: str) -> None:
    conn.execute(
        "delete from unreadable_files where kb_id = %s and relative_path = %s",
        (kb_id, relative_path),
    )


def list_unreadable(conn, kb_id: str):
    return conn.execute(
        """
        select file_name, relative_path, reason, recorded_at
        from unreadable_files
        where kb_id = %s
        order by recorded_at desc, relative_path
        """,
        (kb_id,),
    ).fetchall()


def hydrate_chunks(conn, chunk_ids: list[str]):
    if not chunk_ids:
        return []
    return conn.execute(
        """
        select c.chunk_id, c.text, c.block_index, c.piece, c.token_count,
               r.record_id, r.external_record_id, r.record_name, r.kb_id,
               r.indexing_status, r.has_indexed_copy,
               r.source_modified_ms, r.created_at, r.updated_at,
               b.citation
        from chunks c
        join records r on r.record_id = c.record_id
        left join blocks b on b.block_id = c.block_id
        where c.chunk_id = any(%s)
        """,
        (chunk_ids,),
    ).fetchall()
