"""Provider-neutral canonical local book library for Audiobook Studio."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import unicodedata
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from preparation_contract import (
    NORMALIZATION_RULES_VERSION,
    PREPARATION_SCHEMA_VERSION,
    SEGMENTATION_RULES_VERSION,
)


BOOK_SCHEMA_VERSION = 1
SOURCE_RELATIVE_PATH = Path("source/original.txt")
TTS_RELATIVE_PATH = Path("tts/working.txt")
SOURCE_INTEGRITY_STATES = {"OK", "MISSING", "HASH_MISMATCH", "DOWNLOAD_REQUIRED"}
MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024


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


def _is_dataless_file(path: Path) -> bool:
    """Return true without opening an iCloud/File Provider placeholder.

    Reading a dataless file can synchronously start a download.  Library
    inspection is an offline operation, so it must inspect the macOS file flag
    before hashing or parsing any book asset.
    """
    try:
        flags = path.stat().st_flags
    except (AttributeError, OSError):
        return False
    return bool(flags & getattr(stat, "SF_DATALESS", 0x40000000))


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


def _validate_author_pronunciation(value: str) -> str:
    normalized = unicodedata.normalize("NFC", _required_text(value, "Author pronunciation"))
    if len(normalized) > 300 or any(character in normalized for character in "\r\n\0"):
        raise BookLibraryError("Author pronunciation must be one line of at most 300 characters.")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise BookLibraryError("Author pronunciation contains unsupported control characters.")
    return normalized


def author_pronunciation_identity(book: Mapping[str, Any]) -> str:
    """Bind a prepared derivative to the exact author/pronunciation metadata."""
    author = unicodedata.normalize("NFC", str(book.get("author") or "").strip())
    pronunciation = unicodedata.normalize(
        "NFC", str(book.get("author_pronunciation") or author).strip()
    )
    encoded = json.dumps(
        {"author": author, "author_pronunciation": pronunciation},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


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
            for path in self.books_root.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".json"
            and path.name.casefold() != "book-template.json"
            and not path.name.startswith(".")
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

    def load_book_profile(
        self, book_id: str | Path, *, allow_disabled: bool = False,
    ) -> dict[str, Any]:
        path = self.resolve_book_profile(book_id)
        try:
            book = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BookLibraryError(f"Book profile is unreadable: {path.name}") from error
        if not isinstance(book, dict):
            raise BookLibraryError(f"Book profile must be an object: {path.name}")
        enabled = book.get("enabled", True)
        if enabled is not True and not (allow_disabled and enabled is False):
            raise BookLibraryError(f"Book profile disabled: {path.name}")
        for key in ("title", "author", "language", "default_speaker", "audiobook_instruct", "jobs"):
            if key not in book:
                raise BookLibraryError(f"{path.name}: missing {key}")
        if not isinstance(book["jobs"], dict):
            raise BookLibraryError(f"{path.name}: jobs must be an object")
        if "slug" in book and normalize_slug(str(book["slug"])) != path.stem:
            raise BookLibraryError(f"{path.name}: slug does not match profile filename")
        return book

    def replace_book_profile(self, book_id: str | Path, book: Mapping[str, Any]) -> Path:
        """Atomically replace one existing profile after validating its identity."""
        path = self.resolve_book_profile(book_id)
        payload = deepcopy(dict(book))
        slug = normalize_slug(str(payload.get("slug") or path.stem))
        if slug != path.stem:
            raise BookLibraryError("Book slug does not match the profile being replaced.")
        for key in ("title", "author", "language", "default_speaker", "audiobook_instruct", "jobs"):
            if key not in payload:
                raise BookLibraryError(f"{path.name}: missing {key}")
        if not isinstance(payload["jobs"], dict):
            raise BookLibraryError(f"{path.name}: jobs must be an object")

        # A READY preparation is sealed only after its final serialized artifacts
        # exist. This keeps the profile as the trust root without allowing the
        # JSON artifacts to self-authorize by preserving an embedded identity.
        preparation = payload.get("preparation")
        if isinstance(preparation, dict) and preparation.get("status") == "READY":
            for hash_key, path_key in (
                ("structure_sha256", "structure_path"),
                ("segments_sha256", "segments_path"),
            ):
                if preparation.get(hash_key):
                    continue
                artifact_path = self._asset_path(slug, preparation.get(path_key))
                if artifact_path is None or not artifact_path.is_file():
                    raise BookLibraryError(f"Prepared artifact is missing before profile publish: {path_key}")
                preparation[hash_key] = sha256_file(artifact_path)

        _atomic_write_json(path, payload)
        return path

    def archive_book(self, book_id: str | Path) -> dict[str, Any]:
        """Move one book into a private, recoverable archive without deleting it.

        Both the registry profile and its sibling asset directory are moved on
        the same filesystem.  A partially completed move is rolled back, and
        symlinks are rejected so a crafted book ID cannot move data outside the
        canonical library.
        """
        profile_path = self.resolve_book_profile(book_id)
        slug = normalize_slug(profile_path.stem)
        asset_root = self.books_root / slug

        try:
            profile_stat = profile_path.lstat()
        except OSError as error:
            raise BookLibraryError("Book profile cannot be archived.") from error
        if profile_path.is_symlink() or not stat.S_ISREG(profile_stat.st_mode):
            raise BookLibraryError("Book profile must be a regular file, not a link.")
        if asset_root.exists() or asset_root.is_symlink():
            try:
                asset_stat = asset_root.lstat()
            except OSError as error:
                raise BookLibraryError("Book assets cannot be archived safely.") from error
            if asset_root.is_symlink() or not stat.S_ISDIR(asset_stat.st_mode):
                raise BookLibraryError("Book asset root must be a directory, not a link.")

        archive_root = self.books_root / ".archive"
        archive_parent = archive_root / slug
        for path in (archive_root, archive_parent):
            if path.exists() and path.is_symlink():
                raise BookLibraryError("Book archive path cannot contain a symlink.")
        try:
            archive_parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BookLibraryError("Book archive directory is unavailable.") from error

        archived_at = _utc_now()
        archive_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:12]
        )
        final_root = archive_parent / archive_id
        pending_root = archive_parent / f".{archive_id}.pending"
        if final_root.exists() or pending_root.exists():
            raise BookLibraryError("A colliding book archive already exists.")
        pending_root.mkdir()

        archived_profile = pending_root / profile_path.name
        archived_assets = pending_root / slug
        profile_moved = False
        assets_moved = False
        try:
            if asset_root.exists():
                os.replace(asset_root, archived_assets)
                assets_moved = True
            os.replace(profile_path, archived_profile)
            profile_moved = True
            _atomic_write_json(pending_root / "archive.json", {
                "schema_version": 1,
                "book_id": profile_path.name,
                "slug": slug,
                "archived_at": archived_at,
                "profile_filename": profile_path.name,
                "asset_directory": slug if assets_moved else None,
            })
            os.replace(pending_root, final_root)
        except Exception as error:
            # Restore user data to its exact canonical paths if publication of
            # the archive did not complete.  Never overwrite an intervening
            # path: that would make recovery ambiguous.
            rollback_errors: list[Exception] = []
            if profile_moved and archived_profile.exists():
                if profile_path.exists():
                    rollback_errors.append(RuntimeError("canonical profile path appeared during rollback"))
                else:
                    try:
                        os.replace(archived_profile, profile_path)
                    except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                        rollback_errors.append(rollback_error)
            if assets_moved and archived_assets.exists():
                if asset_root.exists() or asset_root.is_symlink():
                    rollback_errors.append(RuntimeError("canonical asset path appeared during rollback"))
                else:
                    try:
                        os.replace(archived_assets, asset_root)
                    except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                        rollback_errors.append(rollback_error)
            if pending_root.exists() and not any(pending_root.iterdir()):
                pending_root.rmdir()
            if rollback_errors:
                raise BookLibraryError(
                    "Book archive failed and automatic recovery was incomplete."
                ) from error
            raise BookLibraryError("Book archive failed; the original book was restored.") from error

        return {
            "schema_version": 1,
            "archived": True,
            "book_id": profile_path.name,
            "slug": slug,
            "archived_at": archived_at,
            "archive_path": str(final_root),
            "profile_path": str(final_root / profile_path.name),
            "asset_path": str(final_root / slug) if assets_moved else None,
            "provider_requests": 0,
            "paid_execution": False,
            "billing_changed": False,
            "remote_request_sent": False,
        }

    def delete_book_permanently(self, book_id: str | Path) -> dict[str, Any]:
        """Permanently remove one book from the local library without an archive.

        Only the canonical registry profile and its sibling imported asset
        directory are in scope.  The user's original source file, rendered
        audio, billing history, and provider records live elsewhere and are
        deliberately untouched.  Targets are first moved into a uniquely named
        local staging directory so a failed second move can be rolled back
        without leaving a half-visible library entry.
        """
        profile_path = self.resolve_book_profile(book_id)
        slug = normalize_slug(profile_path.stem)
        asset_root = self.books_root / slug

        if self.books_root.is_symlink():
            raise BookLibraryError("Book library root cannot be a symlink.")
        try:
            profile_stat = profile_path.lstat()
        except OSError as error:
            raise BookLibraryError("Book profile cannot be deleted.") from error
        if profile_path.is_symlink() or not stat.S_ISREG(profile_stat.st_mode):
            raise BookLibraryError("Book profile must be a regular file, not a link.")
        book = self.load_book_profile(profile_path.name, allow_disabled=True)
        if book.get("kind") != "production":
            raise BookLibraryError(
                "Only books added by the user can be permanently deleted."
            )
        if asset_root.exists() or asset_root.is_symlink():
            try:
                asset_stat = asset_root.lstat()
            except OSError as error:
                raise BookLibraryError("Book assets cannot be deleted safely.") from error
            if asset_root.is_symlink() or not stat.S_ISDIR(asset_stat.st_mode):
                raise BookLibraryError("Book asset root must be a directory, not a link.")

        deletion_root = self.books_root / f".delete-{slug}-{uuid.uuid4().hex}.pending"
        if deletion_root.exists() or deletion_root.is_symlink():
            raise BookLibraryError("A colliding book deletion path already exists.")
        try:
            deletion_root.mkdir()
        except OSError as error:
            raise BookLibraryError("Book deletion staging directory is unavailable.") from error

        staged_profile = deletion_root / profile_path.name
        staged_assets = deletion_root / slug
        profile_moved = False
        assets_moved = False
        try:
            if asset_root.exists():
                os.replace(asset_root, staged_assets)
                assets_moved = True
            os.replace(profile_path, staged_profile)
            profile_moved = True
        except Exception as error:
            rollback_errors: list[Exception] = []
            if profile_moved and staged_profile.exists():
                if profile_path.exists():
                    rollback_errors.append(RuntimeError("canonical profile path appeared during rollback"))
                else:
                    try:
                        os.replace(staged_profile, profile_path)
                    except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                        rollback_errors.append(rollback_error)
            if assets_moved and staged_assets.exists():
                if asset_root.exists() or asset_root.is_symlink():
                    rollback_errors.append(RuntimeError("canonical asset path appeared during rollback"))
                else:
                    try:
                        os.replace(staged_assets, asset_root)
                    except Exception as rollback_error:  # pragma: no cover - catastrophic filesystem failure
                        rollback_errors.append(rollback_error)
            if deletion_root.exists() and not any(deletion_root.iterdir()):
                deletion_root.rmdir()
            if rollback_errors:
                raise BookLibraryError(
                    "Book deletion failed and automatic recovery was incomplete."
                ) from error
            raise BookLibraryError("Book deletion failed; the original book was restored.") from error

        cleanup_complete = True
        cleanup_warning = None
        try:
            shutil.rmtree(deletion_root)
        except OSError:
            # Moving both canonical targets is the deletion commit point.  A
            # cleanup failure after it must not be reported as if the visible
            # book still existed: callers need to reload the library.  The
            # uniquely named hidden staging directory is retained for an
            # operator to inspect/clean rather than risking a partial rollback.
            cleanup_complete = False
            cleanup_warning = (
                "Книга удалена из библиотеки, но служебные остатки не удалось очистить полностью."
            )

        return {
            "schema_version": 1,
            "deleted": True,
            "archived": False,
            "archive_created": False,
            "book_id": profile_path.name,
            "slug": slug,
            "profile_deleted": True,
            "assets_deleted": assets_moved,
            "cleanup_complete": cleanup_complete,
            "cleanup_warning": cleanup_warning,
            "provider_requests": 0,
            "paid_execution": False,
            "billing_changed": False,
            "remote_request_sent": False,
        }

    def import_text_book(
        self,
        *,
        source_file: Path,
        title: str,
        author: str,
        author_pronunciation: str | None = None,
        slug: str,
    ) -> dict[str, Any]:
        source_file = Path(source_file)
        try:
            source_stat = source_file.lstat()
        except OSError as error:
            raise BookLibraryError("Выбранный TXT-файл не существует.") from error
        if source_file.is_symlink() or not stat.S_ISREG(source_stat.st_mode):
            raise BookLibraryError("Выберите обычный TXT-файл, а не ссылку или папку.")
        if source_file.suffix.lower() != ".txt":
            raise BookLibraryError("Можно загрузить только файл с расширением .txt.")
        if source_stat.st_size > MAX_SOURCE_FILE_BYTES:
            raise BookLibraryError("Файл книги слишком большой. Максимальный размер TXT — 20 МБ.")
        try:
            source_bytes = source_file.read_bytes()
            source_text = source_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise BookLibraryError("TXT-файл должен быть сохранён в кодировке UTF-8.") from error
        except OSError as error:
            raise BookLibraryError("Не удалось прочитать выбранный TXT-файл.") from error
        if not source_text.strip():
            raise BookLibraryError("TXT-файл пуст или содержит только пробелы.")

        normalized_slug = normalize_slug(slug)
        normalized_title = _required_text(title, "Title")
        normalized_author = _required_text(author, "Author")
        normalized_author_pronunciation = _validate_author_pronunciation(
            author_pronunciation or normalized_author,
        )
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
                "author_pronunciation": normalized_author_pronunciation,
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

    def resolve_book_asset(self, book_id: str | Path, relative_value: Any) -> Path:
        profile_path = self.resolve_book_profile(book_id)
        book = self.load_book_profile(profile_path.name)
        slug = normalize_slug(str(book.get("slug") or profile_path.stem))
        path = self._asset_path(slug, relative_value)
        if path is None:
            raise BookLibraryError("Book asset path is missing or unsafe.")
        return path

    def _preparation_facts(
        self,
        *,
        slug: str,
        book: Mapping[str, Any],
        source_integrity: str,
    ) -> dict[str, Any]:
        preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else None
        tts = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else {}
        working_path = self._asset_path(slug, tts.get("path"))
        working_download_required = bool(
            working_path is not None
            and working_path.is_file()
            and _is_dataless_file(working_path)
        )
        working_sha = (
            sha256_file(working_path)
            if working_path is not None
            and working_path.is_file()
            and not working_download_required
            else None
        )
        if source_integrity == "DOWNLOAD_REQUIRED" or working_download_required:
            status = "DOWNLOAD_REQUIRED"
        elif source_integrity != "OK":
            status = "SOURCE_INTEGRITY_ERROR"
        elif preparation is None:
            status = "NOT_PREPARED"
        elif working_sha is None or working_sha != preparation.get("working_copy_sha256"):
            status = "STALE"
        elif (
            preparation.get("schema_version") != PREPARATION_SCHEMA_VERSION
            or preparation.get("normalization_rules_version") != NORMALIZATION_RULES_VERSION
            or preparation.get("segmentation_rules_version") != SEGMENTATION_RULES_VERSION
            or preparation.get("author_pronunciation_identity_sha256")
            != author_pronunciation_identity(book)
        ):
            status = "STALE"
        else:
            normalized_path = self._asset_path(slug, preparation.get("normalized_path"))
            structure_path = self._asset_path(slug, preparation.get("structure_path"))
            segments_path = self._asset_path(slug, preparation.get("segments_path"))
            artifact_paths = (normalized_path, structure_path, segments_path)
            artifact_download_required = any(
                path is not None and path.is_file() and _is_dataless_file(path)
                for path in artifact_paths
            )
            if artifact_download_required:
                return {
                    "preparation_status": "DOWNLOAD_REQUIRED",
                    "working_copy_current_sha256": working_sha,
                    "preparation_schema_version": preparation.get("schema_version"),
                    "preparation_revision": preparation.get("revision"),
                    "preparation_identity": preparation.get("identity_sha256"),
                    "prepared_at": preparation.get("prepared_at"),
                    "normalized_sha256": preparation.get("normalized_sha256"),
                    "structure_sha256": preparation.get("structure_sha256"),
                    "segments_sha256": preparation.get("segments_sha256"),
                    "normalized_path": preparation.get("normalized_path"),
                    "structure_path": preparation.get("structure_path"),
                    "segments_path": preparation.get("segments_path"),
                    "chapter_count": preparation.get("chapter_count", 0),
                    "prepared_segment_count": preparation.get("segment_count", 0),
                }
            artifacts_present = all(path is not None and path.is_file() for path in artifact_paths)
            normalized_matches = bool(
                normalized_path is not None
                and normalized_path.is_file()
                and preparation.get("normalized_sha256")
                and sha256_file(normalized_path) == preparation.get("normalized_sha256")
            )
            structure_hash_matches = bool(
                structure_path is not None
                and structure_path.is_file()
                and preparation.get("structure_sha256")
                and sha256_file(structure_path) == preparation.get("structure_sha256")
            )
            segments_hash_matches = bool(
                segments_path is not None
                and segments_path.is_file()
                and preparation.get("segments_sha256")
                and sha256_file(segments_path) == preparation.get("segments_sha256")
            )
            structure_identity_matches = False
            if structure_hash_matches and structure_path is not None:
                try:
                    structure_payload = json.loads(structure_path.read_text(encoding="utf-8"))
                    structure_identity_matches = (
                        isinstance(structure_payload, dict)
                        and structure_payload.get("preparation_identity") == preparation.get("identity_sha256")
                        and isinstance(structure_payload.get("chapters"), list)
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    structure_identity_matches = False
            segments_identity_matches = False
            if segments_hash_matches and segments_path is not None:
                try:
                    segments_payload = json.loads(segments_path.read_text(encoding="utf-8"))
                    segments_identity_matches = (
                        isinstance(segments_payload, dict)
                        and segments_payload.get("preparation_identity") == preparation.get("identity_sha256")
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    segments_identity_matches = False
            status = (
                "READY"
                if preparation.get("status") == "READY"
                and artifacts_present
                and normalized_matches
                and structure_hash_matches
                and segments_hash_matches
                and structure_identity_matches
                and segments_identity_matches
                else "STALE"
            )
        return {
            "preparation_status": status,
            "working_copy_current_sha256": working_sha,
            "preparation_schema_version": preparation.get("schema_version") if preparation else None,
            "preparation_revision": preparation.get("revision") if preparation else None,
            "preparation_identity": preparation.get("identity_sha256") if preparation else None,
            "prepared_at": preparation.get("prepared_at") if preparation else None,
            "normalized_sha256": preparation.get("normalized_sha256") if preparation else None,
            "structure_sha256": preparation.get("structure_sha256") if preparation else None,
            "segments_sha256": preparation.get("segments_sha256") if preparation else None,
            "normalized_path": preparation.get("normalized_path") if preparation else None,
            "structure_path": preparation.get("structure_path") if preparation else None,
            "segments_path": preparation.get("segments_path") if preparation else None,
            "chapter_count": preparation.get("chapter_count") if preparation else 0,
            "prepared_segment_count": preparation.get("segment_count") if preparation else 0,
        }

    def load_book_for_execution(self, book_id: str | Path) -> dict[str, Any]:
        """Resolve lightweight prepared jobs to inline segments, failing closed if stale."""
        profile_path = self.resolve_book_profile(book_id)
        book = self.load_book_profile(profile_path.name)
        preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else None
        if preparation is None:
            return book

        details = self.book_details(profile_path.name)
        if details["preparation_status"] != "READY":
            raise BookLibraryError(
                f"Book preparation is {details['preparation_status']}; synthesis was not started."
            )
        slug = normalize_slug(str(book.get("slug") or profile_path.stem))
        segments_path = self._asset_path(slug, preparation.get("segments_path"))
        if segments_path is None or not segments_path.is_file():
            raise BookLibraryError("Prepared segment artifact is missing.")
        try:
            artifact_bytes = segments_path.read_bytes()
        except OSError as error:
            raise BookLibraryError("Prepared segment artifact is unreadable.") from error
        if (
            not isinstance(preparation.get("segments_sha256"), str)
            or sha256_bytes(artifact_bytes) != preparation.get("segments_sha256")
        ):
            raise BookLibraryError("Prepared segment artifact hash does not match the book profile.")
        try:
            artifact = json.loads(artifact_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BookLibraryError("Prepared segment artifact is unreadable.") from error
        if not isinstance(artifact, dict) or artifact.get("preparation_identity") != preparation.get("identity_sha256"):
            raise BookLibraryError("Prepared segment identity does not match the book profile.")
        entries = artifact.get("segments")
        preview = artifact.get("preview")
        if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
            raise BookLibraryError("Prepared segment artifact has an invalid segment list.")
        all_entries = list(entries)
        if isinstance(preview, dict):
            all_entries.append(preview)
        by_id = {
            str(item.get("id")): item
            for item in all_entries
            if isinstance(item.get("id"), str) and item.get("id")
        }
        resolved = deepcopy(book)
        for job_id, job in resolved["jobs"].items():
            if not isinstance(job, dict) or not isinstance(job.get("segment_ids"), list):
                continue
            if job.get("preparation_identity") != preparation.get("identity_sha256"):
                raise BookLibraryError(f"Prepared job identity mismatch: {job_id}")
            materialized: list[dict[str, Any]] = []
            for segment_id in job["segment_ids"]:
                entry = by_id.get(str(segment_id))
                if entry is None or not isinstance(entry.get("text"), str) or not entry["text"].strip():
                    raise BookLibraryError(f"Prepared job references an invalid segment: {segment_id}")
                materialized.append(deepcopy(entry))
            if not materialized:
                raise BookLibraryError(f"Prepared job has no segments: {job_id}")
            job["segments"] = materialized
        return resolved

    def book_details(self, book_id: str | Path) -> dict[str, Any]:
        profile_path = self.resolve_book_profile(book_id)
        book = self.load_book_profile(profile_path.name)
        slug = normalize_slug(str(book.get("slug") or profile_path.stem))
        source = book.get("source") if isinstance(book.get("source"), dict) else {}
        tts = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else {}
        source_path = self._asset_path(slug, source.get("path"))
        expected_sha = source.get("sha256") if isinstance(source.get("sha256"), str) else None
        if source_path is not None and source_path.is_file() and _is_dataless_file(source_path):
            source_integrity = "DOWNLOAD_REQUIRED"
            current_source_sha = None
        elif source_path is None or not source_path.is_file():
            source_integrity = "MISSING"
            current_source_sha = None
        else:
            current_source_sha = sha256_file(source_path)
            source_integrity = "OK" if expected_sha and current_source_sha == expected_sha else "HASH_MISMATCH"
        tts_path = self._asset_path(slug, tts.get("path"))
        if tts_path is not None and tts_path.is_file() and _is_dataless_file(tts_path):
            tts_status = "DOWNLOAD_REQUIRED"
        else:
            tts_status = "CREATED" if tts_path is not None and tts_path.is_file() else "MISSING"
        preparation_facts = self._preparation_facts(
            slug=slug,
            book=book,
            source_integrity=source_integrity,
        )
        jobs_available = (
            not isinstance(book.get("preparation"), dict)
            or preparation_facts["preparation_status"] == "READY"
        )
        jobs = [
            {
                "id": str(job_id),
                "label": str(job.get("label") or job_id),
                "segment_count": len(job.get("segments") or job.get("segment_ids") or []),
                **({"kind": str(job["kind"])} if isinstance(job.get("kind"), str) else {}),
            }
            for job_id, job in book["jobs"].items()
            if jobs_available
            if isinstance(job_id, str)
            and isinstance(job, dict)
            and (
                isinstance(job.get("segments"), list) and bool(job["segments"])
                or isinstance(job.get("segment_ids"), list) and bool(job["segment_ids"])
            )
        ]
        return {
            "schema_version": BOOK_SCHEMA_VERSION,
            "book_id": profile_path.name,
            "id": profile_path.name,
            "slug": slug,
            "title": str(book["title"]),
            "author": str(book["author"]),
            "author_pronunciation": (
                str(book["author_pronunciation"])
                if isinstance(book.get("author_pronunciation"), str)
                else None
            ),
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
            "tts_working_copy_current_sha256": preparation_facts["working_copy_current_sha256"],
            "tts_working_copy_source_sha256": tts.get("source_sha256"),
            "tts_working_copy_revision": tts.get("revision"),
            "tts_working_copy_status": tts_status,
            "remote_request_sent": False,
            **preparation_facts,
        }

    def list_book_summaries(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in self.list_book_profiles():
            try:
                result.append(self.book_details(path.name))
            except BookLibraryError:
                continue
        return result
