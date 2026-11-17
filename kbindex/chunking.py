"""Policy B. One point per block. Long blocks split on token boundaries, no overlap."""

from __future__ import annotations

from collections.abc import Callable
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


def chunk_blocks(
    blocks: list[tuple[int, str]],
    *,
    window: int,
    encode: Tokenizer | None = None,
    decode: Decoder | None = None,
) -> list[Piece]:
    """`blocks` is `(block_index, text)`. Empty text yields no piece."""
    encode = encode or _char_tokens
    decode = decode or _char_decode
    out: list[Piece] = []
    for index, text in blocks:
        if not text.strip():
            continue
        for piece_no, part in enumerate(split_block(text, window=window, encode=encode, decode=decode)):
            out.append(Piece(index, piece_no, part, len(encode(part))))
    return out
