"""Offline shared Content Quality Lexicon for Audiobook Studio.

The shared mutable store is intentionally app-neutral and contains only USER
rules. Audiobook Studio vendors the shared v1 schema/core pack, adds an
Audiobook-only TTS technical overlay, and never contacts BOOK OS, GitHub, a
model, a provider, or billing at runtime.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
CONTRACT_VERSION = "1"
CONTRACT_DRAFT_SOURCE_REPO = "niknikdym-hue/book-os"
CONTRACT_DRAFT_SOURCE_PR = 21
CONTRACT_DRAFT_SOURCE_HEAD = "95ec3d05c14372c9178d75ae980314f1e2ca18ca"

PROFILE_BOOK_PROSE = "BOOK_PROSE"
PROFILE_AUDIOBOOK_PRE_SYNTHESIS = "AUDIOBOOK_PRE_SYNTHESIS"
PROFILE_AUDIOBOOK_TTS_TECHNICAL = "AUDIOBOOK_TTS_TECHNICAL"
PROFILES = (
    PROFILE_BOOK_PROSE,
    PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
    PROFILE_AUDIOBOOK_TTS_TECHNICAL,
)
MATCH_TYPES = ("PHRASE", "TERM", "REGEX")
ACTIONS = ("BLOCK", "WARN", "ALLOW")
ORIGINS = ("SYSTEM", "USER")
DEFAULT_EDITORIAL_PROFILES = (PROFILE_BOOK_PROSE, PROFILE_AUDIOBOOK_PRE_SYNTHESIS)

STUDIO_DIR = Path(__file__).resolve().parent
CONTRACTS_DIR = STUDIO_DIR / "contracts"
SCHEMA_PATH = CONTRACTS_DIR / "content-quality-lexicon-v1.schema.json"
CORE_PATH = CONTRACTS_DIR / "content-quality-core-ru-v1.json"
TECHNICAL_PATH = CONTRACTS_DIR / "audiobook-tts-technical-v1.json"
DEFAULT_USER_STORE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "ContentQualityLexicon"
    / "user-rules-v1.json"
)

_DOCUMENT_KEYS = {"schema_version", "revision", "updated_at", "entries"}
_REQUIRED_DOCUMENT_KEYS = {"schema_version", "revision", "entries"}
_ENTRY_KEYS = {
    "rule_id",
    "value",
    "match_type",
    "action",
    "profiles",
    "origin",
    "rationale",
    "created_at",
    "updated_at",
}
_REQUIRED_ENTRY_KEYS = {
    "rule_id",
    "value",
    "match_type",
    "action",
    "profiles",
    "origin",
}


class ContentQualityError(RuntimeError):
    """Fail-closed local Content Quality error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_rule_value(value: str) -> str:
    if not isinstance(value, str):
        raise ContentQualityError("invalid_rule_value", "Rule value must be text.")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise ContentQualityError("invalid_rule_value", "Rule value cannot be empty.")
    return normalized


def _validate_optional_text(value: Any, *, field: str, maximum: int) -> None:
    if value is not None and (not isinstance(value, str) or len(value) > maximum):
        raise ContentQualityError("schema_invalid", f"Invalid {field}.")


