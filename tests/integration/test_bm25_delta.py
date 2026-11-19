"""Incremental BM25 counts against a real Postgres. Skipped unless INTEGRATION=1."""

from __future__ import annotations

import json
import math
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest

from kbindex.config import load_settings
from kbindex.db import (
    Database,
    bm25_rows,
    _drop_wiped_deltas,
    _wipe_postings,
    clear_postings,
    delete_chunks_for,
    delete_postings,
    insert_chunks,
    insert_weighted_postings,
    record_id_for,
    write_postings,
)
from kbindex.embed import FakeEmbedder
from kbindex.maintain import fold_all, recount
from kbindex.pipeline import Engine

pytestmark = pytest.mark.integration

TOKENIZER = "fastembed"
MAIN_WORKDIR = Path("/tmp/local-rag-main")
SIDE = Path(__file__).with_name("main_bm25_side.py")


def _admin():
    return psycopg.connect("dbname=postgres", autocommit=True)


def _fresh(name: str) -> str:
    with _admin() as conn:
        conn.execute(f'drop database if exists "{name}" with (force)')
        conn.execute(f'create database "{name}"')
    return f"dbname={name}"


def _truth(conn, tokenizer: str = TOKENIZER) -> tuple[int, dict[str, int]]:
    df = {
        row["term"]: int(row["n"])
        for row in conn.execute(
            """
            select term, count(*) as n from bm25_postings
            where generation = 1 and tokenizer = %s
            group by term
            """,
            (tokenizer,),
        )
    }
    n = conn.execute(
        """
        select count(*) as n from (
          select chunk_id from bm25_postings
          where generation = 1 and tokenizer = %s
          group by chunk_id
        ) c
        """,
        (tokenizer,),
    ).fetchone()["n"]
    return int(n), df


def _visible(conn, tokenizer: str = TOKENIZER) -> tuple[int, dict[str, int]]:
    rows = conn.execute(
        """
        select term from bm25_postings where generation = 1 and tokenizer = %s
        union
        select term from bm25_terms where generation = 1 and tokenizer = %s
        union
        select term from bm25_term_delta where generation = 1 and tokenizer = %s
        """,
        (tokenizer, tokenizer, tokenizer),
    ).fetchall()
    terms = [row["term"] for row in rows] or ["__none__"]
    stats, df_rows, _posts = bm25_rows(conn, tokenizer, terms)
    df = {row["term"]: int(row["df"]) for row in df_rows if row["term"] != "__none__"}
    return int(stats["doc_count"]), df


def _assert_match(conn) -> tuple[int, dict[str, int]]:
    n_true, df_true = _truth(conn)
    n_vis, df_vis = _visible(conn)
    assert n_vis == n_true, (n_vis, n_true)
    for term in set(df_true) | set(df_vis):
        assert df_vis.get(term, 0) == df_true.get(term, 0), term
    return n_true, df_true


def _add(conn, chunk_id: str, terms: list[str], weight: float = 1.0) -> None:
    insert_weighted_postings(
        conn,
        TOKENIZER,
        {chunk_id: [(term, weight) for term in terms]},
        length_from_weight=False,
    )


def _record(conn, kb: str, external: str):
    rid = record_id_for(kb, external)
    conn.execute(
        """
        insert into records (
          record_id, kb_id, external_record_id, version, record_name, indexing_status
        ) values (%s, %s, %s, 1, %s, 'COMPLETED')
        on conflict (record_id) do nothing
        """,
        (rid, kb, external, external),
    )
    return rid


def _chunks_for(conn, rid, terms: list[str]) -> str:
    chunk_id = f"{rid}:0"
    insert_chunks(conn, rid, [(chunk_id, 0, 0, "text", len(terms))])
    _add(conn, chunk_id, terms)
    return chunk_id


def _keyword_scores(stats, df_rows, posts) -> list[tuple[str, float]]:
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
    return ranked


def _scores(conn, queries: list[list[str]]) -> list[list[tuple[str, float]]]:
    return [_keyword_scores(*bm25_rows(conn, TOKENIZER, terms)) for terms in queries]


