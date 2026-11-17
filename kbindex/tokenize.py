"""Sudachi mode C and provisional character bigrams."""

from __future__ import annotations

import unicodedata

from sudachipy import dictionary, tokenizer as sudachi_tokenizer


_TOKENIZER = None


def _analyzer():
    global _TOKENIZER
    if _TOKENIZER is None:
        holder = dictionary.Dictionary()
        _TOKENIZER = holder.tokenizer() if hasattr(holder, "tokenizer") else holder.create()
    return _TOKENIZER


def sudachi_terms(text: str, *, mode: str = "C", normalize: bool = True) -> list[str]:
    modes = {
        "A": sudachi_tokenizer.Tokenizer.SplitMode.A,
        "B": sudachi_tokenizer.Tokenizer.SplitMode.B,
        "C": sudachi_tokenizer.Tokenizer.SplitMode.C,
    }
    if mode not in modes:
        raise ValueError(f"unknown sudachi mode {mode}")
    out: list[str] = []
    for morpheme in _analyzer().tokenize(text, modes[mode]):
        form = morpheme.normalized_form() if normalize else morpheme.surface()
        if form:
            out.append(form)
    return out


def char_bigrams(text: str) -> list[str]:
    """Provisional rule: NFKC, drop space and control, then adjacent code points."""
    cleaned = []
    for char in unicodedata.normalize("NFKC", text):
        if char.isspace() or unicodedata.category(char).startswith("C"):
            continue
        cleaned.append(char)
    return [cleaned[i] + cleaned[i + 1] for i in range(len(cleaned) - 1)]
