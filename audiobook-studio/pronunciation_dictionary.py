"""Private, offline, provider-neutral pronunciation dictionary for Studio.

The mutable dictionary is user data under ``AUDIOBOOK_STUDIO_HOME/settings``.
This module deliberately has no provider, model, billing, or network imports.
It stores canonical Unicode combining-acute pronunciations; provider-specific
rendering belongs to the backend adapters.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
CONTEXTUAL_REGISTRY_SCHEMA_VERSION = 1
DEFAULT_CONTEXTUAL_REGISTRY_PATH = Path(__file__).with_name("pronunciation-contextual-v1.json")
MODES = ("AUTO", "REVIEW_REQUIRED", "DISABLED")
SOURCES = ("STUDIO_CORRECTION", "MIGRATED_BOOK_RULE", "DICTIONARY_EDIT")
_COMBINING_ACUTE = "\u0301"
_RUSSIAN_VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_ENTRY_ID = re.compile(r"^PRON-GLOBAL-[A-Z0-9]{12,32}$")
_DOCUMENT_KEYS = {"schema_version", "revision", "entries"}
_ENTRY_KEYS = {
    "entry_id", "normalized_word", "word", "mode", "preferred", "variants",
    "actor", "source", "created_at", "updated_at",
}
_REQUIRED_ENTRY_KEYS = {
    "entry_id", "normalized_word", "word", "mode", "preferred", "variants",
    "actor", "created_at", "updated_at",
}
_VARIANT_KEYS = {"vowel_number", "display", "first_seen_at", "last_seen_at"}
_REQUIRED_VARIANT_KEYS = {"vowel_number", "display"}
_CONTEXTUAL_ENTRY_KEYS = {
    "normalized_word", "word", "variants", "source", "provenance",
}
_CONTEXTUAL_VARIANT_KEYS = {"vowel_number", "display", "meaning"}


class PronunciationDictionaryError(RuntimeError):
    """Fail-closed local dictionary error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_word(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return unicodedata.normalize(
        "NFC", "".join(character for character in decomposed if character != _COMBINING_ACUTE)
    )


def normalize_word(value: str) -> str:
    """Return the Unicode/case-insensitive dictionary identity for one word."""
    if not isinstance(value, str):
        raise PronunciationDictionaryError("invalid_word", "Pronunciation word must be text.")
    word = unicodedata.normalize("NFKC", _plain_word(value)).strip()
    if (
        not word
        or len(word) > 120
        or any(character.isspace() for character in word)
        or any(unicodedata.category(character).startswith("C") for character in word)
        or not any(character in _RUSSIAN_VOWELS for character in word)
    ):
        raise PronunciationDictionaryError(
            "invalid_word", "Pronunciation dictionary requires one word with a Russian vowel."
        )
    # Permit letters and normal intra-word hyphen/apostrophe characters only.
    if any(not (character.isalpha() or character in "-'’") for character in word):
        raise PronunciationDictionaryError("invalid_word", "Pronunciation word contains punctuation.")
    return unicodedata.normalize("NFC", word.casefold())


def _canonical_display(word: str, vowel_number: int) -> str:
    plain = unicodedata.normalize("NFC", _plain_word(word).strip())
    positions = [index for index, character in enumerate(plain) if character in _RUSSIAN_VOWELS]
    if (
        isinstance(vowel_number, bool)
        or not isinstance(vowel_number, int)
        or vowel_number < 1
        or vowel_number > len(positions)
    ):
        raise PronunciationDictionaryError(
            "invalid_vowel_number", "Stress vowel number is outside the selected word."
        )
    index = positions[vowel_number - 1]
    return unicodedata.normalize("NFC", plain[: index + 1] + _COMBINING_ACUTE + plain[index + 1 :])


def load_contextual_registry(
    path: Path | str = DEFAULT_CONTEXTUAL_REGISTRY_PATH,
) -> dict[str, dict[str, Any]]:
    """Load the small, versioned authority for words that always need context."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PronunciationDictionaryError(
            "contextual_registry_invalid", "Contextual pronunciation registry is unreadable."
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "entries"}
        or payload.get("schema_version") != CONTEXTUAL_REGISTRY_SCHEMA_VERSION
        or not isinstance(payload.get("entries"), list)
    ):
        raise PronunciationDictionaryError(
            "contextual_registry_invalid", "Contextual pronunciation registry schema is invalid."
        )
    result: dict[str, dict[str, Any]] = {}
    for raw in payload["entries"]:
        if not isinstance(raw, dict) or set(raw) != _CONTEXTUAL_ENTRY_KEYS:
            raise PronunciationDictionaryError(
                "contextual_registry_invalid", "Contextual pronunciation entry is invalid."
            )
        word = raw.get("word")
        normalized = raw.get("normalized_word")
        variants = raw.get("variants")
        if (
            not isinstance(word, str)
            or normalize_word(word) != normalized
            or normalized in result
            or not isinstance(raw.get("source"), str)
            or not raw["source"]
            or not isinstance(raw.get("provenance"), str)
            or not raw["provenance"]
            or not isinstance(variants, list)
            or len(variants) < 2
        ):
            raise PronunciationDictionaryError(
                "contextual_registry_invalid", "Contextual pronunciation entry is malformed."
            )
        seen: set[int] = set()
        clean_variants: list[dict[str, Any]] = []
        for variant in variants:
            if not isinstance(variant, dict) or set(variant) != _CONTEXTUAL_VARIANT_KEYS:
                raise PronunciationDictionaryError(
                    "contextual_registry_invalid", "Contextual pronunciation variant is invalid."
                )
            vowel_number = variant.get("vowel_number")
            display = variant.get("display")
            meaning = variant.get("meaning")
            if (
                isinstance(vowel_number, bool)
                or not isinstance(vowel_number, int)
                or vowel_number in seen
                or not isinstance(display, str)
                or unicodedata.normalize("NFC", display) != _canonical_display(word, vowel_number)
                or not isinstance(meaning, str)
                or not meaning
            ):
                raise PronunciationDictionaryError(
                    "contextual_registry_invalid", "Contextual pronunciation variant is malformed."
                )
            seen.add(vowel_number)
            clean_variants.append({
                "vowel_number": vowel_number,
                "display": unicodedata.normalize("NFC", display),
                "meaning": meaning,
            })
        result[normalized] = {**deepcopy(raw), "variants": clean_variants}
    return result


def _validate_timestamp(value: Any, *, field: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PronunciationDictionaryError("schema_invalid", f"Invalid {field}.")


def _validate_variant(raw: Any, *, word: str) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or set(raw) - _VARIANT_KEYS
        or not _REQUIRED_VARIANT_KEYS.issubset(raw)
    ):
        raise PronunciationDictionaryError("schema_invalid", "Invalid pronunciation variant.")
    number = raw.get("vowel_number")
    display = raw.get("display")
    if not isinstance(display, str) or not display:
        raise PronunciationDictionaryError("schema_invalid", "Pronunciation display is required.")
    try:
        expected = _canonical_display(word, number)
    except PronunciationDictionaryError as error:
        raise PronunciationDictionaryError("schema_invalid", "Invalid variant vowel number.") from error
    if unicodedata.normalize("NFC", display) != expected:
        raise PronunciationDictionaryError(
            "schema_invalid", "Pronunciation display does not match word/vowel_number."
        )
    if "first_seen_at" in raw:
        _validate_timestamp(raw["first_seen_at"], field="first_seen_at", nullable=True)
    if "last_seen_at" in raw:
        _validate_timestamp(raw["last_seen_at"], field="last_seen_at", nullable=True)
    return raw


def validate_dictionary_document(payload: Any) -> dict[str, Any]:
    """Dependency-free strict implementation of the vendored schema-v1 boundary."""
    if not isinstance(payload, dict):
        raise PronunciationDictionaryError("schema_invalid", "Dictionary fields do not match schema v1.")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        code = (
            "schema_upgrade_required"
            if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION
            else "schema_invalid"
        )
        raise PronunciationDictionaryError(code, f"Unsupported dictionary schema_version: {version!r}.")
    if set(payload) != _DOCUMENT_KEYS:
        raise PronunciationDictionaryError("schema_invalid", "Dictionary fields do not match schema v1.")
    revision = payload.get("revision")
    entries = payload.get("entries")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise PronunciationDictionaryError("schema_invalid", "Dictionary revision must be non-negative.")
    if not isinstance(entries, list):
        raise PronunciationDictionaryError("schema_invalid", "Dictionary entries must be an array.")

    seen_ids: set[str] = set()
    seen_words: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) - _ENTRY_KEYS
            or not _REQUIRED_ENTRY_KEYS.issubset(entry)
        ):
            raise PronunciationDictionaryError("schema_invalid", "Invalid dictionary entry.")
        entry_id = entry.get("entry_id")
        word = entry.get("word")
        normalized = entry.get("normalized_word")
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise PronunciationDictionaryError("schema_invalid", "Invalid pronunciation entry_id.")
        if entry_id in seen_ids:
            raise PronunciationDictionaryError("schema_invalid", "Duplicate pronunciation entry_id.")
        seen_ids.add(entry_id)
        if not isinstance(word, str) or normalize_word(word) != normalized:
            raise PronunciationDictionaryError("schema_invalid", "Invalid normalized pronunciation word.")
        if normalized in seen_words:
            raise PronunciationDictionaryError("schema_invalid", "Duplicate normalized pronunciation word.")
        seen_words.add(normalized)
        if entry.get("mode") not in MODES or entry.get("actor") != "OWNER":
            raise PronunciationDictionaryError("schema_invalid", "Invalid pronunciation entry mode/actor.")
        if "source" in entry and entry["source"] not in SOURCES:
            raise PronunciationDictionaryError("schema_invalid", "Invalid pronunciation source.")
        _validate_timestamp(entry.get("created_at"), field="created_at")
        _validate_timestamp(entry.get("updated_at"), field="updated_at")
        variants = entry.get("variants")
        if not isinstance(variants, list) or not variants:
            raise PronunciationDictionaryError("schema_invalid", "Pronunciation variants cannot be empty.")
        variant_keys: set[tuple[int, str]] = set()
        for variant in variants:
            _validate_variant(variant, word=word)
            key = (variant["vowel_number"], unicodedata.normalize("NFC", variant["display"]))
            if key in variant_keys:
                raise PronunciationDictionaryError("schema_invalid", "Duplicate pronunciation variant.")
            variant_keys.add(key)
        preferred = entry.get("preferred")
        if preferred is not None:
            _validate_variant(preferred, word=word)
            preferred_key = (
                preferred["vowel_number"], unicodedata.normalize("NFC", preferred["display"])
            )
            if preferred_key not in variant_keys:
                raise PronunciationDictionaryError("schema_invalid", "Preferred variant is not in variants.")
        if entry["mode"] == "AUTO" and preferred is None:
            raise PronunciationDictionaryError("schema_invalid", "AUTO pronunciation requires preferred.")
        if entry["mode"] == "REVIEW_REQUIRED" and preferred is not None:
            raise PronunciationDictionaryError(
                "schema_invalid", "REVIEW_REQUIRED pronunciation cannot be applied globally."
            )
    return payload


def _empty_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "entries": []}


def _assert_workspace_root(root: Path) -> Path:
    absolute = Path(os.path.abspath(os.path.expanduser(str(root))))
    try:
        metadata = absolute.lstat()
    except OSError as error:
        raise PronunciationDictionaryError("workspace_missing", "Workspace root does not exist.") from error
    if absolute.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise PronunciationDictionaryError("unsafe_workspace_path", "Workspace root must be a real directory.")
    return absolute


def _ensure_private_directory(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise PronunciationDictionaryError("unsafe_dictionary_path", "Dictionary escaped workspace.") from error
    current = root
    for component in relative.parts:
        current = current / component
        if current.exists() or current.is_symlink():
            try:
                metadata = current.lstat()
            except OSError as error:
                raise PronunciationDictionaryError("unsafe_dictionary_path", "Unsafe dictionary directory.") from error
            if current.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise PronunciationDictionaryError(
                    "unsafe_dictionary_path", "Dictionary path component is not a real directory."
                )
        else:
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                # Another Studio process may have created the same private
                # component between lstat and mkdir; inspect it below rather
                # than turning safe concurrent initialization into failure.
                try:
                    metadata = current.lstat()
                except OSError as error:
                    raise PronunciationDictionaryError(
                        "unsafe_dictionary_path", "Unsafe dictionary directory."
                    ) from error
                if current.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                    raise PronunciationDictionaryError(
                        "unsafe_dictionary_path", "Dictionary path component is not a real directory."
                    )
            except OSError as error:
                raise PronunciationDictionaryError("dictionary_unavailable", "Cannot create dictionary directory.") from error
        try:
            os.chmod(current, 0o700)
        except OSError as error:
            raise PronunciationDictionaryError("dictionary_unavailable", "Cannot secure dictionary directory.") from error


def _assert_private_file(path: Path, *, missing_ok: bool) -> None:
    if not (path.exists() or path.is_symlink()):
        if missing_ok:
            return
        raise PronunciationDictionaryError("dictionary_missing", "Dictionary file is missing.")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise PronunciationDictionaryError("dictionary_unavailable", "Cannot inspect dictionary file.") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise PronunciationDictionaryError("unsafe_dictionary_path", "Dictionary file must be regular.")


@contextmanager
def _advisory_lock(root: Path, lock_path: Path):
    _ensure_private_directory(root, lock_path.parent)
    _assert_private_file(lock_path, missing_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise PronunciationDictionaryError("unsafe_lock_path", "Cannot open dictionary lock safely.") from error
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        # fdopen owns descriptor after successful construction.
        raise


def _atomic_write_json(root: Path, path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_directory(root, path.parent)
    _assert_private_file(path, missing_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _assert_private_file(path, missing_ok=True)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _word_pattern(word: str) -> re.Pattern[str]:
    pieces: list[str] = []
    for character in unicodedata.normalize("NFC", _plain_word(word)):
        pieces.append(re.escape(character))
        if character in _RUSSIAN_VOWELS:
            pieces.append(f"{_COMBINING_ACUTE}?")
    return re.compile(rf"(?<!\w){''.join(pieces)}(?!\w)", re.IGNORECASE | re.UNICODE)


class PronunciationDictionary:
    """Cross-process safe schema-v1 dictionary rooted in one Studio workspace."""

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        contextual_registry_path: Path | str = DEFAULT_CONTEXTUAL_REGISTRY_PATH,
    ) -> None:
        self.workspace_root = _assert_workspace_root(Path(workspace_root))
        self.path = self.workspace_root / "settings" / "pronunciation" / "user-dictionary-v1.json"
        self.lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        self.contextual_registry_path = Path(contextual_registry_path)

    def contextual_registry(self) -> dict[str, dict[str, Any]]:
        return load_contextual_registry(self.contextual_registry_path)

    def is_contextual_word(self, word: str) -> bool:
        return normalize_word(word) in self.contextual_registry()

    @staticmethod
    def _contextual_variants(
        contextual: Mapping[str, Any],
        *,
        word: str,
        now: str,
        selected_vowel_number: int | None = None,
        existing: Iterable[Mapping[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        by_number = {
            variant.get("vowel_number"): deepcopy(variant)
            for variant in existing
            if isinstance(variant, Mapping)
        }
        result: list[dict[str, Any]] = []
        for authority in contextual["variants"]:
            vowel_number = authority["vowel_number"]
            stored = by_number.get(vowel_number, {})
            first_seen = stored.get("first_seen_at")
            last_seen = stored.get("last_seen_at")
            if vowel_number == selected_vowel_number and first_seen is None:
                first_seen = now
                last_seen = now
            result.append({
                "vowel_number": vowel_number,
                "display": _canonical_display(word, vowel_number),
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
            })
        return result

    def _load_unlocked(self) -> dict[str, Any]:
        _ensure_private_directory(self.workspace_root, self.path.parent)
        if not (self.path.exists() or self.path.is_symlink()):
            return _empty_document()
        _assert_private_file(self.path, missing_ok=False)
        try:
            raw = self.path.read_bytes()
            payload = json.loads(raw.decode("utf-8", errors="strict"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PronunciationDictionaryError(
                "dictionary_corrupt", "Pronunciation dictionary is unreadable; mutation is blocked."
            ) from error
        try:
            return validate_dictionary_document(payload)
        except PronunciationDictionaryError as error:
            if error.code == "schema_upgrade_required":
                raise
            raise PronunciationDictionaryError(
                "dictionary_schema_invalid", "Pronunciation dictionary is invalid; mutation is blocked."
            ) from error

    def _result(self, document: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
        return {
            **fields,
            "revision": document["revision"],
            **_offline_fields(),
        }

    def snapshot(self) -> dict[str, Any]:
        document = self._load_unlocked()
        return {
            **deepcopy(document),
            "path": str(self.path),
            "exists": self.path.exists(),
            "sha256": _sha256_file(self.path) if self.path.exists() else _canonical_hash(document),
            "auto_entry_count": sum(entry["mode"] == "AUTO" for entry in document["entries"]),
            **_offline_fields(),
        }

    def ensure_created(self) -> dict[str, Any]:
        """Atomically publish an empty private store only when none exists.

        An existing document is validated but never rewritten, including the
        fail-closed corrupt/higher-schema cases handled by ``_load_unlocked``.
        """
        with _advisory_lock(self.workspace_root, self.lock_path):
            existed = self.path.exists() or self.path.is_symlink()
            document = self._load_unlocked()
            if existed:
                return self._result(
                    document,
                    created=False,
                    path=str(self.path),
                    exists=True,
                    sha256=_sha256_file(self.path),
                )
            _atomic_write_json(self.workspace_root, self.path, document)
            return self._result(
                document,
                created=True,
                path=str(self.path),
                exists=True,
                sha256=_sha256_file(self.path),
            )

    def auto_entries(self) -> list[dict[str, Any]]:
        return [
            deepcopy(entry) for entry in self._load_unlocked()["entries"] if entry["mode"] == "AUTO"
        ]

    def repair_known_contextual_entries(self) -> dict[str, Any]:
        """Downgrade legacy AUTO homographs without touching book evidence/text."""
        contextual_registry = self.contextual_registry()
        with _advisory_lock(self.workspace_root, self.lock_path):
            document = self._load_unlocked()
            entries = deepcopy(document["entries"])
            repaired: list[str] = []
            now = _utc_now()
            for entry in entries:
                contextual = contextual_registry.get(entry["normalized_word"])
                if contextual is None:
                    continue
                reconciled = self._contextual_variants(
                    contextual,
                    word=entry["word"],
                    now=now,
                    existing=entry["variants"],
                )
                changed = reconciled != entry["variants"]
                entry["variants"] = reconciled
                if entry["mode"] == "AUTO":
                    entry["mode"] = "REVIEW_REQUIRED"
                    entry["preferred"] = None
                    changed = True
                if changed:
                    entry["updated_at"] = now
                    entry["source"] = "MIGRATED_BOOK_RULE"
                    repaired.append(entry["normalized_word"])
            if not repaired:
                return self._result(document, changed=False, repaired_words=[])
            next_document = {
                **document,
                "revision": document["revision"] + 1,
                "entries": entries,
            }
            validate_dictionary_document(next_document)
            _atomic_write_json(self.workspace_root, self.path, next_document)
            return self._result(
                next_document,
                changed=True,
                repaired_words=repaired,
            )

    def upsert(
        self,
        word: str,
        vowel_number: int,
        display: str,
        source: str = "STUDIO_CORRECTION",
    ) -> dict[str, Any]:
        normalized = normalize_word(word)
        canonical_word = unicodedata.normalize("NFC", _plain_word(word).strip())
        if source not in SOURCES:
            raise PronunciationDictionaryError("invalid_source", "Unsupported pronunciation source.")
        expected_display = _canonical_display(canonical_word, vowel_number)
        if not isinstance(display, str) or unicodedata.normalize("NFC", display) != expected_display:
            raise PronunciationDictionaryError(
                "invalid_display", "Display must be the canonical acute form for word/vowel_number."
            )
        with _advisory_lock(self.workspace_root, self.lock_path):
            document = self._load_unlocked()
            contextual = self.contextual_registry().get(normalized)
            if contextual is not None and vowel_number not in {
                variant["vowel_number"] for variant in contextual["variants"]
            }:
                raise PronunciationDictionaryError(
                    "contextual_variant_not_allowed",
                    "Selected pronunciation is not an allowed contextual variant.",
                )
            existing = next(
                (entry for entry in document["entries"] if entry["normalized_word"] == normalized), None
            )
            now = _utc_now()
            if existing is None:
                variant = {
                    "vowel_number": vowel_number,
                    "display": expected_display,
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
                entry = {
                    "entry_id": f"PRON-GLOBAL-{uuid.uuid4().hex[:20].upper()}",
                    "normalized_word": normalized,
                    "word": canonical_word,
                    "mode": "REVIEW_REQUIRED" if contextual is not None else "AUTO",
                    "preferred": None if contextual is not None else deepcopy(variant),
                    "variants": (
                        self._contextual_variants(
                            contextual,
                            word=canonical_word,
                            now=now,
                            selected_vowel_number=vowel_number,
                        )
                        if contextual is not None
                        else [variant]
                    ),
                    "actor": "OWNER",
                    "source": source,
                    "created_at": now,
                    "updated_at": now,
                }
                next_document = {
                    **document,
                    "revision": document["revision"] + 1,
                    "entries": [*document["entries"], entry],
                }
                validate_dictionary_document(next_document)
                _atomic_write_json(self.workspace_root, self.path, next_document)
                return self._result(
                    next_document,
                    changed=True,
                    conflict=contextual is not None,
                    contextual=contextual is not None,
                    entry=deepcopy(entry),
                )

            entry = deepcopy(existing)
            if contextual is not None:
                reconciled = self._contextual_variants(
                    contextual,
                    word=entry["word"],
                    now=now,
                    selected_vowel_number=vowel_number,
                    existing=entry["variants"],
                )
                changed = reconciled != entry["variants"]
                entry["variants"] = reconciled
                if entry["mode"] != "REVIEW_REQUIRED" or entry["preferred"] is not None:
                    entry["mode"] = "REVIEW_REQUIRED"
                    entry["preferred"] = None
                    changed = True
                if not changed:
                    return self._result(
                        document,
                        changed=False,
                        conflict=True,
                        contextual=True,
                        entry=entry,
                    )
                entry.update({"source": source, "updated_at": now})
                entries = [
                    entry if item["entry_id"] == entry["entry_id"] else item
                    for item in document["entries"]
                ]
                next_document = {
                    **document,
                    "revision": document["revision"] + 1,
                    "entries": entries,
                }
                validate_dictionary_document(next_document)
                _atomic_write_json(self.workspace_root, self.path, next_document)
                return self._result(
                    next_document,
                    changed=True,
                    conflict=True,
                    contextual=True,
                    entry=deepcopy(entry),
                )
            stored_display = _canonical_display(str(entry["word"]), vowel_number)
            matching = next(
                (variant for variant in entry["variants"] if variant["vowel_number"] == vowel_number),
                None,
            )
            if matching is not None and entry["mode"] != "DISABLED":
                return self._result(document, changed=False, conflict=entry["mode"] == "REVIEW_REQUIRED", entry=entry)
            if matching is None:
                entry["variants"].append({
                    "vowel_number": vowel_number,
                    "display": stored_display,
                    "first_seen_at": now,
                    "last_seen_at": now,
                })
                entry["mode"] = "REVIEW_REQUIRED"
                entry["preferred"] = None
                conflict = True
            else:
                matching["last_seen_at"] = now
                if len(entry["variants"]) == 1:
                    entry["mode"] = "AUTO"
                    entry["preferred"] = deepcopy(matching)
                    conflict = False
                else:
                    entry["mode"] = "REVIEW_REQUIRED"
                    entry["preferred"] = None
                    conflict = True
            # ``normalized_word`` is case-insensitive, while the entry's first
            # owner spelling is stable display metadata.  A later upsert with
            # different casing must not make older variants schema-invalid.
            entry.update({"source": source, "updated_at": now})
            entries = [entry if item["entry_id"] == entry["entry_id"] else item for item in document["entries"]]
            next_document = {**document, "revision": document["revision"] + 1, "entries": entries}
            validate_dictionary_document(next_document)
            _atomic_write_json(self.workspace_root, self.path, next_document)
            return self._result(next_document, changed=True, conflict=conflict, entry=deepcopy(entry))

    def _mutate_entry(self, entry_id: str, mutation) -> dict[str, Any]:
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise PronunciationDictionaryError("invalid_entry_id", "Invalid pronunciation entry_id.")
        with _advisory_lock(self.workspace_root, self.lock_path):
            document = self._load_unlocked()
            index = next(
                (index for index, entry in enumerate(document["entries"]) if entry["entry_id"] == entry_id),
                None,
            )
            if index is None:
                raise PronunciationDictionaryError("entry_not_found", f"Pronunciation entry not found: {entry_id}")
            entry = deepcopy(document["entries"][index])
            changed = bool(mutation(entry))
            if not changed:
                return self._result(document, changed=False, entry=entry)
            entry["updated_at"] = _utc_now()
            entry["source"] = "DICTIONARY_EDIT"
            entries = list(document["entries"])
            entries[index] = entry
            next_document = {**document, "revision": document["revision"] + 1, "entries": entries}
            validate_dictionary_document(next_document)
            _atomic_write_json(self.workspace_root, self.path, next_document)
            return self._result(next_document, changed=True, entry=deepcopy(entry))

    def set_preferred(self, entry_id: str, vowel_number: int) -> dict[str, Any]:
        def mutation(entry: dict[str, Any]) -> bool:
            variant = next(
                (item for item in entry["variants"] if item["vowel_number"] == vowel_number), None
            )
            if variant is None:
                raise PronunciationDictionaryError(
                    "variant_not_found", "Preferred vowel number is not a saved variant."
                )
            if entry["mode"] == "AUTO" and entry["preferred"] == variant:
                return False
            entry["mode"] = "AUTO"
            entry["preferred"] = deepcopy(variant)
            return True

        return self._mutate_entry(entry_id, mutation)

    def disable(self, entry_id: str) -> dict[str, Any]:
        def mutation(entry: dict[str, Any]) -> bool:
            if entry["mode"] == "DISABLED":
                return False
            entry["mode"] = "DISABLED"
            return True

        return self._mutate_entry(entry_id, mutation)

    def delete(self, entry_id: str) -> dict[str, Any]:
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise PronunciationDictionaryError("invalid_entry_id", "Invalid pronunciation entry_id.")
        with _advisory_lock(self.workspace_root, self.lock_path):
            document = self._load_unlocked()
            retained = [entry for entry in document["entries"] if entry["entry_id"] != entry_id]
            if len(retained) == len(document["entries"]):
                raise PronunciationDictionaryError("entry_not_found", f"Pronunciation entry not found: {entry_id}")
            next_document = {
                **document, "revision": document["revision"] + 1, "entries": retained
            }
            validate_dictionary_document(next_document)
            _atomic_write_json(self.workspace_root, self.path, next_document)
            return self._result(next_document, changed=True, entry_id=entry_id, deleted=True)


def apply_auto_pronunciations(
    text: str,
    entries: Iterable[Mapping[str, Any]],
    book_entries: Iterable[Mapping[str, Any]] = (),
    *,
    working_copy_sha256: str = "",
) -> str:
    """Materialize AUTO entries while preserving higher-priority book choices.

    BOOK overrides exclude the whole matching word from global replacement.
    OCCURRENCE overrides exclude only their exact original-text interval.  All
    replacements are calculated against one normalized snapshot and applied in
    reverse order, so offset shifts cannot bypass an occurrence override.
    """
    if not isinstance(text, str):
        raise PronunciationDictionaryError("invalid_text", "Pronunciation text must be Unicode text.")
    working = unicodedata.normalize("NFC", text)
    book_words: set[str] = set()
    occurrence_ranges: list[tuple[int, int]] = []
    for raw in book_entries:
        if not isinstance(raw, Mapping):
            continue
        try:
            normalized = normalize_word(str(raw.get("word") or ""))
        except PronunciationDictionaryError:
            continue
        scope = str(raw.get("scope") or "").upper()
        if scope == "BOOK":
            book_words.add(normalized)
        elif scope == "OCCURRENCE":
            start, end = raw.get("start"), raw.get("end")
            if (
                working_copy_sha256
                and raw.get("text_sha256") == working_copy_sha256
                and isinstance(start, int) and not isinstance(start, bool)
                and isinstance(end, int) and not isinstance(end, bool)
                and 0 <= start < end <= len(working)
                and normalize_word(_plain_word(working[start:end])) == normalized
            ):
                occurrence_ranges.append((start, end))

    replacements: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("mode") != "AUTO":
            continue
        word = str(entry.get("word") or "")
        normalized = normalize_word(word)
        if normalized in book_words:
            continue
        preferred = entry.get("preferred")
        if not isinstance(preferred, Mapping):
            raise PronunciationDictionaryError("schema_invalid", "AUTO entry has no preferred variant.")
        vowel_number = preferred.get("vowel_number")
        for match in _word_pattern(word).finditer(working):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occurrence_ranges + occupied):
                continue
            replacement = _canonical_display(match.group(0), vowel_number)
            if replacement != match.group(0):
                replacements.append((span[0], span[1], replacement))
                occupied.append(span)
    for start, end, replacement in sorted(replacements, reverse=True):
        working = working[:start] + replacement + working[end:]
    return unicodedata.normalize("NFC", working)


def contextual_review_items(
    text: str,
    book_entries: Iterable[Mapping[str, Any]] = (),
    *,
    working_copy_sha256: str = "",
    registry_path: Path | str = DEFAULT_CONTEXTUAL_REGISTRY_PATH,
) -> list[dict[str, Any]]:
    """Return unresolved plain contextual-word occurrences for native review.

    BOOK decisions resolve every matching occurrence. OCCURRENCE decisions
    resolve only their exact current range. An already accented token is not
    surfaced as plain unresolved text, while the persisted override remains
    the authority used by provider preparation.
    """
    if not isinstance(text, str):
        raise PronunciationDictionaryError("invalid_text", "Pronunciation text must be Unicode text.")
    registry = load_contextual_registry(registry_path)
    book_words: set[str] = set()
    occurrence_ranges: list[tuple[str, int, int]] = []
    for raw in book_entries:
        if not isinstance(raw, Mapping):
            continue
        try:
            normalized = normalize_word(str(raw.get("word") or ""))
        except PronunciationDictionaryError:
            continue
        scope = str(raw.get("scope") or "").upper()
        if scope == "BOOK":
            book_words.add(normalized)
        elif scope == "OCCURRENCE":
            start, end = raw.get("start"), raw.get("end")
            if (
                isinstance(working_copy_sha256, str)
                and working_copy_sha256
                and raw.get("text_sha256") == working_copy_sha256
                and isinstance(start, int) and not isinstance(start, bool)
                and isinstance(end, int) and not isinstance(end, bool)
                and 0 <= start < end <= len(text)
            ):
                occurrence_ranges.append((normalized, start, end))

    items: list[dict[str, Any]] = []
    for normalized, contextual in registry.items():
        if normalized in book_words:
            continue
        for match in _word_pattern(str(contextual["word"])).finditer(text):
            start, end = match.span()
            if _COMBINING_ACUTE in match.group(0):
                continue
            if any(
                item_word == normalized and item_start == start and item_end == end
                for item_word, item_start, item_end in occurrence_ranges
            ):
                continue
            items.append({
                "item_id": f"CONTEXT-{normalized}-{start}-{end}",
                "normalized_word": normalized,
                "word": match.group(0),
                "start": start,
                "end": end,
                "context": _contextual_snippet(text, start, end),
                "variants": deepcopy(contextual["variants"]),
            })
    return sorted(items, key=lambda item: (item["start"], item["normalized_word"]))


def _contextual_snippet(text: str, start: int, end: int, radius: int = 48) -> str:
    """Show a readable sentence fragment without beginning or ending mid-word."""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = ""
    suffix = ""
    if left > 0:
        boundary = next((index for index in range(left, start) if text[index].isspace()), start)
        left = min(boundary + 1, start)
        prefix = "… "
    if right < len(text):
        boundary = next((index for index in range(right - 1, end - 1, -1) if text[index].isspace()), end)
        right = max(boundary, end)
        suffix = " …"
    fragment = " ".join(text[left:right].split())
    return f"{prefix}{fragment}{suffix}"


def _workspace_from_library(library: Any) -> Path:
    books_root = Path(library.books_root)
    if books_root.name == "books" and books_root.parent.name == "studio-workspace" and books_root.parent.parent.name == "runtime":
        return books_root.parent.parent.parent
    return books_root.parent


def migrate_book_rules(
    library: Any,
    dictionary: PronunciationDictionary | None = None,
) -> dict[str, Any]:
    """Idempotently import valid owner-created BOOK rules from all book profiles."""
    store = dictionary or PronunciationDictionary(_workspace_from_library(library))
    contextual_repair = store.repair_known_contextual_entries()
    considered = 0
    changed = 0
    conflicts = 0
    conflict_words: set[str] = set()
    for profile in library.list_book_profiles():
        try:
            book = library.load_book_profile(profile.name, allow_disabled=True)
        except Exception:
            continue
        document = book.get("pronunciation_overrides")
        if not isinstance(document, Mapping) or document.get("schema_version") != 1:
            continue
        raw_entries = document.get("entries")
        if not isinstance(raw_entries, list):
            continue
        for entry in raw_entries:
            if (
                not isinstance(entry, Mapping)
                or entry.get("scope") != "BOOK"
                or entry.get("actor") != "OWNER"
            ):
                continue
            try:
                result = store.upsert(
                    str(entry.get("word") or ""),
                    entry.get("vowel_number"),
                    str(entry.get("display") or ""),
                    source="MIGRATED_BOOK_RULE",
                )
            except PronunciationDictionaryError:
                continue
            considered += 1
            changed += int(bool(result["changed"]))
            normalized = normalize_word(str(entry.get("word") or ""))
            if result.get("conflict") and result["changed"] and normalized not in conflict_words:
                conflicts += 1
                conflict_words.add(normalized)
    return {
        "schema_version": 1,
        "contextual_repair_changed": bool(contextual_repair["changed"]),
        "contextual_repaired_words": contextual_repair["repaired_words"],
        "considered_book_rules": considered,
        "changed_entries": changed,
        "conflicts_created": conflicts,
        "dictionary_revision": store.snapshot()["revision"],
        **_offline_fields(),
    }
