"""Fold and recount BM25 document frequency and document count.

Search adds unfolded deltas itself, so neither command has to be running for counts to be right.
``fold`` only compacts the delta tables. ``recount`` recomputes both from postings.
Startup migration does not recount: after an upgrade, run ``kbindex-maintain recount`` once.

Doc-count deltas live in ``bm25_count_delta`` rather than under a sentinel term. PipesHub stores
them in ``lexical_df_delta`` with ``term = -1`` because that table's term is an integer. Terms
here are text, and a separate append-only table is the same rule: the writer adds one row per
statement, and fold sums every row into the counter.
"""

from __future__ import annotations

import sys
import time

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

BUSY = -1
BATCH = 100_000
MAX_BATCHES = 100
LOCK_CLASS = 7361

FOLD_COUNTS = """
with taken as (
  delete from bm25_count_delta d
   where d.seq in (select t.seq from bm25_count_delta t order by t.seq limit %(batch)s)
  returning d.generation, d.tokenizer, d.d
),
sums as (
  select generation, tokenizer, sum(d)::bigint as d
  from taken
  group by generation, tokenizer
  having sum(d) <> 0
),
cnt as (
  insert into bm25_stats as s (generation, tokenizer, doc_count)
  select generation, tokenizer, d::int from sums
  on conflict (generation, tokenizer) do update set doc_count = s.doc_count + excluded.doc_count
  returning 1
)
select (select count(*) from taken) as n
"""

FOLD_TERMS = """
with taken as (
  delete from bm25_term_delta d
   where d.seq in (select t.seq from bm25_term_delta t order by t.seq limit %(batch)s)
  returning d.generation, d.tokenizer, d.term, d.d
),
sums as (
  select s.*, coalesce(f.df, 0) + s.d as df
  from (
    select generation, tokenizer, term, sum(d)::bigint as d
    from taken
    group by 1, 2, 3
    having sum(d) <> 0
  ) s
  left join bm25_terms f
    on f.generation = s.generation and f.tokenizer = s.tokenizer and f.term = s.term
),
gone as (
  delete from bm25_terms f
  using sums s
  where f.generation = s.generation and f.tokenizer = s.tokenizer and f.term = s.term and s.df = 0
  returning 1
),
up as (
  insert into bm25_terms as f (generation, tokenizer, term, df)
  select s.generation, s.tokenizer, s.term, s.d::int from sums s where s.df <> 0
  on conflict (generation, tokenizer, term) do update set df = f.df + excluded.df
  returning 1
)
select (select count(*) from taken) as n
"""

RECOUNT_COUNTS = """
with live as (
  select generation, tokenizer, count(*) as n
  from (
    select generation, tokenizer, chunk_id
    from bm25_postings
    group by generation, tokenizer, chunk_id
  ) c
  group by generation, tokenizer
),
pending as (
  select generation, tokenizer, sum(d) as d
  from bm25_count_delta
  group by generation, tokenizer
),
keys as (
  select generation, tokenizer from live
  union select generation, tokenizer from pending
  union select generation, tokenizer from bm25_stats
)
insert into bm25_stats as s (generation, tokenizer, doc_count)
select k.generation, k.tokenizer, (coalesce(l.n, 0) - coalesce(p.d, 0))::int
from keys k
left join live l using (generation, tokenizer)
left join pending p using (generation, tokenizer)
on conflict (generation, tokenizer) do update set doc_count = excluded.doc_count
returning s.tokenizer,
  (s.doc_count + coalesce((
     select sum(d.d) from bm25_count_delta d
     where d.generation = s.generation and d.tokenizer = s.tokenizer
  ), 0))::int as doc_count
"""

