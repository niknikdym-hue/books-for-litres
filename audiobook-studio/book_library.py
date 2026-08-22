"""Provider-neutral canonical local book library for Audiobook Studio."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


BOOK_SCHEMA_VERSION = 1
SOURCE_RELATIVE_PATH = Path("source/original.txt")
TTS_RELATIVE_PATH = Path("tts/working.txt")
SOURCE_INTEGRITY_STATES = {"OK", "MISSING", "HASH_MISMATCH"}


class BookLibraryError(RuntimeError):
    """A fail-closed local book-library error."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_slug(value: str) -> str:
    """Normalize case/Unicode while rejecting unsafe or ambiguous path input."""
    if not isinstance(value, str):
        raise BookLibraryError("Book ID / slug must be text.")
    slug = unicodedata.normalize("NFKC", value).strip().lower()
    if not slug or len(slug) > 80:
        raise BookLibraryError("Book ID / slug must contain 1–80 characters.")
    if slug in {".", ".."} or slug.startswith(".") or slug.endswith("."):
        raise BookLibraryError("Book ID / slug is not filesystem-safe.")
    if not slug[0].isalnum() or not slug[-1].isalnum():
        raise BookLibraryError("Book ID / slug must start and end with a letter or number.")
    if any(not (character.isalnum() or character in "-_") for character in slug):
        raise BookLibraryError("Book ID / slug may contain only letters, numbers, '-' and '_'.")
    if any(separator in slug for separator in ("/", "\\", os.sep, os.altsep or os.sep)):
        raise BookLibraryError("Book ID / slug cannot contain a path.")
    return slug


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BookLibraryError(f"{label} is required.")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


