"""Materialize canonical stress marks into the editable TTS working copy.

The human-facing canonical representation is a Unicode combining acute placed
on the stressed vowel (for example ``замо́к``). Provider-specific syntax is
rendered later by backend adapters. The immutable imported source is untouched.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from book_library import BookLibrary
from tts_text_review import (
    TTSTextReviewError,
    save_working_copy,
    stress_candidates,
    working_copy_status,
)


_COMBINING_ACUTE = "\u0301"
_RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _word_pattern(word: str) -> re.Pattern[str]:
    # Match both a plain word and the same word carrying an existing canonical
    # stress mark after any vowel. This lets the owner correct замо́к -> за́мок.
    parts: list[str] = []
    for character in word:
        parts.append(re.escape(character))
        if character in _RUSSIAN_VOWELS:
            parts.append(f"{_COMBINING_ACUTE}?")
    return re.compile(rf"(?<!\w){''.join(parts)}(?!\w)", re.IGNORECASE | re.UNICODE)


def _plain_word(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace(_COMBINING_ACUTE, ""))


def _accented_word(matched_word: str, vowel_number: int) -> str:
    plain = _plain_word(matched_word)
    candidates = stress_candidates(plain)
    candidate = next((item for item in candidates if item["vowel_number"] == vowel_number), None)
    if candidate is None:
        raise TTSTextReviewError("invalid_stress_choice", "Selected stress is outside the matched word.")
    return unicodedata.normalize("NFC", str(candidate["display"]))


def _pronunciation_document(book: Mapping[str, Any]) -> dict[str, Any]:
    raw = book.get("pronunciation_overrides")
    if raw in (None, {}):
        return {"schema_version": 1, "revision": 0, "entries": []}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise TTSTextReviewError("pronunciation_invalid", "Pronunciation overlay schema is invalid.")
    revision = raw.get("revision")
    entries = raw.get("entries")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or not isinstance(entries, list):
        raise TTSTextReviewError("pronunciation_invalid", "Pronunciation overlay is malformed.")
    return {"schema_version": 1, "revision": revision, "entries": [dict(item) for item in entries if isinstance(item, dict)]}


def _publish_book_rule(
    library: BookLibrary,
    book_name: str,
    *,
    word: str,
    vowel_number: int,
    display: str,
) -> dict[str, Any]:
    profile_name = library.resolve_book_profile(book_name).name
    book = library.load_book_profile(profile_name)
    pronunciation = _pronunciation_document(book)
    normalized_word = unicodedata.normalize("NFKC", word).casefold()
    entries = pronunciation["entries"]
    existing_index = next(
        (
            index
            for index, entry in enumerate(entries)
            if entry.get("scope") == "BOOK"
            and unicodedata.normalize("NFKC", str(entry.get("word") or "")).casefold() == normalized_word
        ),
        None,
    )
    now = _utc_now()
    if existing_index is not None:
        current = dict(entries[existing_index])
        if current.get("vowel_number") == vowel_number and current.get("display") == display:
            return {"changed": False, "entry": current}
        current.update({
            "vowel_number": vowel_number,
            "display": display,
            "updated_at": now,
            "actor": "OWNER",
        })
        entries[existing_index] = current
        published_entry = current
    else:
        published_entry = {
            "override_id": f"PRON-{uuid.uuid4().hex[:20].upper()}",
            "scope": "BOOK",
            "word": word,
            "vowel_number": vowel_number,
            "display": display,
            "start": None,
            "end": None,
            "text_sha256": None,
            "created_at": now,
            "actor": "OWNER",
        }
        entries.append(published_entry)

    next_book = deepcopy(book)
    next_book["pronunciation_overrides"] = {
        "schema_version": 1,
        "revision": pronunciation["revision"] + 1,
        "entries": entries,
    }
    library.replace_book_profile(profile_name, next_book)
    return {"changed": True, "entry": published_entry}


def apply_book_stress(
    library: BookLibrary,
    book_name: str,
    *,
    word: str,
    vowel_number: int,
) -> dict[str, Any]:
    """Accent every BOOK-scoped occurrence and persist/update its provenance rule.

    Text materialization happens before metadata publication. If the text changes,
    READY preparation becomes STALE immediately, so no provider execution can
    race through with old audio identity. A metadata failure restores old bytes.
    """
    selected = _plain_word(word.strip())
    if not selected or any(character.isspace() for character in selected):
        raise TTSTextReviewError("invalid_pronunciation_word", "Select exactly one word for stress editing.")
    candidates = stress_candidates(selected)
    if not any(item["vowel_number"] == vowel_number for item in candidates):
        raise TTSTextReviewError("invalid_stress_choice", "Selected stress is outside the word.")

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
    display = _accented_word(selected, vowel_number)
    text_changed = edited_text != original_text
    saved = before
    if text_changed:
        saved = save_working_copy(
            library,
            book_name,
            text=edited_text,
            expected_sha256=str(before["working_copy_sha256"]),
        )
    try:
        rule = _publish_book_rule(
            library,
            book_name,
            word=selected,
            vowel_number=vowel_number,
            display=display,
        )
    except Exception:
        if text_changed:
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
        "changed": bool(text_changed or rule["changed"]),
        "text_changed": text_changed,
        "word": selected,
        "vowel_number": vowel_number,
        "display": display,
        "scope": "BOOK",
        "matches_materialized": replacement_count,
        "pronunciation_entry": rule.get("entry"),
        **final,
    }
