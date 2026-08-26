"""Offline, provider-neutral text preparation for canonical Audiobook Studio books."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from book_library import BookLibrary, BookLibraryError, sha256_bytes, sha256_file


PREPARATION_SCHEMA_VERSION = 1
NORMALIZATION_RULES_VERSION = "2"
SEGMENTATION_RULES_VERSION = "1"
NORMALIZED_RELATIVE_PATH = Path("prepared/normalized.txt")
STRUCTURE_RELATIVE_PATH = Path("prepared/structure.json")
SEGMENTS_RELATIVE_PATH = Path("prepared/segments.json")
TARGET_SEGMENT_CHARS = 900
HARD_SEGMENT_CHARS = 1200
PREVIEW_MAX_CHARS = 320
PREPARATION_STATES = {"NOT_PREPARED", "READY", "STALE", "SOURCE_INTEGRITY_ERROR"}

_RUSSIAN_ORDINAL_CHAPTERS = (
    "первая", "вторая", "третья", "четвёртая", "пятая",
    "шестая", "седьмая", "восьмая", "девятая", "десятая",
    "одиннадцатая", "двенадцатая", "тринадцатая", "четырнадцатая", "пятнадцатая",
    "шестнадцатая", "семнадцатая", "восемнадцатая", "девятнадцатая", "двадцатая",
)
_EXPLICIT_CHAPTER = re.compile(
    rf"^\s*глава\s+([0-9]+|[ivxlcdm]+|{'|'.join(_RUSSIAN_ORDINAL_CHAPTERS)})"
    r"(?:\s*[.\-—–:]\s*|\s+)?(.*?)\s*$",
    re.IGNORECASE,
)
_NUMERIC_CHAPTER = re.compile(r"^\s*(\d{1,3})[.)]\s+(.{1,120}?)\s*$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")


class BookTextPreparationError(RuntimeError):
    """A fail-closed local preparation error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def normalize_working_text(value: str) -> str:
    """Apply only deterministic, non-lexical V1 normalization."""
    if not isinstance(value, str):
        raise BookTextPreparationError("TTS working copy must be text.")
    if value.startswith("\ufeff"):
        value = value[1:]
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines: list[str] = []
    previous_blank = False
    for raw_line in value.split("\n"):
        line = raw_line.rstrip(" \t")
        blank = not line.strip()
        if blank:
            if previous_blank or not normalized_lines:
                continue
            normalized_lines.append("")
        else:
            normalized_lines.append(line)
        previous_blank = blank
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    normalized = "\n".join(normalized_lines)
    if not normalized.strip():
        raise BookTextPreparationError("TTS working copy is empty after conservative normalization.")
    return normalized + "\n"


def _is_heading_boundary(lines: list[str], index: int) -> bool:
    before = index == 0 or not lines[index - 1].strip()
    after = index == len(lines) - 1 or not lines[index + 1].strip()
    return before and after


def _numeric_progression(lines: list[str]) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, int, str, str]] = []
    for index, line in enumerate(lines):
        match = _NUMERIC_CHAPTER.fullmatch(line)
        if match and _is_heading_boundary(lines, index):
            candidates.append((index, int(match.group(1)), match.group(2).strip(), line.strip()))
    if len(candidates) < 2 or candidates[0][1] != 1:
        return []
    if [number for _, number, _, _ in candidates] != list(range(1, len(candidates) + 1)):
        return []
    return [(index, title, heading) for index, _, title, heading in candidates]


def detect_chapters(normalized_text: str) -> list[dict[str, Any]]:
    """Detect explicit Russian headings, otherwise return one conservative fallback chapter."""
    lines = normalized_text.rstrip("\n").split("\n")
    headings: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = _EXPLICIT_CHAPTER.fullmatch(line)
        if match:
            title = match.group(2).strip() or line.strip()
            headings.append((index, title, line.strip()))
    if not headings:
        headings = _numeric_progression(lines)
    if not headings:
        text = normalized_text.strip()
        return [{
            "id": "ch001",
            "index": 1,
            "heading": None,
            "title": "Основной текст",
            "body": text,
            "text": text,
        }]

    raw_chapters: list[tuple[str | None, str, str]] = []
    preamble = "\n".join(lines[:headings[0][0]]).strip()
    if preamble:
        raw_chapters.append((None, "Введение", preamble))
    for position, (line_index, title, heading) in enumerate(headings):
        next_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_index + 1:next_index]).strip()
        raw_chapters.append((heading, title, body))

    result: list[dict[str, Any]] = []
    for index, (heading, title, body) in enumerate(raw_chapters, 1):
        spoken_text = "\n\n".join(part for part in (heading, body) if part and part.strip())
        if not spoken_text.strip():
            continue
        result.append({
            "id": f"ch{index:03d}",
            "index": index,
            "heading": heading,
            "title": title,
            "body": body,
            "text": spoken_text,
        })
    if not result:
        raise BookTextPreparationError("Chapter detection produced no readable text.")
    return result


