"""One real ruri-v3 embedding. Fills PipesHub gap 5.

Principle: behavior. The vector length is what Qdrant will store.
PipesHub: tests/integration/vector_db/test_e2e_pipeline.py uses FakeEmbedder.
Marked slow so the default pytest run does not download the model.
"""

import pytest

pytestmark = pytest.mark.slow


def test_ruri_dimension_and_order():
    pytest.importorskip("sentence_transformers")
    from kbindex.embed import RuriEmbedder

    model = RuriEmbedder("cl-nagoya/ruri-v3-310m", "cpu")
    assert model.dim == 768
    weather = model.embed_documents(["東京都の天気は晴れです。"])[0]
    library = model.embed_documents(["図書館は水曜が休館です。"])[0]
    query = model.embed_query("東京の天気")

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    assert dot(query, weather) > dot(query, library)