class BookLibrary:
    """The only resolver and publisher for the flat ``books/*.json`` registry."""

    def __init__(self, books_root: Path) -> None:
        self.books_root = Path(books_root)

    def list_book_profiles(self) -> list[Path]:
        if not self.books_root.is_dir():
            return []
        return sorted(
            path
            for path in self.books_root.glob("*.json")
            if path.is_file() and path.name != "BOOK-TEMPLATE.json" and not path.name.startswith(".")
        )

    def resolve_book_profile(self, book_id: str | Path) -> Path:
        raw = str(book_id)
        if Path(raw).name != raw:
            raise BookLibraryError("Book profile ID cannot contain a path.")
        stem = raw[:-5] if raw.endswith(".json") else raw
        slug = normalize_slug(stem)
        path = self.books_root / f"{slug}.json"
        if not path.is_file():
            raise BookLibraryError(f"Book profile not found: {raw}")
        return path

    def load_book_profile(self, book_id: str | Path) -> dict[str, Any]:
        path = self.resolve_book_profile(book_id)
        try:
            book = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BookLibraryError(f"Book profile is unreadable: {path.name}") from error
        if not isinstance(book, dict):
            raise BookLibraryError(f"Book profile must be an object: {path.name}")
        if book.get("enabled", True) is not True:
            raise BookLibraryError(f"Book profile disabled: {path.name}")
        for key in ("title", "author", "language", "default_speaker", "audiobook_instruct", "jobs"):
            if key not in book:
                raise BookLibraryError(f"{path.name}: missing {key}")
        if not isinstance(book["jobs"], dict):
            raise BookLibraryError(f"{path.name}: jobs must be an object")
        if "slug" in book and normalize_slug(str(book["slug"])) != path.stem:
            raise BookLibraryError(f"{path.name}: slug does not match profile filename")
        return book

    def import_text_book(
        self,
        *,
        source_file: Path,
        title: str,
        author: str,
        slug: str,
    ) -> dict[str, Any]:
        source_file = Path(source_file)
        try:
            source_stat = source_file.lstat()
        except OSError as error:
            raise BookLibraryError("Source TXT does not exist.") from error
        if source_file.is_symlink() or not stat.S_ISREG(source_stat.st_mode):
            raise BookLibraryError("Source TXT must be a regular file, not a symlink.")
        if source_file.suffix.lower() != ".txt":
            raise BookLibraryError("BOOK_LIBRARY_ADD_BOOK_V1 accepts only .txt files.")
        try:
            source_bytes = source_file.read_bytes()
            source_text = source_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise BookLibraryError("Source TXT must use strict UTF-8 encoding.") from error
        except OSError as error:
            raise BookLibraryError("Source TXT could not be read.") from error
        if not source_text.strip():
            raise BookLibraryError("Source TXT is empty or contains only whitespace.")

        normalized_slug = normalize_slug(slug)
        normalized_title = _required_text(title, "Title")
        normalized_author = _required_text(author, "Author")
        profile_path = self.books_root / f"{normalized_slug}.json"
        asset_root = self.books_root / normalized_slug
        self.books_root.mkdir(parents=True, exist_ok=True)
        if profile_path.exists() or asset_root.exists():
            raise BookLibraryError(f"A book with ID '{normalized_slug}' already exists.")

        source_sha = sha256_bytes(source_bytes)
        imported_at = _utc_now()
        staging_root = Path(tempfile.mkdtemp(prefix=f".import-{normalized_slug}-", dir=self.books_root))
        temporary_profile = self.books_root / f".{normalized_slug}.{staging_root.name}.json.tmp"
        asset_published = False
        try:
            staged_source = staging_root / SOURCE_RELATIVE_PATH
            staged_tts = staging_root / TTS_RELATIVE_PATH
            staged_source.parent.mkdir(parents=True, exist_ok=False)
            staged_tts.parent.mkdir(parents=True, exist_ok=False)
            staged_source.write_bytes(source_bytes)
            staged_tts.write_bytes(source_bytes)
            if staged_source.read_bytes() != source_bytes or staged_tts.read_bytes() != source_bytes:
                raise BookLibraryError("Imported book bytes failed verification.")
            os.chmod(staged_source, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            read_only = not bool(staged_source.stat().st_mode & stat.S_IWUSR)

            profile: dict[str, Any] = {
                "schema_version": BOOK_SCHEMA_VERSION,
                "kind": "production",
                "enabled": True,
                "slug": normalized_slug,
                "title": normalized_title,
                "author": normalized_author,
                "language": "Russian",
                "default_speaker": "Vivian",
                "selected_backend": "yandex",
                "selected_profile_id": "yandex_lera",
                "audiobook_instruct": (
                    "Read in natural modern Russian as a professional audiobook narrator. "
                    "Preserve the exact working text and do not add or omit words."
                ),
                "pronunciation_overrides": {},
                "jobs": {},
                "source": {
                    "path": SOURCE_RELATIVE_PATH.as_posix(),
                    "filename": source_file.name,
                    "sha256": source_sha,
                    "byte_size": len(source_bytes),
                    "imported_at": imported_at,
                    "immutable": True,
                    "read_only": read_only,
                },
                "tts_working_copy": {
                    "path": TTS_RELATIVE_PATH.as_posix(),
                    "sha256": source_sha,
                    "source_sha256": source_sha,
                    "revision": 1,
                },
            }
            _atomic_write_json(temporary_profile, profile)
            verified = json.loads(temporary_profile.read_text(encoding="utf-8"))
            if verified != profile or sha256_file(staged_source) != source_sha:
                raise BookLibraryError("Imported book metadata failed verification.")

            os.replace(staging_root, asset_root)
            asset_published = True
            os.replace(temporary_profile, profile_path)
            return self.book_details(profile_path.name)
        except Exception:
            if asset_published and not profile_path.exists() and asset_root.exists():
                shutil.rmtree(asset_root)
            raise
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root)
            if temporary_profile.exists():
                temporary_profile.unlink()

    def _asset_path(self, slug: str, relative_value: Any) -> Path | None:
        if not isinstance(relative_value, str) or not relative_value:
            return None
        relative = Path(relative_value)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        root = self.books_root / slug
        candidate = root / relative
        try:
            candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError:
            return None
        return candidate

    def book_details(self, book_id: str | Path) -> dict[str, Any]:
        profile_path = self.resolve_book_profile(book_id)
        book = self.load_book_profile(profile_path.name)
        slug = normalize_slug(str(book.get("slug") or profile_path.stem))
        source = book.get("source") if isinstance(book.get("source"), dict) else {}
        tts = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else {}
        source_path = self._asset_path(slug, source.get("path"))
        expected_sha = source.get("sha256") if isinstance(source.get("sha256"), str) else None
        if source_path is None or not source_path.is_file():
            source_integrity = "MISSING"
            current_source_sha = None
        else:
            current_source_sha = sha256_file(source_path)
            source_integrity = "OK" if expected_sha and current_source_sha == expected_sha else "HASH_MISMATCH"
        tts_path = self._asset_path(slug, tts.get("path"))
        tts_status = "CREATED" if tts_path is not None and tts_path.is_file() else "MISSING"
        jobs = [
            {
                "id": str(job_id),
                "label": str(job.get("label") or job_id),
                "segment_count": len(job.get("segments") or []),
            }
            for job_id, job in book["jobs"].items()
            if isinstance(job_id, str)
            and isinstance(job, dict)
            and isinstance(job.get("segments"), list)
            and job["segments"]
        ]
        return {
            "schema_version": BOOK_SCHEMA_VERSION,
            "book_id": profile_path.name,
            "id": profile_path.name,
            "slug": slug,
            "title": str(book["title"]),
            "author": str(book["author"]),
            "kind": str(book.get("kind") or "legacy"),
            "enabled": True,
            "status": "READY" if jobs else "NO_PREPARED_JOBS",
            "language": str(book["language"]),
            "default_speaker": str(book["default_speaker"]),
            "selected_backend": str(book.get("selected_backend") or ""),
            "selected_profile_id": str(book.get("selected_profile_id") or ""),
            "jobs": jobs,
            "source_filename": str(source.get("filename") or ""),
            "source_path": str(source.get("path") or ""),
            "source_sha256": expected_sha,
            "source_current_sha256": current_source_sha,
            "source_byte_size": source.get("byte_size"),
            "source_imported_at": source.get("imported_at"),
            "source_immutable": bool(source.get("immutable", False)),
            "source_read_only": bool(source.get("read_only", False)),
            "source_integrity": source_integrity,
            "tts_working_copy_path": str(tts.get("path") or ""),
            "tts_working_copy_sha256": tts.get("sha256"),
            "tts_working_copy_source_sha256": tts.get("source_sha256"),
            "tts_working_copy_revision": tts.get("revision"),
            "tts_working_copy_status": tts_status,
            "remote_request_sent": False,
        }

    def list_book_summaries(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in self.list_book_profiles():
            try:
                result.append(self.book_details(path.name))
            except BookLibraryError:
                continue
        return result
