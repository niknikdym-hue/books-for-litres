"""Provider-neutral persistence and WAV integrity helpers for Studio backends."""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
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
    data_bytes: int
    block_align: int
    riff_declared_size: int
    data_declared_size: int
    riff_size_sentinel: bool
    data_size_sentinel: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WavValidationError(ValueError):
    """Raised when a file is not a usable PCM WAV segment."""


class WavTruncatedError(WavValidationError):
    """Raised when a WAV container declares audio bytes that are not present."""


RIFF_SIZE_SENTINEL = 0xFFFFFFFF


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


def wav_size_markers(path: Path) -> dict[str, Any]:
    """Return only allow-listed RIFF size markers for safe diagnostics."""
    result: dict[str, Any] = {
        "riff_declared_size": None,
        "data_declared_size": None,
        "riff_size_sentinel": False,
        "data_size_sentinel": False,
    }
    path = Path(path)
    try:
        file_size = path.stat().st_size
        with path.open("rb") as source:
            header = source.read(12)
            if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return result
            riff_size = int.from_bytes(header[4:8], "little")
            result["riff_declared_size"] = riff_size
            result["riff_size_sentinel"] = riff_size == RIFF_SIZE_SENTINEL
            offset = 12
            while offset + 8 <= file_size:
                source.seek(offset)
                chunk_header = source.read(8)
                chunk_id = chunk_header[:4]
                chunk_size = int.from_bytes(chunk_header[4:8], "little")
                if chunk_id == b"data":
                    result["data_declared_size"] = chunk_size
                    result["data_size_sentinel"] = chunk_size == RIFF_SIZE_SENTINEL
                    break
                if chunk_size == RIFF_SIZE_SENTINEL:
                    break
                offset += 8 + chunk_size + (chunk_size & 1)
    except OSError:
        return result
    return result


def inspect_pcm_wav(path: Path) -> WavMetadata:
    """Validate finalized or streaming-sentinel PCM RIFF/WAVE without trusting ``wave`` sizes."""
    path = Path(path)
    try:
        file_size = path.stat().st_size
        with path.open("rb") as source:
            header = source.read(12)
            if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                raise WavValidationError(f"Not a RIFF/WAVE file: {path}")

            riff_size = int.from_bytes(header[4:8], "little")
            riff_sentinel = riff_size == RIFF_SIZE_SENTINEL
            if riff_sentinel:
                container_end = file_size
            else:
                declared_file_size = riff_size + 8
                if declared_file_size < 12:
                    raise WavValidationError("RIFF size is too small for a WAVE container.")
                if file_size < declared_file_size:
                    raise WavTruncatedError(f"WAV ended before its declared RIFF size: {path}")
                if file_size > declared_file_size:
                    raise WavValidationError("WAV contains bytes beyond its finalized RIFF size.")
                container_end = declared_file_size

            fmt_payload: bytes | None = None
            data_size: int | None = None
            data_declared_size: int | None = None
            data_sentinel = False
            offset = 12
            while offset < container_end:
                if container_end - offset < 8:
                    raise WavValidationError("WAV contains an incomplete chunk header.")
                source.seek(offset)
                chunk_header = source.read(8)
                if len(chunk_header) != 8:
                    raise WavTruncatedError("WAV ended inside a chunk header.")
                chunk_id = chunk_header[:4]
                chunk_size = int.from_bytes(chunk_header[4:8], "little")
                payload_start = offset + 8

                if chunk_size == RIFF_SIZE_SENTINEL:
                    if chunk_id != b"data":
                        raise WavValidationError("Only a WAV data chunk may use the streaming size sentinel.")
                    if data_size is not None:
                        raise WavValidationError("WAV contains multiple data chunks.")
                    data_declared_size = chunk_size
                    data_sentinel = True
                    data_size = container_end - payload_start
                    offset = container_end
                    continue

                payload_end = payload_start + chunk_size
                padded_end = payload_end + (chunk_size & 1)
                if payload_end > container_end or padded_end > container_end:
                    raise WavTruncatedError(f"WAV ended before chunk {chunk_id!r} was complete.")
                if chunk_id == b"fmt ":
                    if fmt_payload is not None:
                        raise WavValidationError("WAV contains multiple fmt chunks.")
                    source.seek(payload_start)
                    fmt_payload = source.read(chunk_size)
                    if len(fmt_payload) != chunk_size:
                        raise WavTruncatedError("WAV ended inside its fmt chunk.")
                elif chunk_id == b"data":
                    if data_size is not None:
                        raise WavValidationError("WAV contains multiple data chunks.")
                    data_declared_size = chunk_size
                    data_size = chunk_size
                offset = padded_end
    except WavValidationError:
        raise
    except OSError as error:
        raise WavValidationError(f"Unreadable WAV: {path}") from error

    if fmt_payload is None or len(fmt_payload) < 16:
        raise WavValidationError("WAV fmt chunk is missing or incomplete.")
    if data_size is None or data_declared_size is None:
        raise WavValidationError("WAV data chunk is missing.")

    audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack(
        "<HHIIHH", fmt_payload[:16]
    )
    if audio_format != 1:
        raise WavValidationError(f"Unsupported compressed WAV encoding: format={audio_format}")
    if channels < 1 or channels > 8:
        raise WavValidationError(f"Invalid WAV channel count: {channels}")
    if bits_per_sample % 8:
        raise WavValidationError(f"Unsupported PCM bit depth: {bits_per_sample}")
    sample_width = bits_per_sample // 8
    if sample_width not in {1, 2, 3, 4}:
        raise WavValidationError(f"Unsupported PCM sample width: {sample_width}")
    if sample_rate < 8_000 or sample_rate > 384_000:
        raise WavValidationError(f"Invalid WAV sample rate: {sample_rate}")
    expected_block_align = channels * sample_width
    if block_align != expected_block_align or byte_rate != sample_rate * block_align:
        raise WavValidationError("WAV fmt chunk has inconsistent PCM alignment or byte rate.")
    if data_size <= 0:
        raise WavValidationError("WAV contains no audio frames.")
    if data_size % block_align:
        if data_sentinel:
            raise WavTruncatedError("Streaming WAV ended with an incomplete PCM frame.")
        raise WavValidationError("Finalized WAV data size is not aligned to complete PCM frames.")

    frames = data_size // block_align
    duration = frames / sample_rate
    if frames <= 0 or duration <= 0:
        raise WavValidationError("WAV duration is zero.")
    return WavMetadata(
        duration,
        sample_rate,
        channels,
        sample_width,
        frames,
        "NONE",
        data_size,
        block_align,
        riff_size,
        data_declared_size,
        riff_sentinel,
        data_sentinel,
    )


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