RECOUNT_TERMS = """
with live as (
  select p.generation, p.tokenizer, p.term, count(*) as n
  from bm25_postings p
  group by 1, 2, 3
),
pending as (
  select d.generation, d.tokenizer, d.term, sum(d.d) as d
  from bm25_term_delta d
  group by 1, 2, 3
),
stale as (
  delete from bm25_terms f
  where not exists (
    select 1 from live l
    where l.generation = f.generation and l.tokenizer = f.tokenizer and l.term = f.term
  )
  and not exists (
    select 1 from pending x
    where x.generation = f.generation and x.tokenizer = f.tokenizer and x.term = f.term
  )
  returning 1
),
done as (delete from bm25_df_pending returning 1),
up as (
  insert into bm25_terms as f (generation, tokenizer, term, df)
  select k.generation, k.tokenizer, k.term, (coalesce(l.n, 0) - coalesce(x.d, 0))::int
  from (
    select generation, tokenizer, term from live
    union
    select generation, tokenizer, term from pending
  ) k
  left join live l using (generation, tokenizer, term)
  left join pending x using (generation, tokenizer, term)
  on conflict (generation, tokenizer, term) do update set df = excluded.df
  returning 1
)
select (select count(*) from up) as n
"""


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True, connect_timeout=3)


def _lock(conn) -> bool:
    return conn.execute(
        "select pg_try_advisory_xact_lock(%s, hashtext('bm25')) as locked",
        (LOCK_CLASS,),
    ).fetchone()["locked"]


def fold_once(conn) -> int:
    """Fold up to BATCH deltas. Returns how many were folded, or BUSY."""
    with conn.transaction():
        if not _lock(conn):
            return BUSY
        counts = int(conn.execute(FOLD_COUNTS, {"batch": BATCH}).fetchone()["n"])
        terms = int(conn.execute(FOLD_TERMS, {"batch": BATCH}).fetchone()["n"])
        return counts + terms


def fold_all(dsn: str) -> tuple[int, str | None]:
    """Fold until the backlog is inside one batch, or MAX_BATCHES transactions were spent."""
    done = 0
    with _connect(dsn) as conn:
        for _ in range(MAX_BATCHES):
            n = fold_once(conn)
            if n == BUSY:
                return done, "busy"
            if not n:
                break
            done += n
            if n < BATCH:
                break
    return done, None


def recount(dsn: str) -> list[dict] | None:
    """Recompute counters from one snapshot, minus the deltas that snapshot sees.

    None: another fold or recount holds the lock, or a fold committed under this snapshot.
    """
    with _connect(dsn) as conn:
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
        try:
            with conn.transaction():
                if not _lock(conn):
                    return None
                rows = [dict(row) for row in conn.execute(RECOUNT_COUNTS).fetchall()]
                conn.execute(RECOUNT_TERMS)
                return rows
        except psycopg.errors.SerializationFailure:
            return None


def _interval(args: list[str]) -> float:
    try:
        value = float(args[0]) if args else 30.0
    except ValueError:
        raise SystemExit(2) from None
    if not 0 < value < float("inf"):
        raise SystemExit(2)
    return value


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    usage = "usage: kbindex-maintain fold [--watch [SECONDS]] | recount"
    if not args or args[0] not in {"fold", "recount"}:
        print(usage, file=sys.stderr)
        raise SystemExit(2)
    from kbindex.config import load_settings

    dsn = load_settings().database_url
    try:
        if args[0] == "recount" and len(args) == 1:
            rows = recount(dsn)
            if rows is None:
                print("busy (a fold or recount holds it; run again)", file=sys.stderr)
                raise SystemExit(6)
            if not rows:
                print("no documents")
            for row in rows:
                print(f"{row['tokenizer']}: {row['doc_count']}")
            return
        if args[0] == "fold" and (len(args) == 1 or (len(args) in (2, 3) and args[1] == "--watch")):
            if len(args) == 1:
                done, failed = fold_all(dsn)
                print(f"deltas folded: {done}" + (f"; {failed}" if failed else ""))
                raise SystemExit(6 if failed else 0)
            interval = _interval(args[2:])
            while True:
                try:
                    done, failed = fold_all(dsn)
                    if done or failed:
                        print(f"deltas folded: {done}" + (f"; {failed}" if failed else ""))
                except psycopg.Error as exc:
                    print(f"fold pass failed: {exc}", file=sys.stderr)
                time.sleep(interval)
    except SystemExit:
        raise
    except psycopg.Error as exc:
        print(f"failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(usage, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
