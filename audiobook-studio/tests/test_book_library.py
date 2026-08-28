from __future__ import annotations

import hashlib
import json
import os
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
        with self.assertRaises(BookLibraryError):
            self.import_book()

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


if __name__ == "__main__":
    unittest.main()
