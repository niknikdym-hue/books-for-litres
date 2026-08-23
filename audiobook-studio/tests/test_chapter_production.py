from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from chapter_production import ChapterProductionError, ChapterProductionService


class ChapterProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.books.mkdir()
        self.source = self.root / "source.txt"
        self.source.write_text(
            "Глава 1. Начало\n\nПервое предложение. Второе предложение.\n\n"
            "Глава 2. Продолжение\n\nТретье предложение. Четвёртое предложение.\n",
            encoding="utf-8",
        )
        self.library = BookLibrary(self.books)
        self.library.import_text_book(
            source_file=self.source,
            title="Книга",
            author="Автор",
            slug="book",
        )
        self.preparation = BookTextPreparationService(
            self.library,
            now=lambda: "2026-08-23T12:00:00+00:00",
        )
        self.preparation.prepare("book")
        self.service = ChapterProductionService(self.library)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_catalog_exposes_only_chapter_jobs_without_network(self) -> None:
        catalog = self.service.chapter_catalog("book")
        self.assertEqual(len(catalog["chapters"]), 2)
        self.assertTrue(all(item["job_id"].startswith("chapter-") for item in catalog["chapters"]))
        self.assertFalse(catalog["remote_request_sent"])

    def test_yandex_plan_is_bound_to_exact_preparation_and_segments(self) -> None:
        plan = self.service.plan(
            book_id="book",
            job_id="chapter-ch001",
            engine="yandex",
            profile_id="yandex_lera",
        )
        self.assertEqual(plan["decision"], "READY_FOR_PROVIDER_PREFLIGHT")
        self.assertTrue(plan["chapter_production_identity"])
        self.assertTrue(plan["preparation_identity"])
        self.assertGreater(plan["segment_count"], 0)
        self.assertTrue(all(len(item["text_sha256"]) == 64 for item in plan["segments"]))
        self.assertTrue(plan["execution_policy"]["requires_cost_preflight"])
        self.assertEqual(plan["execution_policy"]["confirmation_scope"], "chapter")
        self.assertIsNone(plan["execution_policy"]["max_network_requests"])
        self.assertFalse(plan["remote_request_sent"])

    def test_openai_policy_preserves_one_request_per_confirmation(self) -> None:
        plan = self.service.plan(
            book_id="book",
            job_id="chapter-ch001",
            engine="openai",
            profile_id="openai_cedar",
        )
        self.assertEqual(plan["decision"], "READY_FOR_SEGMENT_PLAN")
        self.assertEqual(plan["execution_policy"]["confirmation_scope"], "segment")
        self.assertEqual(plan["execution_policy"]["max_network_requests"], 1)
        self.assertFalse(plan["remote_request_sent"])

    def test_qwen_is_not_falsely_advertised_as_resumable(self) -> None:
        plan = self.service.plan(
            book_id="book",
            job_id="chapter-ch001",
            engine="qwen",
            profile_id="qwen_vivian",
        )
        self.assertEqual(plan["decision"], "ADAPTER_PENDING")
        self.assertIn("qwen_persistent_resume_adapter_pending", plan["blockers"])
        self.assertEqual(plan["execution_policy"]["max_network_requests"], 0)

    def test_preview_job_is_rejected_for_chapter_production(self) -> None:
        with self.assertRaisesRegex(ChapterProductionError, "only prepared chapter jobs"):
            self.service.plan(
                book_id="book",
                job_id="short-test",
                engine="yandex",
                profile_id="yandex_lera",
            )

    def test_stale_working_copy_blocks_old_chapter_plan(self) -> None:
        working = self.books / "book/tts/working.txt"
        working.write_text(working.read_text(encoding="utf-8") + "\nПравка.\n", encoding="utf-8")
        with self.assertRaisesRegex(ChapterProductionError, "STALE"):
            self.service.plan(
                book_id="book",
                job_id="chapter-ch001",
                engine="openai",
                profile_id="openai_onyx",
            )

    def test_reprepare_invalidates_old_chapter_identity(self) -> None:
        before = self.service.plan(
            book_id="book",
            job_id="chapter-ch001",
            engine="yandex",
            profile_id="yandex_lera",
        )
        working = self.books / "book/tts/working.txt"
        working.write_text(
            working.read_text(encoding="utf-8").replace("Первое предложение.", "Изменённое первое предложение."),
            encoding="utf-8",
        )
        self.preparation.prepare("book")
        after = self.service.plan(
            book_id="book",
            job_id="chapter-ch001",
            engine="yandex",
            profile_id="yandex_lera",
        )
        self.assertNotEqual(before["preparation_identity"], after["preparation_identity"])
        self.assertNotEqual(before["chapter_production_identity"], after["chapter_production_identity"])

    def test_engine_and_profile_validation_fail_closed(self) -> None:
        with self.assertRaises(ChapterProductionError):
            self.service.plan(
                book_id="book",
                job_id="chapter-ch001",
                engine="unknown",
                profile_id="voice",
            )
        with self.assertRaises(ChapterProductionError):
            self.service.plan(
                book_id="book",
                job_id="chapter-ch001",
                engine="yandex",
                profile_id="",
            )


if __name__ == "__main__":
    unittest.main()
