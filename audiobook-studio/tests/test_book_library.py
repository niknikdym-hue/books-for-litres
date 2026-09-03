from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import book_library
from book_library import BookLibrary, BookLibraryError


class BookLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.source = self.root / "source.txt"
        self.source_bytes = "Первая настоящая книга.\nВторая строка.\n".encode("utf-8")
        self.source.write_bytes(self.source_bytes)
        self.library = BookLibrary(self.books)

    def tearDown(self):
        self.temporary.cleanup()

    def import_book(self, slug: str = "my-book") -> dict:
        return self.library.import_text_book(
            source_file=self.source,
            title="Моя книга",
            author="Автор",
            slug=slug,
        )

    def test_utf8_txt_import_passes_with_expected_profile_defaults(self):
        result = self.import_book()
        profile = json.loads((self.books / "my-book.json").read_text(encoding="utf-8"))
        self.assertEqual(result["book_id"], "my-book.json")
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["kind"], "production")
        self.assertTrue(profile["enabled"])
        self.assertEqual(profile["language"], "Russian")
        self.assertEqual(profile["default_speaker"], "Vivian")
        self.assertEqual(profile["selected_backend"], "yandex")
        self.assertEqual(profile["selected_profile_id"], "yandex_lera")
        self.assertEqual(profile["jobs"], {})

    def test_empty_source_is_rejected(self):
        self.source.write_text("  \n\t", encoding="utf-8")
        with self.assertRaises(BookLibraryError):
            self.import_book()
        self.assertFalse(self.books.exists() and list(self.books.glob("*.json")))

    def test_invalid_utf8_is_rejected(self):
        self.source.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(BookLibraryError, "UTF-8"):
            self.import_book()

    def test_source_larger_than_20_mib_is_rejected_before_reading(self):
        with self.source.open("wb") as handle:
            handle.truncate(book_library.MAX_SOURCE_FILE_BYTES + 1)
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("oversized file was read")):
            with self.assertRaisesRegex(BookLibraryError, "20 МБ"):
                self.import_book()
        self.assertFalse(self.books.exists())

    def test_unsafe_and_traversal_slugs_fail_closed(self):
        for slug in ("../escape", "a/b", "a\\b", ".hidden", "has space", "name.json"):
            with self.subTest(slug=slug), self.assertRaises(BookLibraryError):
                self.import_book(slug)

    def test_duplicate_slug_does_not_overwrite(self):
        self.import_book()
        profile_before = (self.books / "my-book.json").read_bytes()
        source_before = (self.books / "my-book/source/original.txt").read_bytes()
        self.source.write_text("Другой текст", encoding="utf-8")
        with self.assertRaises(BookLibraryError):
            self.import_book()
        self.assertEqual((self.books / "my-book.json").read_bytes(), profile_before)
        self.assertEqual((self.books / "my-book/source/original.txt").read_bytes(), source_before)

    def test_source_bytes_and_sha_are_preserved(self):
        result = self.import_book()
        expected = hashlib.sha256(self.source_bytes).hexdigest()
        original = self.books / "my-book/source/original.txt"
        self.assertEqual(original.read_bytes(), self.source_bytes)
        self.assertEqual(result["source_sha256"], expected)
        self.assertEqual(result["source_integrity"], "OK")
        self.assertFalse(original.stat().st_mode & stat.S_IWUSR)

    def test_source_and_tts_copy_are_separate_with_identical_initial_bytes(self):
        self.import_book()
        original = self.books / "my-book/source/original.txt"
        working = self.books / "my-book/tts/working.txt"
        self.assertNotEqual(original, working)
        self.assertEqual(original.read_bytes(), self.source_bytes)
        self.assertEqual(working.read_bytes(), self.source_bytes)
        self.assertTrue(working.stat().st_mode & stat.S_IWUSR)

    def test_editing_tts_copy_does_not_change_source_or_stored_hash(self):
        self.import_book()
        original = self.books / "my-book/source/original.txt"
        working = self.books / "my-book/tts/working.txt"
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        working.write_text("Изменённая TTS-копия", encoding="utf-8")
        details = self.library.book_details("my-book")
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(details["source_sha256"], original_hash)
        self.assertEqual(details["source_integrity"], "OK")
        self.assertEqual(details["tts_working_copy_status"], "CREATED")

    def test_external_source_tamper_is_detected_without_rewriting_profile(self):
        self.import_book()
        original = self.books / "my-book/source/original.txt"
        os.chmod(original, stat.S_IRUSR | stat.S_IWUSR)
        original.write_text("Подмена", encoding="utf-8")
        profile_before = (self.books / "my-book.json").read_bytes()
        details = self.library.book_details("my-book")
        self.assertEqual(details["source_integrity"], "HASH_MISMATCH")
        self.assertNotEqual(details["source_current_sha256"], details["source_sha256"])
        self.assertEqual((self.books / "my-book.json").read_bytes(), profile_before)

    def test_missing_source_is_reported(self):
        self.import_book()
        original = self.books / "my-book/source/original.txt"
        os.chmod(original, stat.S_IRUSR | stat.S_IWUSR)
        original.unlink()
        self.assertEqual(self.library.book_details("my-book")["source_integrity"], "MISSING")

    def test_dataless_source_requires_download_without_reading_placeholder(self):
        self.import_book()
        original = self.books / "my-book/source/original.txt"
        real_sha256 = book_library.sha256_file

        def guarded_sha256(path):
            if Path(path) == original:
                raise AssertionError("dataless source bytes were opened")
            return real_sha256(path)

        with mock.patch("book_library._is_dataless_file", side_effect=lambda path: Path(path) == original), \
             mock.patch("book_library.sha256_file", side_effect=guarded_sha256):
            details = self.library.book_details("my-book")

        self.assertEqual(details["source_integrity"], "DOWNLOAD_REQUIRED")
        self.assertEqual(details["preparation_status"], "DOWNLOAD_REQUIRED")
        self.assertIsNone(details["source_current_sha256"])
        self.assertEqual(details["jobs"], [])

    def test_dataless_working_copy_requires_download_without_reading_placeholder(self):
        self.import_book()
        working = self.books / "my-book/tts/working.txt"
        real_sha256 = book_library.sha256_file

        def guarded_sha256(path):
            if Path(path) == working:
                raise AssertionError("dataless working-copy bytes were opened")
            return real_sha256(path)

        with mock.patch("book_library._is_dataless_file", side_effect=lambda path: Path(path) == working), \
             mock.patch("book_library.sha256_file", side_effect=guarded_sha256):
            details = self.library.book_details("my-book")

        self.assertEqual(details["source_integrity"], "OK")
        self.assertEqual(details["tts_working_copy_status"], "DOWNLOAD_REQUIRED")
        self.assertEqual(details["preparation_status"], "DOWNLOAD_REQUIRED")
        self.assertIsNone(details["tts_working_copy_current_sha256"])

    def test_dataless_prepared_artifact_requires_download_without_reading_it(self):
        self.import_book()
        profile_path = self.books / "my-book.json"
        prepared_root = self.books / "my-book/prepared"
        prepared_root.mkdir()
        normalized = prepared_root / "normalized.txt"
        structure = prepared_root / "structure.json"
        segments = prepared_root / "segments.json"
        normalized.write_text("Текст\n", encoding="utf-8")
        structure.write_text('{"chapters": []}', encoding="utf-8")
        segments.write_text('{"segments": []}', encoding="utf-8")
        working = self.books / "my-book/tts/working.txt"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["preparation"] = {
            "status": "READY",
            "schema_version": book_library.PREPARATION_SCHEMA_VERSION,
            "normalization_rules_version": book_library.NORMALIZATION_RULES_VERSION,
            "segmentation_rules_version": book_library.SEGMENTATION_RULES_VERSION,
            "working_copy_sha256": hashlib.sha256(working.read_bytes()).hexdigest(),
            "author_pronunciation_identity_sha256": book_library.author_pronunciation_identity(profile),
            "identity_sha256": "identity",
            "normalized_path": "prepared/normalized.txt",
            "normalized_sha256": hashlib.sha256(normalized.read_bytes()).hexdigest(),
            "structure_path": "prepared/structure.json",
            "structure_sha256": hashlib.sha256(structure.read_bytes()).hexdigest(),
            "segments_path": "prepared/segments.json",
            "segments_sha256": hashlib.sha256(segments.read_bytes()).hexdigest(),
            "chapter_count": 1,
            "segment_count": 1,
        }
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        real_sha256 = book_library.sha256_file

        def guarded_sha256(path):
            if Path(path) == structure:
                raise AssertionError("dataless prepared artifact bytes were opened")
            return real_sha256(path)

        with mock.patch("book_library._is_dataless_file", side_effect=lambda path: Path(path) == structure), \
             mock.patch("book_library.sha256_file", side_effect=guarded_sha256):
            details = self.library.book_details("my-book")

        self.assertEqual(details["preparation_status"], "DOWNLOAD_REQUIRED")
        self.assertEqual(details["jobs"], [])

    def test_profile_is_published_last_and_failure_cleans_own_assets(self):
        real_replace = os.replace

        def fail_profile_publish(source, destination):
            if Path(destination) == self.books / "my-book.json":
                raise OSError("simulated profile publish failure")
            return real_replace(source, destination)

        with mock.patch("book_library.os.replace", side_effect=fail_profile_publish):
            with self.assertRaises(OSError):
                self.import_book()
        self.assertFalse((self.books / "my-book.json").exists())
        self.assertFalse((self.books / "my-book").exists())
        self.assertEqual(list(self.books.glob(".import-*")), [])

    def test_empty_jobs_is_valid_and_synthesis_input_remains_absent(self):
        self.import_book()
        book = self.library.load_book_profile("my-book.json")
        self.assertEqual(book["jobs"], {})
        self.assertEqual(self.library.book_details("my-book")["status"], "NO_PREPARED_JOBS")

    def test_disabled_profile_requires_explicit_authority_only_load(self):
        self.import_book()
        path = self.books / "my-book.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["enabled"] = False
        path.write_text(json.dumps(profile), encoding="utf-8")
        with self.assertRaises(BookLibraryError):
            self.library.load_book_profile("my-book.json")
        loaded = self.library.load_book_profile(
            "my-book.json", allow_disabled=True,
        )
        self.assertIs(loaded["enabled"], False)

    def test_registry_discovery_survives_new_instance(self):
        self.import_book()
        restarted = BookLibrary(self.books)
        self.assertEqual([path.name for path in restarted.list_book_profiles()], ["my-book.json"])
        self.assertEqual(restarted.book_details("my-book")["title"], "Моя книга")

    def test_registry_enumerates_json_extension_case_insensitively(self):
        self.books.mkdir(parents=True)
        (self.books / "Demo-Book.JSON").write_text("{malformed", encoding="utf-8")
        (self.books / "BOOK-TEMPLATE.JSON").write_text("{}", encoding="utf-8")
        (self.books / ".hidden.JSON").write_text("{}", encoding="utf-8")
        self.assertEqual(
            [path.name for path in self.library.list_book_profiles()],
            ["Demo-Book.JSON"],
        )

    def test_import_reports_no_remote_request(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network attempted")) as request:
            result = self.import_book()
        request.assert_not_called()
        self.assertFalse(result["remote_request_sent"])

    def test_existing_unrelated_files_are_preserved(self):
        self.books.mkdir(parents=True)
        unrelated = self.books / "keep-me.txt"
        unrelated.write_text("user data", encoding="utf-8")
        self.import_book()
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "user data")

    def test_archive_book_moves_profile_and_assets_to_recoverable_private_archive(self):
        self.import_book()
        profile_before = (self.books / "my-book.json").read_bytes()
        source_before = (self.books / "my-book/source/original.txt").read_bytes()
        extra = self.books / "my-book/user-notes/keep.txt"
        extra.parent.mkdir()
        extra.write_text("never delete this", encoding="utf-8")

        result = self.library.archive_book("my-book")
        archive = Path(result["archive_path"])

        self.assertTrue(result["archived"])
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])
        self.assertFalse((self.books / "my-book.json").exists())
        self.assertFalse((self.books / "my-book").exists())
        self.assertEqual((archive / "my-book.json").read_bytes(), profile_before)
        self.assertEqual((archive / "my-book/source/original.txt").read_bytes(), source_before)
        self.assertEqual((archive / "my-book/user-notes/keep.txt").read_text(encoding="utf-8"), "never delete this")
        manifest = json.loads((archive / "archive.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["book_id"], "my-book.json")
        self.assertEqual(self.library.list_book_profiles(), [])

    def test_archived_slug_can_be_imported_again_without_overwriting_archive(self):
        self.import_book()
        archived = self.library.archive_book("my-book")
        archived_profile = Path(archived["profile_path"])
        archived_bytes = archived_profile.read_bytes()

        result = self.import_book()

        self.assertEqual(result["book_id"], "my-book.json")
        self.assertEqual(archived_profile.read_bytes(), archived_bytes)

    def test_archive_rejects_traversal_and_symlink_targets(self):
        self.import_book()
        with self.assertRaises(BookLibraryError):
            self.library.archive_book("../my-book")

        external = self.root / "external-assets"
        external.mkdir()
        asset_root = self.books / "my-book"
        shutil.rmtree(asset_root)
        asset_root.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(BookLibraryError, "not a link"):
            self.library.archive_book("my-book")
        self.assertTrue((self.books / "my-book.json").exists())
        self.assertTrue(external.exists())

    def test_archive_rolls_back_assets_if_profile_move_fails(self):
        self.import_book()
        profile = self.books / "my-book.json"
        assets = self.books / "my-book"
        profile_before = profile.read_bytes()
        source_before = (assets / "source/original.txt").read_bytes()
        real_replace = os.replace

        def fail_profile_move(source, destination):
            if Path(source) == profile:
                raise OSError("simulated profile move failure")
            return real_replace(source, destination)

        with mock.patch("book_library.os.replace", side_effect=fail_profile_move):
            with self.assertRaisesRegex(BookLibraryError, "original book was restored"):
                self.library.archive_book("my-book")

        self.assertEqual(profile.read_bytes(), profile_before)
        self.assertEqual((assets / "source/original.txt").read_bytes(), source_before)

    def test_resolver_accepts_slug_or_profile_filename_only(self):
        self.import_book()
        self.assertEqual(self.library.resolve_book_profile("my-book").name, "my-book.json")
        self.assertEqual(self.library.resolve_book_profile("my-book.json").name, "my-book.json")
        with self.assertRaises(BookLibraryError):
            self.library.resolve_book_profile("../my-book.json")

    def test_symlink_source_is_rejected(self):
        link = self.root / "link.txt"
        link.symlink_to(self.source)
        with self.assertRaises(BookLibraryError):
            self.library.import_text_book(source_file=link, title="Book", author="Author", slug="link-book")

    def test_non_txt_source_reports_supported_extension(self):
        other = self.root / "book.docx"
        other.write_bytes(self.source_bytes)
        with self.assertRaisesRegex(BookLibraryError, r"\.txt"):
            self.library.import_text_book(source_file=other, title="Book", author="Author", slug="docx-book")

    def test_author_pronunciation_rejects_multiline_content(self):
        with self.assertRaisesRegex(BookLibraryError, "one line"):
            self.library.import_text_book(
                source_file=self.source,
                title="Book",
                author="Author",
                author_pronunciation="Author\nInjected chapter",
                slug="unsafe-pronunciation",
            )
        self.assertFalse((self.books / "unsafe-pronunciation.json").exists())


if __name__ == "__main__":
    unittest.main()