def _split_hard(value: str, hard_chars: int) -> list[str]:
    remaining = value.strip()
    result: list[str] = []
    while len(remaining) > hard_chars:
        boundary = max(remaining.rfind(" ", 0, hard_chars + 1), remaining.rfind("\n", 0, hard_chars + 1))
        if boundary <= 0:
            boundary = hard_chars
        piece = remaining[:boundary].rstrip()
        if piece:
            result.append(piece)
        remaining = remaining[boundary:].lstrip()
    if remaining:
        result.append(remaining)
    return result


def _split_long_paragraph(paragraph: str, target_chars: int, hard_chars: int) -> list[str]:
    sentences = [item.strip() for item in _SENTENCE_BOUNDARY.split(paragraph.strip()) if item.strip()]
    pieces: list[str] = []
    for sentence in sentences:
        pieces.extend(_split_hard(sentence, hard_chars))
    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if current and len(candidate) > target_chars:
            packed.append(current)
            current = piece
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def segment_chapter_text(
    chapter: Mapping[str, Any],
    *,
    target_chars: int = TARGET_SEGMENT_CHARS,
    hard_chars: int = HARD_SEGMENT_CHARS,
) -> list[dict[str, Any]]:
    if target_chars <= 0 or hard_chars < target_chars:
        raise BookTextPreparationError("Invalid provider-neutral segmentation limits.")
    text = str(chapter.get("text") or "").strip()
    if not text:
        raise BookTextPreparationError(f"Chapter {chapter.get('id')} is empty.")
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    packed: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > hard_chars:
            if current:
                packed.append(current)
                current = ""
            packed.extend(_split_long_paragraph(paragraph, target_chars, hard_chars))
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > target_chars:
            packed.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        packed.append(current)
    if not packed or any(not item.strip() or len(item) > hard_chars for item in packed):
        raise BookTextPreparationError(f"Chapter {chapter.get('id')} could not be segmented safely.")

    result: list[dict[str, Any]] = []
    chapter_id = str(chapter["id"])
    for index, prepared_text in enumerate(packed, 1):
        prepared_hash = sha256_bytes(prepared_text.encode("utf-8"))
        result.append({
            "id": f"{chapter_id}_s{index:04d}",
            "chapter_id": chapter_id,
            "chapter_index": int(chapter["index"]),
            "index": index,
            "text": prepared_text,
            "characters": len(prepared_text),
            "utf8_bytes": len(prepared_text.encode("utf-8")),
            "source_text_sha256": prepared_hash,
            "prepared_text_sha256": prepared_hash,
            "pause_after_ms": 700 if index < len(packed) else 0,
        })
    return result


