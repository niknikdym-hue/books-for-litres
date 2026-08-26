"""Provider-neutral technical QA and persistent manual audio review.

The service is deliberately offline. It validates already-produced WAV files,
persists review state under the canonical Audiobook Studio workspace, and
never calls a synthesis provider. Manual approval is bound to the exact audio
bytes, path identity, and optional synthesis fingerprint so regenerated audio
can never inherit an old approval silently.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backends.common import WavValidationError, atomic_write_json, inspect_pcm_wav, utc_now_iso


QA_SCHEMA_VERSION = 1
AUTOMATIC_STATES = {"PASS", "WARN", "FAIL"}
MANUAL_STATES = {"UNREVIEWED", "APPROVED", "REJECTED", "REGENERATE_REQUESTED", "STALE"}
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class AudioQAError(RuntimeError):
    """Raised when QA/review input is unsafe or inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or not _ID_RE.fullmatch(value):
        raise AudioQAError(f"Invalid {label}: {value!r}")
    return value


def _path_identity(path: Path) -> str:
    resolved = str(Path(path).expanduser().resolve(strict=False))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _read_pcm16_samples(path: Path) -> list[int] | None:
    """Read PCM16 samples from finalized or streaming-sentinel RIFF/WAVE."""
    raw = Path(path).read_bytes()
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return None
    offset = 12
    data: bytes | None = None
    fmt: bytes | None = None
    while offset + 8 <= len(raw):
        chunk_id = raw[offset : offset + 4]
        declared = int.from_bytes(raw[offset + 4 : offset + 8], "little")
        payload_start = offset + 8
        if declared == 0xFFFFFFFF:
            if chunk_id != b"data":
                return None
            payload_end = len(raw)
        else:
            payload_end = payload_start + declared
            if payload_end > len(raw):
                return None
        payload = raw[payload_start:payload_end]
        if chunk_id == b"fmt ":
            fmt = payload
        elif chunk_id == b"data":
            data = payload
            break
        if declared == 0xFFFFFFFF:
            break
        offset = payload_end + (declared & 1)
    if fmt is None or data is None or len(fmt) < 16:
        return None
    audio_format, _channels, _sample_rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if audio_format != 1 or bits != 16 or len(data) % 2:
        return None
    count = len(data) // 2
    if count == 0:
        return []
    return list(struct.unpack(f"<{count}h", data))


def _signal_metrics(path: Path, sample_width_bytes: int) -> dict[str, Any]:
    if sample_width_bytes != 2:
        return {
            "available": False,
            "reason": "pcm16_required",
            "peak_fraction": None,
            "clipped_fraction": None,
            "near_silence_fraction": None,
        }
    samples = _read_pcm16_samples(path)
    if samples is None or not samples:
        return {
            "available": False,
            "reason": "samples_unavailable",
            "peak_fraction": None,
            "clipped_fraction": None,
            "near_silence_fraction": None,
        }
    absolute = [abs(value) for value in samples]
    peak = max(absolute) / 32768.0
    clipped = sum(1 for value in absolute if value >= 32760) / len(absolute)
    near_silence = sum(1 for value in absolute if value <= 64) / len(absolute)
    return {
        "available": True,
        "reason": None,
        "peak_fraction": round(peak, 8),
        "clipped_fraction": round(clipped, 8),
        "near_silence_fraction": round(near_silence, 8),
    }


