"""Offline author-controlled chapter cue library for Audiobook Studio.

The cue is optional per book. The curated library is derived locally from the
owner's installed, licensed GarageBand Apple Loops. Raw Apple assets are never
copied into the repository, application bundle, or standalone exports. Chapter
assembly receives only a book-specific PCM working excerpt selected by the owner.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from book_library import BookLibraryError, normalize_slug
from media_tools import resolve_ffmpeg


SCHEMA_VERSION = 1
SAMPLE_RATE = 48_000
CHANNELS = 1
SAMPLE_WIDTH = 2
DEFAULT_SOUND_ID = "garageband-lounge-vibes-05-64aca586a5b04c77"
BUILTIN_RECIPE_VERSION = "audiobook-studio-original-cue-v2"
GARAGEBAND_SOUND_ID = "garageband-lounge-vibes-05-64aca586a5b04c77"
GARAGEBAND_SOURCE = Path(
    "/Library/Audio/Apple Loops/Apple/Apple Loops for GarageBand/Lounge Vibes 05.caf"
)
GARAGEBAND_SOURCE_SHA256 = "64aca586a5b04c77c8b063106d1988f0e76f5d25056fab1236a79740b5351ec2"
GARAGEBAND_LICENSE = Path(
    "/Applications/GarageBand.app/Contents/Resources/GarageBand License Agreement.pdf"
)
GARAGEBAND_LICENSE_SHA256 = "c22ae2ba2ee7f9ba3adf81ecb2b95576c54141ce2a11c1f2a06de0571d4c2700"
GARAGEBAND_DERIVATION_VERSION = "garageband-local-project-audio-v1"

GARAGEBAND_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "sound_id": GARAGEBAND_SOUND_ID,
        "filename": "Lounge Vibes 05.caf",
        "relative_source": "Apple Loops for GarageBand/Lounge Vibes 05.caf",
        "source_sha256": GARAGEBAND_SOURCE_SHA256,
        "target_stem": "lounge-vibes-05",
        "label": "Lounge Vibes 05 · любимый",
        "description": "Ваш любимый мягкий lounge-переход.",
        "genres": ("Нон-фикшн", "Лёгкое / романтическое"),
        "source_duration_seconds": 5.999977,
    },
    {
        "sound_id": "garageband-moving-chords-fx-aed6dd04b562e51e",
        "filename": "Moving Chords FX.caf",
        "relative_source": "19 Transition Effects/Moving Chords FX.caf",
        "source_sha256": "aed6dd04b562e51edc0bea12a7037aec51c6207f6b77675167a3ca39f66326a4",
        "target_stem": "moving-chords-fx",
        "label": "Мягкая смена",
        "description": "Современный гармонический переход без рекламной интонации.",
        "genres": ("Нон-фикшн", "Художественная проза"),
        "source_duration_seconds": 3.692313,
    },
    {
        "sound_id": "garageband-dollar-bin-harp-67b08d97f6f89d84",
        "filename": "Dollar Bin Harp Sample 01.caf",
        "relative_source": "Watch the Sound/Dollar Bin Harp Sample 01.caf",
        "source_sha256": "67b08d97f6f89d84c917fd19b6338caccf772348df388232362010ded951a1af",
        "target_stem": "dollar-bin-harp-sample-01",
        "label": "Тихая арфа",
        "description": "Тёплый акустический жест для спокойной литературной главы.",
        "genres": ("Художественная проза", "Лёгкое / романтическое"),
        "source_duration_seconds": 5.581406,
    },
    {
        "sound_id": "garageband-only-a-dream-delay-0cdbc0f14fd4a147",
        "filename": "Only A Dream Delay FX.caf",
        "relative_source": "Watch the Sound/Only A Dream Delay FX.caf",
        "source_sha256": "0cdbc0f14fd4a1477c835fe1f43d0ae2298191797ea0bef7b7b4756e136f7ad8",
        "target_stem": "only-a-dream-delay-fx",
        "label": "Воздух",
        "description": "Самый спокойный атмосферный вариант с мягким хвостом.",
        "genres": ("Художественная проза", "Хоррор / мистика"),
        "source_duration_seconds": 6.0,
    },
    {
        "sound_id": "garageband-brief-synth-fx-0efa379fc69627ce",
        "filename": "Brief Synth FX.caf",
        "relative_source": "19 Transition Effects/Brief Synth FX.caf",
        "source_sha256": "0efa379fc69627ce22af0a152eed8c8a07464cdbd59dc7b4b88a53df06d16b20",
        "target_stem": "brief-synth-fx",
        "label": "Новый поворот",
        "description": "Короткий нейтральный маркер для современной нон-фикшн книги.",
        "genres": ("Нон-фикшн", "Детектив / триллер"),
        "source_duration_seconds": 3.428571,
    },
    {
        "sound_id": "garageband-triplet-pluck-798f1db44ba6d764",
        "filename": "Triplet Pluck Pattern.caf",
        "relative_source": "19 Transition Effects/Triplet Pluck Pattern.caf",
        "source_sha256": "798f1db44ba6d7649ef0cb8fccd2cdbb9f48fb373a6167fc7816a5c6df3e0f4a",
        "target_stem": "triplet-pluck-pattern",
        "label": "После паузы",
        "description": "Ясный, но ненавязчивый мелодический акцент.",
        "genres": ("Нон-фикшн", "Лёгкое / романтическое"),
        "source_duration_seconds": 3.428571,
    },
    {
        "sound_id": "garageband-short-airy-riser-38adc7b2418c6f64",
        "filename": "Short Airy Riser 01.caf",
        "relative_source": "19 Transition Effects/Short Airy Riser 01.caf",
        "source_sha256": "38adc7b2418c6f6429f2a415c17e75b963b6b3ed959b9a8fcf824ed9ddcda64e",
        "target_stem": "short-airy-riser-01",
        "label": "Лёгкое дыхание",
        "description": "Короткий воздушный переход для быстрого начала главы.",
        "genres": ("Нон-фикшн", "Художественная проза"),
        "source_duration_seconds": 1.875011,
    },
    {
        "sound_id": "garageband-light-sweep-dd7934cfa351d336",
        "filename": "Light Sweep FX.caf",
        "relative_source": "19 Transition Effects/Light Sweep FX.caf",
        "source_sha256": "dd7934cfa351d336264fddd219581df39a42d035d9bd0793579fe559549ebca0",
        "target_stem": "light-sweep-fx",
        "label": "Светлая линия",
        "description": "Мягкая текстура, которая не спорит с голосом диктора.",
        "genres": ("Художественная проза", "Хоррор / мистика"),
        "source_duration_seconds": 5.333333,
    },
    {
        "sound_id": "garageband-pulling-focus-d4a4ba236ba22040",
        "filename": "Pulling Focus FX.caf",
        "relative_source": "19 Transition Effects/Pulling Focus FX.caf",
        "source_sha256": "d4a4ba236ba2204029e350df6afa97ddf5476e86adfd7ef3947f09f4397489d7",
        "target_stem": "pulling-focus-fx",
        "label": "Фокус",
        "description": "Глубокий современный переход с аккуратным движением.",
        "genres": ("Детектив / триллер", "Хоррор / мистика"),
        "source_duration_seconds": 5.333333,
    },
)

LEGACY_GENERATED_SOUND_IDS = frozenset(
    {"soft-bell", "warm-mark", "glass-note", "calm-pulse", "minimal-chime"}
)

LEGACY_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "sound_id": "soft-bell",
        "label": "Тихий рассвет",
        "description": "Воздушный светлый переход с мягким послезвучием.",
        "recipe": {
            "version": BUILTIN_RECIPE_VERSION,
            "duration_seconds": 3.20,
            "peak_target_dbfs": -10.0,
            "events": (
                {"start": 0.00, "duration": 2.25, "frequency": 392.00, "gain": 0.62, "attack": 0.18, "release": 1.10, "decay": 0.42, "harmonics": ((1.0, 1.0), (2.0, 0.22), (3.0, 0.08)), "fm_hz": 0.31, "fm_depth": 0.22},
                {"start": 0.38, "duration": 2.30, "frequency": 587.33, "gain": 0.50, "attack": 0.24, "release": 1.25, "decay": 0.34, "harmonics": ((1.0, 1.0), (2.01, 0.18), (4.0, 0.05)), "fm_hz": 0.23, "fm_depth": 0.16},
                {"start": 0.82, "duration": 1.85, "frequency": 783.99, "gain": 0.27, "attack": 0.10, "release": 1.05, "decay": 0.56, "harmonics": ((1.0, 1.0), (2.0, 0.12))},
            ),
            "texture": {"seed": 1701, "gain": 0.020, "lowpass_hz": 1850.0, "highpass_hz": 310.0, "attack": 0.55, "release": 0.90},
            "delay_taps": ((0.19, 0.14), (0.37, 0.08), (0.61, 0.045)),
        },
    },
    {
        "sound_id": "warm-mark",
        "label": "Бархатная глава",
        "description": "Тёплый камерный акцент с округлым низким тембром.",
        "recipe": {
            "version": BUILTIN_RECIPE_VERSION,
            "duration_seconds": 2.75,
            "peak_target_dbfs": -9.5,
            "events": (
                {"start": 0.00, "duration": 2.20, "frequency": 196.00, "gain": 0.72, "attack": 0.035, "release": 0.90, "decay": 1.15, "harmonics": ((1.0, 1.0), (2.0, 0.34), (3.0, 0.15), (4.0, 0.06))},
                {"start": 0.22, "duration": 1.95, "frequency": 293.66, "gain": 0.43, "attack": 0.045, "release": 0.82, "decay": 1.30, "harmonics": ((1.0, 1.0), (2.0, 0.27), (5.0, 0.05))},
                {"start": 0.48, "duration": 1.72, "frequency": 392.00, "gain": 0.30, "attack": 0.030, "release": 0.76, "decay": 1.48, "harmonics": ((1.0, 1.0), (2.0, 0.20), (3.0, 0.08))},
            ),
            "texture": {"seed": 2903, "gain": 0.012, "lowpass_hz": 720.0, "highpass_hz": 85.0, "attack": 0.08, "release": 0.75},
            "delay_taps": ((0.105, 0.10), (0.235, 0.065), (0.43, 0.035)),
        },
    },
    {
        "sound_id": "glass-note",
        "label": "Хрустальная строка",
        "description": "Три прозрачные ноты, раскрывающиеся вверх.",
        "recipe": {
            "version": BUILTIN_RECIPE_VERSION,
            "duration_seconds": 3.45,
            "peak_target_dbfs": -11.0,
            "events": (
                {"start": 0.00, "duration": 2.55, "frequency": 659.25, "gain": 0.48, "attack": 0.012, "release": 1.55, "decay": 0.78, "harmonics": ((1.0, 1.0), (2.756, 0.28), (5.404, 0.12)), "fm_hz": 3.10, "fm_depth": 0.38},
                {"start": 0.34, "duration": 2.48, "frequency": 830.61, "gain": 0.42, "attack": 0.012, "release": 1.48, "decay": 0.82, "harmonics": ((1.0, 1.0), (2.756, 0.25), (4.10, 0.09)), "fm_hz": 3.70, "fm_depth": 0.30},
                {"start": 0.71, "duration": 2.35, "frequency": 987.77, "gain": 0.36, "attack": 0.010, "release": 1.42, "decay": 0.88, "harmonics": ((1.0, 1.0), (2.756, 0.22), (5.40, 0.07)), "fm_hz": 4.20, "fm_depth": 0.26},
            ),
            "texture": {"seed": 4111, "gain": 0.009, "lowpass_hz": 6100.0, "highpass_hz": 1800.0, "attack": 0.18, "release": 1.20},
            "delay_taps": ((0.145, 0.17), (0.305, 0.105), (0.535, 0.055)),
        },
    },
    {
        "sound_id": "calm-pulse",
        "label": "Спокойный путь",
        "description": "Ровное мягкое движение для серьёзной прозы.",
        "recipe": {
            "version": BUILTIN_RECIPE_VERSION,
            "duration_seconds": 3.80,
            "peak_target_dbfs": -10.5,
            "events": (
                {"start": 0.00, "duration": 3.25, "frequency": 220.00, "gain": 0.44, "attack": 0.32, "release": 1.15, "decay": 0.18, "harmonics": ((1.0, 1.0), (2.0, 0.17), (3.0, 0.05)), "tremolo_hz": 1.35, "tremolo_depth": 0.20},
                {"start": 0.42, "duration": 2.75, "frequency": 329.63, "gain": 0.35, "attack": 0.24, "release": 1.10, "decay": 0.22, "harmonics": ((1.0, 1.0), (2.0, 0.14)), "tremolo_hz": 1.35, "tremolo_depth": 0.14},
                {"start": 1.12, "duration": 1.95, "frequency": 440.00, "gain": 0.23, "attack": 0.22, "release": 0.95, "decay": 0.28, "harmonics": ((1.0, 1.0), (1.5, 0.08))},
            ),
            "texture": {"seed": 5527, "gain": 0.016, "lowpass_hz": 1250.0, "highpass_hz": 145.0, "attack": 0.75, "release": 1.10},
            "delay_taps": ((0.27, 0.105), (0.54, 0.060), (0.81, 0.030)),
        },
    },
    {
        "sound_id": "minimal-chime",
        "label": "Чистый переход",
        "description": "Лаконичная современная фраза без лишней драматичности.",
        "recipe": {
            "version": BUILTIN_RECIPE_VERSION,
            "duration_seconds": 2.40,
            "peak_target_dbfs": -10.0,
            "events": (
                {"start": 0.00, "duration": 1.65, "frequency": 261.63, "gain": 0.50, "attack": 0.025, "release": 0.68, "decay": 0.72, "harmonics": ((1.0, 1.0), (2.0, 0.16), (4.0, 0.035))},
                {"start": 0.20, "duration": 1.55, "frequency": 392.00, "gain": 0.38, "attack": 0.020, "release": 0.72, "decay": 0.80, "harmonics": ((1.0, 1.0), (2.0, 0.13))},
                {"start": 0.43, "duration": 1.45, "frequency": 523.25, "gain": 0.31, "attack": 0.018, "release": 0.77, "decay": 0.86, "harmonics": ((1.0, 1.0), (3.0, 0.07))},
            ),
            "texture": {"seed": 6763, "gain": 0.007, "lowpass_hz": 3400.0, "highpass_hz": 620.0, "attack": 0.06, "release": 0.72},
            "delay_taps": ((0.125, 0.105), (0.265, 0.060), (0.405, 0.032)),
        },
    },
)

# Kept as a public compatibility name for old imports. Synthetic test cues are
# deliberately no longer part of the product catalog.
CATALOG: tuple[dict[str, Any], ...] = ()


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
    return workspace_root / "author-assets" / "chapter-cues" / "generated-v2"


def _garageband_asset_root(workspace_root: Path) -> Path:
    return workspace_root / "author-assets" / "chapter-cues" / "garageband-local-v1"


def _book_asset_root(workspace_root: Path, book_slug: str) -> Path:
    return workspace_root / "author-assets" / "chapter-cues" / "books" / _safe_slug(book_slug)


def _preference_path(workspace_root: Path, book_slug: str) -> Path:
    return workspace_root / "settings" / "book-sound" / f"{_safe_slug(book_slug)}.json"


def _favorites_path(workspace_root: Path) -> Path:
    return workspace_root / "settings" / "book-sound" / "favorites.json"


def _read_favorites(workspace_root: Path) -> set[str]:
    path = _favorites_path(workspace_root)
    if not path.exists():
        return {GARAGEBAND_SOUND_ID}
    if path.is_symlink() or not path.is_file():
        raise BookSoundDesignError("unsafe_favorites_path", "Избранные звуки повреждены.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BookSoundDesignError("invalid_sound_favorites", "Избранные звуки повреждены.") from error
    identifiers = value.get("sound_ids") if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(identifiers, list):
        raise BookSoundDesignError("invalid_sound_favorites", "Избранные звуки имеют неверный формат.")
    known = {item["sound_id"] for item in GARAGEBAND_CATALOG}
    return {str(item) for item in identifiers if str(item) in known}


def set_sound_favorite(
    workspace_root: Path, book_slug: str, *, sound_id: str, favorite: bool
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    known = {item["sound_id"] for item in GARAGEBAND_CATALOG}
    if sound_id not in known:
        raise BookSoundDesignError("unknown_chapter_cue", "Неизвестный звук перед главой.")
    favorites = _read_favorites(root)
    if favorite:
        favorites.add(sound_id)
    else:
        favorites.discard(sound_id)
    _atomic_json(
        _favorites_path(root),
        {"schema_version": 1, "sound_ids": sorted(favorites)},
    )
    return book_sound_status(root, book_slug)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_symlink_component(path: Path) -> bool:
    absolute = Path(path).expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


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


def _recipe(item: dict[str, Any]) -> dict[str, Any]:
    """Return the complete, machine-readable recipe that defines one WAV."""
    # JSON normalization guarantees callers and the persisted sidecar observe
    # exactly the same list/dict vocabulary (rather than Python-only tuples).
    return json.loads(
        json.dumps(
            {
                "engine": "python-stdlib-deterministic-additive-v1",
                "sample_rate_hz": SAMPLE_RATE,
                "channels": CHANNELS,
                "sample_width_bytes": SAMPLE_WIDTH,
                **dict(item["recipe"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _recipe_sha256(recipe: dict[str, Any]) -> str:
    payload = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _edge_envelope(position: float, duration: float, attack: float, release: float) -> float:
    attack_gain = min(1.0, position / max(attack, 1.0 / SAMPLE_RATE))
    release_gain = min(1.0, (duration - position) / max(release, 1.0 / SAMPLE_RATE))
    return max(0.0, attack_gain) * max(0.0, release_gain)


def _synthesize(item: dict[str, Any], path: Path) -> None:
    """Render an original cue using only deterministic local DSP primitives."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise BookSoundDesignError("unsafe_chapter_cue", "Файл звука не должен быть symlink.")
    recipe = _recipe(item)
    duration = float(recipe["duration_seconds"])
    total_frames = int(round(duration * SAMPLE_RATE))
    dry = [0.0] * total_frames

    # Layered additive instruments. Each event has its own harmonic spectrum,
    # amplitude contour, and optional slow FM/tremolo movement.
    for event_index, event in enumerate(recipe["events"]):
        start_frame = max(0, int(round(float(event["start"]) * SAMPLE_RATE)))
        event_duration = float(event["duration"])
        end_frame = min(total_frames, start_frame + int(round(event_duration * SAMPLE_RATE)))
        fundamental = float(event["frequency"])
        event_gain = float(event["gain"])
        attack = float(event["attack"])
        release = float(event["release"])
        decay = float(event["decay"])
        harmonics = tuple((float(ratio), float(gain)) for ratio, gain in event["harmonics"])
        harmonic_gain = sum(gain for _, gain in harmonics)
        fm_hz = float(event.get("fm_hz", 0.0))
        fm_depth = float(event.get("fm_depth", 0.0))
        tremolo_hz = float(event.get("tremolo_hz", 0.0))
        tremolo_depth = float(event.get("tremolo_depth", 0.0))
        for frame in range(start_frame, end_frame):
            local_t = (frame - start_frame) / SAMPLE_RATE
            envelope = _edge_envelope(local_t, event_duration, attack, release)
            envelope *= math.exp(-decay * local_t)
            if tremolo_hz:
                envelope *= 1.0 - tremolo_depth * (0.5 - 0.5 * math.sin(2.0 * math.pi * tremolo_hz * local_t))
            phase_modulation = fm_depth * math.sin(2.0 * math.pi * fm_hz * local_t) if fm_hz else 0.0
            value = 0.0
            for partial_index, (ratio, partial_gain) in enumerate(harmonics):
                phase = 2.0 * math.pi * fundamental * ratio * local_t
                phase += phase_modulation * ratio + event_index * 0.19 + partial_index * 0.11
                value += partial_gain * math.sin(phase)
            dry[frame] += event_gain * envelope * value / harmonic_gain

    # A seeded filtered texture prevents the cues from sounding like bare test
    # beeps. The same recipe always creates exactly the same samples.
    texture = dict(recipe["texture"])
    state = int(texture["seed"]) & 0xFFFFFFFF
    lowpass = 0.0
    slow_lowpass = 0.0
    low_alpha = 1.0 - math.exp(-2.0 * math.pi * float(texture["lowpass_hz"]) / SAMPLE_RATE)
    high_alpha = 1.0 - math.exp(-2.0 * math.pi * float(texture["highpass_hz"]) / SAMPLE_RATE)
    texture_gain = float(texture["gain"])
    for frame in range(total_frames):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        noise = (state / 4294967295.0) * 2.0 - 1.0
        lowpass += low_alpha * (noise - lowpass)
        slow_lowpass += high_alpha * (lowpass - slow_lowpass)
        t = frame / SAMPLE_RATE
        envelope = _edge_envelope(t, duration, float(texture["attack"]), float(texture["release"]))
        dry[frame] += (lowpass - slow_lowpass) * texture_gain * envelope

    # A short multi-tap FIR ambience is deterministic and leaves the source
    # intelligible when the cue is joined to a spoken chapter.
    rendered = list(dry)
    for delay_seconds, delay_gain in recipe["delay_taps"]:
        delay_frames = int(round(float(delay_seconds) * SAMPLE_RATE))
        for frame in range(delay_frames, total_frames):
            rendered[frame] += dry[frame - delay_frames] * float(delay_gain)

    peak = max((abs(value) for value in rendered), default=0.0)
    if peak <= 0.0:
        raise BookSoundDesignError("chapter_cue_synthesis_failed", "Не удалось создать встроенный звук.")
    target_peak = 10.0 ** (float(recipe["peak_target_dbfs"]) / 20.0)
    scale = target_peak / peak
    final_fade_frames = int(round(0.012 * SAMPLE_RATE))
    frames = bytearray()
    for frame, value in enumerate(rendered):
        edge_gain = min(1.0, frame / max(final_fade_frames, 1))
        edge_gain *= min(1.0, (total_frames - 1 - frame) / max(final_fade_frames, 1))
        pcm = int(round(max(-1.0, min(1.0, value * scale * edge_gain)) * 32767))
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


def _garageband_source(item: dict[str, Any]) -> Path:
    return Path("/Library/Audio/Apple Loops/Apple") / str(item["relative_source"])


def _garageband_option(
    workspace_root: Path, item: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Create a local working derivative of one byte-identified Apple Loop."""
    source = _garageband_source(item)
    license_path = GARAGEBAND_LICENSE
    if (
        not source.is_file()
        or _has_symlink_component(source)
        or _sha256(source) != item["source_sha256"]
    ):
        return None, f"{item['filename']}: файл отсутствует или изменён"
    if (
        not license_path.is_file()
        or _has_symlink_component(license_path)
        or _sha256(license_path) != GARAGEBAND_LICENSE_SHA256
    ):
        return None, "Лицензия установленного GarageBand не подтверждена"

    ffmpeg = resolve_ffmpeg(workspace_root)
    if not ffmpeg.available or ffmpeg.path is None:
        return None, "Для локальной подготовки звуков GarageBand требуется FFmpeg"

    asset_root = _garageband_asset_root(workspace_root)
    asset_root.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(asset_root):
        raise BookSoundDesignError("unsafe_chapter_cue", "Папка GarageBand-звука не должна быть ссылкой.")
    target = asset_root / f"{item['target_stem']}.wav"
    metadata_path = asset_root / f"{item['target_stem']}.provenance.json"
    source_duration = float(item["source_duration_seconds"])
    fade_out_start = max(0.0, source_duration - 0.18)
    recipe = {
        "version": GARAGEBAND_DERIVATION_VERSION,
        "source_sha256": item["source_sha256"],
        "source_format": "CAF/AAC stereo 44100 Hz",
        "output_format": "WAV PCM16 mono 48000 Hz",
        "gain_db": -10.0,
        "fade_in_seconds": 0.03,
        "fade_out_seconds": 0.18,
        "fade_out_start_seconds": fade_out_start,
        "ffmpeg_version": ffmpeg.version,
    }
    recipe_digest = _recipe_sha256(recipe)
    metadata: dict[str, Any] | None = None
    if metadata_path.is_file() and not metadata_path.is_symlink():
        try:
            candidate = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                metadata = candidate
        except (OSError, ValueError):
            metadata = None
    target_sha = _sha256(target) if target.is_file() and not target.is_symlink() else None
    if (
        metadata is None
        or metadata.get("recipe_sha256") != recipe_digest
        or metadata.get("source_sha256") != item["source_sha256"]
        or metadata.get("wav_sha256") != target_sha
    ):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{item['target_stem']}.", suffix=".wav", dir=asset_root
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            arguments = [
                str(ffmpeg.path), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-map_metadata", "-1", "-vn", "-ac", "1",
                "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
                "-af", (
                    "volume=-10dB,afade=t=in:st=0:d=0.03,"
                    f"afade=t=out:st={fade_out_start:.6f}:d=0.18"
                ),
                "-fflags", "+bitexact", "-flags:a", "+bitexact", "-y", str(temporary),
            ]
            completed = subprocess.run(arguments, capture_output=True, timeout=60, check=False)
            if completed.returncode != 0:
                return None, f"{item['filename']}: локальная подготовка не удалась"
            os.replace(temporary, target)
            _atomic_json(
                metadata_path,
                {
                    "schema_version": 1,
                    "sound_id": item["sound_id"],
                    "origin": "APPLE_GARAGEBAND_DIGITAL_MATERIAL",
                    "rights": "APPLE_LICENSED_AUDIO_PROJECT_USE",
                    "source_path": str(source),
                    "source_sha256": item["source_sha256"],
                    "source_copyright": "PowerFX Systems AB",
                    "source_artist": "PowerFX.com",
                    "license_path": str(license_path),
                    "license_sha256": GARAGEBAND_LICENSE_SHA256,
                    "license_id": "GARAGEBAND-SLA-EA1922-2024-08-20-2G",
                    "recipe": recipe,
                    "recipe_sha256": recipe_digest,
                    "wav_sha256": _sha256(target),
                    "standalone_distribution_allowed": False,
                },
            )
        finally:
            temporary.unlink(missing_ok=True)

    if target.is_symlink() or not target.is_file():
        return None, f"{item['filename']}: рабочая WAV-копия недоступна"
    with wave.open(str(target), "rb") as audio:
        if (
            audio.getnchannels() != CHANNELS
            or audio.getsampwidth() != SAMPLE_WIDTH
            or audio.getframerate() != SAMPLE_RATE
            or audio.getcomptype() != "NONE"
        ):
            raise BookSoundDesignError("chapter_cue_pcm_invalid", "GarageBand-звук имеет неверный PCM contract.")
        duration_seconds = audio.getnframes() / SAMPLE_RATE
    rights_provenance = {
        "verified": True,
        "royalty_free_project_use": True,
        "commercial_audiobook_distribution": True,
        "standalone_distribution": False,
        "sample_library_repackaging": False,
        "machine_learning_use": False,
        "license_id": "GARAGEBAND-SLA-EA1922-2024-08-20-2G",
        "license_sha256": GARAGEBAND_LICENSE_SHA256,
    }
    option = {
        "sound_id": item["sound_id"],
        "label": item["label"],
        "description": item["description"],
        "genres": list(item["genres"]),
        "path": str(target),
        "sha256": _sha256(target),
        "duration_seconds": duration_seconds,
        "sample_rate_hz": SAMPLE_RATE,
        "channels": CHANNELS,
        "sample_width_bytes": SAMPLE_WIDTH,
        "origin": "APPLE_GARAGEBAND_DIGITAL_MATERIAL",
        "rights": "APPLE_LICENSED_AUDIO_PROJECT_USE",
        "rights_provenance": rights_provenance,
        "source_path": str(source),
        "source_sha256": item["source_sha256"],
        "source_copyright": "PowerFX Systems AB",
        "source_artist": "PowerFX.com",
        "recipe": recipe,
        "recipe_sha256": recipe_digest,
        "recipe_path": str(metadata_path),
        "production_policy": {
            "allowed_scope": "INCORPORATED_IN_AUDIOBOOK_CHAPTER_SOUNDTRACK_ONLY",
            "raw_asset_export_allowed": False,
            "separate_cue_export_allowed": False,
            "bundle_raw_asset_in_app": False,
            "include_raw_asset_in_release": False,
        },
    }
    return option, None


def _garageband_catalog(workspace_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    options: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for item in GARAGEBAND_CATALOG:
        option, problem = _garageband_option(workspace_root, item)
        if option is not None:
            options.append(option)
        elif problem:
            unavailable.append(problem)
    discovery = {
        "requested_historical_label": "Lounge Vibes 05.7",
        "requested_historical_asset": "EXACT_SOURCE_NOT_FOUND",
        "similar_local_asset": "Lounge Vibes 05.caf",
        "available": bool(options),
        "selectable": bool(options),
        "message": (
            f"Доступно профессиональных звуков GarageBand: {len(options)}. "
            "Точный файл «Lounge Vibes 05.7» не найден; «Lounge Vibes 05» показан под своим настоящим именем."
            + (f" Недоступно: {len(unavailable)}." if unavailable else "")
        ),
    }
    return options, discovery


def ensure_catalog(workspace_root: Path) -> list[dict[str, Any]]:
    root = _workspace(workspace_root)
    result, _ = _garageband_catalog(root)
    return result


def _clip_values(preference: dict[str, Any], option: dict[str, Any]) -> tuple[float, float]:
    source_duration = float(option["duration_seconds"])
    minimum_duration = min(0.5, source_duration)
    start = float(preference.get("clip_start_seconds", 0.0))
    default_duration = min(3.0, source_duration)
    duration = float(preference.get("clip_duration_seconds", default_duration))
    if (
        not math.isfinite(start)
        or not math.isfinite(duration)
        or start < 0.0
        or duration <= 0.0
        or duration < minimum_duration
        or duration > 4.0
        or start + duration > source_duration + (1.0 / SAMPLE_RATE)
    ):
        raise BookSoundDesignError(
            "invalid_chapter_cue_excerpt",
            "Фрагмент звука должен длиться от 0,5 до 4 секунд и находиться внутри записи.",
        )
    return start, min(duration, source_duration - start)


def _excerpt_option(
    workspace_root: Path,
    book_slug: str,
    option: dict[str, Any],
    preference: dict[str, Any],
) -> dict[str, Any]:
    """Return a deterministic, book-specific PCM excerpt used by assembly."""
    start, duration = _clip_values(preference, option)
    source = Path(option["path"])
    identity = hashlib.sha256(
        f"{option['sha256']}\0{start:.6f}\0{duration:.6f}\0excerpt-v1".encode("utf-8")
    ).hexdigest()
    root = _book_asset_root(workspace_root, book_slug) / "selections"
    root.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(root):
        raise BookSoundDesignError("unsafe_chapter_cue", "Папка фрагмента звука не должна быть ссылкой.")
    target = root / f"{identity}.wav"
    metadata_path = root / f"{identity}.json"
    valid = target.is_file() and not target.is_symlink()
    metadata: dict[str, Any] | None = None
    if valid and metadata_path.is_file() and not metadata_path.is_symlink():
        try:
            candidate = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata = candidate if isinstance(candidate, dict) else None
        except (OSError, ValueError):
            metadata = None
    valid = bool(
        valid
        and metadata
        and metadata.get("identity") == identity
        and metadata.get("wav_sha256") == _sha256(target)
    )
    if not valid:
        with wave.open(str(source), "rb") as audio:
            if (
                audio.getnchannels() not in (1, 2)
                or audio.getsampwidth() != SAMPLE_WIDTH
                or not 8_000 <= audio.getframerate() <= 192_000
                or audio.getcomptype() != "NONE"
            ):
                raise BookSoundDesignError("chapter_cue_pcm_invalid", "Звук имеет неверный PCM contract.")
            sample_rate = audio.getframerate()
            channels = audio.getnchannels()
            start_frame = int(round(start * sample_rate))
            frame_count = int(round(duration * sample_rate))
            audio.setpos(start_frame)
            raw_frames = audio.readframes(frame_count)
        samples = [value[0] for value in struct.iter_unpack("<h", raw_frames)]
        actual_frames = len(samples) // channels
        fade_frames = min(int(0.03 * sample_rate), max(1, actual_frames // 2))
        output_frames = bytearray()
        for index, sample in enumerate(samples):
            frame_index = index // channels
            gain = 1.0
            if frame_index < fade_frames:
                gain = min(gain, frame_index / fade_frames)
            remaining = actual_frames - 1 - frame_index
            if remaining < fade_frames:
                gain = min(gain, remaining / fade_frames)
            output_frames.extend(struct.pack("<h", int(round(sample * max(0.0, gain)))))
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{identity}.", suffix=".wav", dir=root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with wave.open(str(temporary), "wb") as output:
                output.setnchannels(channels)
                output.setsampwidth(SAMPLE_WIDTH)
                output.setframerate(sample_rate)
                output.writeframes(output_frames)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        _atomic_json(
            metadata_path,
            {
                "schema_version": 1,
                "identity": identity,
                "book_slug": _safe_slug(book_slug),
                "sound_id": option["sound_id"],
                "source_sha256": option["sha256"],
                "clip_start_seconds": start,
                "clip_duration_seconds": duration,
                "fade_in_seconds": 0.03,
                "fade_out_seconds": 0.03,
                "wav_sha256": _sha256(target),
            },
        )
    selected = dict(option)
    selected.update(
        {
            "path": str(target),
            "sha256": _sha256(target),
            "source_duration_seconds": float(option["duration_seconds"]),
            "duration_seconds": duration,
            "selection_start_seconds": start,
            "selection_duration_seconds": duration,
            "selection_identity": identity,
        }
    )
    if selected.get("origin") == "USER_IMPORTED" and isinstance(selected.get("rights_provenance"), dict):
        provenance = dict(selected["rights_provenance"])
        provenance["imported_original_sha256"] = provenance.get("source_sha256")
        provenance["source_sha256"] = selected["sha256"]
        selected["rights_provenance"] = provenance
    return selected


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
    sound_id = str(value.get("sound_id") or "")
    custom = value.get("custom_sound")
    if sound_id.startswith("custom-"):
        if not isinstance(custom, dict) or custom.get("sound_id") != sound_id:
            raise BookSoundDesignError("invalid_sound_preference", "Настройки пользовательского звука повреждены.")
        custom_path = Path(str(custom.get("path") or ""))
        allowed_root = _book_asset_root(workspace_root, book_slug).resolve(strict=True)
        try:
            resolved = custom_path.resolve(strict=True)
            resolved.relative_to(allowed_root)
        except (OSError, ValueError) as error:
            raise BookSoundDesignError("unsafe_chapter_cue", "Пользовательский звук находится вне папки книги.") from error
        if custom_path.is_symlink() or not custom_path.is_file() or _sha256(custom_path) != custom.get("sha256"):
            raise BookSoundDesignError("unsafe_chapter_cue", "Пользовательский звук изменён или недоступен.")
    elif sound_id in {item["sound_id"] for item in GARAGEBAND_CATALOG}:
        item = next(item for item in GARAGEBAND_CATALOG if item["sound_id"] == sound_id)
        option, _ = _garageband_option(workspace_root, item)
        if option is None:
            raise BookSoundDesignError(
                "selected_chapter_cue_unavailable",
                "Выбранный GarageBand-звук больше недоступен на этом Mac.",
            )
    elif sound_id in LEGACY_GENERATED_SOUND_IDS:
        # Old synthetic cues are retired. Never silently replace an enabled
        # book sound: migrate the read view to safe sound-off.
        value = dict(value)
        value.update({"enabled": False, "sound_id": DEFAULT_SOUND_ID})
        value.pop("clip_start_seconds", None)
        value.pop("clip_duration_seconds", None)
    else:
        _catalog_item(sound_id)
    return value


def book_sound_status(workspace_root: Path, book_slug: str) -> dict[str, Any]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    favorites = _read_favorites(root)
    options = [
        {**item, "is_favorite": item["sound_id"] in favorites}
        for item in ensure_catalog(root)
    ]
    _, garageband_discovery = _garageband_catalog(root)
    preference = _read_preference(root, slug)
    if isinstance(preference.get("custom_sound"), dict):
        options.append(dict(preference["custom_sound"]))
    matches = [item for item in options if item["sound_id"] == preference["sound_id"]]
    if matches:
        selected = _excerpt_option(root, slug, matches[0], preference)
    elif not preference["enabled"]:
        selected = {
            "sound_id": DEFAULT_SOUND_ID,
            "label": "Звуки GarageBand недоступны",
            "description": "Установите GarageBand и его библиотеку Apple Loops.",
            "path": "",
            "sha256": "",
            "duration_seconds": 0.0,
            "source_duration_seconds": 0.0,
            "selection_start_seconds": 0.0,
            "selection_duration_seconds": 0.0,
            "sample_rate_hz": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_width_bytes": SAMPLE_WIDTH,
            "origin": "UNAVAILABLE",
            "rights": "UNAVAILABLE",
            "genres": [],
            "is_favorite": False,
        }
    else:
        raise BookSoundDesignError(
            "chapter_cue_library_unavailable",
            "Выбранный профессиональный звук GarageBand недоступен на этом Mac.",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "book_slug": slug,
        "enabled": preference["enabled"],
        "sound_id": preference["sound_id"],
        "apply_before": "EACH_CHAPTER",
        "clip_start_seconds": selected["selection_start_seconds"],
        "clip_duration_seconds": selected["selection_duration_seconds"],
        "selected": selected,
        "options": options,
        "garageband_discovery": garageband_discovery,
        **_offline_fields(),
    }


def set_book_sound(
    workspace_root: Path,
    book_slug: str,
    *,
    enabled: bool,
    sound_id: str,
    clip_start_seconds: float | None = None,
    clip_duration_seconds: float | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    options = ensure_catalog(root)
    previous = _read_preference(root, slug)
    custom = previous.get("custom_sound")
    if sound_id.startswith("custom-"):
        if not isinstance(custom, dict) or custom.get("sound_id") != sound_id:
            raise BookSoundDesignError("unknown_chapter_cue", "Неизвестный пользовательский звук.")
    elif not any(item["sound_id"] == sound_id for item in options):
        raise BookSoundDesignError("unknown_chapter_cue", "Неизвестный звук перед главой.")
    option = (
        dict(custom)
        if sound_id.startswith("custom-") and isinstance(custom, dict)
        else next(item for item in options if item["sound_id"] == sound_id)
    )
    same_sound = previous.get("sound_id") == sound_id
    proposed = {
        "clip_start_seconds": (
            clip_start_seconds
            if clip_start_seconds is not None
            else previous.get("clip_start_seconds", 0.0) if same_sound else 0.0
        ),
        "clip_duration_seconds": (
            clip_duration_seconds
            if clip_duration_seconds is not None
            else previous.get("clip_duration_seconds", min(3.0, float(option["duration_seconds"])))
            if same_sound else min(3.0, float(option["duration_seconds"]))
        ),
    }
    start, duration = _clip_values(proposed, option)
    value = {
        "schema_version": SCHEMA_VERSION,
        "book_slug": slug,
        "enabled": bool(enabled),
        "sound_id": sound_id,
        "apply_before": "EACH_CHAPTER",
        "clip_start_seconds": start,
        "clip_duration_seconds": duration,
    }
    if isinstance(custom, dict):
        value["custom_sound"] = custom
    _atomic_json(_preference_path(root, slug), value)
    return book_sound_status(root, slug)


def import_book_sound(
    workspace_root: Path,
    book_slug: str,
    source_path: Path,
    *,
    label: str | None = None,
    rights_confirmed: bool = False,
) -> dict[str, Any]:
    """Copy one user-selected PCM WAV into this book's offline asset folder."""
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    source = Path(source_path).expanduser().absolute()
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != ".wav":
        raise BookSoundDesignError("unsupported_custom_sound", "Выберите обычный WAV-файл, не ссылку.")
    if source.stat().st_size > 20 * 1024 * 1024:
        raise BookSoundDesignError("custom_sound_too_large", "Файл звука не должен превышать 20 МБ.")
    try:
        with wave.open(str(source), "rb") as audio:
            if (
                audio.getcomptype() != "NONE"
                or audio.getnchannels() not in (1, 2)
                or audio.getsampwidth() != 2
                or not 8_000 <= audio.getframerate() <= 192_000
                or audio.getnframes() <= 0
            ):
                raise BookSoundDesignError(
                    "unsupported_custom_sound",
                    "Поддерживается PCM WAV: 16-bit, mono/stereo, 8–192 кГц.",
                )
            duration_seconds = audio.getnframes() / audio.getframerate()
            if duration_seconds > 60:
                raise BookSoundDesignError("custom_sound_too_long", "Звук перед главой должен быть короче 60 секунд.")
            sample_rate = audio.getframerate()
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
    except (wave.Error, EOFError) as error:
        raise BookSoundDesignError("unsupported_custom_sound", "Не удалось прочитать WAV-файл.") from error
    if not rights_confirmed:
        raise BookSoundDesignError(
            "custom_sound_rights_not_confirmed",
            "Подтвердите, что у вас есть право использовать этот звук в аудиокниге.",
        )

    digest = _sha256(source)
    sound_id = f"custom-{digest[:16]}"
    asset_root = _book_asset_root(root, slug)
    asset_root.mkdir(parents=True, exist_ok=True)
    if asset_root.is_symlink():
        raise BookSoundDesignError("unsafe_chapter_cue", "Папка звука книги не должна быть ссылкой.")
    target = asset_root / f"{sound_id}.wav"
    if target.exists() and (target.is_symlink() or _sha256(target) != digest):
        raise BookSoundDesignError("custom_sound_collision", "Не удалось безопасно сохранить пользовательский звук.")
    if not target.exists():
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{sound_id}.", suffix=".wav", dir=asset_root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary, follow_symlinks=False)
            if _sha256(temporary) != digest:
                raise BookSoundDesignError("custom_sound_copy_mismatch", "Копия пользовательского звука повреждена.")
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    custom = {
        "sound_id": sound_id,
        "label": (label or source.stem).strip()[:80] or "Мой звук",
        "description": "Пользовательский звук для этой книги.",
        "path": str(target),
        "sha256": digest,
        "duration_seconds": duration_seconds,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "origin": "USER_IMPORTED",
        "rights": "USER_CONFIRMED_AUDIOBOOK_USE",
        "rights_provenance": {
            "confirmed": True,
            "verification_method": "OWNER_ATTESTATION",
            "attestation": "I_CONFIRM_RIGHTS_TO_USE_AND_COMMERCIALLY_DISTRIBUTE_IN_THIS_AUDIOBOOK",
            "confirmed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_sha256": digest,
            "commercial_audiobook_distribution": True,
            "standalone_distribution": False,
        },
        "production_policy": {
            "allowed_scope": "INCORPORATED_IN_AUDIOBOOK_CHAPTER_SOUNDTRACK_ONLY",
            "raw_asset_export_allowed": False,
            "separate_cue_export_allowed": False,
            "include_raw_asset_in_release": False,
        },
    }
    _atomic_json(
        _preference_path(root, slug),
        {
            "schema_version": SCHEMA_VERSION,
            "book_slug": slug,
            "enabled": True,
            "sound_id": sound_id,
            "apply_before": "EACH_CHAPTER",
            "clip_start_seconds": 0.0,
            "clip_duration_seconds": min(3.0, duration_seconds),
            "custom_sound": custom,
        },
    )
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
        "source_duration_seconds": selected.get("source_duration_seconds", selected["duration_seconds"]),
        "selection_start_seconds": selected.get("selection_start_seconds", 0.0),
        "selection_duration_seconds": selected.get("selection_duration_seconds", selected["duration_seconds"]),
        "selection_identity": selected.get("selection_identity"),
        "sample_rate_hz": selected["sample_rate_hz"],
        "channels": selected["channels"],
        "sample_width_bytes": selected["sample_width_bytes"],
        "origin": selected["origin"],
        "rights": selected["rights"],
        **(
            {
                "rights_provenance": selected["rights_provenance"],
                "source_path": selected["source_path"],
                "source_sha256": selected["source_sha256"],
                "source_copyright": selected["source_copyright"],
                "source_artist": selected["source_artist"],
                "production_policy": selected["production_policy"],
            }
            if selected["origin"] == "APPLE_GARAGEBAND_DIGITAL_MATERIAL"
            else {}
        ),
        **(
            {
                "rights_provenance": selected["rights_provenance"],
                "production_policy": selected["production_policy"],
            }
            if selected["origin"] == "USER_IMPORTED"
            and isinstance(selected.get("rights_provenance"), dict)
            and isinstance(selected.get("production_policy"), dict)
            else {}
        ),
        **(
            {
                "recipe": selected["recipe"],
                "recipe_sha256": selected["recipe_sha256"],
                "recipe_path": selected["recipe_path"],
            }
            if selected["origin"] == "STUDIO_GENERATED"
            else {}
        ),
    }
