"""Offline whole-book delivery formats for Audiobook Studio.

The author must explicitly choose one format per book.  There is deliberately
no default selection.  All outputs are derived from the existing exact-current
release authority and clean chapter masters; this module never performs TTS,
network, paid, or billing operations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from audio_qa_review import path_identity, sha256_file
from backends.common import atomic_write_json, utc_now_iso
from book_library import BookLibraryError, normalize_slug
from mastering_export import (
    MasteringExportError,
    _canonical_json,
    _prepare_output_parent,
    _require_regular_path,
    _safe_output_name,
    _validate_output_root,
    resolve_current_master,
)
from media_tools import FFmpegResolution, resolve_ffmpeg
from production_authority_lock import production_authority_lock


SCHEMA_VERSION = 1
PROFILE_VERSION = 1

DELIVERY_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "id": "chapters",
        "title": "По главам",
        "description": "Отдельный готовый файл для каждой главы.",
        "detail": "Подходит для загрузки на большинство площадок.",
        "kind": "directory",
        "extension": None,
        "requires_complete_book": False,
        "recommended": False,
        "internal_profile": "litres_author_v1",
    },
    {
        "id": "m4b",
        "title": "Одним файлом M4B",
        "description": "Вся книга одним файлом с оглавлением и обложкой.",
        "detail": "Удобно слушать как обычную аудиокнигу на телефоне и компьютере.",
        "kind": "file",
        "extension": "m4b",
        "requires_complete_book": True,
        "recommended": False,
        "audio": {"codec": "AAC", "bitrate_bps": 128_000, "sample_rate_hz": 48_000, "channels": 1},
    },
    {
        "id": "mp3",
        "title": "Одним файлом MP3",
        "description": "Вся книга одним универсальным аудиофайлом.",
        "detail": "Подходит для устройств и сервисов без поддержки M4B.",
        "kind": "file",
        "extension": "mp3",
        "requires_complete_book": True,
        "recommended": False,
        "audio": {"codec": "MP3", "bitrate_bps": 192_000, "sample_rate_hz": 44_100, "channels": 1, "bitrate_mode": "CBR"},
    },
    {
        "id": "hq_archive",
        "title": "Архив высокого качества",
        "description": "Мастер-файлы всех глав без дополнительного сжатия в одном архиве.",
        "detail": "Для хранения, передачи звукорежиссёру и будущих переизданий.",
        "kind": "file",
        "extension": "zip",
        "requires_complete_book": True,
        "recommended": False,
        "audio": {"codec": "PCM16 WAV", "sample_rate_hz": 48_000, "channels": 1},
    },
)

PROFILE_BY_ID = {item["id"]: item for item in DELIVERY_PROFILES}


class BookDeliveryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _book_slug(value: Any) -> str:
    try:
        return normalize_slug(str(value or ""))
    except BookLibraryError as error:
        raise BookDeliveryError("invalid_book_slug", "Некорректная книга.") from error


def _safe_component(value: str, fallback: str) -> str:
    text = re.sub(r"[\x00-\x1f/:\\]", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .") or fallback
    return text[:140].rstrip(" .") or fallback


def _chapter_filename(position: int, title: str, extension: str) -> str:
    mp3_name = _safe_output_name(position, title)
    return str(Path(mp3_name).with_suffix(f".{extension}"))


def _ffmetadata_escape(value: str) -> str:
    result = str(value).replace("\\", "\\\\")
    for character in ("=", ";", "#"):
        result = result.replace(character, f"\\{character}")
    return result.replace("\n", " ").replace("\r", " ")


def _write_ffmetadata(path: Path, *, book: Mapping[str, Any], chapters: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        ";FFMETADATA1",
        f"title={_ffmetadata_escape(str(book.get('title') or 'Аудиокнига'))}",
        f"artist={_ffmetadata_escape(str(book.get('author') or ''))}",
        f"album={_ffmetadata_escape(str(book.get('title') or 'Аудиокнига'))}",
    ]
    cursor_ms = 0
    for item in chapters:
        duration_ms = max(1, round(float(item["wav"]["duration_seconds"]) * 1000))
        end_ms = cursor_ms + duration_ms
        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={cursor_ms}",
            f"END={end_ms}",
            f"title={_ffmetadata_escape(str(item['title']))}",
        ])
        cursor_ms = end_ms
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _zip_add_file(archive: zipfile.ZipFile, source: Path, name: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with source.open("rb") as handle, archive.open(info, "w") as target:
        shutil.copyfileobj(handle, target, length=1024 * 1024)


class BookDeliveryService:
    def __init__(self, *, workspace_root: Path, exports_root: Path, masters_root: Path) -> None:
        requested_workspace = Path(workspace_root).expanduser().absolute()
        self.workspace_root = requested_workspace.resolve(strict=True)
        self.exports_root = _validate_output_root(requested_workspace, exports_root, "Exports root")
        self.masters_root = Path(masters_root).expanduser().absolute()
        try:
            self.masters_root.relative_to(self.workspace_root)
        except ValueError as error:
            raise BookDeliveryError("masters_root_escape", "Masters root вне рабочего пространства.") from error
        self.settings_root = self.workspace_root / "settings" / "book-delivery"

    def _selection_path(self, book_slug: str) -> Path:
        return self.settings_root / f"{_book_slug(book_slug)}.json"

    def selected_profile(self, book_slug: str) -> str | None:
        path = self._selection_path(book_slug)
        if not path.is_file() or path.is_symlink():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = payload.get("selected_profile_id") if isinstance(payload, Mapping) else None
        return value if value in PROFILE_BY_ID else None

    def set_selected_profile(self, book_slug: str, profile_id: str | None) -> dict[str, Any]:
        book = _book_slug(book_slug)
        if profile_id not in PROFILE_BY_ID and profile_id is not None:
            raise BookDeliveryError("unknown_delivery_profile", "Неизвестный формат выпуска.")
        _prepare_output_parent(self.workspace_root, self.settings_root)
        path = self._selection_path(book)
        if path.is_symlink():
            raise BookDeliveryError("symlink_setting", "Настройка формата является ссылкой.")
        atomic_write_json(path, {
            "schema_version": SCHEMA_VERSION,
            "book_slug": book,
            "selected_profile_id": profile_id,
            "updated_at": utc_now_iso(),
        })
        return self.selection_status(book)

    def selection_status(self, book_slug: str) -> dict[str, Any]:
        selected = self.selected_profile(book_slug)
        return {
            "schema_version": SCHEMA_VERSION,
            "book_slug": _book_slug(book_slug),
            "selected_profile_id": selected,
            "profiles": [dict(item) for item in DELIVERY_PROFILES],
            "decision": "READY" if selected else "SELECTION_REQUIRED",
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }

    def _profile_root(self, book_slug: str, profile_id: str) -> Path:
        return self.exports_root / _book_slug(book_slug) / "delivery" / profile_id

    def _validated_release(self, value: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        manifest = json.loads(json.dumps(value, ensure_ascii=False))
        if manifest.get("status") != "RELEASE_READY":
            raise BookDeliveryError("book_not_ready", "Сначала примите и подготовьте все главы книги.")
        whole = manifest.get("whole_book")
        book = manifest.get("book")
        records = manifest.get("chapters")
        if (
            not isinstance(whole, Mapping)
            or whole.get("ready") is not True
            or not isinstance(book, Mapping)
            or not isinstance(records, list)
            or len(records) != int(whole.get("expected_chapters") or 0)
        ):
            raise BookDeliveryError("book_not_ready", "Полный комплект принятых глав ещё не готов.")
        slug = _book_slug(book.get("slug"))
        chapters: list[dict[str, Any]] = []
        for expected, record in zip(book.get("chapters") or [], records, strict=True):
            if not isinstance(expected, Mapping) or not isinstance(record, Mapping):
                raise BookDeliveryError("invalid_release_authority", "Порядок глав повреждён.")
            if expected.get("job_id") != record.get("job_id"):
                raise BookDeliveryError("invalid_release_authority", "Порядок глав не совпадает с книгой.")
            master = resolve_current_master(
                workspace_root=self.workspace_root,
                masters_root=self.masters_root,
                book_slug=slug,
                job_id=str(record.get("job_id") or ""),
                expected_master_identity=record.get("master_identity"),
            )
            if (
                master.get("audio_sha256") != record.get("master_sha256")
                or master.get("master_manifest_sha256") != record.get("master_manifest_sha256")
            ):
                raise BookDeliveryError("stale_master", "Одна из глав изменилась после подготовки выпуска.")
            audio = _require_regular_path(Path(master["audio_path"]), root=self.workspace_root, label="Chapter master")
            chapters.append({
                "position": int(record.get("position") or len(chapters) + 1),
                "job_id": str(record["job_id"]),
                "chapter_id": str(record.get("chapter_id") or ""),
                "title": str(record.get("chapter_title") or expected.get("title") or record["job_id"]),
                "master_identity": str(record["master_identity"]),
                "master_manifest_sha256": str(record["master_manifest_sha256"]),
                "audio_path": str(audio),
                "audio_sha256": str(master["audio_sha256"]),
                "path_identity": path_identity(audio),
                "wav": dict(master["wav"]),
            })
        return dict(book), chapters

    def _identity(self, profile_id: str, book: Mapping[str, Any], chapters: Sequence[Mapping[str, Any]]) -> str:
        return _hash({
            "schema_version": SCHEMA_VERSION,
            "profile": PROFILE_BY_ID[profile_id],
            "book": {
                "slug": book.get("slug"), "title": book.get("title"),
                "author": book.get("author"), "cover": book.get("cover"),
            },
            "chapters": [
                {key: item[key] for key in (
                    "position", "job_id", "chapter_id", "title", "master_identity",
                    "master_manifest_sha256", "audio_sha256", "wav",
                )}
                for item in chapters
            ],
        })

    def _current(self, book_slug: str, profile_id: str) -> dict[str, Any] | None:
        pointer = self._profile_root(book_slug, profile_id) / "CURRENT.json"
        if not pointer.is_file() or pointer.is_symlink():
            return None
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            manifest = _require_regular_path(Path(data["manifest_path"]), root=self.workspace_root, label="Delivery manifest")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            output = _require_regular_path(Path(payload["output"]["path"]), root=self.workspace_root, label="Delivery output")
            if (
                payload.get("schema_version") != SCHEMA_VERSION
                or payload.get("delivery_identity") != data.get("delivery_identity")
                or payload.get("profile_id") != profile_id
                or payload.get("output", {}).get("sha256") != sha256_file(output)
                or payload.get("output", {}).get("path_identity") != path_identity(output)
            ):
                return None
            payload["manifest_path"] = str(manifest)
            return payload
        except (OSError, ValueError, KeyError, TypeError, MasteringExportError):
            return None

    def status(self, book_slug: str, release_manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
        base = self.selection_status(book_slug)
        selected = base["selected_profile_id"]
        expected = ready = 0
        blockers: list[str] = []
        release_ready = False
        if isinstance(release_manifest, Mapping):
            whole = release_manifest.get("whole_book")
            if isinstance(whole, Mapping):
                expected = int(whole.get("expected_chapters") or 0)
                ready = int(whole.get("ready_chapters") or 0)
                release_ready = bool(whole.get("ready") is True and release_manifest.get("status") == "RELEASE_READY")
                blockers = [str(item) for item in whole.get("blockers") or []]
        current = self._current(book_slug, selected) if selected and selected != "chapters" else None
        if selected is None:
            decision = "SELECTION_REQUIRED"
        elif selected == "chapters":
            decision = "CHAPTERS_SELECTED"
        elif not release_ready:
            decision = "BOOK_INCOMPLETE"
        elif current is not None:
            decision = "ALREADY_EXPORTED"
        else:
            decision = "READY_TO_EXPORT"
        return {
            **base,
            "decision": decision,
            "expected_chapters": expected,
            "ready_chapters": ready,
            "book_ready": release_ready,
            "blockers": blockers,
            "delivery": current,
        }

    def _ffmpeg(self) -> tuple[FFmpegResolution, Path]:
        resolution = resolve_ffmpeg(self.workspace_root)
        if not resolution.available or resolution.path is None:
            raise BookDeliveryError("ffmpeg_unavailable", "Инструмент подготовки аудио недоступен.")
        ffprobe = resolution.path.with_name("ffprobe")
        if not ffprobe.is_file() or not os.access(ffprobe, os.X_OK):
            raise BookDeliveryError("ffprobe_unavailable", "Инструмент проверки аудио недоступен.")
        return resolution, ffprobe

    def _cover(self, book: Mapping[str, Any]) -> Path:
        cover = book.get("cover")
        if not isinstance(cover, Mapping) or not isinstance(cover.get("path"), str):
            raise BookDeliveryError("missing_cover", "Для выпуска нужна обложка.")
        path = _require_regular_path(Path(cover["path"]), root=self.workspace_root, label="Book cover")
        if cover.get("sha256") != sha256_file(path):
            raise BookDeliveryError("cover_changed", "Обложка изменилась.")
        return path

    def _encode_audio(
        self, *, profile_id: str, book: Mapping[str, Any], chapters: Sequence[Mapping[str, Any]],
        output: Path, working: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resolution, ffprobe = self._ffmpeg()
        cover = self._cover(book)
        metadata = working / "chapters.ffmeta"
        _write_ffmetadata(metadata, book=book, chapters=chapters)
        inputs: list[str] = []
        for item in chapters:
            inputs.extend(["-i", str(item["audio_path"])])
        cover_index = len(chapters)
        metadata_index = cover_index + 1
        filter_inputs = "".join(f"[{index}:a:0]" for index in range(len(chapters)))
        arguments = [
            str(resolution.path), "-nostdin", "-hide_banner", "-loglevel", "error",
            *inputs, "-i", str(cover), "-f", "ffmetadata", "-i", str(metadata),
            "-filter_complex", f"{filter_inputs}concat=n={len(chapters)}:v=0:a=1[a]",
            "-map", "[a]", "-map", f"{cover_index}:v:0", "-map_metadata", str(metadata_index),
            "-map_chapters", str(metadata_index), "-c:v", "copy", "-disposition:v", "attached_pic",
            "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)",
        ]
        if profile_id == "m4b":
            arguments.extend(["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1", "-movflags", "+faststart"])
        else:
            arguments.extend([
                "-c:a", "libmp3lame", "-b:a", "192k", "-minrate", "192k", "-maxrate", "192k",
                "-bufsize", "384k", "-ar", "44100", "-ac", "1", "-write_xing", "0", "-id3v2_version", "3",
            ])
        arguments.append(str(output))
        completed = subprocess.run(arguments, capture_output=True, timeout=7200, check=False)
        if completed.returncode != 0:
            raise BookDeliveryError("whole_book_encode_failed", "Не удалось собрать единый аудиофайл.")
        probe = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json", str(output)],
            capture_output=True, text=True, timeout=300, check=False,
        )
        if probe.returncode != 0:
            raise BookDeliveryError("whole_book_validation_failed", "Готовый аудиофайл не прошёл проверку.")
        facts = json.loads(probe.stdout)
        audio_streams = [item for item in facts.get("streams", []) if item.get("codec_type") == "audio"]
        if len(audio_streams) != 1:
            raise BookDeliveryError("whole_book_validation_failed", "В готовом файле повреждён аудиопоток.")
        if profile_id == "m4b" and len(facts.get("chapters") or []) != len(chapters):
            raise BookDeliveryError("chapter_markers_missing", "Оглавление M4B не совпадает с главами книги.")
        tool = {"path": str(resolution.path), "version": resolution.version, "source": resolution.source}
        return facts, tool

    def _build_archive(
        self, *, book: Mapping[str, Any], chapters: Sequence[Mapping[str, Any]], output: Path, working: Path,
    ) -> dict[str, Any]:
        index = {
            "schema_version": SCHEMA_VERSION,
            "title": book.get("title"), "author": book.get("author"),
            "chapters": [
                {"position": item["position"], "title": item["title"], "filename": _chapter_filename(item["position"], item["title"], "wav"), "sha256": item["audio_sha256"]}
                for item in chapters
            ],
        }
        index_path = working / "book.json"
        index_path.write_bytes(_canonical_json(index) + b"\n")
        cover = self._cover(book)
        with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
            _zip_add_file(archive, index_path, "book.json")
            _zip_add_file(archive, cover, f"cover{cover.suffix.lower()}")
            for item in chapters:
                _zip_add_file(archive, Path(item["audio_path"]), f"chapters/{_chapter_filename(item['position'], item['title'], 'wav')}")
        with zipfile.ZipFile(output, "r") as archive:
            bad = archive.testzip()
            if bad is not None or len(archive.namelist()) != len(chapters) + 2:
                raise BookDeliveryError("archive_validation_failed", "Архив не прошёл проверку.")
        return {"entries": len(chapters) + 2, "lossless": True, "chapter_files": len(chapters)}

    def export(self, book_slug: str, release_manifest: Mapping[str, Any]) -> dict[str, Any]:
        book_key = _book_slug(book_slug)
        profile_id = self.selected_profile(book_key)
        if profile_id is None:
            raise BookDeliveryError("selection_required", "Сначала выберите формат выпуска.")
        if profile_id == "chapters":
            return self.status(book_key, release_manifest)
        book, chapters = self._validated_release(release_manifest)
        if _book_slug(book.get("slug")) != book_key:
            raise BookDeliveryError("book_identity_mismatch", "Файлы выпуска относятся к другой книге.")
        identity = self._identity(profile_id, book, chapters)
        profile_root = self._profile_root(book_key, profile_id)
        with production_authority_lock(
            self.workspace_root, provider="delivery", book_slug=book_key,
            job_id="book", profile_id=profile_id, exclusive=True,
        ):
            current = self._current(book_key, profile_id)
            if current is not None and current.get("delivery_identity") == identity:
                return self.status(book_key, release_manifest)
            _prepare_output_parent(self.workspace_root, profile_root)
            output_dir = profile_root / identity
            if output_dir.is_symlink():
                raise BookDeliveryError("symlink_output", "Каталог выпуска является ссылкой.")
            temporary = Path(tempfile.mkdtemp(prefix=".delivery-", dir=profile_root))
            try:
                extension = str(PROFILE_BY_ID[profile_id]["extension"])
                output_name = f"{_safe_component(str(book.get('title') or ''), book_key)}.{extension}"
                temporary_output = temporary / output_name
                if profile_id in {"m4b", "mp3"}:
                    verification, tool = self._encode_audio(
                        profile_id=profile_id, book=book, chapters=chapters,
                        output=temporary_output, working=temporary,
                    )
                else:
                    verification = self._build_archive(book=book, chapters=chapters, output=temporary_output, working=temporary)
                    tool = {"name": "python.zipfile", "version": "1"}
                final_output = output_dir / output_name
                manifest = {
                    "schema_version": SCHEMA_VERSION,
                    "status": "READY",
                    "delivery_identity": identity,
                    "profile_id": profile_id,
                    "profile": PROFILE_BY_ID[profile_id],
                    "created_at": utc_now_iso(),
                    "book": {"slug": book_key, "title": book.get("title"), "author": book.get("author")},
                    "chapters": [{key: item[key] for key in ("position", "job_id", "chapter_id", "title", "master_identity", "master_manifest_sha256", "audio_sha256", "wav")} for item in chapters],
                    "output": {
                        "path": str(final_output), "path_identity": path_identity(final_output),
                        "sha256": sha256_file(temporary_output), "size_bytes": temporary_output.stat().st_size,
                    },
                    "verification": verification,
                    "tool": tool,
                    "provider_requests": 0,
                    "remote_request_sent": False,
                    "paid_execution": False,
                    "billing_changed": False,
                }
                atomic_write_json(temporary / "MANIFEST.json", manifest)
                if output_dir.exists():
                    existing = self._current(book_key, profile_id)
                    if existing is not None and existing.get("delivery_identity") == identity:
                        return self.status(book_key, release_manifest)
                    raise BookDeliveryError("publish_conflict", "Конфликт готового выпуска.")
                temporary.rename(output_dir)
                atomic_write_json(profile_root / "CURRENT.json", {
                    "schema_version": SCHEMA_VERSION,
                    "delivery_identity": identity,
                    "manifest_path": str(output_dir / "MANIFEST.json"),
                    "updated_at": utc_now_iso(),
                })
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return self.status(book_key, release_manifest)
