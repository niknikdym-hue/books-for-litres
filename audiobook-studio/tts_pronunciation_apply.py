"""Materialize canonical stress marks into the editable TTS working copy.

The human-facing canonical representation is a Unicode combining acute placed
on the stressed vowel (for example ``замо́к``). Provider-specific syntax is
rendered later by backend adapters. The immutable imported source is untouched.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from book_library import BookLibrary
from tts_text_review import (
    TTSTextReviewError,
    add_pronunciation_override,
    save_working_copy,
    stress_candidates,
    working_copy_status,
)


_COMBINING_ACUTE = "\u0301"


def _word_pattern(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE | re.UNICODE)


def _accented_word(matched_word: str, vowel_number: int) -> str:
    candidates = stress_candidates(matched_word)
    candidate = next((item for item in candidates if item["vowel_number"] == vowel_number), None)
    if candidate is None:
        raise TTSTextReviewError("invalid_stress_choice", "Selected stress is outside the matched word.")
    return unicodedata.normalize("NFC", str(candidate["display"]))


def apply_book_stress(
    library: BookLibrary,
    book_name: str,
    *,
    word: str,
    vowel_number: int,
) -> dict[str, Any]:
    """Accent every exact BOOK-scoped occurrence and persist its provenance rule.

    The text write happens first. That immediately invalidates any READY
    preparation, so provider execution cannot race between text materialization
    and pronunciation metadata publication. If metadata publication fails, the
    previous text is restored using the exact post-edit SHA.
    """
    selected = word.strip()
    if not selected or any(character.isspace() for character in selected):
        raise TTSTextReviewError("invalid_pronunciation_word", "Select exactly one word for stress editing.")
    # Validate the chosen vowel even when the word is not found in this book.
    stress_candidates(selected)

    before = working_copy_status(library, book_name)
    original_text = str(before["text"])
    pattern = _word_pattern(selected)
    matches = list(pattern.finditer(original_text))
    if not matches:
        raise TTSTextReviewError(
            "pronunciation_word_not_found",
            f"Word {selected!r} was not found in the current TTS working copy.",
        )

    replacement_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacement_count
        replacement_count += 1
        return _accented_word(match.group(0), vowel_number)

    edited_text = pattern.sub(replace, original_text)
    if edited_text == original_text or _COMBINING_ACUTE not in edited_text:
        raise TTSTextReviewError("pronunciation_not_materialized", "Stress mark could not be materialized safely.")

    saved = save_working_copy(
        library,
        book_name,
        text=edited_text,
        expected_sha256=str(before["working_copy_sha256"]),
    )
    try:
        rule = add_pronunciation_override(
            library,
            book_name,
            word=selected,
            vowel_number=vowel_number,
            scope="BOOK",
        )
    except Exception:
        # Restore the exact old text. A revision may advance twice, which is
        # intentional audit evidence; semantic state returns to the old bytes.
        save_working_copy(
            library,
            book_name,
            text=original_text,
            expected_sha256=str(saved["working_copy_sha256"]),
        )
        raise

    final = working_copy_status(library, book_name)
    return {
        "schema_version": 1,
        "changed": True,
        "word": selected,
        "vowel_number": vowel_number,
        "display": _accented_word(selected, vowel_number),
        "scope": "BOOK",
        "matches_materialized": replacement_count,
        "pronunciation_entry": rule.get("entry"),
        **final,
    }