def _preview_text(normalized_text: str, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    value = normalized_text.strip()
    if len(value) <= max_chars:
        return value
    prefix = value[:max_chars + 1]
    punctuation = max(prefix.rfind(mark) for mark in (".", "!", "?", "…"))
    if punctuation >= 80:
        return prefix[:punctuation + 1].rstrip()
    boundary = max(prefix.rfind(" "), prefix.rfind("\n"))
    return prefix[:boundary if boundary > 0 else max_chars].rstrip()


class BookTextPreparationService:
    def __init__(
        self,
        library: BookLibrary,
        *,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.library = library
        self._now = now or _utc_now

    def status(self, book_id: str | Path) -> dict[str, Any]:
        details = self.library.book_details(book_id)
        return {
            "schema_version": PREPARATION_SCHEMA_VERSION,
            "book_id": details["book_id"],
            "slug": details["slug"],
            "source_integrity": details["source_integrity"],
            "working_copy_sha256": details["tts_working_copy_current_sha256"],
            "preparation_status": details["preparation_status"],
            "preparation_revision": details["preparation_revision"],
            "preparation_identity": details["preparation_identity"],
            "prepared_at": details["prepared_at"],
            "normalized_sha256": details["normalized_sha256"],
            "chapter_count": details["chapter_count"],
            "segment_count": details["prepared_segment_count"],
            "jobs": details["jobs"],
            "normalized_path": details["normalized_path"],
            "structure_path": details["structure_path"],
            "segments_path": details["segments_path"],
            "remote_request_sent": False,
        }

    def prepare(self, book_id: str | Path) -> dict[str, Any]:
        profile_path = self.library.resolve_book_profile(book_id)
        raw_book = self.library.load_book_profile(profile_path.name)
        slug = str(raw_book.get("slug") or profile_path.stem)
        asset_root = self.library.books_root / slug
        if not asset_root.is_dir():
            raise BookTextPreparationError("Canonical book asset directory is missing.")
        lock_path = asset_root / ".prepare-text.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            return self._prepare_locked(profile_path.name, asset_root)

    def _prepare_locked(self, book_id: str, asset_root: Path) -> dict[str, Any]:
        book = self.library.load_book_profile(book_id)
        details = self.library.book_details(book_id)
        if details["source_integrity"] != "OK":
            raise BookTextPreparationError("SOURCE_INTEGRITY_ERROR: immutable source integrity must be OK.")
        tts = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else {}
        try:
            source_path = self.library.resolve_book_asset(book_id, (book.get("source") or {}).get("path"))
            working_path = self.library.resolve_book_asset(book_id, tts.get("path"))
        except BookLibraryError as error:
            raise BookTextPreparationError(str(error)) from error
        if working_path.is_symlink() or not working_path.is_file():
            raise BookTextPreparationError("TTS working copy is missing or unsafe.")
        try:
            working_bytes = working_path.read_bytes()
            working_text = working_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise BookTextPreparationError("TTS working copy must use strict UTF-8 encoding.") from error
        working_sha = sha256_bytes(working_bytes)
        source_sha = sha256_file(source_path)
        normalized_text = normalize_working_text(working_text)
        normalized_bytes = normalized_text.encode("utf-8")
        normalized_sha = sha256_bytes(normalized_bytes)
        chapters = detect_chapters(normalized_text)
        all_segments: list[dict[str, Any]] = []
        for chapter in chapters:
            chapter_segments = segment_chapter_text(chapter)
            chapter["segment_ids"] = [item["id"] for item in chapter_segments]
            all_segments.extend(chapter_segments)
        if not all_segments:
            raise BookTextPreparationError("Preparation produced no segments.")

        identity_payload = {
            "working_copy_sha256": working_sha,
            "preparation_schema_version": PREPARATION_SCHEMA_VERSION,
            "normalization_rules_version": NORMALIZATION_RULES_VERSION,
            "segmentation_rules_version": SEGMENTATION_RULES_VERSION,
            "target_segment_chars": TARGET_SEGMENT_CHARS,
            "hard_segment_chars": HARD_SEGMENT_CHARS,
        }
        identity_sha = _canonical_hash(identity_payload)
        previous = book.get("preparation") if isinstance(book.get("preparation"), dict) else {}
        revision = int(previous.get("revision") or 0) + 1
        prepared_at = self._now()
        preview_text = _preview_text(normalized_text)
        preview_hash = sha256_bytes(preview_text.encode("utf-8"))
        preview = {
            "id": "preview_s0001",
            "chapter_id": chapters[0]["id"],
            "chapter_index": chapters[0]["index"],
            "index": 1,
            "text": preview_text,
            "characters": len(preview_text),
            "utf8_bytes": len(preview_text.encode("utf-8")),
            "source_text_sha256": preview_hash,
            "prepared_text_sha256": preview_hash,
            "pause_after_ms": 0,
        }

        structure_payload = {
            "schema_version": PREPARATION_SCHEMA_VERSION,
            "preparation_identity": identity_sha,
            "normalization_rules_version": NORMALIZATION_RULES_VERSION,
            "chapters": [{
                "id": chapter["id"],
                "index": chapter["index"],
                "heading": chapter["heading"],
                "title": chapter["title"],
                "body": chapter["body"],
                "body_sha256": sha256_bytes(str(chapter["body"]).encode("utf-8")),
                "body_characters": len(str(chapter["body"])),
                "segment_ids": chapter["segment_ids"],
            } for chapter in chapters],
        }
        segments_payload = {
            "schema_version": PREPARATION_SCHEMA_VERSION,
            "preparation_identity": identity_sha,
            "segmentation_rules_version": SEGMENTATION_RULES_VERSION,
            "target_segment_chars": TARGET_SEGMENT_CHARS,
            "hard_segment_chars": HARD_SEGMENT_CHARS,
            "segments": all_segments,
            "preview": preview,
        }
        managed_jobs: dict[str, Any] = {
            "short-test": {
                "label": "Безопасный короткий тест",
                "kind": "preview",
                "preparation_identity": identity_sha,
                "segment_ids": [preview["id"]],
            }
        }
        for chapter in chapters:
            managed_jobs[f"chapter-{chapter['id']}"] = {
                "label": str(chapter["title"]),
                "kind": "chapter",
                "chapter_id": chapter["id"],
                "preparation_identity": identity_sha,
                "segment_ids": list(chapter["segment_ids"]),
            }
        previous_managed = set(previous.get("managed_job_ids") or [])
        preserved_jobs = {
            key: value
            for key, value in book["jobs"].items()
            if key not in previous_managed
        }
        collisions = sorted(set(preserved_jobs).intersection(managed_jobs))
        if collisions:
            raise BookTextPreparationError(
                f"Prepared job ID collides with an unmanaged existing job: {', '.join(collisions)}"
            )
        new_jobs = {**managed_jobs, **preserved_jobs}
        preparation = {
            "schema_version": PREPARATION_SCHEMA_VERSION,
            "status": "READY",
            "revision": revision,
            "prepared_at": prepared_at,
            "working_copy_sha256": working_sha,
            "source_sha256": source_sha,
            "identity_sha256": identity_sha,
            "normalization_rules_version": NORMALIZATION_RULES_VERSION,
            "segmentation_rules_version": SEGMENTATION_RULES_VERSION,
            "target_segment_chars": TARGET_SEGMENT_CHARS,
            "hard_segment_chars": HARD_SEGMENT_CHARS,
            "normalized_sha256": normalized_sha,
            "normalized_path": NORMALIZED_RELATIVE_PATH.as_posix(),
            "structure_path": STRUCTURE_RELATIVE_PATH.as_posix(),
            "segments_path": SEGMENTS_RELATIVE_PATH.as_posix(),
            "chapter_count": len(chapters),
            "segment_count": len(all_segments),
            "managed_job_ids": list(managed_jobs),
        }

        token = uuid.uuid4().hex
        staging = asset_root / f".prepared-stage-{token}"
        final = asset_root / "prepared"
        backup = asset_root / f".prepared-backup-{token}"
        published_artifacts = False
        profile_published = False
        try:
            (staging / "normalized.txt").parent.mkdir(parents=True, exist_ok=False)
            (staging / "normalized.txt").write_bytes(normalized_bytes)
            _atomic_write_json(staging / "structure.json", structure_payload)
            _atomic_write_json(staging / "segments.json", segments_payload)
            if sha256_file(staging / "normalized.txt") != normalized_sha:
                raise BookTextPreparationError("Normalized text verification failed.")
            if sha256_file(source_path) != source_sha or sha256_file(working_path) != working_sha:
                raise BookTextPreparationError("Book source or working copy changed during preparation.")
            if final.exists():
                os.replace(final, backup)
            os.replace(staging, final)
            published_artifacts = True
            updated_book = dict(book)
            updated_book["jobs"] = new_jobs
            updated_book["preparation"] = preparation
            self.library.replace_book_profile(book_id, updated_book)
            profile_published = True
            if backup.exists():
                shutil.rmtree(backup)
        except Exception:
            if published_artifacts and not profile_published and final.exists():
                shutil.rmtree(final)
            if not profile_published and backup.exists() and not final.exists():
                os.replace(backup, final)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        result = self.status(book_id)
        if result["preparation_status"] != "READY":
            raise BookTextPreparationError("Published preparation did not pass READY integrity checks.")
        return result
