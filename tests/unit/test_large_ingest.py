"""Large-block chunking stays streaming and long embedding batches stay small."""

from kbindex.chunking import Piece, pieces_from_span_batches
from kbindex.embed import FakeEmbedder, RuriEmbedder, TOKEN_SPAN_SECTION_CHARS
from kbindex.pipeline import _stored_error, embed_batch_capacity, embedding_batches, refine_pieces_exactly


def test_span_batches_rejoin_text_without_materializing_all_spans():
    text = "あいうえお" * 31
    spans = [(index, index + 1) for index in range(len(text))]
    batches = [spans[offset : offset + 7] for offset in range(0, len(spans), 7)]

    pieces = list(pieces_from_span_batches(text, batches, 11))

    assert "".join(piece for piece, _count in pieces) == text
    assert all(count <= 11 for _piece, count in pieces)
    assert len(pieces) > 1


def test_span_batches_keeps_exact_window_boundary_in_last_piece():
    text = "x" * 8
    spans = [(index, index + 1) for index in range(len(text))]

    pieces = list(pieces_from_span_batches(text, [spans], 4))

    assert pieces == [("xxxx", 4), ("xxxx", 4)]


def test_embedding_batch_capacity_drops_to_one_near_the_model_window():
    assert embed_batch_capacity(100) == 32
    assert embed_batch_capacity(1000) == 8
    assert embed_batch_capacity(8190) == 1


def test_embedding_batches_do_not_mix_full_window_pieces():
    pieces = [Piece(0, index, "x", count) for index, count in enumerate([100] * 40 + [8190] * 2)]

    sizes = [len(batch) for batch in embedding_batches(pieces)]

    assert sizes == [32, 8, 1, 1]


def test_memory_error_is_written_as_actionable_japanese():
    assert "メモリ" in _stored_error(MemoryError())


def test_ruri_span_batches_are_bounded_and_keep_global_offsets():
    calls = []

    class Tokenizer:
        def __call__(self, text, **_kwargs):
            calls.append(text)
            return {"offset_mapping": [(index, index + 1) for index in range(len(text))]}

    class Model:
        tokenizer = Tokenizer()

    embedder = object.__new__(RuriEmbedder)
    embedder._model = Model()
    text = "x" * (TOKEN_SPAN_SECTION_CHARS + 3)

    batches = list(embedder.token_span_batches(text))

    assert [len(call) for call in calls] == [TOKEN_SPAN_SECTION_CHARS, 3]
    assert batches[1][0] == (TOKEN_SPAN_SECTION_CHARS, TOKEN_SPAN_SECTION_CHARS + 1)
    assert batches[1][-1] == (TOKEN_SPAN_SECTION_CHARS + 2, TOKEN_SPAN_SECTION_CHARS + 3)


def test_exact_retokenization_splits_section_boundary_drift():
    class ExactEmbedder:
        def split_limit(self):
            return 4

        def exact_token_spans(self, text):
            return [(index, index + 2) for index in range(0, len(text), 2)]

    refined = refine_pieces_exactly([Piece(0, 0, "x" * 10, 3)], ExactEmbedder())

    assert [(piece.piece, piece.text, piece.token_count) for piece in refined] == [
        (0, "x" * 8, 4),
        (1, "x" * 2, 1),
    ]


def test_fake_embedder_stream_spans_in_bounded_batches():
    batches = list(FakeEmbedder().token_span_batches("x" * 8193))

    assert [len(batch) for batch in batches] == [8192, 1]
    assert batches[1] == [(8192, 8193)]
