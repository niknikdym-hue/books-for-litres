"""Offline provider-neutral mastering and LitRes chapter export.

Every operation is derived from an exact-current chapter assembly or master.
The module never calls a TTS provider and publishes only immutable derived
artifacts below the canonical ``masters`` and ``exports`` workspace roots.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from audio_qa_review import path_identity, sha256_file
from backends.common import atomic_write_json, inspect_pcm_wav, utc_now_iso
from book_library import BookLibraryError, normalize_slug
from media_tools import FFmpegResolution, resolve_ffmpeg
from production_authority_lock import production_authority_lock


MASTER_SCHEMA_VERSION = 1
EXPORT_SCHEMA_VERSION = 1
MASTER_PRESET_ID = "spoken_word_master_v1"
BOUNDARY_POLICY_ID = "conservative_boundary_padding_v1"
LITRES_PROFILE_ID = "litres_author_v1"
TARGET_SAMPLE_RATE_HZ = 48_000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH_BYTES = 2

MASTER_PRESET: dict[str, Any] = {
    "id": MASTER_PRESET_ID,
    "version": 1,
    "target_integrated_lufs": -19.0,
    "true_peak_ceiling_dbtp": -3.0,
    "loudness_range_target_lu": 11.0,
    "integrated_loudness_tolerance_lu": 0.5,
    "true_peak_tolerance_db": 0.2,
    "sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
    "channels": TARGET_CHANNELS,
    "sample_width_bytes": TARGET_SAMPLE_WIDTH_BYTES,
    "processing": "two_pass_ffmpeg_loudnorm_linear_v1",
    "compression": False,
    "eq": False,
    "denoise": False,
}

BOUNDARY_POLICY: dict[str, Any] = {
    "id": BOUNDARY_POLICY_ID,
    "version": 1,
    "measurement_threshold_dbfs": -50.0,
    "minimum_leading_silence_seconds": 0.5,
    "minimum_trailing_silence_seconds": 1.0,
    "trim": "disabled",
    "mid_chapter_silence": "preserve",
    "post_mastering_minimum_enforcement": True,
    "preferred_maximum_leading_silence_seconds": 2.0,
    "preferred_maximum_trailing_silence_seconds": 3.0,
}

LITRES_PROFILE: dict[str, Any] = {
    "id": LITRES_PROFILE_ID,
    "version": 1,
    "container": "MP3",
    "channels": 2,
    "stereo_contract": "dual_mono_v1",
    "sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
    "bitrate_bps": 128_000,
    "bitrate_mode": "CBR",
    "cover_art_contract": "canonical_attached_pic_if_configured_v1",
    "max_duration_seconds": 3 * 60 * 60,
    "max_file_bytes": 170 * 1024 * 1024,
    "max_book_files": 500,
    "duration_tolerance_seconds": 0.25,
}


class MasteringExportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def master_preset_hash() -> str:
    return _canonical_hash({"preset": MASTER_PRESET, "boundary_policy": BOUNDARY_POLICY})


def litres_profile_hash() -> str:
    return _canonical_hash(LITRES_PROFILE)


def _safe_slug(value: Any) -> str:
    try:
        return normalize_slug(str(value or ""))
    except BookLibraryError as error:
        raise MasteringExportError("invalid_book_slug", "Некорректный идентификатор книги.") from error


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise MasteringExportError("invalid_identity", f"Некорректный {label}.")
    return value


def _safe_output_name(position: int, title: str) -> str:
    normalized = unicodedata.normalize("NFC", title).strip()
    normalized = re.sub(r"[\x00-\x1f/:\\]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .") or f"Глава {position}"
    prefix = f"{position:03d} — "
    suffix = ".mp3"
    byte_budget = 255 - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
    encoded_bytes = 0
    safe_characters: list[str] = []
    for character in normalized:
        character_bytes = len(character.encode("utf-8"))
        if encoded_bytes + character_bytes > byte_budget:
            break
        safe_characters.append(character)
        encoded_bytes += character_bytes
    bounded = "".join(safe_characters).rstrip(" .") or f"Глава {position}"
    return f"{prefix}{bounded}{suffix}"


def _require_regular_path(path: Path, *, root: Path, label: str) -> Path:
    requested_root = Path(root).expanduser().absolute()
    if requested_root.is_symlink():
        raise MasteringExportError("symlink_root", f"{label}: корневой каталог является ссылкой.")
    boundary = requested_root.resolve(strict=True)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise MasteringExportError("path_escape", f"{label} находится вне рабочего пространства.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise MasteringExportError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise MasteringExportError("symlink_input", f"{label} содержит символическую ссылку.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise MasteringExportError("invalid_input", f"{label} должен быть обычным файлом.")
    return resolved


def _prepare_output_parent(workspace_root: Path, parent: Path) -> None:
    workspace = Path(workspace_root).resolve(strict=True)
    requested = Path(parent).absolute()
    try:
        relative = requested.relative_to(workspace)
    except ValueError as error:
        raise MasteringExportError("output_root_escape", "Каталог результата вне рабочего пространства.") from error
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise MasteringExportError("symlink_output_root", "Каталог результата содержит ссылку.")
        current.mkdir(exist_ok=True)


def _validate_output_root(workspace_root: Path, output_root: Path, label: str) -> Path:
    workspace = Path(workspace_root).expanduser().absolute()
    if workspace.is_symlink():
        raise MasteringExportError("symlink_workspace_root", "Workspace root является ссылкой.")
    workspace = workspace.resolve(strict=True)
    requested = Path(output_root).expanduser().absolute()
    try:
        relative = requested.relative_to(workspace)
    except ValueError as error:
        raise MasteringExportError("output_root_escape", f"{label} вне рабочего пространства.") from error
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise MasteringExportError("symlink_output_root", f"{label} содержит символическую ссылку.")
    return requested


def _file_snapshot(path: Path) -> tuple[int, int, int, int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _resolution_identity(value: FFmpegResolution) -> dict[str, Any]:
    if not value.available or value.path is None or not value.version:
        return {"available": False, "path": None, "path_identity": None, "version": None}
    return {
        "available": True,
        "path": str(value.path),
        "path_identity": path_identity(value.path),
        "version": value.version,
        "source": value.source,
    }


def _prepared_ffmpeg(value: Mapping[str, Any]) -> FFmpegResolution:
    return FFmpegResolution(
        bool(value.get("available")),
        Path(value["path"]) if value.get("path") else None,
        value.get("version"),
        str(value.get("source") or "unavailable"),
    )


def resolve_current_assembly(
    *,
    workspace_root: Path,
    chapters_root: Path,
    book_slug: str,
    job_id: str,
    expected_assembly_identity: str | None = None,
) -> dict[str, Any]:
    """Resolve an immutable exact-current CHAPTER_ASSEMBLY_V1 authority."""
    root = Path(workspace_root).expanduser().resolve(strict=True)
    book = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    chapter_root = Path(chapters_root).absolute() / book / job
    pointer_path = _require_regular_path(chapter_root / "CURRENT.json", root=root, label="Assembly CURRENT")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MasteringExportError("invalid_assembly_pointer", "CURRENT сборки повреждён.") from error
    identity = _safe_id(pointer.get("assembly_identity"), "assembly_identity")
    if expected_assembly_identity is not None and identity != expected_assembly_identity:
        raise MasteringExportError("stale_assembly", "Сборка главы устарела.")
    canonical_dir = chapter_root / identity
    manifest_path = _require_regular_path(
        canonical_dir / "MANIFEST.json", root=root, label="Assembly manifest"
    )
    wav_path = _require_regular_path(canonical_dir / "chapter.wav", root=root, label="Assembly WAV")
    if pointer.get("manifest_path") != str(manifest_path):
        raise MasteringExportError("assembly_manifest_identity_mismatch", "CURRENT указывает не на canonical manifest.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MasteringExportError("invalid_assembly_manifest", "Manifest сборки повреждён.") from error
    output = manifest.get("output") if isinstance(manifest, dict) else None
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "READY"
        or manifest.get("assembly_identity") != identity
        or manifest.get("book_slug") != book
        or manifest.get("job_id") != job
        or not isinstance(output, Mapping)
        or output.get("path") != str(wav_path)
        or output.get("path_identity") != path_identity(wav_path)
        or output.get("sha256") != sha256_file(wav_path)
    ):
        raise MasteringExportError("assembly_identity_mismatch", "Точная identity сборки не подтверждена.")
    try:
        wav = inspect_pcm_wav(wav_path).to_dict()
    except Exception as error:
        raise MasteringExportError("corrupt_assembly_wav", "Собранный WAV повреждён.") from error
    if output.get("wav") != wav or any((
        wav["sample_rate_hz"] != TARGET_SAMPLE_RATE_HZ,
        wav["channels"] != TARGET_CHANNELS,
        wav["sample_width_bytes"] != TARGET_SAMPLE_WIDTH_BYTES,
        wav["compression_type"] != "NONE",
    )):
        raise MasteringExportError("invalid_assembly_format", "Сборка не соответствует WAV PCM16 mono 48 kHz.")
    return {
        "schema_version": 1,
        "assembly_identity": identity,
        "assembly_manifest_path": str(manifest_path),
        "assembly_manifest_sha256": sha256_file(manifest_path),
        "audio_path": str(wav_path),
        "audio_sha256": output["sha256"],
        "path_identity": output["path_identity"],
        "wav": wav,
        "book_slug": book,
        "book_title": str(manifest.get("book_title") or ""),
        "job_id": job,
        "job_label": str(manifest.get("job_label") or job),
        "provider": _safe_id(manifest.get("input", {}).get("provider"), "provider"),
        "profile_id": _safe_id(manifest.get("input", {}).get("profile_id"), "profile_id"),
        "input_granularity": manifest.get("input_granularity"),
        "ordered_inputs": manifest.get("ordered_inputs"),
        "provider_requests": 0,
    }


def _boundary_measurements(path: Path) -> dict[str, Any]:
    threshold = 32767.0 * (10.0 ** (float(BOUNDARY_POLICY["measurement_threshold_dbfs"]) / 20.0))
    with wave.open(str(path), "rb") as source:
        frames = source.getnframes()
        rate = source.getframerate()
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise MasteringExportError("invalid_pcm", "Boundary analysis требует mono PCM16.")
        first = frames
        offset = 0
        while offset < frames:
            count = min(65_536, frames - offset)
            data = source.readframes(count)
            for index, (sample,) in enumerate(struct.iter_unpack("<h", data)):
                if abs(sample) > threshold:
                    first = offset + index
                    break
            if first != frames:
                break
            offset += count
        last = frames
        end = frames
        while end > 0:
            count = min(65_536, end)
            start = end - count
            source.setpos(start)
            values = list(struct.iter_unpack("<h", source.readframes(count)))
            for reverse_index, (sample,) in enumerate(reversed(values)):
                if abs(sample) > threshold:
                    last = frames - (start + count - reverse_index - 1) - 1
                    break
            if last != frames:
                break
            end = start
    return {
        "threshold_dbfs": BOUNDARY_POLICY["measurement_threshold_dbfs"],
        "leading_silence_seconds": first / rate,
        "trailing_silence_seconds": last / rate,
        "total_frames": frames,
    }


def _signal_measurements(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as source:
        frames = source.getnframes()
        count = 0
        sum_squares = 0.0
        peak = 0
        clipped = 0
        window = max(1, source.getframerate() // 10)
        window_count = 0
        window_squares = 0.0
        window_levels: list[float] = []
        while True:
            data = source.readframes(65_536)
            if not data:
                break
            for (value,) in struct.iter_unpack("<h", data):
                square = float(value) * float(value)
                count += 1
                sum_squares += square
                peak = max(peak, abs(value))
                clipped += int(abs(value) >= 32767)
                window_count += 1
                window_squares += square
                if window_count == window:
                    chunk_rms = math.sqrt(window_squares / window_count)
                    window_levels.append(20.0 * math.log10(max(chunk_rms / 32768.0, 1e-12)))
                    window_count = 0
                    window_squares = 0.0
        if window_count:
            chunk_rms = math.sqrt(window_squares / window_count)
            window_levels.append(20.0 * math.log10(max(chunk_rms / 32768.0, 1e-12)))
    if not count:
        raise MasteringExportError("silent_or_empty_output", "Master WAV не содержит аудио.")
    rms = math.sqrt(sum_squares / count)
    rms_dbfs = 20.0 * math.log10(max(rms / 32768.0, 1e-12))
    peak_dbfs = 20.0 * math.log10(max(peak / 32768.0, 1e-12))
    ordered = sorted(window_levels)
    noise_floor = ordered[min(len(ordered) - 1, max(0, len(ordered) // 10))]
    return {
        "rms_dbfs": rms_dbfs,
        "sample_peak_dbfs": peak_dbfs,
        "estimated_noise_floor_dbfs": noise_floor,
        "clipped_samples": clipped,
    }


def _parse_loudnorm_json(stderr: bytes | str) -> dict[str, float]:
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    matches = re.findall(r"\{[^{}]*\}", text, flags=re.DOTALL)
    if not matches:
        raise MasteringExportError("loudness_measurement_unavailable", "FFmpeg не вернул loudnorm measurements.")
    try:
        raw = json.loads(matches[-1])
    except (TypeError, ValueError) as error:
        raise MasteringExportError("invalid_loudness_measurement", "Loudnorm measurements повреждены.") from error
    result: dict[str, float] = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            value = float(raw[key])
        except (KeyError, TypeError, ValueError) as error:
            raise MasteringExportError("invalid_loudness_measurement", f"Отсутствует {key}.") from error
        if not math.isfinite(value) or abs(value) > 200:
            raise MasteringExportError("invalid_loudness_measurement", f"Некорректное значение {key}.")
        result[key] = value
    return result


def _redact_arguments(arguments: Sequence[str], replacements: Mapping[str, str]) -> list[str]:
    return [replacements.get(item, item) for item in arguments]


@dataclass
class MasteringService:
    workspace_root: Path
    masters_root: Path

    def __post_init__(self) -> None:
        workspace_requested = Path(self.workspace_root).expanduser().absolute()
        requested = _validate_output_root(workspace_requested, self.masters_root, "Masters root")
        workspace = workspace_requested.resolve(strict=True)
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "masters_root", requested)

    def _resolution(self) -> FFmpegResolution:
        return resolve_ffmpeg(self.workspace_root)

    def _validate_assembly(self, value: Mapping[str, Any]) -> tuple[dict[str, Any], Path, Path]:
        payload = json.loads(json.dumps(value, ensure_ascii=False))
        book = _safe_slug(payload.get("book_slug"))
        job = _safe_id(payload.get("job_id"), "job_id")
        identity = _safe_id(payload.get("assembly_identity"), "assembly_identity")
        canonical = self.workspace_root / "chapters" / book / job / identity
        manifest = _require_regular_path(canonical / "MANIFEST.json", root=self.workspace_root, label="Assembly manifest")
        audio = _require_regular_path(canonical / "chapter.wav", root=self.workspace_root, label="Assembly WAV")
        if payload.get("assembly_manifest_path") != str(manifest) or payload.get("audio_path") != str(audio):
            raise MasteringExportError("assembly_path_identity_mismatch", "Assembly path identity изменилась.")
        if payload.get("assembly_manifest_sha256") != sha256_file(manifest):
            raise MasteringExportError("assembly_manifest_changed", "Assembly manifest изменился.")
        if payload.get("audio_sha256") != sha256_file(audio) or payload.get("path_identity") != path_identity(audio):
            raise MasteringExportError("assembly_audio_changed", "Assembly WAV изменился.")
        facts = inspect_pcm_wav(audio).to_dict()
        if payload.get("wav") != facts:
            raise MasteringExportError("assembly_wav_changed", "PCM facts сборки изменились.")
        payload.update({"book_slug": book, "job_id": job, "assembly_identity": identity})
        return payload, audio, manifest

    def _identity(self, payload: Mapping[str, Any], ffmpeg: FFmpegResolution) -> str:
        return _canonical_hash({
            "schema_version": MASTER_SCHEMA_VERSION,
            "assembly_identity": payload["assembly_identity"],
            "assembly_manifest_sha256": payload["assembly_manifest_sha256"],
            "input_sha256": payload["audio_sha256"],
            "preset": MASTER_PRESET,
            "preset_hash": master_preset_hash(),
            "boundary_policy": BOUNDARY_POLICY,
            "tool": _resolution_identity(ffmpeg),
        })

    def _output_dir(self, payload: Mapping[str, Any], identity: str) -> Path:
        return self.masters_root / payload["book_slug"] / payload["job_id"] / identity

    def _publish_current_pointer(self, payload: Mapping[str, Any], identity: str) -> None:
        output_dir = self._output_dir(payload, identity)
        atomic_write_json(output_dir.parent / "CURRENT.json", {
            "schema_version": MASTER_SCHEMA_VERSION,
            "master_identity": identity,
            "manifest_path": str(output_dir / "MANIFEST.json"),
            "updated_at": utc_now_iso(),
        })

    def prepare(self, value: Mapping[str, Any]) -> dict[str, Any]:
        payload, _, _ = self._validate_assembly(value)
        ffmpeg = self._resolution()
        blockers = [] if ffmpeg.available else ["missing_ffmpeg"]
        identity = self._identity(payload, ffmpeg)
        output_dir = self._output_dir(payload, identity)
        existing = self._read_ready(output_dir, identity)
        return {
            "schema_version": MASTER_SCHEMA_VERSION,
            "state": "READY" if existing else ("BLOCKED" if blockers else "PREPARED"),
            "decision": "ALREADY_MASTERED" if existing else ("BLOCKED" if blockers else "READY_TO_MASTER"),
            "blockers": blockers,
            "blocker_message": "Для мастеринга требуется FFmpeg." if blockers else None,
            "master_preset": MASTER_PRESET,
            "master_preset_hash": master_preset_hash(),
            "boundary_policy": BOUNDARY_POLICY,
            "master_identity": identity,
            "assembly": payload,
            "ffmpeg": ffmpeg.to_dict(),
            "manifest_path": str(output_dir / "MANIFEST.json") if existing else None,
            "master": existing,
            "provider_requests": 0,
            "remote_request_sent": False,
            "billing_changed": False,
        }

    @staticmethod
    def _run(arguments: Sequence[str], *, timeout: int = 900) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(arguments, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MasteringExportError("ffmpeg_failed", "FFmpeg не завершил обработку.") from error

    def _measure_loudness(self, ffmpeg: Path, source: Path) -> tuple[dict[str, float], list[str]]:
        audio_filter = (
            f"loudnorm=I={MASTER_PRESET['target_integrated_lufs']}:"
            f"TP={MASTER_PRESET['true_peak_ceiling_dbtp']}:"
            f"LRA={MASTER_PRESET['loudness_range_target_lu']}:print_format=json"
        )
        arguments = [
            str(ffmpeg), "-nostdin", "-hide_banner", "-i", str(source),
            "-af", audio_filter, "-f", "null", "-",
        ]
        completed = self._run(arguments)
        if completed.returncode != 0:
            raise MasteringExportError("loudness_analysis_failed", "FFmpeg loudness analysis завершился ошибкой.")
        return _parse_loudnorm_json(completed.stderr), _redact_arguments(
            arguments, {str(ffmpeg): "<ffmpeg>", str(source): "<input>"}
        )

    @staticmethod
    def _apply_boundary_padding(source: Path, destination: Path) -> dict[str, Any]:
        before = _boundary_measurements(source)
        lead = max(0.0, float(BOUNDARY_POLICY["minimum_leading_silence_seconds"]) - before["leading_silence_seconds"])
        tail = max(0.0, float(BOUNDARY_POLICY["minimum_trailing_silence_seconds"]) - before["trailing_silence_seconds"])
        lead_frames = math.ceil(lead * TARGET_SAMPLE_RATE_HZ - 1e-12)
        tail_frames = math.ceil(tail * TARGET_SAMPLE_RATE_HZ - 1e-12)
        with wave.open(str(source), "rb") as reader, wave.open(str(destination), "wb") as writer:
            writer.setnchannels(reader.getnchannels())
            writer.setsampwidth(reader.getsampwidth())
            writer.setframerate(reader.getframerate())
            writer.writeframesraw(b"\x00\x00" * lead_frames)
            while True:
                chunk = reader.readframes(65_536)
                if not chunk:
                    break
                writer.writeframesraw(chunk)
            writer.writeframes(b"\x00\x00" * tail_frames)
        after = _boundary_measurements(destination)
        return {
            "policy": BOUNDARY_POLICY,
            "before": before,
            "added_leading_frames": lead_frames,
            "added_trailing_frames": tail_frames,
            "added_leading_seconds": lead_frames / TARGET_SAMPLE_RATE_HZ,
            "added_trailing_seconds": tail_frames / TARGET_SAMPLE_RATE_HZ,
            "after_padding_before_mastering": after,
            "trimmed_frames": 0,
        }

    def master(
        self,
        value: Mapping[str, Any],
        *,
        revalidate: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        provider = _safe_id(value.get("provider"), "provider")
        profile = _safe_id(value.get("profile_id"), "profile_id")
        book = _safe_slug(value.get("book_slug"))
        job = _safe_id(value.get("job_id"), "job_id")
        with production_authority_lock(
            self.workspace_root, provider=provider, book_slug=book,
            job_id=job, profile_id=profile, exclusive=False,
        ):
            with production_authority_lock(
                self.workspace_root, provider="master-book", book_slug=book,
                job_id="book", profile_id=MASTER_PRESET_ID, exclusive=True,
            ):
                with production_authority_lock(
                    self.workspace_root, provider="master", book_slug=book,
                    job_id=job, profile_id=MASTER_PRESET_ID, exclusive=True,
                ):
                    return self._master_locked(value, revalidate=revalidate)

    def _master_locked(
        self,
        value: Mapping[str, Any],
        *,
        revalidate: Callable[[], Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        prepared = self.prepare(value)
        if prepared["decision"] == "BLOCKED":
            raise MasteringExportError("missing_ffmpeg", prepared["blocker_message"])
        if prepared["decision"] == "ALREADY_MASTERED":
            if revalidate is not None and _canonical_json(revalidate()) != _canonical_json(prepared["assembly"]):
                raise MasteringExportError("stale_assembly", "Assembly authority устарела до восстановления CURRENT.")
            self._publish_current_pointer(prepared["assembly"], prepared["master_identity"])
            return prepared["master"]
        payload, source, assembly_manifest = self._validate_assembly(prepared["assembly"])
        source_snapshot = _file_snapshot(source)
        manifest_snapshot = _file_snapshot(assembly_manifest)
        ffmpeg = _prepared_ffmpeg(prepared["ffmpeg"])
        current_ffmpeg = self._resolution()
        if _resolution_identity(current_ffmpeg) != _resolution_identity(ffmpeg) or ffmpeg.path is None:
            raise MasteringExportError("ffmpeg_identity_changed", "FFmpeg identity изменилась после подготовки.")
        identity = prepared["master_identity"]
        output_dir = self._output_dir(payload, identity)
        parent = output_dir.parent
        _prepare_output_parent(self.workspace_root, parent)
        temporary = Path(tempfile.mkdtemp(prefix=".master-", dir=parent))
        try:
            padded = temporary / "boundary-padded.wav"
            boundary = self._apply_boundary_padding(source, padded)
            first_pass, first_arguments = self._measure_loudness(ffmpeg.path, padded)
            audio_filter = (
                f"loudnorm=I={MASTER_PRESET['target_integrated_lufs']}:"
                f"TP={MASTER_PRESET['true_peak_ceiling_dbtp']}:"
                f"LRA={MASTER_PRESET['loudness_range_target_lu']}:"
                f"measured_I={first_pass['input_i']}:measured_TP={first_pass['input_tp']}:"
                f"measured_LRA={first_pass['input_lra']}:measured_thresh={first_pass['input_thresh']}:"
                f"offset={first_pass['target_offset']}:linear=true:print_format=json"
            )
            temporary_wav = temporary / "master.wav"
            second_arguments = [
                str(ffmpeg.path), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(padded), "-map_metadata", "-1", "-vn", "-af", audio_filter,
                "-ac", "1", "-ar", str(TARGET_SAMPLE_RATE_HZ), "-c:a", "pcm_s16le",
                "-fflags", "+bitexact", "-flags:a", "+bitexact", str(temporary_wav),
            ]
            completed = self._run(second_arguments)
            if completed.returncode != 0:
                raise MasteringExportError("mastering_failed", "FFmpeg second pass завершился ошибкой.")
            corrected_wav = temporary / "boundary-corrected.wav"
            post_mastering_boundary = self._apply_boundary_padding(temporary_wav, corrected_wav)
            if (
                post_mastering_boundary["added_leading_frames"]
                or post_mastering_boundary["added_trailing_frames"]
            ):
                os.replace(corrected_wav, temporary_wav)
            else:
                corrected_wav.unlink(missing_ok=True)
            output_wav = inspect_pcm_wav(temporary_wav).to_dict()
            if (
                output_wav["sample_rate_hz"] != TARGET_SAMPLE_RATE_HZ
                or output_wav["channels"] != TARGET_CHANNELS
                or output_wav["sample_width_bytes"] != TARGET_SAMPLE_WIDTH_BYTES
                or output_wav["compression_type"] != "NONE"
            ):
                raise MasteringExportError("invalid_master_format", "Master не соответствует PCM16 mono 48 kHz.")
            verification, verification_arguments = self._measure_loudness(ffmpeg.path, temporary_wav)
            signal = _signal_measurements(temporary_wav)
            final_boundary = _boundary_measurements(temporary_wav)
            boundary_tolerance = 1.0 / TARGET_SAMPLE_RATE_HZ
            if (
                final_boundary["leading_silence_seconds"] + boundary_tolerance
                < float(BOUNDARY_POLICY["minimum_leading_silence_seconds"])
                or final_boundary["trailing_silence_seconds"] + boundary_tolerance
                < float(BOUNDARY_POLICY["minimum_trailing_silence_seconds"])
            ):
                raise MasteringExportError("boundary_padding_failed", "Минимальная граничная тишина не обеспечена.")
            if abs(verification["input_i"] - float(MASTER_PRESET["target_integrated_lufs"])) > float(MASTER_PRESET["integrated_loudness_tolerance_lu"]):
                raise MasteringExportError("loudness_out_of_tolerance", "Итоговая громкость вне допуска.")
            if verification["input_tp"] > float(MASTER_PRESET["true_peak_ceiling_dbtp"]) + float(MASTER_PRESET["true_peak_tolerance_db"]):
                raise MasteringExportError("true_peak_exceeded", "True peak превышает потолок.")
            if signal["clipped_samples"]:
                raise MasteringExportError("clipping_detected", "В master WAV обнаружен клиппинг.")
            if _file_snapshot(source) != source_snapshot or sha256_file(source) != payload["audio_sha256"]:
                raise MasteringExportError("assembly_changed_during_mastering", "Assembly WAV изменился во время мастеринга.")
            if _file_snapshot(assembly_manifest) != manifest_snapshot or sha256_file(assembly_manifest) != payload["assembly_manifest_sha256"]:
                raise MasteringExportError("assembly_changed_during_mastering", "Assembly manifest изменился во время мастеринга.")
            if revalidate is not None and _canonical_json(revalidate()) != _canonical_json(payload):
                raise MasteringExportError("stale_assembly", "Assembly authority устарела во время мастеринга.")
            padded.unlink(missing_ok=True)
            final_wav = output_dir / "master.wav"
            output_sha = sha256_file(temporary_wav)
            manifest = {
                "schema_version": MASTER_SCHEMA_VERSION,
                "status": "READY",
                "master_identity": identity,
                "mastering_preset": MASTER_PRESET,
                "mastering_preset_hash": master_preset_hash(),
                "boundary_policy": boundary,
                "post_mastering_boundary": post_mastering_boundary,
                "book_slug": payload["book_slug"],
                "book_title": payload.get("book_title"),
                "job_id": payload["job_id"],
                "job_label": payload.get("job_label"),
                "provider": payload["provider"],
                "profile_id": payload["profile_id"],
                "created_at": utc_now_iso(),
                "input": {
                    "assembly_identity": payload["assembly_identity"],
                    "assembly_manifest_path": payload["assembly_manifest_path"],
                    "assembly_manifest_sha256": payload["assembly_manifest_sha256"],
                    "audio_path": payload["audio_path"],
                    "audio_sha256": payload["audio_sha256"],
                    "path_identity": payload["path_identity"],
                    "wav": payload["wav"],
                    "ordered_inputs": payload.get("ordered_inputs"),
                },
                "ffmpeg": _resolution_identity(ffmpeg),
                "analysis_pass": {
                    "measurements": first_pass,
                    "arguments": first_arguments,
                },
                "second_pass": {
                    "measurements_used": first_pass,
                    "arguments": _redact_arguments(second_arguments, {
                        str(ffmpeg.path): "<ffmpeg>", str(padded): "<input>",
                        str(temporary_wav): "<output>",
                    }),
                },
                "verification": {
                    "loudness": verification,
                    "arguments": verification_arguments,
                    "signal": signal,
                    "boundary_silence": final_boundary,
                    "internal_quality_benchmark": True,
                },
                "output": {
                    "path": str(final_wav),
                    "path_identity": path_identity(final_wav),
                    "sha256": output_sha,
                    "wav": output_wav,
                },
                "provider_requests": 0,
                "remote_request_sent": False,
                "billing_changed": False,
                "effects": ["loudness_normalization", "boundary_padding_if_required"],
                "warnings": [
                    code for code, applies in (
                        ("excessive_leading_boundary_silence", boundary["before"]["leading_silence_seconds"] > BOUNDARY_POLICY["preferred_maximum_leading_silence_seconds"]),
                        ("excessive_trailing_boundary_silence", boundary["before"]["trailing_silence_seconds"] > BOUNDARY_POLICY["preferred_maximum_trailing_silence_seconds"]),
                    ) if applies
                ],
            }
            atomic_write_json(temporary / "MANIFEST.json", manifest)
            if revalidate is not None and _canonical_json(revalidate()) != _canonical_json(payload):
                raise MasteringExportError("stale_assembly", "Assembly authority устарела перед публикацией.")
            if _file_snapshot(source) != source_snapshot or _file_snapshot(assembly_manifest) != manifest_snapshot:
                raise MasteringExportError("assembly_changed_during_mastering", "Assembly изменилась перед публикацией.")
            try:
                temporary.rename(output_dir)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                winner = self._read_ready(output_dir, identity)
                if winner is None:
                    raise MasteringExportError("publish_conflict", "Конфликт публикации master.")
                self._publish_current_pointer(payload, identity)
                return winner
            self._publish_current_pointer(payload, identity)
            return manifest
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def status(self, value: Mapping[str, Any]) -> dict[str, Any]:
        prepared = self.prepare(value)
        if prepared["decision"] == "ALREADY_MASTERED":
            return prepared
        pointer = self._output_dir(prepared["assembly"], prepared["master_identity"]).parent / "CURRENT.json"
        if pointer.is_file():
            try:
                current = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            if current.get("master_identity") != prepared["master_identity"]:
                prepared["state"] = "STALE"
                prepared["decision"] = "READY_TO_MASTER" if not prepared["blockers"] else "BLOCKED"
        return prepared

    def _read_ready(self, output_dir: Path, identity: str) -> dict[str, Any] | None:
        manifest_path, wav_path = output_dir / "MANIFEST.json", output_dir / "master.wav"
        try:
            manifest_path = _require_regular_path(manifest_path, root=self.workspace_root, label="Master manifest")
            wav_path = _require_regular_path(wav_path, root=self.workspace_root, label="Master WAV")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            output = payload.get("output")
            if (
                payload.get("schema_version") != MASTER_SCHEMA_VERSION
                or payload.get("status") != "READY"
                or payload.get("master_identity") != identity
                or not isinstance(output, Mapping)
                or output.get("path") != str(wav_path)
                or output.get("path_identity") != path_identity(wav_path)
                or output.get("sha256") != sha256_file(wav_path)
                or output.get("wav") != inspect_pcm_wav(wav_path).to_dict()
                or payload.get("provider_requests") != 0
                or payload.get("remote_request_sent") is not False
                or payload.get("billing_changed") is not False
                or payload.get("mastering_preset_hash") != master_preset_hash()
            ):
                return None
            return payload
        except (OSError, ValueError, TypeError, MasteringExportError):
            return None


def resolve_current_master(
    *,
    workspace_root: Path,
    masters_root: Path,
    book_slug: str,
    job_id: str,
    expected_master_identity: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    book = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    chapter_root = Path(masters_root).absolute() / book / job
    pointer_path = _require_regular_path(chapter_root / "CURRENT.json", root=root, label="Master CURRENT")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MasteringExportError("invalid_master_pointer", "CURRENT мастеринга повреждён.") from error
    identity = _safe_id(pointer.get("master_identity"), "master_identity")
    if expected_master_identity is not None and identity != expected_master_identity:
        raise MasteringExportError("stale_master", "Master устарел.")
    canonical = chapter_root / identity
    manifest_path = _require_regular_path(canonical / "MANIFEST.json", root=root, label="Master manifest")
    wav_path = _require_regular_path(canonical / "master.wav", root=root, label="Master WAV")
    if pointer.get("manifest_path") != str(manifest_path):
        raise MasteringExportError("master_manifest_identity_mismatch", "CURRENT указывает не на canonical master.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MasteringExportError("invalid_master_manifest", "Master manifest повреждён.") from error
    output = manifest.get("output") if isinstance(manifest, dict) else None
    if (
        manifest.get("schema_version") != MASTER_SCHEMA_VERSION
        or manifest.get("status") != "READY"
        or manifest.get("master_identity") != identity
        or manifest.get("book_slug") != book
        or manifest.get("job_id") != job
        or manifest.get("mastering_preset_hash") != master_preset_hash()
        or not isinstance(output, Mapping)
        or output.get("path") != str(wav_path)
        or output.get("path_identity") != path_identity(wav_path)
        or output.get("sha256") != sha256_file(wav_path)
    ):
        raise MasteringExportError("master_identity_mismatch", "Точная identity master не подтверждена.")
    wav = inspect_pcm_wav(wav_path).to_dict()
    if output.get("wav") != wav:
        raise MasteringExportError("master_wav_changed", "Master WAV изменился.")
    return {
        "schema_version": MASTER_SCHEMA_VERSION,
        "master_identity": identity,
        "master_manifest_path": str(manifest_path),
        "master_manifest_sha256": sha256_file(manifest_path),
        "audio_path": str(wav_path),
        "audio_sha256": output["sha256"],
        "path_identity": output["path_identity"],
        "wav": wav,
        "book_slug": book,
        "book_title": str(manifest.get("book_title") or ""),
        "job_id": job,
        "job_label": str(manifest.get("job_label") or job),
        "provider": _safe_id(manifest.get("provider"), "provider"),
        "profile_id": _safe_id(manifest.get("profile_id"), "profile_id"),
        "assembly_identity": manifest.get("input", {}).get("assembly_identity"),
        "provider_requests": 0,
    }


def canonical_book_authority(book: Mapping[str, Any]) -> dict[str, Any]:
    slug = _safe_slug(book.get("slug"))
    jobs = book.get("jobs")
    if not isinstance(jobs, Mapping):
        raise MasteringExportError("invalid_book_authority", "Canonical jobs книги недоступны.")
    chapters: list[dict[str, Any]] = []
    for job_id, value in jobs.items():
        if not isinstance(value, Mapping) or value.get("kind") != "chapter":
            continue
        chapters.append({
            "position": len(chapters) + 1,
            "job_id": _safe_id(job_id, "job_id"),
            "chapter_id": _safe_id(value.get("chapter_id"), "chapter_id"),
            "title": str(value.get("label") or job_id),
            "preparation_identity": str(value.get("preparation_identity") or ""),
        })
    if not chapters or len(chapters) > int(LITRES_PROFILE["max_book_files"]):
        raise MasteringExportError("invalid_book_chapter_count", "Некорректное число глав книги.")
    cover = book.get("cover")
    return {
        "schema_version": 1,
        "slug": slug,
        "title": str(book.get("title") or ""),
        "author": str(book.get("author") or ""),
        "language": str(book.get("language") or ""),
        "narrator": book.get("narrator"),
        "voice_profile_id": book.get("selected_profile_id"),
        "chapters": chapters,
        "cover": cover if isinstance(cover, Mapping) else None,
        "rights_provenance": book.get("rights_provenance") if isinstance(book.get("rights_provenance"), Mapping) else None,
    }


def build_book_export_state(
    book_authority: Mapping[str, Any],
    chapter_candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected = list(book_authority.get("chapters") or [])
    expected_ids = [item.get("job_id") for item in expected]
    by_job: dict[str, list[Mapping[str, Any]]] = {}
    extras: list[str] = []
    for candidate in chapter_candidates:
        job_id = candidate.get("job_id")
        if job_id not in expected_ids:
            extras.append(str(job_id or "unknown"))
            continue
        by_job.setdefault(str(job_id), []).append(candidate)
    duplicate = [job for job, values in by_job.items() if len(values) != 1]
    ordered = [by_job[job][0] for job in expected_ids if len(by_job.get(job, [])) == 1]
    ready_ids = [item.get("job_id") for item in ordered]
    missing = [job for job in expected_ids if job not in ready_ids]
    blockers: list[str] = []
    if missing:
        blockers.append("missing_chapters")
    if duplicate:
        blockers.append("duplicate_chapters")
    if extras:
        blockers.append("unknown_extra_chapters")
    cover = book_authority.get("cover")
    if not isinstance(cover, Mapping) or not cover.get("sha256"):
        blockers.append("missing_cover")
    rights = book_authority.get("rights_provenance")
    if isinstance(rights, Mapping) and rights.get("third_party_assets") and rights.get("verified") is not True:
        blockers.append("unproven_third_party_assets")
    return {
        "expected_chapters": len(expected),
        "ready_chapters": len(ordered),
        "progress": f"{len(ordered)}/{len(expected)}",
        "ready": not blockers and len(ordered) == len(expected),
        "ordered_candidates": ordered,
        "missing_job_ids": missing,
        "duplicate_job_ids": duplicate,
        "unknown_extra_job_ids": extras,
        "blockers": blockers,
    }


@dataclass
class LitresExportService:
    workspace_root: Path
    exports_root: Path

    def __post_init__(self) -> None:
        workspace_requested = Path(self.workspace_root).expanduser().absolute()
        requested = _validate_output_root(workspace_requested, self.exports_root, "Exports root")
        workspace = workspace_requested.resolve(strict=True)
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "exports_root", requested)

    def _resolution(self) -> FFmpegResolution:
        return resolve_ffmpeg(self.workspace_root)

    def _validated_book(self, value: Mapping[str, Any]) -> dict[str, Any]:
        book = canonical_book_authority(value)
        cover = book.get("cover")
        if isinstance(cover, Mapping):
            cover_path = cover.get("path")
            cover_sha = cover.get("sha256")
            if not isinstance(cover_path, str) or not isinstance(cover_sha, str):
                raise MasteringExportError("invalid_cover", "Cover reference должен содержать path и SHA-256.")
            path = _require_regular_path(Path(cover_path), root=self.workspace_root, label="Cover")
            if sha256_file(path) != cover_sha:
                raise MasteringExportError("cover_sha_mismatch", "SHA обложки изменился.")
            book["cover"] = {
                **dict(cover),
                "path": str(path),
                "path_identity": path_identity(path),
                "sha256": cover_sha,
            }
        return book

    @staticmethod
    def _encoder(ffmpeg: FFmpegResolution) -> str | None:
        if not ffmpeg.available or ffmpeg.path is None:
            return None
        try:
            completed = subprocess.run(
                [str(ffmpeg.path), "-nostdin", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        for encoder in ("libmp3lame", "mp3"):
            if re.search(rf"^\s*A\S*\s+{re.escape(encoder)}\s", completed.stdout, flags=re.MULTILINE):
                return encoder
        return None

    def _validate_master(self, value: Mapping[str, Any]) -> tuple[dict[str, Any], Path, Path]:
        payload = json.loads(json.dumps(value, ensure_ascii=False))
        book = _safe_slug(payload.get("book_slug"))
        job = _safe_id(payload.get("job_id"), "job_id")
        identity = _safe_id(payload.get("master_identity"), "master_identity")
        canonical = self.workspace_root / "masters" / book / job / identity
        manifest = _require_regular_path(canonical / "MANIFEST.json", root=self.workspace_root, label="Master manifest")
        audio = _require_regular_path(canonical / "master.wav", root=self.workspace_root, label="Master WAV")
        if payload.get("master_manifest_path") != str(manifest) or payload.get("audio_path") != str(audio):
            raise MasteringExportError("master_path_identity_mismatch", "Master path identity изменилась.")
        if payload.get("master_manifest_sha256") != sha256_file(manifest):
            raise MasteringExportError("master_manifest_changed", "Master manifest изменился.")
        if payload.get("audio_sha256") != sha256_file(audio) or payload.get("path_identity") != path_identity(audio):
            raise MasteringExportError("master_audio_changed", "Master WAV изменился.")
        if payload.get("wav") != inspect_pcm_wav(audio).to_dict():
            raise MasteringExportError("master_wav_changed", "Master PCM facts изменились.")
        payload.update({"book_slug": book, "job_id": job, "master_identity": identity})
        return payload, audio, manifest

    def _candidate_identity(
        self,
        master: Mapping[str, Any],
        book: Mapping[str, Any],
        chapter: Mapping[str, Any],
        ffmpeg: FFmpegResolution,
        encoder: str,
    ) -> str:
        return self._candidate_identity_from_tool(
            master, book, chapter, _resolution_identity(ffmpeg), encoder
        )

    @staticmethod
    def _candidate_identity_from_tool(
        master: Mapping[str, Any],
        book: Mapping[str, Any],
        chapter: Mapping[str, Any],
        tool: Mapping[str, Any],
        encoder: str,
    ) -> str:
        return _canonical_hash({
            "schema_version": EXPORT_SCHEMA_VERSION,
            "profile": LITRES_PROFILE,
            "profile_hash": litres_profile_hash(),
            "master_identity": master["master_identity"],
            "master_sha256": master["audio_sha256"],
            "master_manifest_sha256": master["master_manifest_sha256"],
            "book_metadata": {
                "title": book["title"], "author": book["author"], "language": book["language"],
                "narrator": book.get("narrator"), "voice_profile_id": book.get("voice_profile_id"),
            },
            "chapter": chapter,
            "cover": book.get("cover"),
            "tool": tool,
            "encoder": encoder,
        })

    def _profile_root(self, book_slug: str) -> Path:
        return self.exports_root / book_slug / LITRES_PROFILE_ID

    def _publish_current_pointers(
        self,
        profile_root: Path,
        output_dir: Path,
        manifest: Mapping[str, Any],
    ) -> None:
        identity = _safe_id(manifest.get("export_identity"), "export_identity")
        validated = self._read_export(output_dir, identity)
        if validated is None:
            raise MasteringExportError("invalid_export_winner", "Export package не прошёл проверку перед публикацией CURRENT.")
        manifest_path = output_dir / "MANIFEST.json"
        for record in validated["chapters"]:
            atomic_write_json(profile_root / f"CURRENT-{record['job_id']}.json", {
                "schema_version": EXPORT_SCHEMA_VERSION,
                "candidate_identity": record["candidate_identity"],
                "manifest_path": str(manifest_path),
                "mp3_path": record["path"],
                "updated_at": utc_now_iso(),
            })
        atomic_write_json(profile_root / "CURRENT.json", {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "export_identity": identity,
            "manifest_path": str(manifest_path),
            "updated_at": utc_now_iso(),
        })

    def _repair_current_pointers(
        self,
        profile_root: Path,
        output_dir: Path,
        manifest: Mapping[str, Any],
        job_id: str,
    ) -> None:
        identity = _safe_id(manifest.get("export_identity"), "export_identity")
        validated = self._read_export(output_dir, identity)
        if validated is None:
            raise MasteringExportError("invalid_export_winner", "Export package не прошёл проверку восстановления CURRENT.")
        record = next(
            (item for item in validated["chapters"] if item.get("job_id") == job_id),
            None,
        )
        if record is None:
            raise MasteringExportError("missing_export_chapter", "Export package не содержит выбранную главу.")
        manifest_path = output_dir / "MANIFEST.json"
        atomic_write_json(profile_root / f"CURRENT-{job_id}.json", {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "candidate_identity": record["candidate_identity"],
            "manifest_path": str(manifest_path),
            "mp3_path": record["path"],
            "updated_at": utc_now_iso(),
        })

        book_pointer = profile_root / "CURRENT.json"
        if book_pointer.is_symlink():
            raise MasteringExportError("symlink_pointer", "Export CURRENT является ссылкой.")
        for chapter in validated["chapters"]:
            pointer = profile_root / f"CURRENT-{chapter['job_id']}.json"
            if pointer.is_symlink():
                raise MasteringExportError("symlink_pointer", "Chapter export CURRENT является ссылкой.")
            if not pointer.is_file():
                return
            try:
                current = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            if (
                current.get("manifest_path") != str(manifest_path)
                or current.get("candidate_identity") != chapter.get("candidate_identity")
            ):
                return
        validated_jobs = {chapter["job_id"] for chapter in validated["chapters"]}
        for pointer in profile_root.glob("CURRENT-*.json"):
            if pointer.is_symlink():
                raise MasteringExportError("symlink_pointer", "Chapter export CURRENT является ссылкой.")
            pointer_job = pointer.name.removeprefix("CURRENT-").removesuffix(".json")
            if pointer_job in validated_jobs:
                continue
            try:
                current = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            if current.get("manifest_path") != str(manifest_path):
                return
        if book_pointer.is_file():
            try:
                current_book = json.loads(book_pointer.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current_book = None
            if isinstance(current_book, Mapping) and (
                current_book.get("export_identity") == identity
                and current_book.get("manifest_path") == str(manifest_path)
            ):
                return
        atomic_write_json(book_pointer, {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "export_identity": identity,
            "manifest_path": str(manifest_path),
            "updated_at": utc_now_iso(),
        })

    def _revalidate_candidate_masters(
        self,
        book: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
    ) -> None:
        chapters = {item["job_id"]: item for item in book["chapters"]}
        for candidate in candidates:
            job_id = candidate.get("job_id")
            chapter = chapters.get(job_id)
            if chapter is None:
                raise MasteringExportError("unknown_chapter", "Export candidate относится к неизвестной главе.")
            current_master = resolve_current_master(
                workspace_root=self.workspace_root,
                masters_root=self.workspace_root / "masters",
                book_slug=book["slug"],
                job_id=job_id,
                expected_master_identity=candidate.get("master_identity"),
            )
            tool = candidate.get("tool")
            encoder = candidate.get("encoder")
            if (
                current_master.get("master_manifest_sha256") != candidate.get("master_manifest_sha256")
                or current_master.get("audio_sha256") != candidate.get("master_sha256")
                or not isinstance(tool, Mapping)
                or not isinstance(encoder, str)
                or candidate.get("candidate_identity") != self._candidate_identity_from_tool(
                    current_master, book, chapter, tool, encoder
                )
            ):
                raise MasteringExportError(
                    "stale_master",
                    "Master authority одной из глав устарела перед публикацией export.",
                )

    def _load_current_candidates(self, book: Mapping[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        root = self._profile_root(book["slug"])
        for chapter in book["chapters"]:
            pointer = root / f"CURRENT-{chapter['job_id']}.json"
            if not pointer.is_file() or pointer.is_symlink():
                continue
            try:
                data = json.loads(pointer.read_text(encoding="utf-8"))
                manifest_path = _require_regular_path(
                    Path(data["manifest_path"]), root=self.workspace_root, label="Export manifest"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                candidate = next(
                    item for item in manifest.get("chapters", [])
                    if item.get("job_id") == chapter["job_id"] and item.get("candidate_identity") == data.get("candidate_identity")
                )
                mp3 = _require_regular_path(Path(candidate["path"]), root=self.workspace_root, label="Export MP3")
                if candidate.get("sha256") != sha256_file(mp3) or candidate.get("path_identity") != path_identity(mp3):
                    continue
                if book.get("cover") is not None:
                    facts = candidate.get("facts")
                    ffmpeg = self._resolution()
                    if (
                        not isinstance(facts, Mapping)
                        or facts.get("cover_art_embedded") is not True
                        or not ffmpeg.available
                        or ffmpeg.path is None
                        or self._inspect_mp3(ffmpeg.path, mp3).get("cover_art_embedded") is not True
                    ):
                        continue
                current_master = resolve_current_master(
                    workspace_root=self.workspace_root,
                    masters_root=self.workspace_root / "masters",
                    book_slug=book["slug"],
                    job_id=chapter["job_id"],
                    expected_master_identity=candidate.get("master_identity"),
                )
                if (
                    current_master["master_manifest_sha256"] != candidate.get("master_manifest_sha256")
                    or current_master["audio_sha256"] != candidate.get("master_sha256")
                ):
                    continue
                tool = candidate.get("tool")
                if not isinstance(tool, Mapping):
                    tool = manifest.get("ffmpeg")
                encoder = candidate.get("encoder")
                if not isinstance(tool, Mapping) or not isinstance(encoder, str):
                    continue
                if candidate.get("candidate_identity") != self._candidate_identity_from_tool(
                    current_master, book, chapter, tool, encoder
                ):
                    continue
                candidate = dict(candidate)
                candidate["tool"] = dict(tool)
                result.append(candidate)
            except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired, MasteringExportError):
                continue
        return result

    def prepare(self, master_value: Mapping[str, Any], book_value: Mapping[str, Any]) -> dict[str, Any]:
        master, _, _ = self._validate_master(master_value)
        book = self._validated_book(book_value)
        if book["slug"] != master["book_slug"]:
            raise MasteringExportError("book_identity_mismatch", "Master относится к другой книге.")
        chapter = next((item for item in book["chapters"] if item["job_id"] == master["job_id"]), None)
        if chapter is None:
            raise MasteringExportError("unknown_chapter", "Глава отсутствует в canonical book authority.")
        ffmpeg = self._resolution()
        encoder = self._encoder(ffmpeg)
        blockers: list[str] = []
        if not ffmpeg.available:
            blockers.append("missing_ffmpeg")
        elif encoder is None:
            blockers.append("missing_mp3_encoder")
        candidate_identity = self._candidate_identity(master, book, chapter, ffmpeg, encoder or "unavailable")
        candidates = [item for item in self._load_current_candidates(book) if item.get("job_id") != master["job_id"]]
        pointer = self._profile_root(book["slug"]) / f"CURRENT-{master['job_id']}.json"
        existing: dict[str, Any] | None = None
        if pointer.is_file() and not pointer.is_symlink():
            try:
                data = json.loads(pointer.read_text(encoding="utf-8"))
                if data.get("candidate_identity") == candidate_identity:
                    manifest_path = _require_regular_path(
                        Path(data["manifest_path"]), root=self.workspace_root, label="Export manifest"
                    )
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    existing = next(item for item in manifest["chapters"] if item["candidate_identity"] == candidate_identity)
                    existing_mp3 = _require_regular_path(
                        Path(existing["path"]), root=self.workspace_root, label="Export MP3"
                    )
                    if (
                        existing.get("sha256") != sha256_file(existing_mp3)
                        or existing.get("path_identity") != path_identity(existing_mp3)
                    ):
                        existing = None
            except (OSError, ValueError, KeyError, StopIteration):
                existing = None
        if existing:
            candidates.append(existing)
        book_state = build_book_export_state(book, candidates)
        return {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "state": "READY" if existing else ("BLOCKED" if blockers else "PREPARED"),
            "decision": "ALREADY_EXPORTED" if existing else ("BLOCKED" if blockers else "READY_TO_EXPORT"),
            "blockers": blockers,
            "blocker_message": (
                "Для MP3-экспорта требуется FFmpeg." if "missing_ffmpeg" in blockers else
                "В текущем FFmpeg нет подходящего MP3 encoder." if blockers else None
            ),
            "profile": LITRES_PROFILE,
            "profile_hash": litres_profile_hash(),
            "candidate_identity": candidate_identity,
            "master": master,
            "book": book,
            "chapter": chapter,
            "ffmpeg": ffmpeg.to_dict(),
            "encoder": encoder,
            "chapter_export": existing,
            "book_export": book_state,
            "manifest_path": None,
            "provider_requests": 0,
            "remote_request_sent": False,
            "billing_changed": False,
        }

    @staticmethod
    def _inspect_mp3(ffmpeg: Path, mp3: Path) -> dict[str, Any]:
        completed = subprocess.run(
            [str(ffmpeg), "-nostdin", "-hide_banner", "-i", str(mp3), "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, text=True, timeout=900, check=False,
        )
        if completed.returncode != 0:
            raise MasteringExportError("mp3_decode_failed", "MP3 не проходит независимое декодирование.")
        text = completed.stderr
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        stream_match = re.search(r"Audio:\s*mp3[^,]*,\s*(\d+)\s*Hz,\s*([^,]+).*?(\d+)\s*kb/s", text)
        if not duration_match or not stream_match:
            raise MasteringExportError("mp3_facts_unavailable", "Не удалось прочитать параметры MP3.")
        hours, minutes, seconds = duration_match.groups()
        channel_label = stream_match.group(2).strip().lower()
        channels = 2 if "stereo" in channel_label else 1 if "mono" in channel_label else 0
        return {
            "duration_seconds": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
            "sample_rate_hz": int(stream_match.group(1)),
            "channels": channels,
            "channel_layout": channel_label,
            "bitrate_bps": int(stream_match.group(3)) * 1000,
            "size_bytes": mp3.stat().st_size,
            "decodable": True,
            "cover_art_embedded": bool(re.search(r"Stream #\d+:\d+.*Video:.*attached pic", text, flags=re.IGNORECASE)),
        }

    def export(
        self,
        master_value: Mapping[str, Any],
        book_value: Mapping[str, Any],
        *,
        revalidate_master: Callable[[], Mapping[str, Any]] | None = None,
        revalidate_book: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        book_slug = _safe_slug(master_value.get("book_slug"))
        book = self._validated_book(book_value)
        if book["slug"] != book_slug:
            raise MasteringExportError("book_identity_mismatch", "Master относится к другой книге.")
        with production_authority_lock(
            self.workspace_root, provider="master-book", book_slug=book_slug,
            job_id="book", profile_id=MASTER_PRESET_ID, exclusive=False,
        ):
            with production_authority_lock(
                self.workspace_root, provider="export", book_slug=book_slug,
                job_id="book", profile_id=LITRES_PROFILE_ID, exclusive=True,
            ):
                return self._export_locked(
                    master_value, book_value,
                    revalidate_master=revalidate_master, revalidate_book=revalidate_book,
                )

    def _export_locked(
        self,
        master_value: Mapping[str, Any],
        book_value: Mapping[str, Any],
        *,
        revalidate_master: Callable[[], Mapping[str, Any]] | None,
        revalidate_book: Callable[[], Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        prepared = self.prepare(master_value, book_value)
        if prepared["decision"] == "BLOCKED":
            raise MasteringExportError(prepared["blockers"][0], prepared["blocker_message"])
        if prepared["decision"] == "ALREADY_EXPORTED":
            if revalidate_master is not None and _canonical_json(revalidate_master()) != _canonical_json(prepared["master"]):
                raise MasteringExportError("stale_master", "Master authority устарела до восстановления CURRENT.")
            if revalidate_book is not None and _canonical_json(self._validated_book(revalidate_book())) != _canonical_json(prepared["book"]):
                raise MasteringExportError("book_authority_changed", "Book authority изменилась до восстановления CURRENT.")
            current = self.status(master_value, book_value)
            manifest_path = Path(current["manifest_path"])
            self._repair_current_pointers(
                self._profile_root(prepared["book"]["slug"]),
                manifest_path.parent,
                current["export_manifest"],
                prepared["master"]["job_id"],
            )
            return self.status(master_value, book_value)
        master, source, master_manifest = self._validate_master(prepared["master"])
        source_snapshot, manifest_snapshot = _file_snapshot(source), _file_snapshot(master_manifest)
        book = prepared["book"]
        chapter = prepared["chapter"]
        ffmpeg = _prepared_ffmpeg(prepared["ffmpeg"])
        current_ffmpeg = self._resolution()
        encoder = self._encoder(current_ffmpeg)
        if _resolution_identity(current_ffmpeg) != _resolution_identity(ffmpeg) or encoder != prepared["encoder"] or ffmpeg.path is None:
            raise MasteringExportError("ffmpeg_identity_changed", "FFmpeg/encoder identity изменилась.")
        profile_root = self._profile_root(book["slug"])
        _prepare_output_parent(self.workspace_root, profile_root)
        temporary_root = Path(tempfile.mkdtemp(prefix=".export-", dir=profile_root))
        try:
            temporary_mp3 = temporary_root / "chapter.mp3"
            cover = book.get("cover")
            cover_source = Path(cover["path"]) if isinstance(cover, Mapping) else None
            cover_snapshot = _file_snapshot(cover_source) if cover_source is not None else None
            arguments = [
                str(ffmpeg.path), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(source),
            ]
            if cover_source is not None:
                arguments.extend([
                    "-i", str(cover_source), "-map", "0:a:0", "-map", "1:v:0",
                    "-c:v", "copy", "-disposition:v", "attached_pic",
                ])
            else:
                arguments.extend(["-map", "0:a:0", "-vn"])
            arguments.extend([
                "-map_metadata", "-1", "-ac", "2",
                "-ar", str(LITRES_PROFILE["sample_rate_hz"]), "-c:a", encoder,
                "-b:a", "128k", "-minrate", "128k", "-maxrate", "128k", "-bufsize", "256k",
                "-write_xing", "0", "-id3v2_version", "3",
                "-metadata", f"title={chapter['title']}",
                "-metadata", f"album={book['title']}",
                "-metadata", f"artist={book['author']}",
                "-metadata", f"track={chapter['position']}",
                str(temporary_mp3),
            ])
            completed = subprocess.run(arguments, capture_output=True, timeout=900, check=False)
            if completed.returncode != 0:
                raise MasteringExportError("mp3_encode_failed", "FFmpeg не создал MP3.")
            facts = self._inspect_mp3(ffmpeg.path, temporary_mp3)
            if facts["channels"] != 2 or facts["sample_rate_hz"] != LITRES_PROFILE["sample_rate_hz"]:
                raise MasteringExportError("invalid_mp3_format", "MP3 должен быть stereo 48 kHz.")
            if abs(facts["bitrate_bps"] - LITRES_PROFILE["bitrate_bps"]) > 8_000:
                raise MasteringExportError("invalid_mp3_bitrate", "MP3 bitrate не соответствует профилю 128 kbps.")
            if facts["duration_seconds"] > LITRES_PROFILE["max_duration_seconds"]:
                raise MasteringExportError("mp3_too_long", "Файл превышает 3 часа.")
            if facts["size_bytes"] > LITRES_PROFILE["max_file_bytes"]:
                raise MasteringExportError("mp3_too_large", "Файл превышает 170 MB.")
            if abs(facts["duration_seconds"] - master["wav"]["duration_seconds"]) > LITRES_PROFILE["duration_tolerance_seconds"]:
                raise MasteringExportError("mp3_duration_mismatch", "MP3 duration не совпадает с master.")
            if cover_source is not None and facts.get("cover_art_embedded") is not True:
                raise MasteringExportError("missing_cover_art", "MP3 не содержит canonical cover art.")
            if _file_snapshot(source) != source_snapshot or sha256_file(source) != master["audio_sha256"]:
                raise MasteringExportError("master_changed_during_export", "Master изменился во время экспорта.")
            if _file_snapshot(master_manifest) != manifest_snapshot or sha256_file(master_manifest) != master["master_manifest_sha256"]:
                raise MasteringExportError("master_changed_during_export", "Master manifest изменился.")
            if cover_source is not None and (
                _file_snapshot(cover_source) != cover_snapshot
                or sha256_file(cover_source) != cover["sha256"]
                or path_identity(cover_source) != cover["path_identity"]
            ):
                raise MasteringExportError("cover_changed_during_export", "Canonical cover изменился во время экспорта.")
            if revalidate_master is not None and _canonical_json(revalidate_master()) != _canonical_json(master):
                raise MasteringExportError("stale_master", "Master authority устарела во время экспорта.")
            if revalidate_book is not None and _canonical_json(self._validated_book(revalidate_book())) != _canonical_json(book):
                raise MasteringExportError("book_authority_changed", "Book authority изменилась во время экспорта.")
            candidate_identity = prepared["candidate_identity"]
            candidate = {
                "candidate_identity": candidate_identity,
                "job_id": master["job_id"],
                "chapter_id": chapter["chapter_id"],
                "chapter_title": chapter["title"],
                "position": chapter["position"],
                "master_identity": master["master_identity"],
                "master_manifest_sha256": master["master_manifest_sha256"],
                "master_sha256": master["audio_sha256"],
                "sha256": sha256_file(temporary_mp3),
                "facts": facts,
                "encoder": encoder,
                "tool": _resolution_identity(ffmpeg),
                "arguments": _redact_arguments(arguments, {
                    str(ffmpeg.path): "<ffmpeg>", str(source): "<master>", str(temporary_mp3): "<output>",
                    **({str(cover_source): "<cover>"} if cover_source is not None else {}),
                }),
                "metadata": {
                    "title": book["title"], "author": book["author"],
                    "chapter_title": chapter["title"], "chapter_position": chapter["position"],
                    "narrator": book.get("narrator"), "voice_profile_id": master["profile_id"],
                    "language": book["language"],
                },
            }
            candidates = [item for item in self._load_current_candidates(book) if item.get("job_id") != master["job_id"]]
            candidates.append(candidate)
            state = build_book_export_state(book, candidates)
            ordered_candidate_identities = [item["candidate_identity"] for item in state["ordered_candidates"]]
            export_identity = _canonical_hash({
                "schema_version": EXPORT_SCHEMA_VERSION,
                "profile_hash": litres_profile_hash(),
                "book": book,
                "ordered_candidate_identities": ordered_candidate_identities,
            })
            output_dir = profile_root / export_identity
            package_temp = Path(tempfile.mkdtemp(prefix=".package-", dir=profile_root))
            try:
                chapter_records: list[dict[str, Any]] = []
                for item in state["ordered_candidates"]:
                    final_name = _safe_output_name(int(item["position"]), str(item["chapter_title"]))
                    destination = package_temp / final_name
                    if item["candidate_identity"] == candidate_identity:
                        shutil.copyfile(temporary_mp3, destination)
                    else:
                        existing = _require_regular_path(Path(item["path"]), root=self.workspace_root, label="Existing chapter MP3")
                        shutil.copyfile(existing, destination)
                    record = json.loads(json.dumps(item, ensure_ascii=False))
                    record.update({
                        "filename": final_name,
                        "path": str(output_dir / final_name),
                        "path_identity": path_identity(output_dir / final_name),
                        "sha256": sha256_file(destination),
                    })
                    chapter_records.append(record)
                package_state = build_book_export_state(book, chapter_records)
                package_cover: dict[str, Any] | None = None
                if cover_source is not None:
                    suffix = cover_source.suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
                        suffix = ".img"
                    cover_destination = package_temp / f"cover{suffix}"
                    shutil.copyfile(cover_source, cover_destination)
                    package_cover = {
                        **dict(cover),
                        "package_path": str(output_dir / cover_destination.name),
                        "package_path_identity": path_identity(output_dir / cover_destination.name),
                        "package_sha256": sha256_file(cover_destination),
                    }
                manifest = {
                    "schema_version": EXPORT_SCHEMA_VERSION,
                    "status": "RELEASE_READY" if package_state["ready"] else "INCOMPLETE",
                    "chapter_status": "CHAPTER_EXPORT_READY",
                    "export_identity": export_identity,
                    "export_profile": LITRES_PROFILE,
                    "export_profile_hash": litres_profile_hash(),
                    "created_at": utc_now_iso(),
                    "book": book,
                    "chapter_expected_order": book["chapters"],
                    "chapters": chapter_records,
                    "whole_book": package_state,
                    "cover": package_cover,
                    "rights_provenance": book.get("rights_provenance"),
                    "total_file_count": len(chapter_records),
                    "ffmpeg": _resolution_identity(ffmpeg),
                    "provider_requests": 0,
                    "remote_request_sent": False,
                    "billing_changed": False,
                }
                atomic_write_json(package_temp / "MANIFEST.json", manifest)
                if revalidate_master is not None and _canonical_json(revalidate_master()) != _canonical_json(master):
                    raise MasteringExportError("stale_master", "Master authority устарела перед публикацией.")
                if revalidate_book is not None and _canonical_json(self._validated_book(revalidate_book())) != _canonical_json(book):
                    raise MasteringExportError("book_authority_changed", "Book authority изменилась перед публикацией.")
                self._revalidate_candidate_masters(book, state["ordered_candidates"])
                try:
                    package_temp.rename(output_dir)
                except OSError as error:
                    if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                        raise
                    winner = self._read_export(output_dir, export_identity)
                    if winner is None:
                        raise MasteringExportError("publish_conflict", "Конфликт публикации export.")
                    manifest = winner
                self._publish_current_pointers(profile_root, output_dir, manifest)
                return self.status(master_value, book_value)
            finally:
                if package_temp.exists():
                    shutil.rmtree(package_temp)
        finally:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)

    def status(self, master_value: Mapping[str, Any], book_value: Mapping[str, Any]) -> dict[str, Any]:
        prepared = self.prepare(master_value, book_value)
        pointer = self._profile_root(prepared["book"]["slug"]) / f"CURRENT-{prepared['master']['job_id']}.json"
        if pointer.is_symlink():
            raise MasteringExportError("symlink_pointer", "Export CURRENT является ссылкой.")
        if prepared["decision"] != "ALREADY_EXPORTED":
            if pointer.is_file():
                prepared["state"] = "STALE"
                prepared["decision"] = "READY_TO_EXPORT" if not prepared["blockers"] else "BLOCKED"
            return prepared
        data = json.loads(pointer.read_text(encoding="utf-8"))
        manifest_path = _require_regular_path(
            Path(data["manifest_path"]), root=self.workspace_root, label="Export manifest"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validated_manifest = self._read_export(manifest_path.parent, manifest.get("export_identity"))
        if validated_manifest is None:
            raise MasteringExportError("export_identity_mismatch", "Export package identity изменилась.")
        manifest = validated_manifest
        prepared["manifest_path"] = str(manifest_path)
        prepared["export_manifest"] = manifest
        prepared["book_export"] = manifest["whole_book"]
        prepared["chapter_export"] = next(
            item for item in manifest["chapters"]
            if item["candidate_identity"] == prepared["candidate_identity"]
        )
        output = prepared["chapter_export"]
        mp3 = _require_regular_path(Path(output["path"]), root=self.workspace_root, label="Export MP3")
        if output.get("sha256") != sha256_file(mp3) or output.get("path_identity") != path_identity(mp3):
            raise MasteringExportError("export_identity_mismatch", "MP3 export identity изменилась.")
        return prepared

    def _read_export(self, output_dir: Path, identity: str) -> dict[str, Any] | None:
        try:
            manifest_path = _require_regular_path(output_dir / "MANIFEST.json", root=self.workspace_root, label="Export manifest")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != EXPORT_SCHEMA_VERSION or payload.get("export_identity") != identity:
                return None
            if (
                payload.get("export_profile_hash") != litres_profile_hash()
                or payload.get("provider_requests") != 0
                or payload.get("remote_request_sent") is not False
                or payload.get("billing_changed") is not False
            ):
                return None
            cover = payload.get("cover")
            cover_ffmpeg = self._resolution() if isinstance(cover, Mapping) else None
            for item in payload.get("chapters", []):
                path = _require_regular_path(Path(item["path"]), root=self.workspace_root, label="Export MP3")
                if item.get("sha256") != sha256_file(path) or item.get("path_identity") != path_identity(path):
                    return None
                if isinstance(cover, Mapping) and (
                    not isinstance(item.get("facts"), Mapping)
                    or item["facts"].get("cover_art_embedded") is not True
                    or cover_ffmpeg is None
                    or not cover_ffmpeg.available
                    or cover_ffmpeg.path is None
                    or self._inspect_mp3(cover_ffmpeg.path, path).get("cover_art_embedded") is not True
                ):
                    return None
            if isinstance(cover, Mapping):
                package_cover = _require_regular_path(
                    Path(cover["package_path"]), root=self.workspace_root, label="Package cover"
                )
                if (
                    cover.get("package_sha256") != sha256_file(package_cover)
                    or cover.get("package_path_identity") != path_identity(package_cover)
                ):
                    return None
            return payload
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired, MasteringExportError):
            return None