def test_incremental_counts_match_postings_and_recount():
    dsn = _fresh("bm25_delta_ops")
    db = Database(dsn)
    db.migrate()
    rng = random.Random(17)
    live: dict[str, list[str]] = {}
    vocab = [f"t{i}" for i in range(12)]
    checked = 0
    with db.connect() as conn:
        for step in range(36):
            kind = rng.choice(("add", "delete", "reingest", "undo", "update"))
            if kind == "add" or not live:
                cid = f"c{step}"
                terms = rng.sample(vocab, k=rng.randint(1, 4))
                _add(conn, cid, terms, weight=1.0 + step % 3)
                live[cid] = terms
            elif kind == "delete":
                cid = rng.choice(list(live))
                delete_postings(conn, "chunk_id = %s", (cid,))
                del live[cid]
            elif kind == "reingest":
                cid = rng.choice(list(live))
                terms = rng.sample(vocab, k=rng.randint(1, 4))
                delete_postings(conn, "chunk_id = %s", (cid,))
                _add(conn, cid, terms, weight=2.0)
                live[cid] = terms
            elif kind == "undo":
                cid = f"undo{step}"
                _add(conn, cid, rng.sample(vocab, k=2))
                delete_postings(conn, "chunk_id = %s", (cid,))
            else:
                cid = rng.choice(list(live))
                delete_postings(conn, "chunk_id = %s", (cid,))
                terms = rng.sample(vocab, k=3)
                _add(conn, cid, terms, weight=0.5)
                live[cid] = terms
            _assert_match(conn)
            checked += 1
        _add(conn, "same", ["uniq-a", "uniq-b"])
        _add(conn, "same", ["uniq-a", "uniq-b", "uniq-c"], weight=3.0)
        n_docs, df = _assert_match(conn)
        assert df["uniq-a"] == 1 and df["uniq-b"] == 1 and df["uniq-c"] == 1
        conn.commit()

    folded, failed = fold_all(dsn)
    assert failed is None and folded > 0
    with db.connect() as conn:
        _assert_match(conn)
        leftover = conn.execute("select count(*) as n from bm25_term_delta").fetchone()["n"]
        assert int(leftover) == 0
        conn.execute("update bm25_terms set df = df + 9")
        conn.execute("update bm25_stats set doc_count = doc_count + 5")
        conn.commit()
    assert recount(dsn) is not None
    with db.connect() as conn:
        n_docs, df = _assert_match(conn)
        conn.commit()
    assert checked == 36
    assert n_docs == len(live) + 1
    assert len(df) >= 3
    print(f"OPS {checked} doc_count {n_docs} terms {len(df)}")


def test_record_paths_undo_update_clear_and_restore():
    dsn = _fresh("bm25_delta_paths")
    db = Database(dsn)
    db.migrate()
    with db.connect() as conn:
        kept = _record(conn, "kb", "kept")
        _chunks_for(conn, kept, ["alpha", "beta"])
        created = _record(conn, "kb", "new")
        _chunks_for(conn, created, ["alpha"])
        conn.commit()
    with db.connect() as conn:
        delete_chunks_for(conn, created)
        conn.commit()
    with db.connect() as conn:
        n_docs, df = _assert_match(conn)
        assert n_docs == 1 and df == {"alpha": 1, "beta": 1}
        conn.commit()

    with db.connect() as conn:
        delete_chunks_for(conn, kept)
        conn.commit()
    with db.connect() as conn:
        assert _assert_match(conn) == (0, {})
        conn.commit()
    with db.connect() as conn:
        _chunks_for(conn, kept, ["beta", "gamma"])
        conn.commit()
    with db.connect() as conn:
        n_docs, df = _assert_match(conn)
        assert n_docs == 1 and df == {"beta": 1, "gamma": 1}
        conn.commit()

    assert fold_all(dsn)[1] is None
    with db.connect() as conn:
        _assert_match(conn)
        stats = conn.execute("select doc_count from bm25_stats where tokenizer = %s", (TOKENIZER,)).fetchone()
        assert int(stats["doc_count"]) == 1
        clear_postings(conn)
        conn.commit()
    with db.connect() as conn:
        assert _assert_match(conn) == (0, {})
        stats = conn.execute(
            "select doc_count from bm25_stats where generation = 1 and tokenizer = %s",
            (TOKENIZER,),
        ).fetchone()
        assert stats is not None and int(stats["doc_count"]) == 0
        conn.commit()

    with db.connect() as conn:
        rid = _record(conn, "kb", "restored")
        chunk_id = f"{rid}:0"
        insert_chunks(conn, rid, [(chunk_id, 0, 0, "back", 2)])
        write_postings(conn, [(1, TOKENIZER, "alpha", chunk_id, 1.5, 2)])
        snap = {
            "points": [],
            "chunks": [{
                "chunk_id": chunk_id,
                "record_id": rid,
                "block_id": None,
                "block_index": 0,
                "piece": 0,
                "text": "back",
                "token_count": 2,
            }],
            "postings": [{
                "generation": 1,
                "tokenizer": TOKENIZER,
                "term": "alpha",
                "chunk_id": chunk_id,
                "tf": 1.5,
                "doc_len": 2,
            }],
            "statuses": [{"record_id": rid, "indexing_status": "COMPLETED", "failure_reason": None}],
            "generation": None,
        }
        conn.commit()
    engine = Engine(load_settings(), db, _Vectors(), FakeEmbedder())
    engine.restore_index(snap)
    with db.connect() as conn:
        n_docs, df = _assert_match(conn)
        assert n_docs == 1 and df == {"alpha": 1}


def test_clear_postings_keeps_a_delta_committed_after_the_delete():
    """Another KB can commit during a wipe. Its deltas must survive."""
    dsn = _fresh("bm25_delta_wipe_race")
    db = Database(dsn)
    db.migrate()
    with db.connect() as conn:
        _add(conn, "kb-a", ["alpha"])
        conn.commit()
    assert fold_all(dsn)[1] is None
    wiper = db.connect()
    try:
        touched = _wipe_postings(wiper)
        assert touched and touched[0]["tokenizer"] == TOKENIZER
        with db.connect() as other:
            _add(other, "kb-b", ["beta"])
            other.commit()
        _drop_wiped_deltas(wiper, touched)
        wiper.commit()
    finally:
        wiper.close()
    with db.connect() as conn:
        n_docs, df = _assert_match(conn)
        assert n_docs == 1 and df == {"beta": 1}
        stats = conn.execute(
            "select doc_count from bm25_stats where generation = 1 and tokenizer = %s",
            (TOKENIZER,),
        ).fetchone()
        assert stats is not None and int(stats["doc_count"]) == 0


def test_concurrent_inserts_match_recount():
    dsn = _fresh("bm25_delta_concurrent")
    db = Database(dsn)
    db.migrate()
    errors: list[BaseException] = []

    def ingest(worker: int) -> None:
        try:
            local = Database(dsn)
            with local.connect() as conn:
                for i in range(25):
                    _add(conn, f"w{worker}-{i}", ["shared", f"w{worker}", f"n{(worker * 3 + i) % 7}"])
                conn.commit()
        except BaseException as exc:
            errors.append(exc)

    def fold_sometimes() -> None:
        try:
            for _ in range(8):
                fold_all(dsn)
                time.sleep(0.01)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=ingest, args=(i,)) for i in range(4)]
    threads.append(threading.Thread(target=fold_sometimes))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()
    assert errors == []
    with db.connect() as conn:
        _assert_match(conn)
        conn.commit()
    assert recount(dsn) is not None
    with db.connect() as conn:
        n_docs, _df = _assert_match(conn)
        assert n_docs == 100


