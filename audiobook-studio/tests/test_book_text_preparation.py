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

from book_library import BookLibrary, BookLibraryError
from book_text_preparation import (
    HARD_SEGMENT_CHARS,
    BookTextPreparationError,
    BookTextPreparationService,
    detect_chapters,
    normalize_working_text,
    segment_chapter_text,
)


SOURCE_TEXT = (
    "Глава 1. Начало\r\n\r\n"
    "Первое предложение сохраняет слова и пунктуацию. Второе предложение продолжает абзац.\r\n\r\n\r\n"
    "Новый абзац остаётся отдельным смысловым блоком.\r\n\r\n"
    "Глава 2 — Продолжение\r\n\r\n"
    "Вторая глава содержит ещё один консервативно подготовленный фрагмент.\r\n"
)


class BookTextPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.source = self.root / "source.txt"
        self.source.write_text(SOURCE_TEXT, encoding="utf-8", newline="")
        self.library = BookLibrary(self.books)
        self.library.import_text_book(
            source_file=self.source,
            title="Подготовка текста",
            author="Audiobook Studio Test",
            slug="prepared-book",
        )
        self.service = BookTextPreparationService(
            self.library,
            now=lambda: "2026-08-23T00:00:00+00:00",
        )
        self.profile_path = self.books / "prepared-book.json"
        self.asset_root = self.books / "prepared-book"
        self.original = self.asset_root / "source/original.txt"
        self.working = self.asset_root / "tts/working.txt"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self) -> dict:
        return self.service.prepare("prepared-book")

    def test_source_integrity_is_required(self):
        os.chmod(self.original, stat.S_IRUSR | stat.S_IWUSR)
        self.original.write_text("Подмена", encoding="utf-8")
        with self.assertRaisesRegex(BookTextPreparationError, "SOURCE_INTEGRITY_ERROR"):
            self.prepare()
        self.assertEqual(json.loads(self.profile_path.read_text(encoding="utf-8"))["jobs"], {})

    def test_source_bytes_never_change(self):
        before = self.original.read_bytes()
        before_hash = hashlib.sha256(before).hexdigest()
        self.prepare()
        self.assertEqual(self.original.read_bytes(), before)
        self.assertEqual(hashlib.sha256(self.original.read_bytes()).hexdigest(), before_hash)

    def test_normalization_is_deterministic(self):
        first = normalize_working_text(SOURCE_TEXT)
        second = normalize_working_text(SOURCE_TEXT)
        self.assertEqual(first, second)
        self.assertIn("Первое предложение", first)

    def test_crlf_trailing_space_and_blank_runs_are_normalized(self):
        result = normalize_working_text("\ufeffСтрока  \r\n\r\n\r\nАбзац\t\r")
        self.assertEqual(result, "Строка\n\nАбзац\n")
        self.assertNotIn("\r", result)

    def test_paragraph_boundaries_are_preserved(self):
        result = normalize_working_text(SOURCE_TEXT)
        self.assertIn("продолжает абзац.\n\nНовый абзац", result)

    def test_explicit_russian_chapters_are_detected(self):
        chapters = detect_chapters(normalize_working_text(SOURCE_TEXT))
        self.assertEqual([item["title"] for item in chapters], ["Начало", "Продолжение"])
        self.assertEqual(chapters[0]["heading"], "Глава 1. Начало")
        self.assertIn("Первое предложение", chapters[0]["body"])

    def test_explicit_chapter_does_not_require_surrounding_blank_lines(self):
        chapters = detect_chapters("ГЛАВА 1\nТекст главы.\nГлава 2 — Финал\nПоследняя строка.\n")
        self.assertEqual([item["id"] for item in chapters], ["ch001", "ch002"])
        self.assertEqual([item["title"] for item in chapters], ["ГЛАВА 1", "Финал"])

    def test_russian_ordinal_word_chapters_match_real_book_format(self):
        chapters = detect_chapters(
            "Вступление. Перед главами.\n\n"
            "Глава первая. Начало\n\nПервый текст.\n\n"
            "Глава вторая. Продолжение\n\nВторой текст.\n\n"
            "Глава пятнадцатая. Финал\n\nПоследний текст.\n"
        )
        self.assertEqual([item["id"] for item in chapters], ["ch001", "ch002", "ch003", "ch004"])
        self.assertEqual(
            [item["title"] for item in chapters],
            ["Введение", "Начало", "Продолжение", "Финал"],
        )
        self.assertEqual(chapters[1]["heading"], "Глава первая. Начало")

    def test_russian_fourth_ordinal_accepts_common_e_spelling(self):
        chapters = detect_chapters(
            "Глава третья. До\n\nТретий текст.\n\n"
            "Глава четвертая. После\n\nЧетвёртый текст.\n"
        )
        self.assertEqual([item["title"] for item in chapters], ["До", "После"])
        self.assertEqual(chapters[1]["heading"], "Глава четвертая. После")

    def test_no_headings_produces_one_fallback_chapter(self):
        chapters = detect_chapters("Обычный текст.\n\nЕщё один абзац.\n")
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["id"], "ch001")
        self.assertEqual(chapters[0]["title"], "Основной текст")

    def test_numeric_progression_with_titles_is_conservative(self):
        text = "1. Первый раздел\n\nТекст.\n\n2. Второй раздел\n\nЕщё текст.\n"
        chapters = detect_chapters(text)
        self.assertEqual([item["title"] for item in chapters], ["Первый раздел", "Второй раздел"])
        ordinary_list = detect_chapters("1. пункт\n2. пункт\n")
        self.assertEqual(len(ordinary_list), 1)
        self.assertEqual(ordinary_list[0]["title"], "Основной текст")

    def test_chapter_ids_are_stable(self):
        first = detect_chapters(normalize_working_text(SOURCE_TEXT))
        second = detect_chapters(normalize_working_text(SOURCE_TEXT))
        self.assertEqual([item["id"] for item in first], ["ch001", "ch002"])
        self.assertEqual([item["id"] for item in first], [item["id"] for item in second])

    def test_segment_ids_are_stable_and_nonempty(self):
        chapter = detect_chapters(normalize_working_text(SOURCE_TEXT))[0]
        first = segment_chapter_text(chapter, target_chars=80, hard_chars=120)
        second = segment_chapter_text(chapter, target_chars=80, hard_chars=120)
        self.assertEqual([item["id"] for item in first], [item["id"] for item in second])
        self.assertTrue(all(item["id"].startswith("ch001_s") for item in first))
        self.assertTrue(all(item["text"].strip() for item in first))
        self.assertTrue(all(len(item["text"]) <= 120 for item in first))

    def test_single_long_sentence_uses_hard_safety_ceiling(self):
        chapter = {"id": "ch001", "index": 1, "text": " ".join(["слово"] * 400)}
        segments = segment_chapter_text(chapter)
        self.assertTrue(all(0 < len(item["text"]) <= HARD_SEGMENT_CHARS for item in segments))

    def test_prepared_artifact_paths_are_relative_and_profile_is_lightweight(self):
        result = self.prepare()
        for key in ("normalized_path", "structure_path", "segments_path"):
            self.assertFalse(Path(result[key]).is_absolute())
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        self.assertNotIn("segments", profile["jobs"]["chapter-ch001"])
        self.assertEqual(profile["jobs"]["chapter-ch001"]["segment_ids"][0], "ch001_s0001")

    def test_preparation_is_ready_with_chapters_segments_and_preview_job(self):
        result = self.prepare()
        self.assertEqual(result["preparation_status"], "READY")
        self.assertEqual(result["preparation_revision"], 1)
        self.assertEqual(result["chapter_count"], 2)
        self.assertGreaterEqual(result["segment_count"], 2)
        self.assertEqual(result["jobs"][0]["id"], "short-test")
        self.assertFalse(result["remote_request_sent"])

    def test_restart_persists_status_and_materializes_execution_jobs(self):
        self.prepare()
        restarted_library = BookLibrary(self.books)
        restarted_service = BookTextPreparationService(restarted_library)
        self.assertEqual(restarted_service.status("prepared-book")["preparation_status"], "READY")
        execution = restarted_library.load_book_for_execution("prepared-book")
        self.assertTrue(execution["jobs"]["chapter-ch001"]["segments"])
        self.assertEqual(execution["jobs"]["short-test"]["segments"][0]["id"], "preview_s0001")

    def test_editing_working_copy_marks_preparation_stale_and_hides_jobs(self):
        self.prepare()
        self.working.write_text(self.working.read_text(encoding="utf-8") + "\nНовая редакция.\n", encoding="utf-8")
        status = self.service.status("prepared-book")
        self.assertEqual(status["preparation_status"], "STALE")
        self.assertEqual(status["jobs"], [])
        with self.assertRaises(BookLibraryError):
            self.library.load_book_for_execution("prepared-book")

    def test_old_normalization_rules_mark_preparation_stale_and_hide_jobs(self):
        self.prepare()
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        profile["preparation"]["normalization_rules_version"] = "1"
        self.profile_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        status = self.service.status("prepared-book")
        self.assertEqual(status["preparation_status"], "STALE")
        self.assertEqual(status["jobs"], [])
        with self.assertRaisesRegex(BookLibraryError, "preparation is STALE"):
            self.library.load_book_for_execution("prepared-book")

    def test_reprepare_updates_revision_and_new_identity(self):
        first = self.prepare()
        self.working.write_text(self.working.read_text(encoding="utf-8") + "\nНовая редакция.\n", encoding="utf-8")
        second = self.prepare()
        self.assertEqual(second["preparation_revision"], 2)
        self.assertNotEqual(first["preparation_identity"], second["preparation_identity"])
        self.assertEqual(second["preparation_status"], "READY")

    def test_external_source_tamper_becomes_source_integrity_error(self):
        self.prepare()
        os.chmod(self.original, stat.S_IRUSR | stat.S_IWUSR)
        self.original.write_text("Подмена", encoding="utf-8")
        status = self.service.status("prepared-book")
        self.assertEqual(status["preparation_status"], "SOURCE_INTEGRITY_ERROR")
        self.assertEqual(status["jobs"], [])

    def test_source_tamper_before_first_preparation_is_integrity_error(self):
        os.chmod(self.original, stat.S_IRUSR | stat.S_IWUSR)
        self.original.write_text("Подмена до подготовки", encoding="utf-8")
        status = self.service.status("prepared-book")
        self.assertEqual(status["preparation_status"], "SOURCE_INTEGRITY_ERROR")
        self.assertEqual(status["jobs"], [])

    def test_structure_corruption_marks_preparation_stale(self):
        self.prepare()
        (self.asset_root / "prepared/structure.json").write_text('{"chapters": []}\n', encoding="utf-8")
        status = self.service.status("prepared-book")
        self.assertEqual(status["preparation_status"], "STALE")
        with self.assertRaises(BookLibraryError):
            self.library.load_book_for_execution("prepared-book")

    def test_jobs_are_not_published_when_profile_publish_fails(self):
        with mock.patch.object(self.library, "replace_book_profile", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(json.loads(self.profile_path.read_text(encoding="utf-8"))["jobs"], {})
        self.assertFalse((self.asset_root / "prepared").exists())

    def test_preparation_never_requests_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network attempted")) as request:
            result = self.prepare()
        request.assert_not_called()
        self.assertFalse(result["remote_request_sent"])

    def test_billing_ledger_is_unchanged(self):
        ledger = self.root / "runtime/billing/ledger.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text('{"events": []}\n', encoding="utf-8")
        before = ledger.read_bytes()
        self.prepare()
        self.assertEqual(ledger.read_bytes(), before)

    def test_existing_book_library_import_contract_remains_valid(self):
        other = self.root / "other.txt"
        other.write_text("Отдельная книга.", encoding="utf-8")
        result = self.library.import_text_book(
            source_file=other,
            title="Другая",
            author="Автор",
            slug="other-book",
        )
        self.assertEqual(result["preparation_status"], "NOT_PREPARED")
        self.assertEqual(result["jobs"], [])
        self.assertEqual(result["source_integrity"], "OK")


if __name__ == "__main__":
    unittest.main()
