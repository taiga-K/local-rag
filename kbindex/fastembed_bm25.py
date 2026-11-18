"""fastembed Qdrant/bm25, called with the model name and no other arguments.

Document weights are the model's BM25 weights (k=1.2, b=0.75, avg_len=256).
Query terms come from query_embed. The ranker multiplies a document weight by
log((N-n+0.5)/(n+0.5)+1). That is the sparse score in the MIRACL recompute
that matched the recorded PipesHub+ruri nDCG of 0.8314.
"""

from __future__ import annotations

from fastembed import SparseTextEmbedding

_MODEL: SparseTextEmbedding | None = None


def model() -> SparseTextEmbedding:
    global _MODEL
    if _MODEL is None:
        _MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _MODEL


def document_weights(text: str) -> list[tuple[str, float]]:
    embedding = next(iter(model().embed([text])))
    return [(str(int(index)), float(value)) for index, value in zip(embedding.indices, embedding.values, strict=True)]


def query_terms(text: str) -> list[str]:
    embedding = next(iter(model().query_embed([text])))
    return [str(int(index)) for index in embedding.indices]