def validate_lexicon_document(
    payload: Any,
    *,
    user_store: bool = False,
    expected_origin: str | None = None,
) -> dict[str, Any]:
    """Validate the complete schema-v1 interoperability boundary without deps.

    The vendored JSON Schema is the published contract; this strict validator is
    its dependency-free runtime implementation for schema_version=1.
    """
    if not isinstance(payload, dict):
        raise ContentQualityError("schema_invalid", "Lexicon document must be an object.")
    if set(payload) - _DOCUMENT_KEYS or not _REQUIRED_DOCUMENT_KEYS.issubset(payload):
        raise ContentQualityError("schema_invalid", "Lexicon document fields do not match v1 schema.")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        code = "schema_upgrade_required" if isinstance(version, int) and version > SCHEMA_VERSION else "schema_invalid"
        raise ContentQualityError(code, f"Unsupported lexicon schema_version: {version!r}.")
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ContentQualityError("schema_invalid", "Lexicon revision must be a non-negative integer.")
    _validate_optional_text(payload.get("updated_at"), field="updated_at", maximum=256)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ContentQualityError("schema_invalid", "Lexicon entries must be an array.")

    seen_ids: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise ContentQualityError("schema_invalid", "Each lexicon entry must be an object.")
        if set(raw) - _ENTRY_KEYS or not _REQUIRED_ENTRY_KEYS.issubset(raw):
            raise ContentQualityError("schema_invalid", "Lexicon entry fields do not match v1 schema.")
        rule_id = raw.get("rule_id")
        value = raw.get("value")
        match_type = raw.get("match_type")
        action = raw.get("action")
        profiles = raw.get("profiles")
        origin = raw.get("origin")
        if not isinstance(rule_id, str) or not 1 <= len(rule_id) <= 96:
            raise ContentQualityError("schema_invalid", "Invalid rule_id.")
        if rule_id in seen_ids:
            raise ContentQualityError("schema_invalid", f"Duplicate rule_id: {rule_id}")
        seen_ids.add(rule_id)
        if not isinstance(value, str) or not 1 <= len(value) <= 1000:
            raise ContentQualityError("schema_invalid", f"Invalid rule value for {rule_id}.")
        if match_type not in MATCH_TYPES or action not in ACTIONS or origin not in ORIGINS:
            raise ContentQualityError("schema_invalid", f"Invalid rule enum for {rule_id}.")
        if (
            not isinstance(profiles, list)
            or not profiles
            or len(profiles) != len(set(profiles))
            or any(profile not in PROFILES for profile in profiles)
        ):
            raise ContentQualityError("schema_invalid", f"Invalid profiles for {rule_id}.")
        _validate_optional_text(raw.get("rationale"), field="rationale", maximum=2000)
        _validate_optional_text(raw.get("created_at"), field="created_at", maximum=256)
        _validate_optional_text(raw.get("updated_at"), field="updated_at", maximum=256)
        if expected_origin is not None and origin != expected_origin:
            raise ContentQualityError("schema_invalid", f"Unexpected origin for {rule_id}.")
        if user_store and origin != "USER":
            raise ContentQualityError("schema_invalid", "Shared mutable store may contain only USER rules.")
        if user_store and match_type == "REGEX":
            raise ContentQualityError("user_regex_forbidden", "User-defined REGEX is forbidden in schema v1.")
    return payload


def resolve_user_store_path() -> Path:
    override = os.environ.get("CONTENT_QUALITY_LEXICON_PATH", "").strip()
    if not override:
        return DEFAULT_USER_STORE
    path = Path(override).expanduser()
    if not path.is_absolute():
        raise ContentQualityError(
            "invalid_lexicon_path_override",
            "CONTENT_QUALITY_LEXICON_PATH must be an absolute path.",
        )
    return path


def _empty_user_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "updated_at": None,
        "entries": [],
    }


def _ensure_private_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, stat.S_IRWXU)
    except OSError:
        pass


