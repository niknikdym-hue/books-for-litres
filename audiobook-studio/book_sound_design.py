"""Offline author-controlled chapter cue library for Audiobook Studio.

The cue is optional per book. Built-in cues are generated locally from deterministic
math (no third-party audio, no rights ambiguity, no provider/model/billing calls).
When enabled, chapter assembly may prepend the selected cue before every chapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import struct
import tempfile
import wave
from pathlib import Path
from typing import Any

from book_library import BookLibraryError, normalize_slug


SCHEMA_VERSION = 1
SAMPLE_RATE = 48_000
CHANNELS = 1
SAMPLE_WIDTH = 2
DEFAULT_SOUND_ID = "soft-bell"

CATALOG: tuple[dict[str, Any], ...] = (
    {
        "sound_id": "soft-bell",
        "label": "Мягкий колокол",
        "description": "Короткий спокойный двухтоновый сигнал.",
        "frequencies": (523.25, 659.25),
        "duration": 1.10,
    },
    {
        "sound_id": "warm-mark",
        "label": "Тёплый акцент",
        "description": "Низкий мягкий акцент без резкого начала.",
        "frequencies": (392.00, 493.88),
        "duration": 0.95,
    },
    {
        "sound_id": "glass-note",
        "label": "Стеклянный штрих",
        "description": "Светлый короткий переход перед новой главой.",
        "frequencies": (783.99, 1046.50),
        "duration": 0.85,
    },
    {
        "sound_id": "calm-pulse",
        "label": "Спокойный импульс",
        "description": "Очень сдержанный тональный импульс.",
        "frequencies": (440.00, 554.37),
        "duration": 0.75,
    },
    {
        "sound_id": "minimal-chime",
        "label": "Минималистичный сигнал",
        "description": "Три тихих ноты с плавным затуханием.",
        "frequencies": (587.33, 739.99, 880.00),
        "duration": 1.25,
    },
)


class BookSoundDesignError(RuntimeError):
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


def _safe_slug(value: str) -> str:
    try:
        return normalize_slug(value)
    except BookLibraryError as error:
        raise BookSoundDesignError("invalid_book_slug", "Некорректный идентификатор книги.") from error


def _workspace(root: Path) -> Path:
    candidate = Path(root).expanduser().absolute()
    if candidate.is_symlink():
        raise BookSoundDesignError("unsafe_workspace", "Workspace не должен быть symlink.")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate.resolve(strict=True)


def _catalog_item(sound_id: str) -> dict[str, Any]:
    matches = [item for item in CATALOG if item["sound_id"] == sound_id]
    if len(matches) != 1:
        raise BookSoundDesignError("unknown_chapter_cue", "Неизвестный звук перед главой.")
    return dict(matches[0])


def _asset_root(workspace_root: Path) -> Path:
    return workspace_root / "author-assets" / "chapter-cues" / "generated-v1"


def _preference_path(workspace_root: Path, book_slug: str) -> Path:
    return workspace_root / "settings" / "book-sound" / f"{_safe_slug(book_slug)}.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BookSoundDesignError("unsafe_preference_path", "Файл настроек звука не должен быть symlink.")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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


def _synthesize(item: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BookSoundDesignError("unsafe_chapter_cue", "Файл звука не должен быть symlink.")
    duration = float(item["duration"])
    frequencies = tuple(float(value) for value in item["frequencies"])
    total_frames = int(round(duration * SAMPLE_RATE))
    amplitude = 0.19
    frames = bytearray()
    for frame in range(total_frames):
        t = frame / SAMPLE_RATE
        progress = frame / max(total_frames - 1, 1)
        attack = min(1.0, progress / 0.06)
        release = max(0.0, min(1.0, (1.0 - progress) / 0.38))
        envelope = attack * (release ** 1.7)
        sample = 0.0
        for index, frequency in enumerate(frequencies):
            weight = 1.0 / (index + 1)
            phase = index * 0.31
            sample += weight * math.sin(2.0 * math.pi * frequency * t + phase)
        sample /= sum(1.0 / (index + 1) for index in range(len(frequencies)))
        pcm = int(max(-1.0, min(1.0, sample * envelope * amplitude)) * 32767)
        frames.extend(struct.pack("<h", pcm))

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".wav", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(SAMPLE_WIDTH)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(frames)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_catalog(workspace_root: Path) -> list[dict[str, Any]]:
    root = _workspace(workspace_root)
    assets = _asset_root(root)
    assets.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, Any]] = []
    for raw in CATALOG:
        item = dict(raw)
        path = assets / f"{item['sound_id']}.wav"
        if not path.exists():
            _synthesize(item, path)
        if path.is_symlink() or not path.is_file():
            raise BookSoundDesignError("unsafe_chapter_cue", "Файл звука перед главой небезопасен.")
        with wave.open(str(path), "rb") as source:
            if (
                source.getnchannels() != CHANNELS
                or source.getsampwidth() != SAMPLE_WIDTH
                or source.getframerate() != SAMPLE_RATE
                or source.getcomptype() != "NONE"
            ):
                raise BookSoundDesignError("chapter_cue_pcm_invalid", "Встроенный звук имеет неверный PCM contract.")
            duration_seconds = source.getnframes() / SAMPLE_RATE
        result.append(
            {
                "sound_id": item["sound_id"],
                "label": item["label"],
                "description": item["description"],
                "path": str(path),
                "sha256": _sha256(path),
                "duration_seconds": duration_seconds,
                "sample_rate_hz": SAMPLE_RATE,
                "channels": CHANNELS,
                "sample_width_bytes": SAMPLE_WIDTH,
                "origin": "STUDIO_GENERATED",
                "rights": "PROJECT_ORIGINAL_GENERATED_AUDIO",
            }
        )
    return result


def _read_preference(workspace_root: Path, book_slug: str) -> dict[str, Any]:
    path = _preference_path(workspace_root, book_slug)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "book_slug": _safe_slug(book_slug),
            "enabled": False,
            "sound_id": DEFAULT_SOUND_ID,
            "apply_before": "EACH_CHAPTER",
        }
    if path.is_symlink() or not path.is_file():
        raise BookSoundDesignError("unsafe_preference_path", "Настройки звука повреждены.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BookSoundDesignError("invalid_sound_preference", "Настройки звука повреждены.") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("book_slug") != _safe_slug(book_slug)
        or not isinstance(value.get("enabled"), bool)
        or value.get("apply_before") != "EACH_CHAPTER"
    ):
        raise BookSoundDesignError("invalid_sound_preference", "Настройки звука имеют неверную схему.")
    _catalog_item(str(value.get("sound_id") or ""))
    return value


def book_sound_status(workspace_root: Path, book_slug: str) -> dict[str, Any]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    options = ensure_catalog(root)
    preference = _read_preference(root, slug)
    selected = next(item for item in options if item["sound_id"] == preference["sound_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "book_slug": slug,
        "enabled": preference["enabled"],
        "sound_id": preference["sound_id"],
        "apply_before": "EACH_CHAPTER",
        "selected": selected,
        "options": options,
        **_offline_fields(),
    }


def set_book_sound(
    workspace_root: Path,
    book_slug: str,
    *,
    enabled: bool,
    sound_id: str,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    _catalog_item(sound_id)
    ensure_catalog(root)
    value = {
        "schema_version": SCHEMA_VERSION,
        "book_slug": slug,
        "enabled": bool(enabled),
        "sound_id": sound_id,
        "apply_before": "EACH_CHAPTER",
    }
    _atomic_json(_preference_path(root, slug), value)
    return book_sound_status(root, slug)


def chapter_cue_for_book(workspace_root: Path, book_slug: str) -> dict[str, Any] | None:
    status = book_sound_status(workspace_root, book_slug)
    if not status["enabled"]:
        return None
    selected = dict(status["selected"])
    return {
        "schema_version": SCHEMA_VERSION,
        "book_slug": status["book_slug"],
        "apply_before": "EACH_CHAPTER",
        "sound_id": selected["sound_id"],
        "label": selected["label"],
        "path": selected["path"],
        "sha256": selected["sha256"],
        "duration_seconds": selected["duration_seconds"],
        "sample_rate_hz": selected["sample_rate_hz"],
        "channels": selected["channels"],
        "sample_width_bytes": selected["sample_width_bytes"],
        "origin": selected["origin"],
        "rights": selected["rights"],
    }
