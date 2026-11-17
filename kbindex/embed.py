"""Embeddings. The same model encodes documents and queries. No prefix.

The design leaves a query prefix undecided and tells the code to add none.
"""

from __future__ import annotations

import hashlib


class Embedder:
    dim = 32
    max_seq_length = 64

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        raise NotImplementedError

    def split_limit(self) -> int:
        return self.max_seq_length


class FakeEmbedder(Embedder):
    """Stable unit vectors from a hash. Used when embedding.backend is fake."""

    def __init__(self, dim: int = 32, window: int = 64) -> None:
        self.dim = dim
        self.max_seq_length = window

    def _unit(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        values: list[float] = []
        while len(values) < self.dim:
            digest = hashlib.sha256(digest).digest()
            values.extend(byte / 127.5 - 1 for byte in digest)
        vec = values[: self.dim]
        norm = sum(item * item for item in vec) ** 0.5 or 1.0
        return [item / norm for item in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._unit(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._unit(text)

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [(index, index + 1) for index in range(len(text))]


class RuriEmbedder(Embedder):
    def __init__(self, model: str, device: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.max_seq_length = int(self._model.max_seq_length)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        row = self._model.encode([text], normalize_embeddings=True)[0]
        return list(map(float, row))

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        encoded = self._model.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return [(start, end) for start, end in encoded["offset_mapping"] if end > start]

    def split_limit(self) -> int:
        return max(1, self.max_seq_length - 2)


def load_embedder(backend: str, model: str, device: str) -> Embedder:
    if backend == "fake":
        return FakeEmbedder()
    if backend == "sentence-transformers":
        return RuriEmbedder(model, device)
    raise ValueError(f"unknown embedding backend {backend}")
