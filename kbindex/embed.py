"""Embeddings. Fake is deterministic. Real loads ruri-v3."""

from __future__ import annotations

import hashlib
import struct

DOC_PREFIX = "検索文書: "
QUERY_PREFIX = "検索クエリ: "
DIM = 768


class Embedder:
    dim = DIM
    max_seq_length = 32

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class FakeEmbedder(Embedder):
    """Stable unit vectors from a hash. Not a language model."""

    def __init__(self, dim: int = 32, window: int = 32) -> None:
        self.dim = dim
        self.max_seq_length = window

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = (digest * ((self.dim * 4 // len(digest)) + 1))[: self.dim * 4]
        nums = list(struct.unpack(f"<{self.dim}f", struct.pack(f"<{self.dim}I", *struct.unpack(f"<{self.dim}I", raw[: self.dim * 4]))))
        # The pack dance above is fragile. Use ints instead.
        return nums

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._unit(DOC_PREFIX + text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._unit(QUERY_PREFIX + text)

    def _unit(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        values = []
        while len(values) < self.dim:
            digest = hashlib.sha256(digest).digest()
            values.extend(byte / 127.5 - 1 for byte in digest)
        vec = values[: self.dim]
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


class RuriEmbedder(Embedder):
    def __init__(self, model: str, device: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.max_seq_length = int(self._model.max_seq_length)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode([DOC_PREFIX + text for text in texts], normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        row = self._model.encode([QUERY_PREFIX + text], normalize_embeddings=True)[0]
        return list(map(float, row))


def load_embedder(backend: str, model: str, device: str) -> Embedder:
    if backend == "fake":
        return FakeEmbedder()
    if backend == "sentence-transformers":
        return RuriEmbedder(model, device)
    raise ValueError(f"unknown embedding backend {backend}")