def test_pending_scores_match_recount_and_pending_clears():
    dsn = _fresh("bm25_delta_pending")
    queries = [["alpha", "beta"], ["gamma"], ["missing"]]
    docs = [
        {"id": "c1", "pairs": [["alpha", 1.0], ["beta", 2.0]]},
        {"id": "c2", "pairs": [["alpha", 0.5]]},
        {"id": "c3", "pairs": [["gamma", 1.25], ["beta", 0.25]]},
    ]
    _run_main({"cmd": "apply", "dsn": dsn, "ops": [{"op": "add", "id": doc["id"], "pairs": doc["pairs"]} for doc in docs]})
    db = Database(dsn)
    db.migrate()
    with db.connect() as conn:
        pending = conn.execute("select tokenizer from bm25_df_pending").fetchall()
        assert [row["tokenizer"] for row in pending] == [TOKENIZER]
        assert int(conn.execute("select count(*) as n from bm25_term_delta").fetchone()["n"]) == 0
        before = _scores(conn, queries)
        conn.commit()
    recounted = _scores_from_postings(db, queries)
    assert before == recounted
    assert recount(dsn) is not None
    with db.connect() as conn:
        assert conn.execute("select 1 from bm25_df_pending").fetchone() is None
        assert int(conn.execute("select count(*) as n from bm25_term_delta").fetchone()["n"]) == 0
        after = _scores(conn, queries)
        conn.commit()
    assert after == recounted
    assert fold_all(dsn)[0] == 0


def test_fold_leaves_pending_in_place():
    dsn = _fresh("bm25_delta_fold_pending")
    db = Database(dsn)
    db.migrate()
    with db.connect() as conn:
        _add(conn, "c1", ["alpha"])
        conn.execute(
            "insert into bm25_df_pending (generation, tokenizer) values (1, %s) on conflict do nothing",
            (TOKENIZER,),
        )
        conn.commit()
    fold_all(dsn)
    with db.connect() as conn:
        assert conn.execute("select 1 from bm25_df_pending").fetchone() is not None
        _assert_match(conn)


def test_scores_match_main_before_fold_after_fold_and_after_recount():
    dsn = _fresh("bm25_delta_scores")
    docs = [
        {"id": f"d{i}", "pairs": [[f"t{i % 5}", 1.0], [f"t{(i * 2) % 5}", 0.5 + i * 0.1]]}
        for i in range(12)
    ]
    queries = [[f"t{i}"] for i in range(5)] + [["t0", "t1", "t4"]]
    ops = [{"op": "add", "id": doc["id"], "pairs": doc["pairs"]} for doc in docs]
    ops.append({"op": "score", "queries": queries})
    ops.append({"op": "delete", "id": "d3"})
    ops.append({"op": "score", "queries": queries})
    ops.append({"op": "add", "id": "d3", "pairs": [["t1", 4.0], ["t2", 0.2]]})
    ops.append({"op": "score", "queries": queries})
    main_scores = _run_main({"cmd": "apply", "dsn": _fresh("bm25_main_scores"), "ops": ops})

    db = Database(dsn)
    db.migrate()
    branch_scores = []
    with db.connect() as conn:
        for op in ops:
            if op["op"] == "add":
                insert_weighted_postings(
                    conn,
                    TOKENIZER,
                    {op["id"]: [(term, float(weight)) for term, weight in op["pairs"]]},
                    length_from_weight=False,
                )
            elif op["op"] == "delete":
                delete_postings(conn, "chunk_id = %s", (op["id"],))
            elif op["op"] == "score":
                branch_scores.append(_scores(conn, op["queries"]))
        conn.commit()
    decoded = _decode_scores(main_scores)
    assert branch_scores == decoded
    compared = sum(len(query) for snapshot in decoded for query in snapshot)
    print(f"SCORE_ROWS {compared} across {len(decoded)} states")
    folded, failed = fold_all(dsn)
    assert failed is None and folded > 0
    with db.connect() as conn:
        after_fold = _scores(conn, queries)
        conn.commit()
    assert after_fold == _decode_scores(main_scores)[-1]
    assert recount(dsn) is not None
    with db.connect() as conn:
        after_recount = _scores(conn, queries)
    assert after_recount == _decode_scores(main_scores)[-1]


