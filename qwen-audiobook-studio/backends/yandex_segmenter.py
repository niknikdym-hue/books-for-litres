from __future__ import annotations

import re

from .yandex_types import TextSegment, collapse_ws


def _fits(text: str, max_chars: int, max_words: int) -> bool:
    return len(text) <= max_chars and len(text.split()) <= max_words


def _split_long_piece(text: str, max_chars: int, max_words: int) -> list[str]:
    text = collapse_ws(text)
    if not text:
        return []
    if _fits(text, max_chars, max_words):
        return [text]

    clauses = [p.strip() for p in re.split(r"(?<=[,;:—])\s+", text) if p.strip()]
    if len(clauses) > 1:
        out: list[str] = []
        current = ""
        for part in clauses:
            candidate = f"{current} {part}".strip() if current else part
            if current and not _fits(candidate, max_chars, max_words):
                out.extend(_split_long_piece(current, max_chars, max_words))
                current = part
            else:
                current = candidate
        if current:
            out.extend(_split_long_piece(current, max_chars, max_words))
        return out

    out: list[str] = []
    current_words: list[str] = []
    for word in text.split():
        if len(word) > max_chars:
            if current_words:
                out.append(" ".join(current_words))
                current_words = []
            out.extend(word[i:i + max_chars] for i in range(0, len(word), max_chars))
            continue
        candidate_words = current_words + [word]
        candidate = " ".join(candidate_words)
        if current_words and not _fits(candidate, max_chars, max_words):
            out.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words = candidate_words
    if current_words:
        out.append(" ".join(current_words))
    return out


def segment_text(
    text: str,
    *,
    max_chars: int = 220,
    max_words: int = 34,
    sentence_pause_ms: int = 380,
    paragraph_pause_ms: int = 700,
) -> list[TextSegment]:
    """Literary-first splitter for SpeechKit v3 normal mode (unsafeMode=False)."""
    if max_chars <= 0 or max_chars > 250:
        raise ValueError("max_chars must be in 1..250 for SpeechKit v3 normal mode")
    if max_words <= 0:
        raise ValueError("max_words must be positive")

    paragraphs = [p for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    raw: list[TextSegment] = []
    for p_idx, paragraph in enumerate(paragraphs, start=1):
        paragraph = collapse_ws(paragraph)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", paragraph) if s.strip()] or [paragraph]
        pieces: list[str] = []
        for sentence in sentences:
            pieces.extend(_split_long_piece(sentence, max_chars, max_words))

        packed: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip() if current else piece
            if current and not _fits(candidate, max_chars, max_words):
                packed.append(current)
                current = piece
            else:
                current = candidate
        if current:
            packed.append(current)

        for i, piece in enumerate(packed):
            raw.append(TextSegment(
                segment_id="",
                text=piece,
                pause_after_ms=paragraph_pause_ms if i == len(packed) - 1 else sentence_pause_ms,
                paragraph_index=p_idx,
            ))

    if raw:
        last = raw[-1]
        raw[-1] = TextSegment("", last.text, 0, last.paragraph_index)

    return [
        TextSegment(f"s{i:04d}", seg.text, seg.pause_after_ms, seg.paragraph_index)
        for i, seg in enumerate(raw, start=1)
    ]
