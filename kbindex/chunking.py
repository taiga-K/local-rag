"""Policy B. One point per block. Long blocks split on token boundaries, no overlap."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


Tokenizer = Callable[[str], list[int]]
Decoder = Callable[[list[int]], str]


@dataclass(frozen=True)
class Piece:
    block_index: int
    piece: int
    text: str
    token_count: int


def _char_tokens(text: str) -> list[int]:
    return [ord(ch) for ch in text]


def _char_decode(tokens: list[int]) -> str:
    return "".join(chr(n) for n in tokens)


def split_block(text: str, *, window: int, encode: Tokenizer, decode: Decoder) -> list[str]:
    """Cut `text` into the fewest pieces that each have at most `window` tokens.

    Pieces join back to `text`. There is no overlap. This is PipesHub policy B
    (`_slice_on_character_boundaries`), not the overlapping sentence windows of
    policy A.
    """
    if window < 1:
        raise ValueError("window must be positive")
    tokens = encode(text)
    if len(tokens) <= window:
        return [text] if text else []
    parts: list[str] = []
    for start in range(0, len(tokens), window):
        piece = decode(tokens[start : start + window])
        if piece:
            parts.append(piece)
    if "".join(parts) != text:
        # A tokenizer that does not round-trip falls back to characters.
        return [text[i : i + window] for i in range(0, len(text), window)]
    return parts


def pieces_from_spans(text: str, spans: list[tuple[int, int]], window: int) -> list[tuple[str, int]]:
    """Cut `text` on token spans. The pieces join back to `text` and do not overlap."""
    return list(pieces_from_span_batches(text, [spans], window))


def pieces_from_span_batches(
    text: str,
    batches: Iterable[list[tuple[int, int]]],
    window: int,
) -> Iterable[tuple[str, int]]:
    """Cut text while keeping only one tokenizer section and one output window in memory.

    A long block can produce millions of spans. Materializing that list before cutting
    is enough to kill the indexing worker, so spans are consumed as bounded batches.
    """
    if window < 1:
        raise ValueError("window must be positive")
    pending: list[tuple[int, int]] = []
    start = 0

    def emit(group: list[tuple[int, int]], end: int) -> tuple[str, int] | None:
        nonlocal start
        if end < start:
            end = start
        piece = text[start:end]
        if not piece:
            return None
        start = end
        return piece, len(group)

    for batch in batches:
        pending.extend(batch)
        while len(pending) > window:
            group = pending[:window]
            del pending[:window]
            emitted = emit(group, group[-1][1])
            if emitted is not None:
                yield emitted
    if pending:
        emitted = emit(pending, len(text))
        if emitted is not None:
            yield emitted
    elif start == 0 and text:
        yield text, 1


def chunk_blocks(
    blocks: list[tuple[int, str]],
    *,
    window: int,
    encode: Tokenizer | None = None,
    decode: Decoder | None = None,
    spans: Callable[[str], list[tuple[int, int]]] | None = None,
    span_batches: Callable[[str], Iterable[list[tuple[int, int]]]] | None = None,
) -> list[Piece]:
    """`blocks` is `(block_index, text)`. Empty text yields no piece."""
    encode = encode or _char_tokens
    decode = decode or _char_decode
    out: list[Piece] = []
    for index, text in blocks:
        if not text.strip():
            continue
        if span_batches is not None:
            for piece_no, (part, count) in enumerate(pieces_from_span_batches(text, span_batches(text), window)):
                out.append(Piece(index, piece_no, part, count))
            continue
        if spans is not None:
            for piece_no, (part, count) in enumerate(pieces_from_spans(text, spans(text), window)):
                out.append(Piece(index, piece_no, part, count))
            continue
        for piece_no, part in enumerate(split_block(text, window=window, encode=encode, decode=decode)):
            out.append(Piece(index, piece_no, part, len(encode(part))))
    return out
