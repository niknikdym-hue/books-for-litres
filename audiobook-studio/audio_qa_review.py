"""Provider-neutral, offline technical QA and exact-identity manual review."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Mapping

from backends.common import WavValidationError, atomic_write_json, inspect_pcm_wav, utc_now_iso
from book_library import BookLibraryError, normalize_slug
from media_tools import resolve_ffmpeg
from workspace_paths import load_workspace_paths
from production_authority_lock import production_authority_lock


QA_SCHEMA_VERSION = 3
AUTOMATIC_STATES = {"PASS", "WARN", "FAIL"}
MANUAL_STATES = {"UNREVIEWED", "APPROVED", "REJECTED", "REGENERATE_REQUESTED", "STALE"}
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_IDENTITY_FIELDS = ("audio_sha256", "path_identity", "synthesis_fingerprint")


class AudioQAError(RuntimeError):
    """Raised when QA/review input is unsafe or inconsistent."""


def _sha256_handle(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as handle:
        return _sha256_handle(handle)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@contextmanager
def _stable_audio_snapshot(path: Path) -> Iterator[tuple[Path, os.stat_result, bool]]:
    """Copy one opened inode so every expensive QA check reads identical bytes."""
    snapshot_path: Path | None = None
    try:
        with Path(path).open("rb") as source:
            before = os.fstat(source.fileno())
            with tempfile.NamedTemporaryFile(prefix="audiobook-qa-", suffix=".wav", delete=False) as target:
                snapshot_path = Path(target.name)
                shutil.copyfileobj(source, target, length=1024 * 1024)
            after = os.fstat(source.fileno())
        yield snapshot_path, before, _stat_identity(before) == _stat_identity(after)
    finally:
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)


def _path_still_matches_snapshot(
    path: Path,
    source_stat: os.stat_result,
    snapshot_sha256: str,
) -> bool:
    try:
        with Path(path).open("rb") as current:
            opened_stat = os.fstat(current.fileno())
            if _stat_identity(opened_stat) != _stat_identity(source_stat):
                return False
            current_sha256 = _sha256_handle(current)
            hashed_stat = os.fstat(current.fileno())
        final_path_stat = Path(path).stat()
        return bool(
            current_sha256 == snapshot_sha256
            and _stat_identity(opened_stat) == _stat_identity(hashed_stat)
            and _stat_identity(final_path_stat) == _stat_identity(hashed_stat)
        )
    except OSError:
        return False


def _safe_id(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not _ID_RE.fullmatch(value)
        or value in {".", ".."}
        or not value.strip(".")
    ):
        raise AudioQAError(f"Invalid {label}: {value!r}")
    return value


def _safe_book_slug(value: str) -> str:
    """Use the one canonical Book Library policy for persisted book identities."""
    try:
        return normalize_slug(value)
    except BookLibraryError as error:
        raise AudioQAError(f"Invalid book_slug: {value!r}") from error


def path_identity(path: Path) -> str:
    resolved = str(Path(path).expanduser().resolve(strict=False))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _validated_reviewed_identity(value: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise AudioQAError("The exact reviewed audio identity is required.")
    result: dict[str, str] = {}
    for field in _IDENTITY_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item:
            raise AudioQAError(f"Reviewed identity is missing {field}.")
        result[field] = item
    return result


def _pcm16_data_region(path: Path) -> tuple[int, int] | None:
    """Return the PCM data offset/size without loading the WAV payload."""
    file_size = Path(path).stat().st_size
    with Path(path).open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            return None
        offset = 12
        fmt: bytes | None = None
        while offset + 8 <= file_size:
            handle.seek(offset)
            chunk_header = handle.read(8)
            if len(chunk_header) != 8:
                return None
            chunk_id = chunk_header[:4]
            declared = int.from_bytes(chunk_header[4:], "little")
            payload_start = offset + 8
            if declared == 0xFFFFFFFF:
                if chunk_id != b"data":
                    return None
                payload_size = file_size - payload_start
            else:
                payload_size = declared
                if payload_start + payload_size > file_size:
                    return None
            if chunk_id == b"fmt ":
                if payload_size < 16 or payload_size > 4096:
                    return None
                handle.seek(payload_start)
                fmt = handle.read(payload_size)
            elif chunk_id == b"data":
                if fmt is None or len(fmt) < 16 or payload_size % 2:
                    return None
                audio_format, _channels, _rate, _byte_rate, _align, bits = struct.unpack(
                    "<HHIIHH", fmt[:16]
                )
                if audio_format != 1 or bits != 16:
                    return None
                return payload_start, payload_size
            if declared == 0xFFFFFFFF:
                return None
            offset = payload_start + payload_size + (payload_size & 1)
    return None


def _signal_metrics(path: Path, sample_width_bytes: int, *, chunk_bytes: int = 65_536) -> dict[str, Any]:
    """Compute PCM16 metrics with memory bounded by ``chunk_bytes``."""
    unavailable = {
        "available": False,
        "reason": "pcm16_required" if sample_width_bytes != 2 else "samples_unavailable",
        "peak_fraction": None,
        "clipped_fraction": None,
        "near_silence_fraction": None,
        "sample_count": 0,
        "stream_chunk_bytes": chunk_bytes,
    }
    if sample_width_bytes != 2:
        return unavailable
    region = _pcm16_data_region(path)
    if region is None:
        return unavailable
    data_offset, data_size = region
    peak = clipped = near_silence = sample_count = 0
    with Path(path).open("rb") as handle:
        handle.seek(data_offset)
        remaining = data_size
        while remaining:
            payload = handle.read(min(chunk_bytes, remaining))
            if not payload:
                return unavailable
            remaining -= len(payload)
            for (sample,) in struct.iter_unpack("<h", payload):
                absolute = abs(sample)
                peak = max(peak, absolute)
                clipped += int(absolute >= 32760)
                near_silence += int(absolute <= 64)
                sample_count += 1
    if not sample_count:
        return unavailable
    return {
        "available": True,
        "reason": None,
        "peak_fraction": round(peak / 32768.0, 8),
        "clipped_fraction": round(clipped / sample_count, 8),
        "near_silence_fraction": round(near_silence / sample_count, 8),
        "sample_count": sample_count,
        "stream_chunk_bytes": chunk_bytes,
    }


def _ffmpeg_check(path: Path) -> dict[str, Any]:
    resolution = resolve_ffmpeg(load_workspace_paths().root)
    if not resolution.available or resolution.path is None:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "exit_code": None,
            "path": None,
            "version": None,
            "source": resolution.source,
        }
    try:
        completed = subprocess.run(
            [str(resolution.path), "-v", "error", "-i", str(path), "-f", "null", "-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "ERROR",
            "available": True,
            "exit_code": None,
            "path": str(resolution.path),
            "version": resolution.version,
            "source": resolution.source,
        }
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "available": True,
        "exit_code": completed.returncode,
        "path": str(resolution.path),
        "version": resolution.version,
        "source": resolution.source,
    }


@dataclass(frozen=True)
class AudioQAReviewService:
    state_root: Path
    expected_channels: int = 1
    expected_sample_width_bytes: int = 2
    absolute_minimum_duration_seconds: float = 0.05
    conservative_seconds_per_character: float = 0.015
    maximum_text_derived_minimum_seconds: float = 30.0
    metrics_chunk_bytes: int = 65_536

    def __post_init__(self) -> None:
        root = Path(self.state_root).expanduser().resolve(strict=False)
        if self.metrics_chunk_bytes <= 0 or self.metrics_chunk_bytes % 2:
            raise ValueError("metrics_chunk_bytes must be a positive even number")
        object.__setattr__(self, "state_root", root)

    def _record_path(
        self,
        *,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
    ) -> Path:
        candidate = (
            self.state_root
            / _safe_book_slug(book_slug)
            / _safe_id(provider, "provider")
            / _safe_id(profile_id, "profile_id")
            / _safe_id(job_id, "job_id")
            / f"{_safe_id(segment_id, 'segment_id')}.json"
        ).resolve(strict=False)
        try:
            candidate.relative_to(self.state_root)
        except ValueError as error:
            raise AudioQAError("QA record path escapes the canonical state root.") from error
        if candidate == self.state_root:
            raise AudioQAError("QA record path must be below the canonical state root.")
        return candidate

    @contextmanager
    def _locked_record(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix(path.suffix + ".lock")
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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

    def _minimum_duration(self, text_characters: int) -> float:
        derived = max(0, text_characters - 2) * self.conservative_seconds_per_character
        return max(
            self.absolute_minimum_duration_seconds,
            min(self.maximum_text_derived_minimum_seconds, derived),
        )

    def _scan_locked(
        self,
        *,
        state_path: Path,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        synthesis_fingerprint: str | None,
        expected_sample_rate_hz: int,
        text_characters: int,
    ) -> dict[str, Any]:
        if expected_sample_rate_hz <= 0:
            raise AudioQAError("Expected sample rate must be positive.")
        if text_characters < 0:
            raise AudioQAError("Text character count cannot be negative.")
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
            "sample_count": 0,
            "stream_chunk_bytes": self.metrics_chunk_bytes,
        }
        ffmpeg = {"status": "NOT_RUN", "available": False, "exit_code": None}
        minimum_duration = self._minimum_duration(text_characters)
        if not isinstance(synthesis_fingerprint, str) or not synthesis_fingerprint:
            reasons.append("current_synthesis_fingerprint_unavailable")

        if not path.exists():
            reasons.append("missing_file")
        elif not path.is_file() or path.is_symlink():
            reasons.append("not_regular_file")
        else:
            try:
                with _stable_audio_snapshot(path) as (snapshot, source_stat, source_stable):
                    metadata = inspect_pcm_wav(snapshot)
                    metadata_dict = metadata.to_dict()
                    audio_sha = sha256_file(snapshot)
                    if metadata.sample_rate_hz != expected_sample_rate_hz:
                        reasons.append("unexpected_sample_rate")
                    if metadata.channels != self.expected_channels:
                        reasons.append("unexpected_channels")
                    if metadata.sample_width_bytes != self.expected_sample_width_bytes:
                        reasons.append("unexpected_sample_width")
                    if metadata.duration_seconds < minimum_duration:
                        reasons.append("implausibly_short_for_text")
                    signal = _signal_metrics(
                        snapshot,
                        metadata.sample_width_bytes,
                        chunk_bytes=self.metrics_chunk_bytes,
                    )
                    if signal["available"]:
                        if float(signal["clipped_fraction"] or 0.0) >= 0.01:
                            warnings.append("gross_clipping")
                        if float(signal["near_silence_fraction"] or 0.0) >= 0.98:
                            warnings.append("near_total_silence")
                    else:
                        warnings.append("signal_metrics_unavailable")
                    ffmpeg = _ffmpeg_check(snapshot)
                    if ffmpeg["status"] in {"FAIL", "ERROR"}:
                        reasons.append("ffmpeg_decode_failed")
                    elif ffmpeg["status"] == "UNAVAILABLE":
                        warnings.append("ffmpeg_unavailable")
                    if not source_stable or not _path_still_matches_snapshot(
                        path, source_stat, audio_sha
                    ):
                        reasons.append("audio_changed_during_scan")
                        audio_sha = None
            except WavValidationError:
                reasons.append("invalid_or_truncated_wav")
            except OSError:
                reasons.append("unreadable_file")

        automatic_status = "FAIL" if reasons else ("WARN" if warnings else "PASS")
        previous = self._read_record(state_path)
        identity = {
            "audio_sha256": audio_sha,
            "path_identity": path_identity(path),
            "synthesis_fingerprint": synthesis_fingerprint,
        }
        previous_identity = (previous or {}).get("identity") if isinstance(previous, dict) else None
        same_identity = previous_identity == identity and audio_sha is not None and bool(synthesis_fingerprint)
        previous_manual = (previous or {}).get("manual_state", "UNREVIEWED")
        if same_identity and previous_manual in MANUAL_STATES:
            manual_state = previous_manual
        elif previous is not None and previous_manual != "UNREVIEWED":
            manual_state = "STALE"
        else:
            manual_state = "UNREVIEWED"
        downstream_eligible = bool(
            automatic_status in {"PASS", "WARN"}
            and manual_state == "APPROVED"
            and audio_sha is not None
            and synthesis_fingerprint
            and same_identity
        )
        now = utc_now_iso()
        record = {
            "schema_version": QA_SCHEMA_VERSION,
            "provider": _safe_id(provider, "provider"),
            "profile_id": _safe_id(profile_id, "profile_id"),
            "book_slug": _safe_book_slug(book_slug),
            "job_id": _safe_id(job_id, "job_id"),
            "segment_id": _safe_id(segment_id, "segment_id"),
            "audio_path": str(path.resolve(strict=False)),
            "identity": identity,
            "production_facts": {
                "expected_sample_rate_hz": expected_sample_rate_hz,
                "text_characters": text_characters,
                "minimum_expected_duration_seconds": round(minimum_duration, 6),
            },
            "automatic_status": automatic_status,
            "automatic_reasons": list(dict.fromkeys(reasons)),
            "automatic_warnings": list(dict.fromkeys(warnings)),
            "wav": metadata_dict,
            "signal_metrics": signal,
            "ffmpeg": ffmpeg,
            "manual_state": manual_state,
            "downstream_eligible": downstream_eligible,
            "scanned_at": now,
            "manual_decided_at": (previous or {}).get("manual_decided_at") if same_identity else None,
            "created_at": (previous or {}).get("created_at") or now,
            "updated_at": now,
            "remote_request_sent": False,
        }
        atomic_write_json(state_path, record)
        return record

    def scan(
        self,
        *,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        synthesis_fingerprint: str | None,
        expected_sample_rate_hz: int,
        text_characters: int,
    ) -> dict[str, Any]:
        state_path = self._record_path(
            provider=provider,
            profile_id=profile_id,
            book_slug=book_slug,
            job_id=job_id,
            segment_id=segment_id,
        )
        with self._locked_record(state_path):
            return self._scan_locked(
                state_path=state_path,
                provider=provider,
                profile_id=profile_id,
                book_slug=book_slug,
                job_id=job_id,
                segment_id=segment_id,
                audio_path=audio_path,
                synthesis_fingerprint=synthesis_fingerprint,
                expected_sample_rate_hz=expected_sample_rate_hz,
                text_characters=text_characters,
            )

    def decide(
        self,
        *,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        decision: str,
        synthesis_fingerprint: str | None,
        expected_sample_rate_hz: int,
        text_characters: int,
        reviewed_identity: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        workspace_root = (
            self.state_root.parent.parent
            if self.state_root.parent.name == "runtime"
            else self.state_root.parent
        )
        with production_authority_lock(
            workspace_root,
            provider=provider,
            book_slug=book_slug,
            job_id=job_id,
            profile_id=profile_id,
            exclusive=True,
        ):
            return self._decide_locked(
                provider=provider,
                profile_id=profile_id,
                book_slug=book_slug,
                job_id=job_id,
                segment_id=segment_id,
                audio_path=audio_path,
                decision=decision,
                synthesis_fingerprint=synthesis_fingerprint,
                expected_sample_rate_hz=expected_sample_rate_hz,
                text_characters=text_characters,
                reviewed_identity=reviewed_identity,
            )

    def _decide_locked(
        self,
        *,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        decision: str,
        synthesis_fingerprint: str | None,
        expected_sample_rate_hz: int,
        text_characters: int,
        reviewed_identity: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        normalized = decision.strip().upper()
        if normalized not in {"APPROVED", "REJECTED", "REGENERATE_REQUESTED"}:
            raise AudioQAError(f"Unsupported manual decision: {decision}")
        expected_identity = _validated_reviewed_identity(reviewed_identity)
        state_path = self._record_path(
            provider=provider,
            profile_id=profile_id,
            book_slug=book_slug,
            job_id=job_id,
            segment_id=segment_id,
        )
        with self._locked_record(state_path):
            record = self._scan_locked(
                state_path=state_path,
                provider=provider,
                profile_id=profile_id,
                book_slug=book_slug,
                job_id=job_id,
                segment_id=segment_id,
                audio_path=audio_path,
                synthesis_fingerprint=synthesis_fingerprint,
                expected_sample_rate_hz=expected_sample_rate_hz,
                text_characters=text_characters,
            )
            if record["identity"] != expected_identity:
                now = utc_now_iso()
                record.update({
                    "manual_state": "STALE",
                    "downstream_eligible": False,
                    "manual_decided_at": None,
                    "updated_at": now,
                })
                atomic_write_json(state_path, record)
                raise AudioQAError("Reviewed audio identity is stale; decision rejected.")
            if normalized == "APPROVED" and record["automatic_status"] == "FAIL":
                raise AudioQAError("Technical QA FAIL cannot be approved.")
            now = utc_now_iso()
            record.update({
                "manual_state": normalized,
                "manual_decided_at": now,
                "updated_at": now,
                "downstream_eligible": bool(
                    normalized == "APPROVED"
                    and record["automatic_status"] in {"PASS", "WARN"}
                    and all(record["identity"].get(field) for field in _IDENTITY_FIELDS)
                ),
                "remote_request_sent": False,
            })
            atomic_write_json(state_path, record)
            return record

    def status(
        self,
        *,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
    ) -> dict[str, Any] | None:
        state_path = self._record_path(
            provider=provider,
            profile_id=profile_id,
            book_slug=book_slug,
            job_id=job_id,
            segment_id=segment_id,
        )
        with self._locked_record(state_path):
            return self._read_record(state_path)

    def downstream_audio(
        self,
        *,
        provider: str,
        profile_id: str,
        book_slug: str,
        job_id: str,
        segment_id: str,
        audio_path: Path,
        synthesis_fingerprint: str | None,
        expected_sample_rate_hz: int,
        text_characters: int,
    ) -> dict[str, Any] | None:
        record = self.scan(
            provider=provider,
            profile_id=profile_id,
            book_slug=book_slug,
            job_id=job_id,
            segment_id=segment_id,
            audio_path=audio_path,
            synthesis_fingerprint=synthesis_fingerprint,
            expected_sample_rate_hz=expected_sample_rate_hz,
            text_characters=text_characters,
        )
        return record if record["downstream_eligible"] else None
