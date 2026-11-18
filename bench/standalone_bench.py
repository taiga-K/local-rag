#!/usr/bin/env python3
"""One-file Japanese retrieval benchmark for a PipesHub-compatible service.

Dependencies: the standard library, datasets, ranx, and requests.

    python standalone_bench.py verify
    python standalone_bench.py run --subset jqara-dev-s40 \
        --base-url http://127.0.0.1:18421 --kb KB --sanity-kb SANITY \
        --out results/run

``verify`` rebuilds the three subsets with seed 20261117 and checks the
SHA-256 lines embedded below. ``run`` refuses to score a dataset until the
three-document check ranks ``keep`` first.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import platform
import random
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import requests
from datasets import load_dataset
from ranx import Qrels, Run, evaluate

SEED = 20261117
LIMIT = 10
REPEATS = 5
RESULT_CAP = 50
EXTERNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$")
RANX_METRICS = ["recall@1", "recall@5", "recall@10", "ndcg@10", "mrr@10"]

JQARA_ID = "hotchpotch/JQaRA"
JSQUAD_URL = "https://raw.githubusercontent.com/yahoojapan/JGLUE/main/datasets/jsquad-v1.3/valid-v1.3.json"
MIRACL_TOPICS_URL = "https://huggingface.co/datasets/miracl/miracl/resolve/main/miracl-v1.0-ja/topics/topics.miracl-v1.0-ja-dev.tsv"
MIRACL_QRELS_URL = "https://huggingface.co/datasets/miracl/miracl/resolve/main/miracl-v1.0-ja/qrels/qrels.miracl-v1.0-ja-dev.tsv"
MIRACL_CORPUS_URL = "https://huggingface.co/datasets/miracl/miracl-corpus/resolve/main/miracl-corpus-v1.0-ja/docs-{shard}.jsonl.gz"
MIRACL_SHARDS = 14

# Hub dataset scripts for JGLUE and MIRACL no longer load. JSQuAD copies on the
# Hub also rewrite the context. These files are the ones the hashes were built
# from: JQaRA through datasets, JSQuAD from the JGLUE release, MIRACL from the
# Hugging Face dataset resolve URLs.

EXPECTED: dict[str, dict[str, str]] = {
    "jqara-dev-s40": {
        "corpus.jsonl": "6912bdc61b732d9d2ad74dab96d8f5408efe12739b00bb9c1ded63c6a33f7070",
        "queries.jsonl": "29139de3c7dfc5806a97098f221d7d0d70dea946c39c81af9eaf36d37b8a80af",
        "qrels.tsv": "99e646f5ddecbf783f2a178c168669893c5101f10cb307da548b930e136b3911",
    },
    "jsquad-valid-s40": {
        "corpus.jsonl": "35df6a278fdc16355038611081b3f85209bb2dfcd51c8d75fdb17af8c93cdf20",
        "queries.jsonl": "3ca860282ea84540d6d6416a0ee47031034c19688d2a3a88f63d70331f9b065a",
        "qrels.tsv": "a952084ce593f096902f52070e10a5b4e981dbdf4f536597b3407607f3a992a7",
    },
    "miracl-ja-dev-s30": {
        "corpus.jsonl": "c07d5427f355e0504bd884573ed80d9f10c33f9b4dbbf075154d3801452c38ab",
        "queries.jsonl": "425093aaac084a9bcc1911e62302e71fde9d9fbf5c33f05f18e6d3b83a0e47b6",
        "qrels.tsv": "0528423e5bb1ef2b298c61bca3045e34d94228a404a3818925cf0baec7681e46",
    },
}

SANITY_DOCS = (
    ("keep", "赤いりんごをかごに入れた"),
    ("drop", "青いバナナを数えた"),
    ("other", "夕方の電車は遅れている"),
)
SANITY_QUERY = "赤いりんご"


def choose_ids(ids: Iterable[str], count: int, seed: int) -> list[str]:
    unique = sorted(set(ids))
    if count < 1 or count > len(unique):
        raise ValueError(f"count must be in 1..{len(unique)}")
    draw = list(unique)
    random.Random(seed).shuffle(draw)
    return sorted(draw[:count])


def external_record_id(doc_id: str) -> str:
    if EXTERNAL_ID.fullmatch(doc_id):
        return doc_id
    return "d" + hashlib.sha256(doc_id.encode("utf-8")).hexdigest()


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    response = requests.get(url, timeout=120, headers={"User-Agent": "standalone-bench"})
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def _bundle(documents: list[tuple[str, str, str]], queries: list[tuple[str, str, dict[str, int]]]) -> dict[str, str]:
    """documents are (doc_id, title, text). queries are (query_id, text, grades)."""
    corpus: list[str] = []
    seen: dict[str, str] = {}
    for doc_id, title, text in documents:
        external = external_record_id(doc_id)
        previous = seen.get(external)
        if previous is not None and previous != doc_id:
            raise ValueError(f"externalRecordId collision between {previous} and {doc_id}")
        seen[external] = doc_id
        corpus.append(json.dumps(
            {"externalRecordId": external, "title": title, "text": text},
            ensure_ascii=False,
            separators=(",", ":"),
        ))
    query_lines: list[str] = []
    qrel_lines: list[str] = []
    for query_id, text, grades in queries:
        query_lines.append(json.dumps(
            {"queryId": query_id, "text": text},
            ensure_ascii=False,
            separators=(",", ":"),
        ))
        ranked = sorted((doc_id for doc_id, grade in grades.items() if grade > 0), key=external_record_id)
        for doc_id in ranked:
            qrel_lines.append(f"{query_id}\t0\t{external_record_id(doc_id)}\t{grades[doc_id]}")
    return {
        "corpus.jsonl": "\n".join(corpus) + "\n",
        "queries.jsonl": "\n".join(query_lines) + "\n",
        "qrels.tsv": "\n".join(qrel_lines) + "\n",
    }


def _jqara(cache: Path) -> dict[str, str]:
    del cache
    table = load_dataset(JQARA_ID, split="dev")
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in table:
        grouped.setdefault(str(row["q_id"]), []).append(row)
    wanted = choose_ids(grouped, 40, SEED)
    documents: dict[str, tuple[str, str]] = {}
    queries: list[tuple[str, str, dict[str, int]]] = []
    for query_id in wanted:
        rows = grouped[query_id]
        grades: dict[str, int] = {}
        for row in rows:
            doc_id = str(row["passage_row_id"])
            documents.setdefault(doc_id, (str(row["title"] or ""), str(row["text"])))
            if int(row["label"]) == 1:
                grades[doc_id] = 1
        if not grades:
            raise ValueError(f"{query_id} has no positive passage")
        queries.append((query_id, str(rows[0]["question"]), grades))
    docs = [(doc_id, documents[doc_id][0], documents[doc_id][1]) for doc_id in sorted(documents)]
    return _bundle(docs, queries)


def _jsquad(cache: Path) -> dict[str, str]:
    payload = json.loads(_download(JSQUAD_URL, cache / "jsquad-valid-v1.3.json").read_text(encoding="utf-8"))
    found: list[dict[str, str]] = []
    for article in payload["data"]:
        title = str(article.get("title") or "")
        for paragraph in article["paragraphs"]:
            context = str(paragraph["context"])
            doc_id = "p" + hashlib.sha256(context.encode("utf-8")).hexdigest()[:16]
            for qa in paragraph["qas"]:
                found.append({
                    "id": str(qa["id"]),
                    "question": str(qa["question"]),
                    "context": context,
                    "title": title,
                    "doc_id": doc_id,
                })
    by_id = {qa["id"]: qa for qa in found}
    wanted = choose_ids(by_id, 40, SEED)
    documents: dict[str, tuple[str, str]] = {}
    for qa in found:
        documents.setdefault(qa["doc_id"], (qa["title"], qa["context"]))
    queries = [(query_id, by_id[query_id]["question"], {by_id[query_id]["doc_id"]: 1}) for query_id in wanted]
    docs = [(doc_id, documents[doc_id][0], documents[doc_id][1]) for doc_id in sorted(documents)]
    return _bundle(docs, queries)


def _read_topics(path: Path) -> dict[str, str]:
    topics: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, query = line.split("\t", 1)
            topics[qid] = query
    return topics


def _read_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ValueError(f"qrels line does not have 4 columns: {line[:80]}")
        qid, _unused, doc_id, relevance = parts
        qrels.setdefault(qid, {})[doc_id] = int(relevance)
    return qrels


def _miracl(cache: Path) -> dict[str, str]:
    topics = _read_topics(_download(MIRACL_TOPICS_URL, cache / "miracl-ja-dev-topics.tsv"))
    qrels = _read_qrels(_download(MIRACL_QRELS_URL, cache / "miracl-ja-dev-qrels.tsv"))
    wanted = choose_ids(topics, 30, SEED)
    needed: set[str] = set()
    queries: list[tuple[str, str, dict[str, int]]] = []
    for query_id in wanted:
        judgments = qrels.get(query_id, {})
        grades = {doc_id: grade for doc_id, grade in judgments.items() if grade > 0}
        if not grades:
            raise ValueError(f"{query_id} has no positive qrel")
        needed.update(judgments)
        queries.append((query_id, topics[query_id], grades))
    found: dict[str, tuple[str, str]] = {}
    remaining = set(needed)
    for shard in range(MIRACL_SHARDS):
        if not remaining:
            break
        path = _download(MIRACL_CORPUS_URL.format(shard=shard), cache / f"miracl-ja-docs-{shard}.jsonl.gz")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                doc_id = str(row["docid"])
                if doc_id not in remaining:
                    continue
                found[doc_id] = (str(row.get("title") or ""), str(row.get("text") or ""))
                remaining.discard(doc_id)
    if remaining:
        sample = ", ".join(sorted(remaining)[:5])
        raise ValueError(f"MIRACL corpus is missing {len(remaining)} judged passages, including {sample}")
    docs = [(doc_id, found[doc_id][0], found[doc_id][1]) for doc_id in sorted(found)]
    return _bundle(docs, queries)


def build_files(name: str, cache: Path) -> dict[str, str]:
    if name == "jqara-dev-s40":
        return _jqara(cache)
    if name == "jsquad-valid-s40":
        return _jsquad(cache)
    if name == "miracl-ja-dev-s30":
        return _miracl(cache)
    raise ValueError(f"unknown subset {name}")


def file_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def verify(cache: Path) -> list[str]:
    mismatches: list[str] = []
    for name, expected in EXPECTED.items():
        files = build_files(name, cache)
        for filename, digest in expected.items():
            got = file_sha256(files[filename])
            if got != digest:
                mismatches.append(f"{name}/{filename} {got} != {digest}")
    return mismatches


def load_subset(name: str, cache: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str, dict[str, int]]]]:
    """Return documents as (id, text) and queries as (id, text, grades)."""
    if name == "jqara-dev-s40":
        return _materialize_jqara()
    if name == "jsquad-valid-s40":
        return _materialize_jsquad(cache)
    if name == "miracl-ja-dev-s30":
        return _materialize_miracl(cache)
    raise ValueError(f"unknown subset {name}")


def _materialize_jqara() -> tuple[list[tuple[str, str]], list[tuple[str, str, dict[str, int]]]]:
    table = load_dataset(JQARA_ID, split="dev")
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in table:
        grouped.setdefault(str(row["q_id"]), []).append(row)
    wanted = choose_ids(grouped, 40, SEED)
    documents: dict[str, str] = {}
    queries: list[tuple[str, str, dict[str, int]]] = []
    for query_id in wanted:
        rows = grouped[query_id]
        grades: dict[str, int] = {}
        for row in rows:
            doc_id = str(row["passage_row_id"])
            documents.setdefault(doc_id, str(row["text"]))
            if int(row["label"]) == 1:
                grades[doc_id] = 1
        queries.append((query_id, str(rows[0]["question"]), grades))
    return [(doc_id, documents[doc_id]) for doc_id in sorted(documents)], queries


def _materialize_jsquad(cache: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str, dict[str, int]]]]:
    payload = json.loads(_download(JSQUAD_URL, cache / "jsquad-valid-v1.3.json").read_text(encoding="utf-8"))
    found: list[dict[str, str]] = []
    for article in payload["data"]:
        for paragraph in article["paragraphs"]:
            context = str(paragraph["context"])
            doc_id = "p" + hashlib.sha256(context.encode("utf-8")).hexdigest()[:16]
            for qa in paragraph["qas"]:
                found.append({"id": str(qa["id"]), "question": str(qa["question"]), "context": context, "doc_id": doc_id})
    by_id = {qa["id"]: qa for qa in found}
    documents: dict[str, str] = {}
    for qa in found:
        documents.setdefault(qa["doc_id"], qa["context"])
    queries = [(qid, by_id[qid]["question"], {by_id[qid]["doc_id"]: 1}) for qid in choose_ids(by_id, 40, SEED)]
    return [(doc_id, documents[doc_id]) for doc_id in sorted(documents)], queries


def _materialize_miracl(cache: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str, dict[str, int]]]]:
    topics = _read_topics(_download(MIRACL_TOPICS_URL, cache / "miracl-ja-dev-topics.tsv"))
    qrels = _read_qrels(_download(MIRACL_QRELS_URL, cache / "miracl-ja-dev-qrels.tsv"))
    wanted = choose_ids(topics, 30, SEED)
    needed: set[str] = set()
    queries: list[tuple[str, str, dict[str, int]]] = []
    for query_id in wanted:
        judgments = qrels.get(query_id, {})
        grades = {doc_id: grade for doc_id, grade in judgments.items() if grade > 0}
        needed.update(judgments)
        queries.append((query_id, topics[query_id], grades))
    found: dict[str, str] = {}
    remaining = set(needed)
    for shard in range(MIRACL_SHARDS):
        if not remaining:
            break
        path = _download(MIRACL_CORPUS_URL.format(shard=shard), cache / f"miracl-ja-docs-{shard}.jsonl.gz")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                doc_id = str(row["docid"])
                if doc_id not in remaining:
                    continue
                found[doc_id] = str(row.get("text") or "")
                remaining.discard(doc_id)
    return [(doc_id, found[doc_id]) for doc_id in sorted(found)], queries


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def latency_summary(pass_values: list[list[float]]) -> dict[str, object]:
    out: dict[str, object] = {"repeats": len(pass_values)}
    for name, percentile in (("p50", 50.0), ("p95", 95.0), ("p99", 99.0)):
        stats = [nearest_rank(values, percentile) for values in pass_values]
        ordered = sorted(stats)
        middle = ordered[len(ordered) // 2]
        if len(ordered) % 2 == 0:
            middle = (ordered[len(ordered) // 2 - 1] + middle) / 2
        out[name] = {"median": middle, "min": ordered[0], "max": ordered[-1]}
    return out


def ranx_mean(rows: Sequence[tuple[str, list[tuple[str, float]], dict[str, int]]]) -> dict[str, float]:
    """rows are (query_id, [(doc_id, score)], grades). Empty rankings score 0."""
    qrels: dict[str, dict[str, int]] = {}
    run: dict[str, dict[str, float]] = {}
    for query_id, hits, grades in rows:
        qrels[query_id] = {doc_id: int(grade) for doc_id, grade in grades.items() if grade > 0}
        scored = {doc_id: float(score) for doc_id, score in hits}
        # ranx rejects a query with no retrieved ids. A non-relevant placeholder
        # keeps the query in the mean and scores 0, which matches the harness.
        run[query_id] = scored or {"__empty__": 0.0}
    result = evaluate(Qrels(qrels), Run(run), RANX_METRICS)
    return {name: float(result[name]) for name in RANX_METRICS}


def metrics_from_jsonl(path: Path) -> dict[str, float]:
    """Score pass 0 of a harness JSONL with ranx. Binary grades, as in JQaRA."""
    rows: list[tuple[str, list[tuple[str, float]], dict[str, int]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("pass") != 0 or row.get("status") != "ok":
            continue
        hits = [(str(hit["doc_id"]), float(hit["score"])) for hit in row["hits"]]
        grades = {str(doc_id): 1 for doc_id in row["relevant"]}
        rows.append((str(row["query_id"]), hits, grades))
    return ranx_mean(rows)


class ServiceError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class CompatibleClient:
    def __init__(
        self,
        base_url: str,
        kb_id: str,
        push_base_url: str | None = None,
        token: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.push_base_url = (push_base_url or base_url).rstrip("/")
        self.kb_id = kb_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.external_to_doc: dict[str, str] = {}
        self.record_to_doc: dict[str, str] = {}

    def push(self, doc_id: str, text: str) -> None:
        external = external_record_id(doc_id)
        body = {
            "recordName": external[:255],
            "mimeType": "application/blocks",
            "externalRecordId": external,
            "version": 1,
            "blocksFormat": 1,
            "blocks": {"blocks": [{"index": 0, "type": "text", "format": "txt", "data": text}]},
        }
        payload = self._post(self.push_base_url + f"/api/v1/kb/{self.kb_id}/records", body, ok=(200, 201))
        if not isinstance(payload, dict):
            raise ServiceError("malformed", "push response must be a JSON object")
        self.external_to_doc[external] = doc_id
        record_id = payload.get("recordId")
        if isinstance(record_id, str) and record_id:
            self.record_to_doc[record_id] = doc_id
        echoed = payload.get("externalRecordId")
        if echoed is not None and echoed != external:
            raise ServiceError("malformed", "push response externalRecordId does not match")

    def retrieve(self, query: str, limit: int = LIMIT) -> list[tuple[str, float]]:
        if limit < 1 or limit > RESULT_CAP:
            raise ValueError(f"limit must be in 1..{RESULT_CAP}")
        payload = self._post(self.base_url + "/api/v1/retrieve", {
            "query": query,
            "limit": limit,
            "rewriteQuery": False,
            "maxChunksPerRecord": 1,
            "filters": {"kb": [self.kb_id]},
        })
        if not isinstance(payload, dict) or not isinstance(payload.get("chunks"), list):
            raise ServiceError("malformed", "retrieve response has no chunks array")
        hits: list[tuple[str, float]] = []
        seen: set[str] = set()
        for chunk in payload["chunks"]:
            if not isinstance(chunk, dict):
                raise ServiceError("malformed", "a chunk is not an object")
            record = chunk.get("record")
            if not isinstance(record, dict) or not isinstance(record.get("recordId"), str) or record["recordId"] == "":
                raise ServiceError("malformed", "a chunk has no record.recordId")
            doc_id = self._doc_id(record["recordId"])
            if doc_id in seen:
                raise ServiceError("malformed", "retrieve response repeats a document id")
            seen.add(doc_id)
            score = chunk.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise ServiceError("malformed", "a chunk score is not a number")
            hits.append((doc_id, float(score)))
        hits.sort(key=lambda item: (-item[1], item[0]))
        return hits[:limit]

    def _doc_id(self, record_id: str) -> str:
        if record_id in self.record_to_doc:
            return self.record_to_doc[record_id]
        if record_id in self.external_to_doc:
            return self.external_to_doc[record_id]
        return record_id

    def _post(self, url: str, body: Mapping[str, object], ok: tuple[int, ...] = (200,)) -> object:
        try:
            response = self.session.post(url, json=body, timeout=self.timeout)
        except requests.Timeout as exc:
            raise ServiceError("timeout", str(exc)) from exc
        except requests.ConnectionError as exc:
            raise ServiceError("unreachable", str(exc)) from exc
        if response.status_code in (502, 503):
            raise ServiceError("unavailable", f"HTTP {response.status_code}")
        if response.status_code not in ok:
            raise ServiceError("malformed", f"HTTP {response.status_code}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ServiceError("malformed", "response body is not JSON") from exc


def _index(client: CompatibleClient, documents: Sequence[tuple[str, str]], wait_seconds: float, poll_seconds: float) -> dict[str, float]:
    started = time.perf_counter()
    client.external_to_doc = {}
    client.record_to_doc = {}
    for doc_id, text in documents:
        client.push(doc_id, text)
    wait_started = time.perf_counter()
    pending = list(documents)
    deadline = time.perf_counter() + wait_seconds
    while pending:
        if time.perf_counter() >= deadline:
            raise ServiceError("timeout", f"{len(pending)} records were not returned by retrieve before the wait ended")
        doc_id, text = pending[0]
        probe = text[:80] or doc_id
        try:
            hits = client.retrieve(probe, min(LIMIT, RESULT_CAP))
        except ServiceError:
            hits = []
        if any(hit_id == doc_id for hit_id, _score in hits):
            pending.pop(0)
            continue
        time.sleep(poll_seconds)
    return {
        "seconds": time.perf_counter() - started,
        "push_seconds": wait_started - started,
        "wait_seconds": time.perf_counter() - wait_started,
    }


def _query_row(client: CompatibleClient, query_id: str, text: str, grades: dict[str, int], pass_index: int) -> dict[str, object]:
    started = time.perf_counter()
    error = None
    try:
        hits = client.retrieve(text, LIMIT)
        status = "ok"
    except ServiceError as exc:
        hits = []
        status = "error"
        error = exc.code
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metrics = None
    if status == "ok":
        metrics = ranx_mean([(query_id, hits, grades)])
    return {
        "query_id": query_id,
        "pass": pass_index,
        "status": status,
        "error": error,
        "latency_ms": elapsed_ms,
        "hits": [{"doc_id": doc_id, "score": score, "rank": index} for index, (doc_id, score) in enumerate(hits, start=1)],
        "relevant": sorted(doc_id for doc_id, grade in grades.items() if grade > 0),
        "metrics": metrics,
    }


def run_benchmark(
    name: str,
    cache: Path,
    base_url: str,
    kb_id: str,
    out_dir: Path,
    push_base_url: str | None = None,
    sanity_kb: str | None = None,
    token: str | None = None,
    wait_seconds: float = 3600.0,
    poll_seconds: float = 0.5,
    timeout: float = 120.0,
    repeats: int = REPEATS,
) -> dict[str, object]:
    documents, queries = load_subset(name, cache)
    sanity = CompatibleClient(base_url, sanity_kb or (kb_id + "-sanity"), push_base_url, token, timeout)
    sanity_started = time.perf_counter()
    try:
        sanity_index = _index(sanity, SANITY_DOCS, wait_seconds, poll_seconds)
        ranked = [doc_id for doc_id, _score in sanity.retrieve(SANITY_QUERY, LIMIT)]
        passed = bool(ranked) and ranked[0] == "keep"
        sanity_report: dict[str, object] = {
            "passed": passed,
            "seconds": time.perf_counter() - sanity_started,
            "ranked": ranked,
            "index": sanity_index,
        }
    except ServiceError as exc:
        sanity_report = {"passed": False, "seconds": time.perf_counter() - sanity_started, "error": exc.code}
        passed = False
    out_dir.mkdir(parents=True, exist_ok=True)
    if not passed:
        summary = {"label": "sanity_failed", "dataset": name, "sanity": sanity_report, "metrics": None}
        _write_summary(out_dir, summary)
        return summary

    client = CompatibleClient(base_url, kb_id, push_base_url, token, timeout)
    index_report = _index(client, documents, wait_seconds, poll_seconds)
    warmup_started = time.perf_counter()
    try:
        client.retrieve(queries[0][1], LIMIT)
        warmup_ms: float | None = (time.perf_counter() - warmup_started) * 1000.0
    except ServiceError:
        warmup_ms = None
    passes: list[list[dict[str, object]]] = []
    for pass_index in range(repeats):
        passes.append([_query_row(client, query_id, text, grades, pass_index) for query_id, text, grades in queries])
    quality = [row for row in passes[0] if row["status"] == "ok"]
    errors = [row for row in passes[0] if row["status"] != "ok"]
    stable = all(
        [[hit["doc_id"] for hit in row["hits"]] for row in later if row["status"] == "ok"]
        == [[hit["doc_id"] for hit in row["hits"]] for row in passes[0] if row["status"] == "ok"]
        for later in passes[1:]
    )
    scored = [
        (str(row["query_id"]), [(str(hit["doc_id"]), float(hit["score"])) for hit in row["hits"]], _grades(queries, str(row["query_id"])))  # type: ignore[index]
        for row in quality
    ]
    means = ranx_mean(scored) if scored else {name: None for name in RANX_METRICS}
    metrics: dict[str, object] = {
        key: {"value": value, "label": "measured", "n": len(quality)} for key, value in means.items()
    }
    metrics["recall@20"] = {
        "value": None,
        "label": "not_measurable",
        "reason": f"the run requests {LIMIT} hits, so Recall@20 is not computed",
    }
    label = "measured"
    if errors:
        label = "measured_with_errors"
    if not stable and label == "measured":
        label = "unstable"
    if quality and all(not row["hits"] for row in quality):
        label = "empty_run"
    latency_passes = [[float(row["latency_ms"]) for row in rows if row["status"] == "ok"] for rows in passes]
    summary = {
        "label": label,
        "dataset": name,
        "n_queries": len(queries),
        "n_documents": len(documents),
        "n_errors": len(errors),
        "n_empty": sum(1 for row in quality if not row["hits"]),
        "requested_depth": LIMIT,
        "result_cap": RESULT_CAP,
        "rankings_stable_across_repeats": stable,
        "metrics": metrics,
        "latency_ms": latency_summary(latency_passes) if all(latency_passes) else None,
        "warmup_ms": warmup_ms,
        "index_seconds": index_report["seconds"],
        "index_phases": {"push_seconds": index_report["push_seconds"], "wait_seconds": index_report["wait_seconds"]},
        "sanity": sanity_report,
        "conditions": {
            "python": sys.version,
            "platform": platform.platform(),
            "seed": SEED,
            "limit": LIMIT,
            "repeats": repeats,
            "metrics": "ranx " + ",".join(RANX_METRICS),
            "latency": "nearest-rank",
        },
    }
    _write_jsonl(out_dir / "queries.jsonl", [row for rows in passes for row in rows])
    _write_summary(out_dir, summary)
    return summary


def _grades(queries: Sequence[tuple[str, str, dict[str, int]]], query_id: str) -> dict[str, int]:
    for qid, _text, grades in queries:
        if qid == query_id:
            return grades
    raise KeyError(query_id)


def _write_summary(out_dir: Path, summary: dict[str, object]) -> None:
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="standalone_bench")
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--subset", required=True, choices=tuple(EXPECTED))
    run_parser.add_argument("--base-url", required=True)
    run_parser.add_argument("--push-base-url", default="")
    run_parser.add_argument("--kb", required=True)
    run_parser.add_argument("--sanity-kb", default="")
    run_parser.add_argument("--token", default="")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    run_parser.add_argument("--wait-seconds", type=float, default=3600.0)
    run_parser.add_argument("--timeout", type=float, default=120.0)
    run_parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args(argv)
    if args.command == "verify":
        mismatches = verify(args.cache)
        if mismatches:
            print("\n".join(mismatches), file=sys.stderr)
            return 1
        for name, expected in EXPECTED.items():
            for filename, digest in expected.items():
                print(f"{digest}  {name}/{filename}")
        return 0
    summary = run_benchmark(
        args.subset,
        args.cache,
        args.base_url,
        args.kb,
        args.out,
        push_base_url=args.push_base_url or None,
        sanity_kb=args.sanity_kb or None,
        token=args.token or None,
        wait_seconds=args.wait_seconds,
        timeout=args.timeout,
        repeats=args.repeats,
    )
    print(summary["label"], args.out / "summary.json")
    return 0 if summary["label"] in {"measured", "measured_with_errors"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