@contextmanager
def _advisory_lock(lock_path: Path):
    _ensure_private_parent(lock_path)
    if lock_path.is_symlink():
        raise ContentQualityError("unsafe_lock_path", "Lexicon lock path must not be a symlink.")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_parent(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json_file(path: Path, *, code: str) -> Any:
    if path.is_symlink():
        raise ContentQualityError("unsafe_lexicon_path", f"Symlink is not allowed: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContentQualityError(code, f"Unreadable JSON: {path}") from error


def load_system_pack(path: Path) -> dict[str, Any]:
    payload = _read_json_file(Path(path), code="system_pack_invalid")
    return validate_lexicon_document(payload, expected_origin="SYSTEM")


class SharedUserLexiconStore:
    """Cross-process safe mutable v1 store shared with BOOK OS."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or resolve_user_store_path())
        self.lock_path = Path(f"{self.path}.lock")

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_user_document()
        payload = _read_json_file(self.path, code="user_store_corrupt")
        try:
            return validate_lexicon_document(payload, user_store=True)
        except ContentQualityError as error:
            if error.code == "schema_upgrade_required":
                raise
            raise ContentQualityError(
                "user_store_schema_invalid",
                "Shared Content Quality Lexicon is corrupt or schema-invalid; mutation is blocked.",
            ) from error

    def load(self) -> dict[str, Any]:
        return self._load_unlocked()

    def evidence(self) -> dict[str, Any]:
        document = self.load()
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "revision": document["revision"],
            "sha256": sha256_file(self.path) if self.path.exists() else _canonical_hash(document),
            "entries": len(document["entries"]),
        }

    @staticmethod
    def _dedup_key(entry: Mapping[str, Any]) -> tuple[str, str]:
        return str(entry["match_type"]), normalize_rule_value(str(entry["value"]))

    def add(
        self,
        value: str,
        *,
        action: str = "BLOCK",
        profiles: Sequence[str] = DEFAULT_EDITORIAL_PROFILES,
        match_type: str = "PHRASE",
        rationale: str | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_rule_value(value)
        if len(value) > 1000:
            raise ContentQualityError("invalid_rule_value", "Rule value is longer than 1000 characters.")
        if match_type == "REGEX":
            raise ContentQualityError("user_regex_forbidden", "User-defined REGEX is forbidden in v1.")
        if match_type not in {"PHRASE", "TERM"} or action not in ACTIONS:
            raise ContentQualityError("invalid_user_rule", "Unsupported user rule type/action.")
        ordered_profiles = [profile for profile in PROFILES if profile in set(profiles)]
        if not ordered_profiles or len(ordered_profiles) != len(set(profiles)):
            raise ContentQualityError("invalid_user_rule", "Invalid user rule profiles.")
        _validate_optional_text(rationale, field="rationale", maximum=2000)
        with _advisory_lock(self.lock_path):
            document = self._load_unlocked()
            key = (match_type, normalized)
            for existing in document["entries"]:
                if self._dedup_key(existing) == key:
                    return {
                        "changed": False,
                        "duplicate": True,
                        "revision": document["revision"],
                        "entry": existing,
                    }
            now = _utc_now()
            entry = {
                "rule_id": f"CQ-USER-{uuid.uuid4().hex[:20].upper()}",
                "value": unicodedata.normalize("NFKC", value).strip(),
                "match_type": match_type,
                "action": action,
                "profiles": ordered_profiles,
                "origin": "USER",
                "rationale": rationale,
                "created_at": now,
                "updated_at": now,
            }
            next_document = {
                **document,
                "revision": document["revision"] + 1,
                "updated_at": now,
                "entries": [*document["entries"], entry],
            }
            validate_lexicon_document(next_document, user_store=True)
            _atomic_write_json(self.path, next_document)
            return {
                "changed": True,
                "duplicate": False,
                "revision": next_document["revision"],
                "entry": entry,
            }

    def remove(self, rule_id: str) -> dict[str, Any]:
        if not isinstance(rule_id, str) or not rule_id:
            raise ContentQualityError("invalid_rule_id", "rule_id is required.")
        with _advisory_lock(self.lock_path):
            document = self._load_unlocked()
            retained = [entry for entry in document["entries"] if entry["rule_id"] != rule_id]
            if len(retained) == len(document["entries"]):
                raise ContentQualityError("rule_not_found", f"User rule not found: {rule_id}")
            now = _utc_now()
            next_document = {
                **document,
                "revision": document["revision"] + 1,
                "updated_at": now,
                "entries": retained,
            }
            validate_lexicon_document(next_document, user_store=True)
            _atomic_write_json(self.path, next_document)
            return {"changed": True, "revision": next_document["revision"], "rule_id": rule_id}


_RESOLUTION_DOCUMENT_KEYS = {"schema_version", "revision", "updated_at", "entries"}
_RESOLUTION_ENTRY_KEYS = {
    "resolution_id",
    "rule_id",
    "profile",
    "text_sha256",
    "actor",
    "reason",
    "created_at",
}


def _safe_book_slug(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or len(value) > 120
    ):
        raise ContentQualityError("invalid_book_slug", "Unsafe book slug for quality resolution store.")
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


class ContentQualityResolutionStore:
    """Audiobook-only human exceptions bound to an exact text SHA."""

    def __init__(self, workspace_root: Path, book_slug: str) -> None:
        root = Path(workspace_root).expanduser().resolve(strict=False)
        slug = _safe_book_slug(book_slug)
        self.path = root / "runtime" / "content-quality-resolutions" / f"{slug}.json"
        self.lock_path = Path(f"{self.path}.lock")

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": 1, "revision": 0, "updated_at": None, "entries": []}

    @staticmethod
    def _validate(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - _RESOLUTION_DOCUMENT_KEYS:
            raise ContentQualityError("resolution_store_invalid", "Invalid quality resolution store.")
        if payload.get("schema_version") != 1:
            raise ContentQualityError("resolution_store_invalid", "Unsupported resolution schema.")
        revision = payload.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ContentQualityError("resolution_store_invalid", "Invalid resolution revision.")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ContentQualityError("resolution_store_invalid", "Resolution entries must be an array.")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != _RESOLUTION_ENTRY_KEYS:
                raise ContentQualityError("resolution_store_invalid", "Invalid resolution entry.")
            if (
                not isinstance(entry["resolution_id"], str)
                or not isinstance(entry["rule_id"], str)
                or entry["profile"] not in (PROFILE_AUDIOBOOK_PRE_SYNTHESIS, PROFILE_AUDIOBOOK_TTS_TECHNICAL)
                or not _is_sha256(entry["text_sha256"])
                or entry["actor"] != "OWNER"
                or not isinstance(entry["reason"], str)
                or not entry["reason"].strip()
                or len(entry["reason"]) > 1000
                or not isinstance(entry["created_at"], str)
            ):
                raise ContentQualityError("resolution_store_invalid", "Invalid resolution entry fields.")
            if entry["resolution_id"] in seen:
                raise ContentQualityError("resolution_store_invalid", "Duplicate resolution id.")
            seen.add(entry["resolution_id"])
        return payload

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        payload = _read_json_file(self.path, code="resolution_store_invalid")
        return self._validate(payload)

    def load(self) -> dict[str, Any]:
        return self._load_unlocked()

    def applicable(self, *, profile: str, text_sha256: str) -> dict[str, dict[str, Any]]:
        if profile not in (PROFILE_AUDIOBOOK_PRE_SYNTHESIS, PROFILE_AUDIOBOOK_TTS_TECHNICAL):
            return {}
        if not _is_sha256(text_sha256):
            raise ContentQualityError("invalid_text_identity", "Invalid text SHA for resolution lookup.")
        return {
            entry["rule_id"]: entry
            for entry in self.load()["entries"]
            if entry["profile"] == profile and entry["text_sha256"] == text_sha256
        }

    def add(
        self,
        *,
        rule_id: str,
        profile: str,
        text_sha256: str,
        reason: str,
        actor: str = "OWNER",
    ) -> dict[str, Any]:
        if actor != "OWNER":
            raise ContentQualityError("human_resolution_required", "Quality resolutions are owner-only.")
        if profile not in (PROFILE_AUDIOBOOK_PRE_SYNTHESIS, PROFILE_AUDIOBOOK_TTS_TECHNICAL):
            raise ContentQualityError("invalid_resolution_profile", "Unsupported resolution profile.")
        if not _is_sha256(text_sha256) or not isinstance(rule_id, str) or not rule_id:
            raise ContentQualityError("invalid_resolution", "Resolution requires exact rule/text identity.")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ContentQualityError("invalid_resolution_reason", "Resolution reason is required (max 1000 chars).")
        resolution_id = _canonical_hash(
            {"rule_id": rule_id, "profile": profile, "text_sha256": text_sha256}
        )[:32]
        with _advisory_lock(self.lock_path):
            document = self._load_unlocked()
            existing = next(
                (entry for entry in document["entries"] if entry["resolution_id"] == resolution_id),
                None,
            )
            if existing is not None:
                return {"changed": False, "revision": document["revision"], "entry": existing}
            now = _utc_now()
            entry = {
                "resolution_id": resolution_id,
                "rule_id": rule_id,
                "profile": profile,
                "text_sha256": text_sha256,
                "actor": "OWNER",
                "reason": reason.strip(),
                "created_at": now,
            }
            next_document = {
                **document,
                "revision": document["revision"] + 1,
                "updated_at": now,
                "entries": [*document["entries"], entry],
            }
            self._validate(next_document)
            _atomic_write_json(self.path, next_document)
            return {"changed": True, "revision": next_document["revision"], "entry": entry}

    def fingerprint_for(self, identities: Sequence[tuple[str, str]]) -> str:
        document = self.load()
        wanted = set(identities)
        applicable = sorted(
            (
                entry
                for entry in document["entries"]
                if (entry["profile"], entry["text_sha256"]) in wanted
            ),
            key=lambda item: item["resolution_id"],
        )
        return _canonical_hash({"schema_version": 1, "entries": applicable})


def _line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    previous = text.rfind("\n", 0, offset)
    column = offset + 1 if previous < 0 else offset - previous
    return line, column


def _literal_pattern(value: str) -> str:
    tokens = re.split(r"\s+", unicodedata.normalize("NFKC", value).strip())
    return r"\s+".join(re.escape(token) for token in tokens if token)


def _compile_rule(rule: Mapping[str, Any]) -> re.Pattern[str]:
    match_type = rule["match_type"]
    if match_type == "PHRASE":
        pattern = _literal_pattern(str(rule["value"]))
    elif match_type == "TERM":
        pattern = rf"(?<!\w){_literal_pattern(str(rule['value']))}(?!\w)"
    else:
        if rule.get("origin") != "SYSTEM":
            raise ContentQualityError("user_regex_forbidden", "Only SYSTEM rules may use REGEX in v1.")
        pattern = str(rule["value"])
    try:
        return re.compile(pattern, re.IGNORECASE | re.UNICODE)
    except re.error as error:
        raise ContentQualityError("system_rule_regex_invalid", f"Invalid REGEX in {rule['rule_id']}.") from error


def _severity(action: str) -> int:
    return {"BLOCK": 0, "WARN": 1, "ALLOW": 2}.get(action, 3)


class ContentQualityLexicon:
    def __init__(
        self,
        *,
        user_store_path: Path | None = None,
        contracts_dir: Path = CONTRACTS_DIR,
    ) -> None:
        self.contracts_dir = Path(contracts_dir)
        self.schema_path = self.contracts_dir / SCHEMA_PATH.name
        self.core_path = self.contracts_dir / CORE_PATH.name
        self.technical_path = self.contracts_dir / TECHNICAL_PATH.name
        self.user_store = SharedUserLexiconStore(user_store_path)

    def _schema_evidence(self) -> dict[str, Any]:
        schema = _read_json_file(self.schema_path, code="schema_contract_invalid")
        if not isinstance(schema, dict) or schema.get("title") != "Content Quality Lexicon v1":
            raise ContentQualityError("schema_contract_invalid", "Vendored lexicon schema is invalid.")
        return {"path": str(self.schema_path), "sha256": sha256_file(self.schema_path)}

    def _packs(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        schema = self._schema_evidence()
        core = load_system_pack(self.core_path)
        technical = load_system_pack(self.technical_path)
        if any(PROFILE_AUDIOBOOK_TTS_TECHNICAL in entry["profiles"] for entry in core["entries"]):
            raise ContentQualityError("profile_isolation_violation", "Shared editorial core leaked TTS technical rules.")
        if any(entry["profiles"] != [PROFILE_AUDIOBOOK_TTS_TECHNICAL] for entry in technical["entries"]):
            raise ContentQualityError("profile_isolation_violation", "Audiobook technical overlay leaked profiles.")
        return schema, core, technical

    def status(self) -> dict[str, Any]:
        schema, core, technical = self._packs()
        user = self.user_store.load()
        user_evidence = self.user_store.evidence()
        return {
            "schema_version": 1,
            "contract_version": CONTRACT_VERSION,
            "contract_source": {
                "repo": CONTRACT_DRAFT_SOURCE_REPO,
                "draft_pr": CONTRACT_DRAFT_SOURCE_PR,
                "head": CONTRACT_DRAFT_SOURCE_HEAD,
                "runtime_dependency": False,
            },
            "schema_sha256": schema["sha256"],
            "core_pack_sha256": sha256_file(self.core_path),
            "technical_pack_sha256": sha256_file(self.technical_path),
            "core_entries": core["entries"],
            "technical_entries": technical["entries"],
            "user_store": user_evidence,
            "user_entries": user["entries"],
            "lexicon_fingerprint": self.lexicon_fingerprint(),
            "provider_requests": 0,
            "remote_request_sent": False,
            "model_calls": 0,
            "paid_execution": False,
            "billing_changed": False,
        }

    def lexicon_fingerprint(self) -> str:
        schema, core, technical = self._packs()
        user = self.user_store.load()
        return _canonical_hash(
            {
                "schema_version": 1,
                "contract_version": CONTRACT_VERSION,
                "schema_sha256": schema["sha256"],
                "core_pack_sha256": sha256_file(self.core_path),
                "technical_pack_sha256": sha256_file(self.technical_path),
                "user_document": user,
            }
        )

    def applicable_rules(self, profile: str) -> list[dict[str, Any]]:
        if profile not in PROFILES:
            raise ContentQualityError("invalid_profile", f"Unsupported quality profile: {profile}")
        _, core, technical = self._packs()
        user = self.user_store.load()
        system_entries = technical["entries"] if profile == PROFILE_AUDIOBOOK_TTS_TECHNICAL else core["entries"]
        return [
            dict(entry)
            for entry in [*system_entries, *user["entries"]]
            if profile in entry["profiles"]
        ]

    def scan(
        self,
        text: str,
        *,
        profile: str,
        resolutions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(text, str):
            raise ContentQualityError("invalid_text", "Quality scan requires text.")
        text_sha = sha256_bytes(text.encode("utf-8"))
        resolution_map = dict(resolutions or {})
        findings: list[dict[str, Any]] = []
        for rule in self.applicable_rules(profile):
            if rule["action"] == "ALLOW":
                continue
            compiled = _compile_rule(rule)
            for match in compiled.finditer(text):
                start, end = match.span()
                if end <= start:
                    continue
                line, column = _line_column(text, start)
                resolution = resolution_map.get(rule["rule_id"])
                resolved = bool(
                    resolution
                    and resolution.get("profile") == profile
                    and resolution.get("text_sha256") == text_sha
                    and resolution.get("actor") == "OWNER"
                )
                findings.append(
                    {
                        "rule_id": rule["rule_id"],
                        "matched_text": text[start:end],
                        "start": start,
                        "end": end,
                        "line": line,
                        "column": column,
                        "action": rule["action"],
                        "profile": profile,
                        "origin": rule["origin"],
                        "rationale": rule.get("rationale"),
                        "text_sha256": text_sha,
                        "resolved": resolved,
                        "resolution_id": resolution.get("resolution_id") if resolved else None,
                    }
                )
        findings.sort(key=lambda item: (item["start"], _severity(item["action"]), item["rule_id"]))
        unresolved_blocks = [item for item in findings if item["action"] == "BLOCK" and not item["resolved"]]
        unresolved_warnings = [item for item in findings if item["action"] == "WARN" and not item["resolved"]]
        state = "BLOCKED" if unresolved_blocks else "WARN" if unresolved_warnings else "PASS"
        status = self.status()
        return {
            "schema_version": 1,
            "profile": profile,
            "state": state,
            "text_sha256": text_sha,
            "findings": findings,
            "blocking_findings": unresolved_blocks,
            "warning_findings": unresolved_warnings,
            "resolved_findings": [item for item in findings if item["resolved"]],
            "evidence": {
                "contract_version": CONTRACT_VERSION,
                "contract_source_head": CONTRACT_DRAFT_SOURCE_HEAD,
                "schema_sha256": status["schema_sha256"],
                "core_pack_sha256": status["core_pack_sha256"],
                "technical_pack_sha256": status["technical_pack_sha256"],
                "user_store_revision": status["user_store"]["revision"],
                "user_store_sha256": status["user_store"]["sha256"],
                "lexicon_fingerprint": status["lexicon_fingerprint"],
            },
            "provider_requests": 0,
            "remote_request_sent": False,
            "model_calls": 0,
            "paid_execution": False,
            "billing_changed": False,
        }

    def scan_for_book(
        self,
        text: str,
        *,
        profile: str,
        workspace_root: Path,
        book_slug: str,
    ) -> dict[str, Any]:
        text_sha = sha256_bytes(text.encode("utf-8"))
        resolutions = ContentQualityResolutionStore(workspace_root, book_slug).applicable(
            profile=profile, text_sha256=text_sha
        )
        return self.scan(text, profile=profile, resolutions=resolutions)

    def gate_fingerprint(
        self,
        *,
        workspace_root: Path,
        book_slug: str,
        working_copy_sha256: str,
        normalized_sha256: str,
    ) -> str:
        if not _is_sha256(working_copy_sha256) or not _is_sha256(normalized_sha256):
            raise ContentQualityError("invalid_text_identity", "Gate fingerprint requires exact text hashes.")
        resolutions = ContentQualityResolutionStore(workspace_root, book_slug)
        resolution_fingerprint = resolutions.fingerprint_for(
            [
                (PROFILE_AUDIOBOOK_PRE_SYNTHESIS, working_copy_sha256),
                (PROFILE_AUDIOBOOK_TTS_TECHNICAL, normalized_sha256),
            ]
        )
        return _canonical_hash(
            {
                "schema_version": 1,
                "contract_version": CONTRACT_VERSION,
                "lexicon_fingerprint": self.lexicon_fingerprint(),
                "working_copy_sha256": working_copy_sha256,
                "normalized_sha256": normalized_sha256,
                "resolution_fingerprint": resolution_fingerprint,
            }
        )


def combined_gate_state(scans: Iterable[Mapping[str, Any]]) -> str:
    states = [str(scan.get("state")) for scan in scans]
    if "BLOCKED" in states:
        return "BLOCKED"
    if "WARN" in states:
        return "WARN"
    return "PASS"
