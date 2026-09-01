"""Offline manual review and pronunciation control for Audiobook Studio.

This module owns the editable TTS working copy, optional exact-SHA owner acceptance,
and provider-neutral stress decisions. The immutable imported source is never edited.
No provider/model/billing call is performed here.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from book_library import BookLibrary, BookLibraryError, sha256_bytes, sha256_file


SCHEMA_VERSION = 1
PRONUNCIATION_SCHEMA_VERSION = 1
_ALLOWED_SCOPES = {"BOOK", "OCCURRENCE"}
_RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")


class TTSTextReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }


def _read_strict_utf8(path: Path, *, code: str) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as error:
        raise TTSTextReviewError(code, f"Unreadable strict UTF-8 text: {path}") from error


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise TTSTextReviewError("unsafe_working_copy", "TTS working copy must not be a symlink.")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _working_context(
    library: BookLibrary, book_name: str
) -> tuple[str, dict[str, Any], dict[str, Any], Path, str, str]:
    profile = library.resolve_book_profile(book_name)
    book = library.load_book_profile(profile.name)
    if book.get("kind") != "production":
        raise TTSTextReviewError("not_production_book", "Manual text review is available only for production books.")
    details = library.book_details(profile.name)
    if details.get("source_integrity") != "OK":
        raise TTSTextReviewError("source_integrity_error", "Immutable source integrity must be OK before editing the TTS copy.")
    tts = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else None
    if not isinstance(tts, dict):
        raise TTSTextReviewError("working_copy_missing", "TTS working copy metadata is missing.")
    working_path = library.resolve_book_asset(profile.name, tts.get("path"))
    if working_path.is_symlink() or not working_path.is_file():
        raise TTSTextReviewError("working_copy_missing", "TTS working copy is missing or unsafe.")
    working_text = _read_strict_utf8(working_path, code="working_copy_invalid")
    working_sha = sha256_bytes(working_text.encode("utf-8"))
    declared_sha = tts.get("sha256")
    if isinstance(declared_sha, str) and declared_sha and declared_sha != working_sha:
        raise TTSTextReviewError(
            "working_copy_metadata_stale",
            "TTS working copy bytes do not match profile metadata; refuse mutation until reconciled.",
        )
    return profile.name, book, tts, working_path, working_text, working_sha


def _manual_review_state(tts: Mapping[str, Any], working_sha: str) -> dict[str, Any]:
    required = bool(tts.get("manual_review_required", False))
    review = tts.get("manual_review") if isinstance(tts.get("manual_review"), dict) else None
    accepted = bool(
        review
        and review.get("actor") == "OWNER"
        and review.get("accepted_sha256") == working_sha
        and isinstance(review.get("accepted_at"), str)
    )
    return {
        "required": required,
        "accepted": accepted,
        "ready": (not required) or accepted,
        "accepted_sha256": review.get("accepted_sha256") if review else None,
        "accepted_at": review.get("accepted_at") if review else None,
    }


def working_copy_status(library: BookLibrary, book_name: str) -> dict[str, Any]:
    profile_name, book, tts, working_path, working_text, working_sha = _working_context(
        library, book_name
    )
    pronunciation = _pronunciation_document(book)
    return {
        "schema_version": SCHEMA_VERSION,
        "book_id": profile_name,
        "working_copy_path": str(working_path),
        "working_copy_sha256": working_sha,
        "working_copy_revision": int(tts.get("revision") or 0),
        "text": working_text,
        "manual_review": _manual_review_state(tts, working_sha),
        "pronunciation_revision": pronunciation["revision"],
        "pronunciation_entries": pronunciation["entries"],
        "preparation_status": library.book_details(profile_name).get("preparation_status"),
        **_offline_fields(),
    }


def save_working_copy(
    library: BookLibrary,
    book_name: str,
    *,
    text: str,
    expected_sha256: str,
) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise TTSTextReviewError("working_copy_empty", "TTS working copy cannot be empty.")
    profile_name, book, tts, working_path, old_text, current_sha = _working_context(
        library, book_name
    )
    if expected_sha256 != current_sha:
        raise TTSTextReviewError(
            "working_copy_conflict",
            "TTS working copy changed since it was opened. Reload before saving.",
        )
    normalized_text = unicodedata.normalize("NFC", text)
    new_bytes = normalized_text.encode("utf-8")
    new_sha = sha256_bytes(new_bytes)
    if new_sha == current_sha:
        return {"changed": False, **working_copy_status(library, profile_name)}

    old_bytes = old_text.encode("utf-8")
    next_book = deepcopy(book)
    next_tts = next_book.setdefault("tts_working_copy", {})
    next_tts["sha256"] = new_sha
    next_tts["revision"] = int(tts.get("revision") or 0) + 1
    next_tts["edited_at"] = _utc_now()
    next_tts["edited_by"] = "OWNER"
    # Any textual edit invalidates a previous exact-SHA acceptance.
    next_tts["manual_review"] = None

    _atomic_write_bytes(working_path, new_bytes)
    try:
        library.replace_book_profile(profile_name, next_book)
    except Exception as error:
        # Keep profile and bytes coherent if publishing metadata fails.
        _atomic_write_bytes(working_path, old_bytes)
        raise TTSTextReviewError(
            "working_copy_publish_failed",
            "Could not publish TTS working copy metadata; previous text was restored.",
        ) from error

    return {"changed": True, **working_copy_status(library, profile_name)}


def set_manual_review_required(
    library: BookLibrary, book_name: str, *, required: bool
) -> dict[str, Any]:
    profile_name, book, tts, _, _, working_sha = _working_context(library, book_name)
    next_book = deepcopy(book)
    next_tts = next_book.setdefault("tts_working_copy", {})
    next_tts["manual_review_required"] = bool(required)
    if required:
        review = next_tts.get("manual_review")
        if not isinstance(review, dict) or review.get("accepted_sha256") != working_sha:
            next_tts["manual_review"] = None
    library.replace_book_profile(profile_name, next_book)
    return working_copy_status(library, profile_name)


def accept_current_working_copy(library: BookLibrary, book_name: str) -> dict[str, Any]:
    profile_name, book, _, _, _, working_sha = _working_context(library, book_name)
    next_book = deepcopy(book)
    next_tts = next_book.setdefault("tts_working_copy", {})
    next_tts["manual_review"] = {
        "actor": "OWNER",
        "accepted_sha256": working_sha,
        "accepted_at": _utc_now(),
    }
    library.replace_book_profile(profile_name, next_book)
    return working_copy_status(library, profile_name)


def assert_manual_review_ready(library: BookLibrary, book_name: str) -> dict[str, Any]:
    status = working_copy_status(library, book_name)
    review = status["manual_review"]
    if not review["ready"]:
        raise TTSTextReviewError(
            "manual_text_acceptance_required",
            "Manual text acceptance is enabled and the exact current TTS working copy has not been accepted.",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "book_id": status["book_id"],
        "working_copy_sha256": status["working_copy_sha256"],
        "manual_review": review,
        **_offline_fields(),
    }


def _pronunciation_document(book: Mapping[str, Any]) -> dict[str, Any]:
    raw = book.get("pronunciation_overrides")
    if raw in (None, {}):
        return {"schema_version": PRONUNCIATION_SCHEMA_VERSION, "revision": 0, "entries": []}
    if not isinstance(raw, dict):
        raise TTSTextReviewError("pronunciation_invalid", "Pronunciation overlay must be an object.")
    if raw.get("schema_version") != PRONUNCIATION_SCHEMA_VERSION:
        raise TTSTextReviewError("pronunciation_invalid", "Unsupported pronunciation overlay schema.")
    revision = raw.get("revision")
    entries = raw.get("entries")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or not isinstance(entries, list):
        raise TTSTextReviewError("pronunciation_invalid", "Pronunciation overlay is malformed.")
    return {"schema_version": PRONUNCIATION_SCHEMA_VERSION, "revision": revision, "entries": entries}


def stress_candidates(word: str) -> list[dict[str, Any]]:
    if not isinstance(word, str) or not word.strip() or any(character.isspace() for character in word.strip()):
        raise TTSTextReviewError("invalid_pronunciation_word", "Select exactly one word for stress editing.")
    clean = unicodedata.normalize("NFC", word.strip())
    positions = [index for index, character in enumerate(clean) if character in _RUSSIAN_VOWELS]
    if not positions:
        raise TTSTextReviewError("no_vowels", "The selected word has no supported Russian vowel.")
    result: list[dict[str, Any]] = []
    for ordinal, character_index in enumerate(positions, start=1):
        canonical = clean[: character_index + 1] + "\u0301" + clean[character_index + 1 :]
        result.append(
            {
                "vowel_number": ordinal,
                "character_index": character_index,
                "display": unicodedata.normalize("NFC", canonical),
                "yandex": clean[:character_index] + "+" + clean[character_index:],
            }
        )
    return result


def provider_stress_preview(word: str, *, vowel_number: int, engine: str) -> dict[str, Any]:
    candidates = stress_candidates(word)
    candidate = next((item for item in candidates if item["vowel_number"] == vowel_number), None)
    if candidate is None:
        raise TTSTextReviewError("invalid_stress_choice", "Selected vowel number is outside the word.")
    normalized_engine = engine.strip().lower()
    if normalized_engine == "yandex":
        provider_mode = "TEXT_MARKUP"
        provider_value = candidate["yandex"]
        explanation = "SpeechKit: '+' is inserted immediately before the stressed vowel."
    elif normalized_engine == "openai":
        provider_mode = "INSTRUCTION"
        provider_value = (
            f"Произнеси слово «{word.strip()}» с ударением как «{candidate['display']}». "
            "Не меняй остальные слова фрагмента."
        )
        explanation = "OpenAI TTS: keep the canonical stress decision provider-neutral and render it as a pronunciation instruction."
    else:
        provider_mode = "CANONICAL_STRESS"
        provider_value = candidate["display"]
        explanation = "Provider adapter must translate the canonical stress decision before execution."
    return {
        "schema_version": SCHEMA_VERSION,
        "engine": normalized_engine,
        "word": word.strip(),
        "vowel_number": vowel_number,
        "display": candidate["display"],
        "provider_mode": provider_mode,
        "provider_value": provider_value,
        "explanation": explanation,
        **_offline_fields(),
    }


def add_pronunciation_override(
    library: BookLibrary,
    book_name: str,
    *,
    word: str,
    vowel_number: int,
    scope: str = "BOOK",
    start: int | None = None,
    end: int | None = None,
) -> dict[str, Any]:
    profile_name, book, _, _, working_text, working_sha = _working_context(library, book_name)
    normalized_scope = scope.strip().upper()
    if normalized_scope not in _ALLOWED_SCOPES:
        raise TTSTextReviewError("invalid_pronunciation_scope", "Pronunciation scope must be BOOK or OCCURRENCE.")
    preview = provider_stress_preview(word, vowel_number=vowel_number, engine="canonical")
    if normalized_scope == "OCCURRENCE":
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise TTSTextReviewError("invalid_pronunciation_offsets", "Occurrence scope requires start/end offsets.")
        if start < 0 or end <= start or end > len(working_text) or working_text[start:end] != word:
            raise TTSTextReviewError("pronunciation_text_mismatch", "Selected occurrence does not match the exact current text.")
    else:
        start = None
        end = None

    pronunciation = _pronunciation_document(book)
    normalized_word = unicodedata.normalize("NFKC", word).casefold()
    dedup_key = (normalized_scope, normalized_word, start, end, working_sha if normalized_scope == "OCCURRENCE" else None)
    for entry in pronunciation["entries"]:
        existing_key = (
            entry.get("scope"),
            unicodedata.normalize("NFKC", str(entry.get("word") or "")).casefold(),
            entry.get("start"),
            entry.get("end"),
            entry.get("text_sha256") if entry.get("scope") == "OCCURRENCE" else None,
        )
        if existing_key == dedup_key:
            return {"changed": False, "entry": entry, **working_copy_status(library, profile_name)}

    entry = {
        "override_id": f"PRON-{uuid.uuid4().hex[:20].upper()}",
        "scope": normalized_scope,
        "word": word,
        "vowel_number": vowel_number,
        "display": preview["display"],
        "start": start,
        "end": end,
        "text_sha256": working_sha if normalized_scope == "OCCURRENCE" else None,
        "created_at": _utc_now(),
        "actor": "OWNER",
    }
    next_book = deepcopy(book)
    next_book["pronunciation_overrides"] = {
        "schema_version": PRONUNCIATION_SCHEMA_VERSION,
        "revision": pronunciation["revision"] + 1,
        "entries": [*pronunciation["entries"], entry],
    }
    library.replace_book_profile(profile_name, next_book)
    result = working_copy_status(library, profile_name)
    return {"changed": True, "entry": entry, **result}


def pronunciation_fingerprint(book: Mapping[str, Any]) -> str:
    return _canonical_hash(_pronunciation_document(book))
