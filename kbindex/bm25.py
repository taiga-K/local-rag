"""Okapi BM25 over per-tokenizer term frequencies. Provisional k1=1.2, b=0.75."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Corpus:
    k1: float = 1.2
    b: float = 0.75
    doc_count: int = 0
    total_tokens: int = 0
    df: Counter[str] = field(default_factory=Counter)
    lengths: dict[str, int] = field(default_factory=dict)
    tf: dict[str, Counter[str]] = field(default_factory=dict)

    def add(self, doc_id: str, terms: list[str]) -> None:
        if doc_id in self.tf:
            self.remove(doc_id)
        counts = Counter(terms)
        self.tf[doc_id] = counts
        self.lengths[doc_id] = sum(counts.values())
        self.doc_count += 1
        self.total_tokens += self.lengths[doc_id]
        for term in counts:
            self.df[term] += 1

    def remove(self, doc_id: str) -> None:
        counts = self.tf.pop(doc_id, None)
        if counts is None:
            return
        self.doc_count -= 1
        self.total_tokens -= self.lengths.pop(doc_id, 0)
        for term in counts:
            self.df[term] -= 1
            if self.df[term] <= 0:
                del self.df[term]

    @property
    def avgdl(self) -> float:
        if self.doc_count == 0:
            return 0.0
        return self.total_tokens / self.doc_count

    def score(self, doc_id: str, query_terms: list[str]) -> float:
        counts = self.tf.get(doc_id)
        if not counts or self.doc_count == 0:
            return 0.0
        dl = self.lengths[doc_id]
        avg = self.avgdl or 1.0
        total = 0.0
        seen: set[str] = set()
        for term in query_terms:
            if term in seen:
                continue
            seen.add(term)
            tf = counts.get(term, 0)
            if tf == 0:
                continue
            n = self.df.get(term, 0)
            idf = math.log(1 + (self.doc_count - n + 0.5) / (n + 0.5))
            denom = tf + self.k1 * (1 - self.b + self.b * dl / avg)
            total += idf * (tf * (self.k1 + 1)) / denom
        return total

    def rank(self, query_terms: list[str]) -> list[tuple[str, float]]:
        scored = [(doc_id, self.score(doc_id, query_terms)) for doc_id in self.tf]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored
