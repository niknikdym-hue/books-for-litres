"""Provider-neutral persistence and WAV integrity helpers for Studio backends."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class WavMetadata:
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    compression_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WavValidationError(ValueError):
    """Raised when a file is not a usable PCM WAV segment."""


class WavTruncatedError(WavValidationError):
    """Raised when a WAV container declares audio bytes that are not present."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def inspect_pcm_wav(path: Path) -> WavMetadata:
    path = Path(path)
    try:
        with path.open("rb") as source:
            header = source.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise WavValidationError(f"Not a RIFF/WAVE file: {path}")
        declared_file_size = int.from_bytes(header[4:8], "little") + 8
        if path.stat().st_size < declared_file_size:
            raise WavTruncatedError(f"WAV ended before its declared RIFF size: {path}")
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
            compression = audio.getcomptype()
            frame_bytes = audio.readframes(frames)
    except (OSError, EOFError, wave.Error) as error:
        raise WavValidationError(f"Unreadable WAV: {path}") from error

    if compression != "NONE":
        raise WavValidationError(f"Unsupported compressed WAV encoding: {compression}")
    if channels < 1 or channels > 8:
        raise WavValidationError(f"Invalid WAV channel count: {channels}")
    if sample_width not in {1, 2, 3, 4}:
        raise WavValidationError(f"Unsupported PCM sample width: {sample_width}")
    if sample_rate < 8_000 or sample_rate > 384_000:
        raise WavValidationError(f"Invalid WAV sample rate: {sample_rate}")
    if frames <= 0:
        raise WavValidationError("WAV contains no audio frames.")
    expected_audio_bytes = frames * channels * sample_width
    if len(frame_bytes) < expected_audio_bytes:
        raise WavTruncatedError("WAV ended before all declared PCM frames were present.")
    duration = frames / sample_rate
    if duration <= 0:
        raise WavValidationError("WAV duration is zero.")
    return WavMetadata(duration, sample_rate, channels, sample_width, frames, compression)


def materialize_validated_file(
    source: Path,
    destination: Path,
    *,
    validator: Callable[[Path], Any],
) -> Any:
    source = Path(source)
    destination = Path(destination)
    metadata = validator(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            return validator(destination)
        except Exception:
            destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    validator(destination)
    return metadata
