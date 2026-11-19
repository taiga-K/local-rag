"""BM25 operations on main 3587e4f. Run with PYTHONPATH set to that worktree."""

from __future__ import annotations

import json
import math
import sys
import time

from kbindex.db import Database, bm25_rows, insert_weighted_postings, rebuild_bm25


def _scores(conn, queries: list[list[str]]) -> list[list[list]]:
    out = []
    for terms in queries:
        stats, df_rows, posts = bm25_rows(conn, "fastembed", terms)
        out.append(_keyword_scores(stats, df_rows, posts))
    return out


def _keyword_scores(stats, df_rows, posts) -> list[list]:
    if not stats or int(stats["doc_count"]) == 0:
        return []
    n_docs = int(stats["doc_count"])
    df = {row["term"]: int(row["df"]) for row in df_rows}
    ordered = sorted(posts, key=lambda row: (row["chunk_id"], row["term"]))
    scores: dict[str, float] = {}
    for row in ordered:
        n = df.get(row["term"], 0)
        idf = math.log((n_docs - n + 0.5) / (n + 0.5) + 1.0)
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + float(row["tf"]) * idf
    ranked = sorted(((cid, score) for cid, score in scores.items() if score > 0), key=lambda item: (-item[1], item[0]))
    return [[cid, score] for cid, score in ranked]


def _add(conn, chunk_id: str, pairs: list[list]) -> None:
    insert_weighted_postings(
        conn,
        "fastembed",
        {chunk_id: [(term, float(weight)) for term, weight in pairs]},
        length_from_weight=False,
    )
    rebuild_bm25(conn)


def _delete(conn, chunk_id: str) -> None:
    conn.execute("delete from bm25_postings where chunk_id = %s", (chunk_id,))
    rebuild_bm25(conn)


def _bench(conn, spec: dict) -> dict:
    terms = int(spec["terms"])
    early = int(spec["early"])
    sizes = [int(n) for n in spec["sizes"]]
    per_doc: list[float] = []

    def one(index: int) -> None:
        pairs = _pairs(index, terms)
        started = time.perf_counter()
        _add(conn, f"bench-{index}", pairs)
        per_doc.append(time.perf_counter() - started)

    for index in range(early):
        one(index)
    conn.commit()
    filled = early
    marginal = []
    for size in sizes:
        while filled < size - 1:
            _bulk(conn, filled, size - 1, terms)
            rebuild_bm25(conn)
            conn.commit()
            filled = size - 1
        started = time.perf_counter()
        one(size - 1)
        marginal.append({"n": size, "seconds": time.perf_counter() - started})
        conn.commit()
        filled = size
    early_seconds = sum(per_doc[:early])
    return {
        "early_n": early,
        "early_seconds": early_seconds,
        "early_docs_per_min": (early / early_seconds) * 60.0 if early_seconds else None,
        "early_mean_seconds": (early_seconds / early) if early else None,
        "marginal": marginal,
    }


def _pairs(index: int, terms: int) -> list[tuple[str, float]]:
    return [(str((index * 17 + slot * 31) % 4000), 1.0 + (slot % 5) * 0.25) for slot in range(terms)]


def _bulk(conn, start: int, stop: int, terms: int) -> None:
    rows = []
    for index in range(start, stop):
        doc_len = terms
        for term, weight in _pairs(index, terms):
            rows.append((term, f"bench-{index}", weight, doc_len))
    if not rows:
        return
    conn.execute("delete from bm25_postings where chunk_id = any(%s)", ([f"bench-{i}" for i in range(start, stop)],))
    terms_l, ids, weights, lengths = map(list, zip(*rows, strict=True))
    conn.execute(
        """
        insert into bm25_postings (generation, tokenizer, term, chunk_id, tf, doc_len)
        select 1, 'fastembed', term, chunk_id, tf, doc_len
        from unnest(%s::text[], %s::text[], %s::float8[], %s::int[])
          as t(term, chunk_id, tf, doc_len)
        """,
        (terms_l, ids, weights, lengths),
    )


def main() -> None:
    spec = json.load(sys.stdin)
    db = Database(spec["dsn"])
    db.migrate()
    with db.connect() as conn:
        if spec["cmd"] == "bench":
            json.dump(_bench(conn, spec), sys.stdout)
            return
        snapshots = []
        for op in spec["ops"]:
            kind = op["op"]
            if kind == "add":
                _add(conn, op["id"], op["pairs"])
            elif kind == "delete":
                _delete(conn, op["id"])
            elif kind == "score":
                snapshots.append(_scores(conn, op["queries"]))
            else:
                raise SystemExit(f"unknown op {kind}")
        conn.commit()
    json.dump(snapshots, sys.stdout)


if __name__ == "__main__":
    main()
