"""Provider rendering for owner-approved Audiobook Studio pronunciation rules.

The canonical book profile stores provider-neutral stress decisions. This module
turns BOOK-scoped decisions into exact provider input without mutating the
immutable source or the editable TTS working copy.

V1 deliberately fails closed on OCCURRENCE rules because prepared chapter/job
text does not yet retain canonical full-working-copy offsets. Ignoring such a
rule would be worse than refusing execution.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
_RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_COMBINING_ACUTE = "\u0301"


class PronunciationRenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _document(book: Mapping[str, Any]) -> dict[str, Any]:
    raw = book.get("pronunciation_overrides")
    if raw in (None, {}):
        return {"schema_version": SCHEMA_VERSION, "revision": 0, "entries": []}
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise PronunciationRenderError("pronunciation_invalid", "Pronunciation overlay schema is invalid.")
    revision = raw.get("revision")
    entries = raw.get("entries")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or not isinstance(entries, list):
        raise PronunciationRenderError("pronunciation_invalid", "Pronunciation overlay is malformed.")
    return {"schema_version": SCHEMA_VERSION, "revision": revision, "entries": entries}


def pronunciation_fingerprint(book: Mapping[str, Any]) -> str:
    return _canonical_hash(_document(book))


def _book_rules(book: Mapping[str, Any]) -> list[dict[str, Any]]:
    document = _document(book)
    result: list[dict[str, Any]] = []
    for raw in document["entries"]:
        if not isinstance(raw, dict):
            raise PronunciationRenderError("pronunciation_invalid", "Pronunciation entry is malformed.")
        scope = raw.get("scope")
        if scope == "OCCURRENCE":
            raise PronunciationRenderError(
                "occurrence_pronunciation_mapping_required",
                "Exact-occurrence pronunciation exists but prepared job offsets are not mapped in V1. Re-encode it as a BOOK rule before synthesis.",
            )
        if scope != "BOOK":
            raise PronunciationRenderError("pronunciation_invalid", f"Unsupported pronunciation scope: {scope!r}.")
        word = raw.get("word")
        vowel_number = raw.get("vowel_number")
        override_id = raw.get("override_id")
        if (
            not isinstance(word, str)
            or not word.strip()
            or any(character.isspace() for character in word.strip())
            or isinstance(vowel_number, bool)
            or not isinstance(vowel_number, int)
            or vowel_number <= 0
            or not isinstance(override_id, str)
            or not override_id
        ):
            raise PronunciationRenderError("pronunciation_invalid", "Pronunciation entry fields are invalid.")
        result.append(dict(raw))
    result.sort(key=lambda item: (unicodedata.normalize("NFKC", str(item["word"])).casefold(), str(item["override_id"])))
    return result


def _stress_character_index(word: str, vowel_number: int) -> int:
    positions = [index for index, character in enumerate(word) if character in _RUSSIAN_VOWELS]
    if vowel_number < 1 or vowel_number > len(positions):
        raise PronunciationRenderError(
            "pronunciation_vowel_out_of_range",
            f"Stored stress choice is outside word {word!r}.",
        )
    return positions[vowel_number - 1]


def _stress_display(word: str, vowel_number: int) -> str:
    index = _stress_character_index(word, vowel_number)
    return unicodedata.normalize("NFC", word[: index + 1] + _COMBINING_ACUTE + word[index + 1 :])


def _yandex_marked(word: str, vowel_number: int) -> str:
    index = _stress_character_index(word, vowel_number)
    return word[:index] + "+" + word[index:]


def _word_pattern(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE | re.UNICODE)


def _apply_yandex_rule(text: str, *, word: str, vowel_number: int) -> tuple[str, int]:
    pattern = _word_pattern(word)
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        replacements += 1
        return _yandex_marked(match.group(0), vowel_number)

    return pattern.sub(replace, text), replacements


def render_yandex_text(text: str, book: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise PronunciationRenderError("pronunciation_text_invalid", "Yandex pronunciation rendering requires non-empty text.")
    rendered = text
    applied: list[dict[str, Any]] = []
    for rule in _book_rules(book):
        rendered, count = _apply_yandex_rule(
            rendered,
            word=str(rule["word"]),
            vowel_number=int(rule["vowel_number"]),
        )
        if count:
            applied.append({
                "override_id": rule["override_id"],
                "word": rule["word"],
                "display": _stress_display(str(rule["word"]), int(rule["vowel_number"])),
                "matches": count,
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "yandex",
        "text": rendered,
        "raw_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "provider_text_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "pronunciation_fingerprint": pronunciation_fingerprint(book),
        "applied": applied,
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }


def openai_pronunciation_instructions(book: Mapping[str, Any]) -> dict[str, Any]:
    rules = _book_rules(book)
    lines: list[str] = []
    applied: list[dict[str, Any]] = []
    for rule in rules:
        word = str(rule["word"])
        display = _stress_display(word, int(rule["vowel_number"]))
        lines.append(f"Произноси слово «{word}» с ударением как «{display}».")
        applied.append({
            "override_id": rule["override_id"],
            "word": word,
            "display": display,
        })
    instructions = "\n".join(lines)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "openai",
        "instruction_suffix": instructions,
        "instructions_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        "pronunciation_fingerprint": pronunciation_fingerprint(book),
        "applied": applied,
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }


def effective_openai_profile(profile: Mapping[str, Any], instruction_suffix: str) -> dict[str, Any]:
    """Return a copy whose instructions are exact synthesis/fingerprint identity."""
    effective = dict(profile)
    suffix = instruction_suffix.strip()
    base = str(profile.get("instructions") or "").rstrip()
    effective["instructions"] = f"{base}\n\n{suffix}" if suffix else base
    return effective


def applied_override_ids(render: Mapping[str, Any]) -> Sequence[str]:
    applied = render.get("applied")
    if not isinstance(applied, list):
        return ()
    return tuple(
        str(item["override_id"])
        for item in applied
        if isinstance(item, Mapping) and isinstance(item.get("override_id"), str)
    )