def _ffmpeg_check(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffmpeg")
    if executable is None:
        return {"status": "UNAVAILABLE", "available": False, "exit_code": None}
    try:
        completed = subprocess.run(
            [executable, "-v", "error", "-i", str(path), "-f", "null", "-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "ERROR", "available": True, "exit_code": None}
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "available": True,
        "exit_code": completed.returncode,
    }


@dataclass(frozen=True)
class AudioQAReviewService:
    state_root: Path
    expected_sample_rate_hz: int = 24_000
    expected_channels: int = 1
    expected_sample_width_bytes: int = 2
    minimum_duration_seconds: float = 0.05

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_root", Path(self.state_root))

    def _record_path(self, *, book_slug: str, job_id: str, segment_id: str) -> Path:
        return (
            self.state_root
            / _safe_id(book_slug, "book_slug")
            / _safe_id(job_id, "job_id")
            / f"{_safe_id(segment_id, 'segment_id')}.json"
        )

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise AudioQAError(f"Invalid QA state: {path}") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != QA_SCHEMA_VERSION:
            raise AudioQAError(f"Unsupported QA state: {path}")
        return payload

    def scan(
        self,
        *,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        synthesis_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        path = Path(audio_path).expanduser()
        reasons: list[str] = []
        warnings: list[str] = []
        metadata_dict: dict[str, Any] | None = None
        audio_sha: str | None = None
        signal = {
            "available": False,
            "reason": "not_scanned",
            "peak_fraction": None,
            "clipped_fraction": None,
            "near_silence_fraction": None,
        }
        ffmpeg = {"status": "NOT_RUN", "available": False, "exit_code": None}

        if not path.exists():
            reasons.append("missing_file")
        elif not path.is_file() or path.is_symlink():
            reasons.append("not_regular_file")
        else:
            try:
                metadata = inspect_pcm_wav(path)
                metadata_dict = metadata.to_dict()
                audio_sha = sha256_file(path)
                if metadata.sample_rate_hz != self.expected_sample_rate_hz:
                    reasons.append("unexpected_sample_rate")
                if metadata.channels != self.expected_channels:
                    reasons.append("unexpected_channels")
                if metadata.sample_width_bytes != self.expected_sample_width_bytes:
                    reasons.append("unexpected_sample_width")
                if metadata.duration_seconds < self.minimum_duration_seconds:
                    reasons.append("duration_too_short")
                signal = _signal_metrics(path, metadata.sample_width_bytes)
                if signal["available"]:
                    if float(signal["clipped_fraction"] or 0.0) >= 0.01:
                        warnings.append("gross_clipping")
                    if float(signal["near_silence_fraction"] or 0.0) >= 0.98:
                        warnings.append("near_total_silence")
                else:
                    warnings.append("signal_metrics_unavailable")
                ffmpeg = _ffmpeg_check(path)
                if ffmpeg["status"] in {"FAIL", "ERROR"}:
                    reasons.append("ffmpeg_decode_failed")
                elif ffmpeg["status"] == "UNAVAILABLE":
                    warnings.append("ffmpeg_unavailable")
            except WavValidationError:
                reasons.append("invalid_or_truncated_wav")
            except OSError:
                reasons.append("unreadable_file")

        automatic_status = "FAIL" if reasons else ("WARN" if warnings else "PASS")
        if automatic_status not in AUTOMATIC_STATES:
            raise AssertionError("invalid automatic status")

        state_path = self._record_path(book_slug=book_slug, job_id=job_id, segment_id=segment_id)
        previous = self._read_record(state_path)
        identity = {
            "audio_sha256": audio_sha,
            "path_identity": _path_identity(path),
            "synthesis_fingerprint": synthesis_fingerprint,
        }
        previous_identity = (previous or {}).get("identity") if isinstance(previous, dict) else None
        same_identity = previous_identity == identity and audio_sha is not None
        previous_manual = (previous or {}).get("manual_state", "UNREVIEWED")
        if same_identity and previous_manual in MANUAL_STATES:
            manual_state = previous_manual
        elif previous is not None and previous_manual != "UNREVIEWED":
            manual_state = "STALE"
        else:
            manual_state = "UNREVIEWED"

        now = utc_now_iso()
        record = {
            "schema_version": QA_SCHEMA_VERSION,
            "book_slug": _safe_id(book_slug, "book_slug"),
            "job_id": _safe_id(job_id, "job_id"),
            "segment_id": _safe_id(segment_id, "segment_id"),
            "audio_path": str(path.resolve(strict=False)),
            "identity": identity,
            "automatic_status": automatic_status,
            "automatic_reasons": reasons,
            "automatic_warnings": warnings,
            "wav": metadata_dict,
            "signal_metrics": signal,
            "ffmpeg": ffmpeg,
            "manual_state": manual_state,
            "downstream_eligible": bool(
                automatic_status in {"PASS", "WARN"}
                and manual_state == "APPROVED"
                and audio_sha is not None
            ),
            "scanned_at": now,
            "manual_decided_at": (previous or {}).get("manual_decided_at") if same_identity else None,
            "created_at": (previous or {}).get("created_at") or now,
            "updated_at": now,
            "remote_request_sent": False,
        }
        atomic_write_json(state_path, record)
        return record

    def decide(
        self,
        *,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        decision: str,
        synthesis_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        normalized = decision.strip().upper()
        if normalized not in {"APPROVED", "REJECTED", "REGENERATE_REQUESTED"}:
            raise AudioQAError(f"Unsupported manual decision: {decision}")
        record = self.scan(
            book_slug=book_slug,
            job_id=job_id,
            segment_id=segment_id,
            audio_path=audio_path,
            synthesis_fingerprint=synthesis_fingerprint,
        )
        if normalized == "APPROVED" and record["automatic_status"] == "FAIL":
            raise AudioQAError("Technical QA FAIL cannot be approved.")
        record["manual_state"] = normalized
        record["manual_decided_at"] = utc_now_iso()
        record["updated_at"] = record["manual_decided_at"]
        record["downstream_eligible"] = bool(
            normalized == "APPROVED" and record["automatic_status"] in {"PASS", "WARN"}
        )
        record["remote_request_sent"] = False
        state_path = self._record_path(book_slug=book_slug, job_id=job_id, segment_id=segment_id)
        atomic_write_json(state_path, record)
        return record

    def status(self, *, book_slug: str, job_id: str, segment_id: str) -> dict[str, Any] | None:
        return self._read_record(self._record_path(book_slug=book_slug, job_id=job_id, segment_id=segment_id))

    def downstream_audio(
        self,
        *,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        synthesis_fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        record = self.scan(
            book_slug=book_slug,
            job_id=job_id,
            segment_id=segment_id,
            audio_path=audio_path,
            synthesis_fingerprint=synthesis_fingerprint,
        )
        return record if record["downstream_eligible"] else None
