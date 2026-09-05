from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from content_quality_lexicon import ContentQualityLexicon
from tts_text_review import (
    TTSTextReviewError,
    accept_current_working_copy,
    add_pronunciation_override,
    assert_manual_review_ready,
    provider_stress_preview,
    save_working_copy,
    set_manual_review_required,
    stress_candidates,
    working_copy_status,
)


class TTSTextReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.library = BookLibrary(self.books)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_book(self, text: str = "Глава 1.\n\nСтарый замок стоял на холме.\n") -> Path:
        source = self.root / "book.txt"
        source.write_text(text, encoding="utf-8")
        self.library.import_text_book(
            source_file=source,
            title="Test Book",
            author="Test Author",
            slug="review-book",
        )
        return self.books / "review-book" / "source" / "original.txt"

    def prepare(self) -> dict:
        lexicon = ContentQualityLexicon(user_store_path=self.root / "shared" / "user-rules-v1.json")
        service = BookTextPreparationService(
            self.library,
            workspace_root=self.root,
            content_quality=lexicon,
            now=lambda: "2026-09-01T00:00:00+00:00",
        )
        return service.prepare("review-book")

    def test_owner_can_edit_working_copy_without_touching_immutable_source(self) -> None:
        source = self.import_book()
        source_before = source.read_bytes()
        status = working_copy_status(self.library, "review-book")
        updated = status["text"].replace("Старый", "Старинный")
        saved = save_working_copy(
            self.library,
            "review-book",
            text=updated,
            expected_sha256=status["working_copy_sha256"],
        )
        self.assertTrue(saved["changed"])
        self.assertIn("Старинный замок", saved["text"])
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(saved["working_copy_revision"], status["working_copy_revision"] + 1)
        self.assertEqual(saved["provider_requests"], 0)
        self.assertEqual(saved["model_calls"], 0)
        self.assertFalse(saved["paid_execution"])

    def test_save_uses_expected_sha_to_prevent_lost_owner_edits(self) -> None:
        self.import_book()
        status = working_copy_status(self.library, "review-book")
        save_working_copy(
            self.library,
            "review-book",
            text=status["text"] + "Новая строка.\n",
            expected_sha256=status["working_copy_sha256"],
        )
        with self.assertRaises(TTSTextReviewError) as captured:
            save_working_copy(
                self.library,
                "review-book",
                text=status["text"] + "Другая строка.\n",
                expected_sha256=status["working_copy_sha256"],
            )
        self.assertEqual(captured.exception.code, "working_copy_conflict")

    def test_edit_marks_previous_preparation_stale(self) -> None:
        self.import_book("Глава 1.\n\nТочный обычный текст.\n")
        ready = self.prepare()
        self.assertEqual(ready["preparation_status"], "READY")
        status = working_copy_status(self.library, "review-book")
        saved = save_working_copy(
            self.library,
            "review-book",
            text=status["text"] + "Исправление перед озвучкой.\n",
            expected_sha256=status["working_copy_sha256"],
        )
        self.assertEqual(saved["preparation_status"], "STALE")

    def test_optional_manual_acceptance_is_exact_sha_and_invalidates_on_edit(self) -> None:
        self.import_book()
        enabled = set_manual_review_required(self.library, "review-book", required=True)
        self.assertTrue(enabled["manual_review"]["required"])
        self.assertFalse(enabled["manual_review"]["ready"])
        with self.assertRaises(TTSTextReviewError) as captured:
            assert_manual_review_ready(self.library, "review-book")
        self.assertEqual(captured.exception.code, "manual_text_acceptance_required")

        accepted = accept_current_working_copy(self.library, "review-book")
        self.assertTrue(accepted["manual_review"]["accepted"])
        self.assertTrue(accepted["manual_review"]["ready"])
        gate = assert_manual_review_ready(self.library, "review-book")
        self.assertEqual(gate["working_copy_sha256"], accepted["working_copy_sha256"])

        saved = save_working_copy(
            self.library,
            "review-book",
            text=accepted["text"] + "После приёмки внесена правка.\n",
            expected_sha256=accepted["working_copy_sha256"],
        )
        self.assertFalse(saved["manual_review"]["accepted"])
        self.assertFalse(saved["manual_review"]["ready"])

    def test_stress_candidates_are_human_readable_and_yandex_preview_is_exact(self) -> None:
        candidates = stress_candidates("замок")
        self.assertEqual([item["display"] for item in candidates], ["за́мок", "замо́к"])
        first = provider_stress_preview("замок", vowel_number=1, engine="yandex")
        second = provider_stress_preview("замок", vowel_number=2, engine="yandex")
        self.assertEqual(first["provider_value"], "з+амок")
        self.assertEqual(second["provider_value"], "зам+ок")
        self.assertEqual(first["provider_requests"], 0)
        self.assertFalse(first["remote_request_sent"])

    def test_stress_candidates_allow_correcting_an_existing_acute(self) -> None:
        candidates = stress_candidates("за́мок")
        self.assertEqual([item["display"] for item in candidates], ["за́мок", "замо́к"])

    def test_openai_preview_keeps_provider_neutral_stress_decision(self) -> None:
        preview = provider_stress_preview("замок", vowel_number=2, engine="openai")
        self.assertEqual(preview["display"], "замо́к")
        self.assertEqual(preview["provider_mode"], "INSTRUCTION")
        self.assertIn("замо́к", preview["provider_value"])
        self.assertEqual(preview["provider_requests"], 0)

    def test_occurrence_override_is_bound_to_exact_current_text_offsets(self) -> None:
        self.import_book()
        status = working_copy_status(self.library, "review-book")
        start = status["text"].index("замок")
        result = add_pronunciation_override(
            self.library,
            "review-book",
            word="замок",
            vowel_number=1,
            scope="OCCURRENCE",
            start=start,
            end=start + len("замок"),
        )
        self.assertTrue(result["changed"])
        entry = result["entry"]
        self.assertEqual(entry["display"], "за́мок")
        self.assertEqual(entry["text_sha256"], status["working_copy_sha256"])
        self.assertEqual(entry["actor"], "OWNER")

        with self.assertRaises(TTSTextReviewError) as captured:
            add_pronunciation_override(
                self.library,
                "review-book",
                word="замок",
                vowel_number=2,
                scope="OCCURRENCE",
                start=0,
                end=5,
            )
        self.assertEqual(captured.exception.code, "pronunciation_text_mismatch")


if __name__ == "__main__":
    unittest.main()
