"""Provider-neutral, offline assembly of exact QA-approved chapter audio."""

from __future__ import annotations

import hashlib
import errno
import json
import os
import shutil
import stat
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from audio_qa_review import path_identity, sha256_file
from backends.common import atomic_write_json, inspect_pcm_wav, utc_now_iso
from book_library import BookLibraryError, normalize_slug
from media_tools import FFmpegResolution, resolve_ffmpeg
from production_authority_lock import production_authority_lock


ASSEMBLY_SCHEMA_VERSION = 1
TARGET_SAMPLE_RATE_HZ = 48_000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH_BYTES = 2


class ChapterAssemblyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _safe_slug(value: str) -> str:
    try:
        return normalize_slug(value)
    except BookLibraryError as error:
        raise ChapterAssemblyError("invalid_book_slug", "Некорректный идентификатор книги.") from error


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ChapterAssemblyError("invalid_identity", f"Некорректный {label}.")
    return value


def _require_real_path(path: Path, *, root: Path, label: str) -> Path:
    candidate = Path(path).expanduser().absolute()
    boundary = Path(root).expanduser().resolve(strict=True)
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise ChapterAssemblyError("path_escape", f"{label} находится вне рабочего пространства.") from error
    current = boundary
    for component in relative.parts:
        current /= component
        try:
            metadata = current.lstat()
        except OSError as error:
            raise ChapterAssemblyError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ChapterAssemblyError("symlink_input", f"{label} содержит символическую ссылку.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise ChapterAssemblyError("invalid_input", f"{label} должен быть обычным файлом.")
    return resolved


def assembly_input_from_qa(
    authority: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the immutable assembly input to current QA/downstream evidence."""
    identity = record.get("identity")
    wav = record.get("wav")
    if not isinstance(identity, Mapping) or not isinstance(wav, Mapping):
        raise ChapterAssemblyError("qa_identity_unavailable", "Точная QA identity недоступна.")
    audio_sha = identity.get("audio_sha256")
    source_path_identity = identity.get("path_identity")
    fingerprint = identity.get("synthesis_fingerprint")
    if not all(isinstance(item, str) and item for item in (
        audio_sha, source_path_identity, fingerprint
    )):
        raise ChapterAssemblyError("qa_identity_unavailable", "Точная QA identity недоступна.")
    manifest_path = authority.get("manifest_path")
    audio_path = authority.get("audio_path")
    if not isinstance(manifest_path, str) or not isinstance(audio_path, str):
        raise ChapterAssemblyError("authority_unavailable", "Production authority недоступен.")
    identity_pairs = (
        (record.get("provider"), authority.get("provider")),
        (record.get("profile_id"), authority.get("profile_id")),
        (record.get("book_slug"), authority.get("book_slug")),
        (record.get("job_id"), authority.get("job_id")),
        (record.get("segment_id"), authority.get("segment_id")),
        (record.get("audio_path"), audio_path),
        (fingerprint, authority.get("synthesis_fingerprint")),
    )
    if any(left != right for left, right in identity_pairs):
        raise ChapterAssemblyError(
            "qa_authority_mismatch", "QA identity больше не совпадает с production authority."
        )
    return {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "book_slug": _safe_slug(str(authority.get("book_slug") or "")),
        "book_title": str(authority.get("book_title") or ""),
        "job_id": _safe_id(authority.get("job_id"), "job_id"),
        "job_label": str(authority.get("job_label") or authority.get("job_id") or ""),
        "provider": _safe_id(authority.get("provider"), "provider"),
        "profile_id": _safe_id(authority.get("profile_id"), "profile_id"),
        "segment_id": _safe_id(authority.get("segment_id"), "segment_id"),
        "granularity": "chapter",
        "source": {
            "audio_path": audio_path,
            "manifest_path": manifest_path,
            "audio_sha256": audio_sha,
            "path_identity": source_path_identity,
            "synthesis_fingerprint": fingerprint,
        },
        "qa": {
            "automatic_status": record.get("automatic_status"),
            "manual_state": record.get("manual_state"),
            "downstream_eligible": record.get("downstream_eligible") is True,
        },
        "wav": {
            "sample_rate_hz": wav.get("sample_rate_hz"),
            "channels": wav.get("channels"),
            "sample_width_bytes": wav.get("sample_width_bytes"),
            "duration_seconds": wav.get("duration_seconds"),
            "compression_type": wav.get("compression_type"),
        },
        "ordered_inputs": [{
            "position": 1,
            "segment_id": _safe_id(authority.get("segment_id"), "segment_id"),
            "audio_sha256": audio_sha,
            "path_identity": source_path_identity,
            "synthesis_fingerprint": fingerprint,
        }],
    }


def assembly_input_from_qa_segments(
    items: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    expected_segment_ids: Sequence[str],
    prepared_text_identity: str,
) -> dict[str, Any]:
    """Build one immutable ordered chapter input from every expected segment."""
    expected = [_safe_id(value, "segment_id") for value in expected_segment_ids]
    if not expected or len(set(expected)) != len(expected):
        raise ChapterAssemblyError("invalid_order", "Ожидаемый набор сегментов неоднозначен.")
    if len(items) != len(expected):
        raise ChapterAssemblyError(
            "incomplete_approved_segment_set",
            "Для сборки главы одобрены не все готовые сегменты.",
        )
    if not isinstance(prepared_text_identity, str) or not prepared_text_identity:
        raise ChapterAssemblyError("invalid_prepared_text_identity", "Identity подготовленного текста недоступна.")

    chapter_inputs = [assembly_input_from_qa(authority, record) for authority, record in items]
    first = chapter_inputs[0]
    ordered: list[dict[str, Any]] = []
    for position, (segment_id, value) in enumerate(zip(expected, chapter_inputs), start=1):
        if value["segment_id"] != segment_id:
            raise ChapterAssemblyError("invalid_order", "Порядок сегментов не совпадает с подготовленным текстом.")
        for field in ("book_slug", "job_id", "provider", "profile_id"):
            if value[field] != first[field]:
                raise ChapterAssemblyError("mixed_chapter_identity", "Сегменты относятся к разным заданиям.")
        ordered.append({
            "position": position,
            "segment_id": segment_id,
            "source": value["source"],
            "qa": value["qa"],
            "wav": value["wav"],
        })
    return {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "book_slug": first["book_slug"],
        "book_title": first["book_title"],
        "job_id": first["job_id"],
        "job_label": first["job_label"],
        "provider": first["provider"],
        "profile_id": first["profile_id"],
        "segment_id": first["job_id"],
        "granularity": "segments",
        "prepared_text_identity": prepared_text_identity,
        "expected_segment_count": len(expected),
        "ordered_segment_ids": expected,
        "pause_contract": "no_added_intersegment_silence_v1",
        "ordered_inputs": ordered,
    }


@dataclass
class ChapterAssemblyService:
    workspace_root: Path
    chapters_root: Path

    def __post_init__(self) -> None:
        requested_workspace = Path(self.workspace_root).expanduser().absolute()
        if requested_workspace.is_symlink():
            raise ChapterAssemblyError(
                "symlink_workspace_root", "Корень рабочего пространства является символической ссылкой."
            )
        workspace = requested_workspace.resolve(strict=True)
        requested_chapters = Path(self.chapters_root).expanduser().absolute()
        try:
            relative = requested_chapters.relative_to(requested_workspace)
        except ValueError as error:
            raise ChapterAssemblyError(
                "chapters_root_escape", "Каталог сборок находится вне рабочего пространства."
            ) from error
        current = requested_workspace
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                raise ChapterAssemblyError(
                    "symlink_output_root", "Каталог сборки содержит символическую ссылку."
                )
        chapters = requested_chapters.resolve(strict=False)
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "chapters_root", chapters)

    def _validate_source(
        self,
        *,
        source: dict[str, Any],
        qa: dict[str, Any],
        wav: dict[str, Any],
        label: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path]:
        if qa.get("automatic_status") == "FAIL":
            raise ChapterAssemblyError("automatic_qa_failed", f"Автопроверка {label} не пройдена.")
        if qa.get("automatic_status") not in {"PASS", "WARN"}:
            raise ChapterAssemblyError("automatic_qa_unavailable", f"Автопроверка {label} недоступна.")
        if qa.get("manual_state") != "APPROVED":
            raise ChapterAssemblyError("manual_approval_required", f"Для сборки требуется одобрение {label}.")
        if qa.get("downstream_eligible") is not True:
            raise ChapterAssemblyError("downstream_blocked", f"{label} не допущен к следующему этапу.")
        audio = _require_real_path(
            Path(source.get("audio_path") or ""), root=self.workspace_root, label=label
        )
        manifest = _require_real_path(
            Path(source.get("manifest_path") or ""), root=self.workspace_root, label="Production manifest"
        )
        expected = tuple(source.get(field) for field in (
            "audio_sha256", "path_identity", "synthesis_fingerprint"
        ))
        if not all(isinstance(item, str) and item for item in expected):
            raise ChapterAssemblyError("qa_identity_unavailable", "Точная QA identity недоступна.")
        if sha256_file(audio) != expected[0]:
            raise ChapterAssemblyError("source_sha_mismatch", f"SHA {label} изменился после проверки.")
        if path_identity(audio) != expected[1]:
            raise ChapterAssemblyError("source_path_mismatch", f"Путь {label} изменился после проверки.")
        metadata = inspect_pcm_wav(audio)
        facts = metadata.to_dict()
        for field in ("sample_rate_hz", "channels", "sample_width_bytes", "duration_seconds"):
            if wav.get(field) != facts.get(field):
                raise ChapterAssemblyError("wav_facts_mismatch", f"PCM-параметры {label} изменились.")
        if metadata.channels != 1 or metadata.sample_width_bytes != 2:
            raise ChapterAssemblyError("unsupported_pcm", "Сборка поддерживает только mono PCM16 WAV.")
        manifest_sha = sha256_file(manifest)
        if source.get("manifest_sha256") not in {None, manifest_sha}:
            raise ChapterAssemblyError("manifest_sha_mismatch", "Production manifest изменился.")
        normalized_source = dict(source)
        normalized_source.update({
            "audio_path": str(audio),
            "manifest_path": str(manifest),
            "manifest_sha256": manifest_sha,
        })
        return normalized_source, dict(qa), facts, audio, manifest

    def _validate_input(self, value: Mapping[str, Any]) -> tuple[dict[str, Any], list[Path], list[Path]]:
        payload = json.loads(json.dumps(value, ensure_ascii=False))
        if payload.get("schema_version") != ASSEMBLY_SCHEMA_VERSION:
            raise ChapterAssemblyError("invalid_schema", "Неподдерживаемая схема входа сборки.")
        payload["book_slug"] = _safe_slug(payload.get("book_slug"))
        for field in ("job_id", "provider", "profile_id", "segment_id"):
            payload[field] = _safe_id(payload.get(field), field)
        ordered = payload.get("ordered_inputs")
        if not isinstance(ordered, list) or not ordered:
            raise ChapterAssemblyError("invalid_order", "Порядок входных аудиофайлов недоступен.")
        positions = [item.get("position") for item in ordered if isinstance(item, dict)]
        if positions != list(range(1, len(ordered) + 1)) or len(positions) != len(ordered):
            raise ChapterAssemblyError("invalid_order", "Порядок входных аудиофайлов неоднозначен.")
        granularity = payload.get("granularity")
        audios: list[Path] = []
        manifests: list[Path] = []
        if granularity == "chapter":
            qa, source, wav = payload.get("qa"), payload.get("source"), payload.get("wav")
            if not all(isinstance(item, dict) for item in (qa, source, wav)) or len(ordered) != 1:
                raise ChapterAssemblyError("invalid_input", "Неполный вход сборки главы.")
            normalized_source, normalized_qa, normalized_wav, audio, manifest = self._validate_source(
                source=source, qa=qa, wav=wav, label="Исходный WAV"
            )
            item = ordered[0]
            if not isinstance(item, dict) or any(
                item.get(field) != normalized_source.get(field)
                for field in ("audio_sha256", "path_identity", "synthesis_fingerprint")
            ):
                raise ChapterAssemblyError("ordered_identity_mismatch", "Ordered input identity не совпадает.")
            payload.update({"source": normalized_source, "qa": normalized_qa, "wav": normalized_wav})
            audios.append(audio)
            manifests.append(manifest)
        elif granularity == "segments":
            segment_ids = payload.get("ordered_segment_ids")
            expected_count = payload.get("expected_segment_count")
            if (
                not isinstance(segment_ids, list)
                or segment_ids != [item.get("segment_id") for item in ordered]
                or expected_count != len(ordered)
                or len(set(segment_ids)) != len(segment_ids)
                or payload.get("pause_contract") != "no_added_intersegment_silence_v1"
                or not isinstance(payload.get("prepared_text_identity"), str)
            ):
                raise ChapterAssemblyError("invalid_order", "Полный порядок сегментов не доказан.")
            for item in ordered:
                source, qa, wav = item.get("source"), item.get("qa"), item.get("wav")
                if not all(isinstance(value, dict) for value in (source, qa, wav)):
                    raise ChapterAssemblyError("invalid_input", "Неполная identity сегмента.")
                normalized_source, normalized_qa, normalized_wav, audio, manifest = self._validate_source(
                    source=source, qa=qa, wav=wav, label=f"Сегмент {item['segment_id']}"
                )
                item.update({"source": normalized_source, "qa": normalized_qa, "wav": normalized_wav})
                audios.append(audio)
                manifests.append(manifest)
            if len({str(path) for path in audios}) != len(audios):
                raise ChapterAssemblyError("duplicate_segment", "Один WAV назначен нескольким сегментам.")
        else:
            raise ChapterAssemblyError("invalid_granularity", "Неподдерживаемая гранулярность сборки.")
        return payload, audios, manifests

    def _resolution(self) -> FFmpegResolution:
        return resolve_ffmpeg(self.workspace_root)

    def _identity(self, payload: Mapping[str, Any], ffmpeg: FFmpegResolution) -> str:
        input_rates = self._input_rates(payload)
        conversion_required = any(rate != TARGET_SAMPLE_RATE_HZ for rate in input_rates)
        contract = {
            "schema_version": ASSEMBLY_SCHEMA_VERSION,
            "input": payload,
            "target": {
                "container": "WAV",
                "codec": "LPCM",
                "sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
                "channels": TARGET_CHANNELS,
                "sample_width_bytes": TARGET_SAMPLE_WIDTH_BYTES,
            },
            "normalization": {
                "required": conversion_required,
                "input_sample_rates_hz": input_rates,
                "tool": "ffmpeg" if conversion_required else "copy",
                "tool_version": ffmpeg.version if conversion_required else None,
            },
            "concat": {
                "contract": "pcm16_mono_48000_ordered_frames_v1",
                "pause_contract": payload.get("pause_contract", "source_is_joined_chapter_v1"),
            },
        }
        return _canonical_hash(contract)

    @staticmethod
    def _input_rates(payload: Mapping[str, Any]) -> list[int]:
        if payload.get("granularity") == "segments":
            return [int(item["wav"]["sample_rate_hz"]) for item in payload["ordered_inputs"]]
        return [int(payload["wav"]["sample_rate_hz"])]

    def prepare(self, value: Mapping[str, Any]) -> dict[str, Any]:
        payload, _, _ = self._validate_input(value)
        ffmpeg = self._resolution()
        conversion_required = any(rate != TARGET_SAMPLE_RATE_HZ for rate in self._input_rates(payload))
        blockers: list[str] = []
        if conversion_required and not ffmpeg.available:
            blockers.append("missing_ffmpeg")
        assembly_identity = self._identity(payload, ffmpeg)
        output_dir = self._output_dir(payload, assembly_identity)
        existing = self._read_ready(output_dir, assembly_identity)
        decision = "ALREADY_ASSEMBLED" if existing is not None else (
            "BLOCKED" if blockers else "READY_TO_ASSEMBLE"
        )
        return {
            "schema_version": ASSEMBLY_SCHEMA_VERSION,
            "state": "READY" if existing is not None else ("BLOCKED" if blockers else "PREPARED"),
            "decision": decision,
            "blockers": blockers,
            "blocker_message": (
                "Для подготовки мастер-файла требуется FFmpeg. Инструмент не найден."
                if blockers else None
            ),
            "assembly_identity": assembly_identity,
            "input": payload,
            "target": self._target_facts(),
            "ffmpeg": ffmpeg.to_dict(),
            "output_path": existing.get("output", {}).get("path") if existing else None,
            "manifest_path": str(output_dir / "MANIFEST.json") if existing else None,
            "segment_counts": {
                "expected": int(payload.get("expected_segment_count") or 1),
                "produced": int(payload.get("expected_segment_count") or 1),
                "approved": int(payload.get("expected_segment_count") or 1),
                "blocked": 0,
            },
            "provider_requests": 0,
            "remote_request_sent": False,
        }

    @staticmethod
    def _prepared_ffmpeg(prepared: Mapping[str, Any]) -> FFmpegResolution:
        facts = prepared["ffmpeg"]
        return FFmpegResolution(
            available=facts["available"],
            path=Path(facts["path"]) if facts.get("path") else None,
            version=facts.get("version"),
            source=facts["source"],
        )

    def _normalize_source(
        self,
        source: Path,
        destination: Path,
        *,
        sample_rate_hz: int,
        ffmpeg: FFmpegResolution,
    ) -> dict[str, Any]:
        arguments: list[str] = []
        converted = sample_rate_hz != TARGET_SAMPLE_RATE_HZ
        if converted:
            if not ffmpeg.available or ffmpeg.path is None:
                raise ChapterAssemblyError("missing_ffmpeg", "Для нормализации требуется FFmpeg.")
            arguments = [
                str(ffmpeg.path), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-map_metadata", "-1", "-vn", "-ac", "1",
                "-ar", str(TARGET_SAMPLE_RATE_HZ), "-c:a", "pcm_s16le",
                "-fflags", "+bitexact", "-flags:a", "+bitexact", str(destination),
            ]
            completed = subprocess.run(arguments, capture_output=True, timeout=300, check=False)
            if completed.returncode != 0:
                raise ChapterAssemblyError("ffmpeg_failed", "FFmpeg не смог подготовить WAV главы.")
        else:
            shutil.copyfile(source, destination)
        metadata = inspect_pcm_wav(destination)
        if (
            metadata.sample_rate_hz != TARGET_SAMPLE_RATE_HZ
            or metadata.channels != TARGET_CHANNELS
            or metadata.sample_width_bytes != TARGET_SAMPLE_WIDTH_BYTES
        ):
            raise ChapterAssemblyError("invalid_output", "Нормализованный WAV не соответствует PCM-контракту.")
        return {
            "required": converted,
            "performed": converted,
            "source_sha256": sha256_file(source),
            "normalized_sha256": sha256_file(destination),
            "wav": metadata.to_dict(),
            "ffmpeg_path": str(ffmpeg.path) if converted else None,
            "ffmpeg_version": ffmpeg.version if converted else None,
            "arguments": [
                "<ffmpeg>" if item == str(ffmpeg.path) else
                "<source>" if item == str(source) else
                "<output>" if item == str(destination) else item
                for item in arguments
            ],
        }

    @staticmethod
    def _concatenate_pcm(inputs: Sequence[Path], output: Path) -> tuple[int, list[int]]:
        per_input_frames: list[int] = []
        with wave.open(str(output), "wb") as target:
            target.setnchannels(TARGET_CHANNELS)
            target.setsampwidth(TARGET_SAMPLE_WIDTH_BYTES)
            target.setframerate(TARGET_SAMPLE_RATE_HZ)
            for source_path in inputs:
                with wave.open(str(source_path), "rb") as source:
                    if (
                        source.getnchannels() != TARGET_CHANNELS
                        or source.getsampwidth() != TARGET_SAMPLE_WIDTH_BYTES
                        or source.getframerate() != TARGET_SAMPLE_RATE_HZ
                        or source.getcomptype() != "NONE"
                    ):
                        raise ChapterAssemblyError("invalid_output", "Сегмент не соответствует PCM-контракту.")
                    frames = source.getnframes()
                    per_input_frames.append(frames)
                    remaining = frames
                    while remaining:
                        count = min(remaining, 65_536)
                        data = source.readframes(count)
                        if len(data) != count * TARGET_SAMPLE_WIDTH_BYTES * TARGET_CHANNELS:
                            raise ChapterAssemblyError("truncated_segment", "Сегмент оборван во время сборки.")
                        target.writeframesraw(data)
                        remaining -= count
            target.writeframes(b"")
        return sum(per_input_frames), per_input_frames

    def assemble(
        self,
        value: Mapping[str, Any],
        *,
        revalidate: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with production_authority_lock(
            self.workspace_root,
            provider=_safe_id(value.get("provider"), "provider"),
            book_slug=_safe_slug(str(value.get("book_slug") or "")),
            job_id=_safe_id(value.get("job_id"), "job_id"),
            profile_id=_safe_id(value.get("profile_id"), "profile_id"),
            exclusive=False,
        ):
            return self._assemble_locked(value, revalidate=revalidate)

    def _assemble_locked(
        self,
        value: Mapping[str, Any],
        *,
        revalidate: Callable[[], Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        prepared = self.prepare(value)
        if prepared["decision"] == "BLOCKED":
            raise ChapterAssemblyError("missing_ffmpeg", prepared["blocker_message"])
        if prepared["decision"] == "ALREADY_ASSEMBLED":
            return self._read_ready(
                Path(prepared["manifest_path"]).parent,
                prepared["assembly_identity"],
            ) or prepared

        payload, sources, manifests = self._validate_input(prepared["input"])
        assembly_identity = prepared["assembly_identity"]
        output_dir = self._output_dir(payload, assembly_identity)
        parent = output_dir.parent
        self._prepare_output_parent(parent)
        temporary = Path(tempfile.mkdtemp(prefix=".assembly-", dir=parent))
        try:
            source_snapshots = [self._file_snapshot(source) for source in sources]
            manifest_snapshots = [self._file_snapshot(manifest) for manifest in manifests]
            temporary_wav = temporary / "chapter.wav"
            ffmpeg = self._prepared_ffmpeg(prepared)
            normalization: list[dict[str, Any]] = []
            normalized_paths: list[Path] = []
            if payload["granularity"] == "segments":
                for index, (item, source) in enumerate(zip(payload["ordered_inputs"], sources), start=1):
                    normalized = temporary / f"normalized-{index:04d}.wav"
                    facts = self._normalize_source(
                        source, normalized,
                        sample_rate_hz=int(item["wav"]["sample_rate_hz"]),
                        ffmpeg=ffmpeg,
                    )
                    facts.update({"position": index, "segment_id": item["segment_id"]})
                    normalization.append(facts)
                    normalized_paths.append(normalized)
                output_frames, input_frames = self._concatenate_pcm(normalized_paths, temporary_wav)
                concat = {
                    "version": "pcm16_mono_48000_ordered_frames_v1",
                    "ordered_input_count": len(normalized_paths),
                    "ordered_input_frames": input_frames,
                    "output_frames": output_frames,
                    "pause_contract": payload["pause_contract"],
                    "added_pause_frames": 0,
                }
            else:
                facts = self._normalize_source(
                    sources[0], temporary_wav,
                    sample_rate_hz=int(payload["wav"]["sample_rate_hz"]),
                    ffmpeg=ffmpeg,
                )
                facts.update({"position": 1, "segment_id": payload["segment_id"]})
                normalization.append(facts)
                with wave.open(str(temporary_wav), "rb") as result_wave:
                    output_frames = result_wave.getnframes()
                concat = {
                    "version": "source_is_joined_chapter_v1",
                    "ordered_input_count": 1,
                    "ordered_input_frames": [output_frames],
                    "output_frames": output_frames,
                    "pause_contract": "source_is_joined_chapter_v1",
                    "added_pause_frames": 0,
                }

            for item, source, snapshot in zip(
                payload["ordered_inputs"] if payload["granularity"] == "segments" else [payload],
                sources,
                source_snapshots,
            ):
                expected_source = item["source"] if payload["granularity"] == "segments" else payload["source"]
                if self._file_snapshot(source) != snapshot or sha256_file(source) != expected_source["audio_sha256"]:
                    raise ChapterAssemblyError(
                        "source_changed_during_assembly", "Исходный WAV изменился во время сборки главы."
                    )

            metadata = inspect_pcm_wav(temporary_wav)
            if (
                metadata.sample_rate_hz != TARGET_SAMPLE_RATE_HZ
                or metadata.channels != TARGET_CHANNELS
                or metadata.sample_width_bytes != TARGET_SAMPLE_WIDTH_BYTES
            ):
                raise ChapterAssemblyError("invalid_output", "Собранный WAV не соответствует PCM-контракту.")
            output_sha = sha256_file(temporary_wav)
            if metadata.duration_seconds != output_frames / TARGET_SAMPLE_RATE_HZ:
                raise ChapterAssemblyError("duration_mismatch", "Длительность собранной главы не совпадает с входами.")
            if revalidate is not None:
                current_payload, _, _ = self._validate_input(revalidate())
                if _canonical_json(current_payload) != _canonical_json(payload):
                    raise ChapterAssemblyError(
                        "assembly_input_became_stale",
                        "Набор сегментов или QA-состояние изменились во время сборки.",
                    )
            if any(
                self._file_snapshot(path) != snapshot
                for path, snapshot in zip(manifests, manifest_snapshots)
            ):
                raise ChapterAssemblyError(
                    "manifest_changed_during_assembly",
                    "Production manifest изменился во время сборки главы.",
                )
            for normalized_path in normalized_paths:
                normalized_path.unlink()
            final_wav = output_dir / "chapter.wav"
            final_manifest = output_dir / "MANIFEST.json"
            manifest = {
                "schema_version": ASSEMBLY_SCHEMA_VERSION,
                "status": "READY",
                "assembly_identity": assembly_identity,
                "book_slug": payload["book_slug"],
                "book_title": payload["book_title"],
                "job_id": payload["job_id"],
                "job_label": payload["job_label"],
                "created_at": utc_now_iso(),
                "input_granularity": payload["granularity"],
                "expected_segment_count": int(payload.get("expected_segment_count") or 1),
                "ordered_segment_ids": payload.get("ordered_segment_ids", [payload["segment_id"]]),
                "ordered_inputs": payload["ordered_inputs"],
                "input": payload,
                "normalization": {
                    "required": any(item["required"] for item in normalization),
                    "performed": any(item["performed"] for item in normalization),
                    "effects": [],
                    "ffmpeg_path": str(ffmpeg.path) if any(item["performed"] for item in normalization) else None,
                    "ffmpeg_version": ffmpeg.version if any(item["performed"] for item in normalization) else None,
                    "ffmpeg_resolution": prepared["ffmpeg"],
                    "segments": normalization,
                },
                "pause_contract": concat["pause_contract"],
                "concat": concat,
                "output": {
                    "path": str(final_wav),
                    "path_identity": path_identity(final_wav),
                    "sha256": output_sha,
                    "wav": metadata.to_dict(),
                },
                "provider_requests": 0,
                "remote_request_sent": False,
            }
            atomic_write_json(temporary / "MANIFEST.json", manifest)
            for item, source, snapshot in zip(
                payload["ordered_inputs"] if payload["granularity"] == "segments" else [payload],
                sources,
                source_snapshots,
            ):
                expected_source = item["source"] if payload["granularity"] == "segments" else payload["source"]
                if self._file_snapshot(source) != snapshot or sha256_file(source) != expected_source["audio_sha256"]:
                    raise ChapterAssemblyError(
                        "source_changed_during_assembly", "Исходный WAV изменился во время сборки главы."
                    )
            if any(
                self._file_snapshot(path) != snapshot
                for path, snapshot in zip(manifests, manifest_snapshots)
            ):
                raise ChapterAssemblyError(
                    "manifest_changed_during_assembly",
                    "Production manifest изменился во время сборки главы.",
                )
            if revalidate is not None:
                final_payload, _, _ = self._validate_input(revalidate())
                if _canonical_json(final_payload) != _canonical_json(payload):
                    raise ChapterAssemblyError(
                        "assembly_input_became_stale",
                        "Набор сегментов или QA-состояние изменились перед публикацией.",
                    )
            try:
                temporary.rename(output_dir)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                existing = self._read_ready(output_dir, assembly_identity)
                if existing is None:
                    raise ChapterAssemblyError("publish_conflict", "Конфликт публикации сборки главы.")
                return existing
            atomic_write_json(parent / "CURRENT.json", {
                "schema_version": ASSEMBLY_SCHEMA_VERSION,
                "assembly_identity": assembly_identity,
                "manifest_path": str(final_manifest),
                "updated_at": utc_now_iso(),
            })
            return manifest
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def status(self, value: Mapping[str, Any]) -> dict[str, Any]:
        prepared = self.prepare(value)
        if prepared["decision"] == "ALREADY_ASSEMBLED":
            prepared["assembly"] = self._read_ready(
                Path(prepared["manifest_path"]).parent,
                prepared["assembly_identity"],
            )
            return prepared
        pointer = self._output_dir(prepared["input"], prepared["assembly_identity"]).parent / "CURRENT.json"
        if pointer.is_file():
            try:
                current = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            if current.get("assembly_identity") != prepared["assembly_identity"]:
                prepared["state"] = "STALE"
                prepared["decision"] = "READY_TO_ASSEMBLE" if not prepared["blockers"] else "BLOCKED"
        return prepared

    def _output_dir(self, payload: Mapping[str, Any], assembly_identity: str) -> Path:
        return (
            self.chapters_root
            / _safe_slug(str(payload["book_slug"]))
            / _safe_id(payload["job_id"], "job_id")
            / assembly_identity
        )

    def _prepare_output_parent(self, parent: Path) -> None:
        current = self.workspace_root
        relative = parent.relative_to(self.workspace_root)
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                raise ChapterAssemblyError("symlink_output_root", "Каталог сборки содержит символическую ссылку.")
            current.mkdir(exist_ok=True)

    @staticmethod
    def _target_facts() -> dict[str, Any]:
        return {
            "container": "WAV",
            "codec": "LPCM",
            "sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
            "channels": TARGET_CHANNELS,
            "sample_width_bytes": TARGET_SAMPLE_WIDTH_BYTES,
        }

    @staticmethod
    def _file_snapshot(path: Path) -> tuple[int, int, int, int, int]:
        metadata = path.stat()
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def _read_ready(self, output_dir: Path, assembly_identity: str) -> dict[str, Any] | None:
        manifest_path = output_dir / "MANIFEST.json"
        wav_path = output_dir / "chapter.wav"
        if not manifest_path.is_file() or not wav_path.is_file():
            return None
        try:
            _require_real_path(manifest_path, root=self.workspace_root, label="Assembly manifest")
            _require_real_path(wav_path, root=self.workspace_root, label="Assembly WAV")
        except ChapterAssemblyError:
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        output = payload.get("output") if isinstance(payload, dict) else None
        if (
            payload.get("schema_version") != ASSEMBLY_SCHEMA_VERSION
            or payload.get("status") != "READY"
            or payload.get("assembly_identity") != assembly_identity
            or not isinstance(output, dict)
            or output.get("path") != str(wav_path)
            or output.get("path_identity") != path_identity(wav_path)
            or output.get("sha256") != sha256_file(wav_path)
        ):
            return None
        metadata = inspect_pcm_wav(wav_path)
        if output.get("wav") != metadata.to_dict():
            return None
        return payload
