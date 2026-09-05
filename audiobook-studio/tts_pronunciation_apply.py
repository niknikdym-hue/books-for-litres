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
from pronunciation_dictionary import (
    PronunciationDictionary,
    apply_auto_pronunciations,
    _workspace_from_library,
)
from tts_text_review import (
    TTSTextReviewError,
    apply_occurrence_pronunciation,
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
    scope: str = "BOOK",
    start: int | None = None,
    end: int | None = None,
    expected_sha256: str = "",
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

    # Validate the private global store before touching the current book.  A
    # corrupt/future-schema dictionary must never turn one owner action into a
    # half-published correction.
    dictionary = PronunciationDictionary(_workspace_from_library(library))
    dictionary.snapshot()
    profile_name = library.resolve_book_profile(book_name).name
    original_book = deepcopy(library.load_book_profile(profile_name))
    before = working_copy_status(library, book_name)
    original_text = str(before["text"])
    normalized_scope = scope.strip().upper()
    if normalized_scope == "OCCURRENCE":
        if start is None or end is None or not expected_sha256:
            raise TTSTextReviewError(
                "invalid_pronunciation_offsets",
                "Occurrence correction requires exact offsets and working-copy SHA.",
            )
        occurrence = apply_occurrence_pronunciation(
            library,
            book_name,
            word=selected,
            vowel_number=vowel_number,
            start=start,
            end=end,
            expected_sha256=expected_sha256,
            post_publish=lambda display: dictionary.upsert(
                selected,
                vowel_number,
                display,
                source="STUDIO_CORRECTION",
            ),
        )
        display = str(occurrence["display"])
        global_rule = occurrence["post_publish_result"]
        final = working_copy_status(library, book_name)
        contextual = bool(global_rule.get("contextual"))
        return {
            "schema_version": 1,
            "changed": True,
            "text_changed": bool(occurrence["text_changed"]),
            "word": selected,
            "vowel_number": vowel_number,
            "display": display,
            "scope": "OCCURRENCE",
            "matches_materialized": 1,
            "pronunciation_entry": occurrence.get("entry"),
            "dictionary_entry": global_rule.get("entry"),
            "dictionary_revision": global_rule.get("revision"),
            "dictionary_changed": bool(global_rule.get("changed")),
            "dictionary_conflict": bool(global_rule.get("conflict")),
            "confirmation_message": (
                f"Для этого места сохранено: {display}. Слово зависит от контекста и не будет автоматически изменяться в других местах."
                if contextual
                else f"{display} добавлено в Словарь ударений"
            ),
            **final,
        }
    if normalized_scope != "BOOK":
        raise TTSTextReviewError(
            "invalid_pronunciation_scope", "Pronunciation scope must be BOOK or OCCURRENCE."
        )
    if dictionary.is_contextual_word(selected):
        raise TTSTextReviewError(
            "contextual_occurrence_required",
            "This word depends on context. Select its exact occurrence in the text.",
        )
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
        global_rule = dictionary.upsert(
            selected,
            vowel_number,
            display,
            source="STUDIO_CORRECTION",
        )
    except Exception:
        if text_changed:
            try:
                save_working_copy(
                    library,
                    book_name,
                    text=original_text,
                    expected_sha256=str(saved["working_copy_sha256"]),
                )
            finally:
                library.replace_book_profile(profile_name, original_book)
        else:
            library.replace_book_profile(profile_name, original_book)
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
        "dictionary_entry": global_rule.get("entry"),
        "dictionary_revision": global_rule.get("revision"),
        "dictionary_changed": bool(global_rule.get("changed")),
        "dictionary_conflict": bool(global_rule.get("conflict")),
        "confirmation_message": (
            "Для этого слова сохранено несколько вариантов. Выбирайте ударение по контексту."
            if global_rule.get("conflict")
            else f"{display} добавлено в Словарь ударений"
        ),
        **final,
    }


def synchronize_global_pronunciations(
    library: BookLibrary,
    book_name: str,
) -> dict[str, Any]:
    """Apply a stable offline dictionary snapshot to one editable working copy.

    Dictionary I/O finishes before the working-copy lock is acquired.  This
    establishes the lock order for V1 and avoids a dictionary/provider cycle;
    provider execution continues to rely on its existing exact-SHA fence.
    """
    dictionary = PronunciationDictionary(_workspace_from_library(library))
    automatic_entries = dictionary.auto_entries()
    before = working_copy_status(library, book_name)
    profile_name = library.resolve_book_profile(book_name).name
    book = library.load_book_profile(profile_name)
    raw_overrides = book.get("pronunciation_overrides")
    book_entries = (
        raw_overrides.get("entries", [])
        if isinstance(raw_overrides, dict) and isinstance(raw_overrides.get("entries"), list)
        else []
    )
    updated_text = apply_auto_pronunciations(
        str(before["text"]),
        automatic_entries,
        book_entries,
        working_copy_sha256=str(before["working_copy_sha256"]),
    )
    if updated_text == before["text"]:
        return {
            "changed": False,
            "dictionary_revision": dictionary.snapshot()["revision"],
            **before,
        }
    after = save_working_copy(
        library,
        profile_name,
        text=updated_text,
        expected_sha256=str(before["working_copy_sha256"]),
    )
    return {
        "changed": True,
        "dictionary_revision": dictionary.snapshot()["revision"],
        **after,
    }
