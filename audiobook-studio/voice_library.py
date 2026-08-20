"""Canonical offline Voice Library for Audiobook Studio."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = 1
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("voice-library.json")
REQUIRED_FIELDS = {
    "profile_id",
    "provider",
    "engine",
    "label",
    "voice_source",
    "voice",
    "language",
    "status",
}
OPTIONAL_FIELDS = {
    "role",
    "speed",
    "model",
    "instructions",
    "response_format",
    "frozen",
    "description",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
PROVIDER_ENGINES = {
    "yandex": "yandex_speechkit_v3",
    "openai": "openai_tts",
}
PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class VoiceLibraryError(ValueError):
    """Raised when a voice registry or dynamic catalog is invalid."""


def _require_non_empty_string(profile: Mapping[str, Any], field: str) -> None:
    value = profile.get(field)
    if not isinstance(value, str) or not value.strip():
        raise VoiceLibraryError(f"Voice profile field {field!r} must be a non-empty string.")


def _validate_static_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise VoiceLibraryError("Every voice profile must be a JSON object.")
    fields = set(profile)
    missing = REQUIRED_FIELDS - fields
    unknown = fields - ALLOWED_FIELDS
    if missing:
        raise VoiceLibraryError(f"Voice profile is missing required fields: {sorted(missing)}")
    if unknown:
        raise VoiceLibraryError(f"Voice profile contains unknown fields: {sorted(unknown)}")
    for field in REQUIRED_FIELDS:
        _require_non_empty_string(profile, field)
    profile_id = profile["profile_id"]
    if not PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise VoiceLibraryError(f"Invalid profile_id: {profile_id!r}")
    provider = profile["provider"]
    expected_engine = PROVIDER_ENGINES.get(provider)
    if expected_engine is None or profile["engine"] != expected_engine:
        raise VoiceLibraryError(
            f"Invalid provider/engine relationship: {provider!r}/{profile['engine']!r}"
        )
    if profile["status"] != "approved":
        raise VoiceLibraryError(f"Static cloud profile {profile_id!r} must be approved.")
    if profile["voice_source"] not in {"builtin", "custom"}:
        raise VoiceLibraryError(f"Unsupported voice_source in {profile_id!r}.")
    if "frozen" in profile and not isinstance(profile["frozen"], bool):
        raise VoiceLibraryError(f"frozen must be boolean in {profile_id!r}.")

    if provider == "yandex":
        for field in ("role", "speed"):
            _require_non_empty_string(profile, field)
        if any(field in profile for field in ("model", "instructions", "response_format")):
            raise VoiceLibraryError(f"OpenAI-only metadata found in Yandex profile {profile_id!r}.")
    elif provider == "openai":
        for field in ("model", "response_format"):
            _require_non_empty_string(profile, field)
        if any(field in profile for field in ("role", "speed")):
            raise VoiceLibraryError(f"Yandex-only metadata found in OpenAI profile {profile_id!r}.")
    return dict(profile)


def load_static_profiles(path: Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    """Load and strictly validate the tracked cloud voice registry."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VoiceLibraryError(f"Cannot load Voice Library registry: {path}") from error
    if not isinstance(data, dict) or set(data) != {"schema_version", "profiles"}:
        raise VoiceLibraryError("Voice Library root must contain only schema_version and profiles.")
    if data["schema_version"] != SCHEMA_VERSION:
        raise VoiceLibraryError(f"Unsupported Voice Library schema_version: {data['schema_version']!r}")
    if not isinstance(data["profiles"], list) or not data["profiles"]:
        raise VoiceLibraryError("Voice Library profiles must be a non-empty list.")
    profiles = [_validate_static_profile(profile) for profile in data["profiles"]]
    profile_ids = [profile["profile_id"] for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise VoiceLibraryError("Voice Library contains duplicate profile_id values.")
    return profiles


def _qwen_profile_id(voice_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", voice_id.lower()).strip("_")
    if not normalized:
        raise VoiceLibraryError(f"Cannot normalize Qwen voice id: {voice_id!r}")
    return f"qwen_{normalized}"


def normalize_qwen_profiles(voices: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Adapt studio.load_voices() output without copying its catalog."""
    profiles: list[dict[str, Any]] = []
    seen_voice_ids: set[str] = set()
    seen_profile_ids: set[str] = set()
    for voice in voices:
        voice_id = voice.get("id")
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise VoiceLibraryError("Qwen voice id must be a non-empty string.")
        if voice_id in seen_voice_ids:
            raise VoiceLibraryError(f"Duplicate Qwen voice id: {voice_id!r}")
        profile_id = _qwen_profile_id(voice_id)
        if profile_id in seen_profile_ids:
            raise VoiceLibraryError(f"Qwen profile_id collision: {profile_id!r}")
        profile = {
            "profile_id": profile_id,
            "provider": "qwen",
            "engine": "qwen_mlx_local",
            "label": voice_id,
            "voice_source": "builtin",
            "voice": voice_id,
            "language": "ru",
            "status": "available",
        }
        note = voice.get("note_ru")
        if isinstance(note, str) and note.strip():
            profile["description"] = note
        profiles.append(profile)
        seen_voice_ids.add(voice_id)
        seen_profile_ids.add(profile_id)
    if not profiles:
        raise VoiceLibraryError("The dynamic Qwen voice catalog is empty.")
    return profiles


def load_voice_library(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    qwen_loader: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
    provider: str | None = None,
    engine: str | None = None,
) -> list[dict[str, Any]]:
    """Return normalized static cloud profiles plus optional dynamic Qwen profiles."""
    profiles = load_static_profiles(registry_path)
    if qwen_loader is not None:
        profiles = normalize_qwen_profiles(qwen_loader()) + profiles
    profile_ids = [profile["profile_id"] for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise VoiceLibraryError("Normalized Voice Library contains duplicate profile_id values.")
    if provider is not None:
        profiles = [profile for profile in profiles if profile["provider"] == provider]
    if engine is not None:
        profiles = [profile for profile in profiles if profile["engine"] == engine]
    return [dict(profile) for profile in profiles]
