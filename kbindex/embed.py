"""Embeddings. Queries and documents are the same string.

PipesHub's encode passes neither prompt_name nor prompt, so ruri receives the
raw text (embedding_main.py L1176-L1184 at 426fc25). The card prefixes are not
applied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

class Embedder:
    dim = 32
    max_seq_length = 64

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        raise NotImplementedError

    def token_span_batches(self, text: str) -> Iterable[list[tuple[int, int]]]:
        raise NotImplementedError

    def exact_token_spans(self, text: str) -> list[tuple[int, int]]:
        return self.token_spans(text)

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

    def token_span_batches(self, text: str) -> Iterable[list[tuple[int, int]]]:
        yield self.token_spans(text)


TOKEN_SPAN_SECTION_CHARS = 8192


class RuriEmbedder(Embedder):
    def __init__(self, model: str, device: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.max_seq_length = int(self._model.max_seq_length)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        row = self._model.encode([text], normalize_embeddings=True)[0]
        return list(map(float, row))

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return self.exact_token_spans(text)

    def exact_token_spans(self, text: str) -> list[tuple[int, int]]:
        encoded = self._model.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return [(start, end) for start, end in encoded["offset_mapping"] if end > start]

    def token_span_batches(self, text: str) -> Iterable[list[tuple[int, int]]]:
        """Tokenize bounded character sections so a huge block does not allocate all input ids at once.

        Sections are tokenized independently, so seam-adjacent tokens are a rough cut.
        The pipeline retokenizes each bounded piece exactly before embedding it.
        """
        for base in range(0, len(text), TOKEN_SPAN_SECTION_CHARS):
            section = text[base : base + TOKEN_SPAN_SECTION_CHARS]
            encoded = self._model.tokenizer(section, add_special_tokens=False, return_offsets_mapping=True)
            yield [
                (base + start, base + end)
                for start, end in encoded["offset_mapping"]
                if end > start
            ]

    def split_limit(self) -> int:
        return max(1, self.max_seq_length - 2)


def load_embedder(backend: str, model: str, device: str) -> Embedder:
    if backend == "fake":
        return FakeEmbedder()
    if backend == "sentence-transformers":
        return RuriEmbedder(model, device)
    raise ValueError(f"unknown embedding backend {backend}")