def test_ingest_time_stays_flat_as_the_corpus_grows():
    terms = 30
    early = 40
    sizes = [250, 500, 1000, 2000, 4000]
    main = _run_main({
        "cmd": "bench",
        "dsn": _fresh("bm25_main_bench"),
        "terms": terms,
        "early": early,
        "sizes": sizes,
    })
    branch = _bench_branch(_fresh("bm25_branch_bench"), terms, early, sizes)
    print("MAIN", json.dumps(main))
    print("BRANCH", json.dumps(branch))
    branch_by_n = {point["n"]: point["seconds"] for point in branch["marginal"]}
    main_by_n = {point["n"]: point["seconds"] for point in main["marginal"]}
    # Empty-table inserts are cheaper than a populated index. From 250 documents
    # onward the branch stays in a small band, while main's rebuild keeps climbing.
    assert branch_by_n[4000] < branch_by_n[250] * 2.0
    assert main_by_n[4000] > main_by_n[250] * 4.0
    assert branch_by_n[4000] < main_by_n[4000] / 20.0


class _Vectors:
    def drop(self) -> None:
        return None

    def ensure(self, _dim: int) -> None:
        return None

    def restore_points(self, _points) -> None:
        return None


def _scores_from_postings(db: Database, queries: list[list[str]]):
    with db.connect() as conn:
        n_docs, df = _truth(conn)
        stats = {"doc_count": n_docs}
        out = []
        for terms in queries:
            posts = conn.execute(
                """
                select term, chunk_id, tf from bm25_postings
                where generation = 1 and tokenizer = %s and term = any(%s)
                """,
                (TOKENIZER, terms),
            ).fetchall()
            df_rows = [{"term": term, "df": df.get(term, 0)} for term in terms]
            out.append(_keyword_scores(stats, df_rows, posts))
        return out


def _decode_scores(payload) -> list[list[list[tuple[str, float]]]]:
    return [
        [[(cid, float(score)) for cid, score in query] for query in snapshot]
        for snapshot in payload
    ]


def _run_main(spec: dict):
    if not MAIN_WORKDIR.joinpath("kbindex", "db.py").exists():
        pytest.skip("main worktree is not at /tmp/local-rag-main")
    proc = subprocess.run(
        [sys.executable, str(SIDE)],
        input=json.dumps(spec),
        text=True,
        capture_output=True,
        cwd=str(MAIN_WORKDIR),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(MAIN_WORKDIR)},
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-4000:] or proc.stdout[-4000:])
    return json.loads(proc.stdout)


def _bench_branch(dsn: str, terms: int, early: int, sizes: list[int]) -> dict:
    db = Database(dsn)
    db.migrate()
    per_doc: list[float] = []

    def pairs(index: int) -> list[tuple[str, float]]:
        return [(str((index * 17 + slot * 31) % 4000), 1.0 + (slot % 5) * 0.25) for slot in range(terms)]

    with db.connect() as conn:
        for index in range(early):
            started = time.perf_counter()
            insert_weighted_postings(conn, TOKENIZER, {f"bench-{index}": pairs(index)}, length_from_weight=False)
            per_doc.append(time.perf_counter() - started)
        conn.commit()
        filled = early
        marginal = []
        for size in sizes:
            if filled < size - 1:
                _bulk_branch(conn, filled, size - 1, pairs)
                conn.execute("analyze bm25_postings")
                conn.commit()
                filled = size - 1
            started = time.perf_counter()
            insert_weighted_postings(conn, TOKENIZER, {f"bench-{size - 1}": pairs(size - 1)}, length_from_weight=False)
            marginal.append({"n": size, "seconds": time.perf_counter() - started})
            conn.commit()
            filled = size
    early_seconds = sum(per_doc)
    return {
        "early_n": early,
        "early_seconds": early_seconds,
        "early_docs_per_min": (early / early_seconds) * 60.0,
        "early_mean_seconds": early_seconds / early,
        "marginal": marginal,
        "marginal_docs_per_min": [
            {"n": point["n"], "docs_per_min": 60.0 / point["seconds"] if point["seconds"] else None}
            for point in marginal
        ],
    }


def _bulk_branch(conn, start: int, stop: int, pairs) -> None:
    rows = []
    for index in range(start, stop):
        weighted = pairs(index)
        doc_len = len(weighted)
        for term, weight in weighted:
            rows.append((1, TOKENIZER, term, f"bench-{index}", weight, doc_len))
    write_postings(conn, rows)

