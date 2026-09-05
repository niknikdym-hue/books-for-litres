from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from content_quality_lexicon import ContentQualityLexicon
from production_authority_lock import production_authority_lock
from pronunciation_dictionary import PronunciationDictionary, PronunciationDictionaryError
from tts_pronunciation_apply import apply_book_stress, synchronize_global_pronunciations
from tts_text_review import working_copy_lock


class PronunciationDictionaryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.library = BookLibrary(self.books)
        self.lexicon = ContentQualityLexicon(
            user_store_path=self.root / "shared/content-quality/user-rules-v1.json"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_book(self, slug: str, text: str) -> None:
        source = self.root / f"{slug}.txt"
        source.write_text(text, encoding="utf-8")
        self.library.import_text_book(
            source_file=source,
            title=slug,
            author="Автор",
            slug=slug,
        )

    def prepare(self, slug: str) -> dict:
        return BookTextPreparationService(
            self.library,
            workspace_root=self.root,
            content_quality=self.lexicon,
            now=lambda: "2026-09-05T00:00:00+00:00",
        ).prepare(slug)

    def test_reopen_materializes_new_auto_rule_and_invalidates_exact_preparation(self) -> None:
        self.import_book("existing", "Глава 1.\n\nДилон читает книгу.\n")
        ready = self.prepare("existing")
        self.assertEqual(ready["preparation_status"], "READY")
        original = (self.books / "existing/source/original.txt").read_bytes()

        PronunciationDictionary(self.root).upsert("Дилон", 1, "Ди́лон")
        synced = synchronize_global_pronunciations(self.library, "existing")
        self.assertTrue(synced["changed"])
        self.assertIn("Ди́лон", synced["text"])
        self.assertEqual(synced["preparation_status"], "STALE")
        self.assertEqual((self.books / "existing/source/original.txt").read_bytes(), original)

        repeated = synchronize_global_pronunciations(self.library, "existing")
        self.assertFalse(repeated["changed"])
        self.assertEqual(repeated["working_copy_sha256"], synced["working_copy_sha256"])

    def test_unaffected_segment_identity_survives_dictionary_materialization(self) -> None:
        self.import_book(
            "segments",
            "Глава 1. Первая\n\nДилон открыла дверь.\n\n"
            "Глава 2. Вторая\n\nСовсем другой неизменный текст.\n",
        )
        self.prepare("segments")
        before = self.library.load_book_for_execution("segments")
        before_second = [
            segment["source_text_sha256"]
            for segment in before["jobs"]["chapter-ch002"]["segments"]
        ]

        PronunciationDictionary(self.root).upsert("Дилон", 1, "Ди́лон")
        self.prepare("segments")
        after = self.library.load_book_for_execution("segments")
        after_second = [
            segment["source_text_sha256"]
            for segment in after["jobs"]["chapter-ch002"]["segments"]
        ]
        self.assertEqual(after_second, before_second)

    def test_failed_global_publish_rolls_back_book_text_and_evidence(self) -> None:
        self.import_book("rollback", "Глава 1.\n\nДилон читает.\n")
        profile_path = self.books / "rollback.json"
        working_path = self.books / "rollback/tts/working.txt"
        profile_before = profile_path.read_bytes()
        working_before = working_path.read_bytes()
        with mock.patch(
            "tts_pronunciation_apply.PronunciationDictionary.upsert",
            side_effect=PronunciationDictionaryError("injected", "injected failure"),
        ):
            with self.assertRaises(PronunciationDictionaryError):
                apply_book_stress(self.library, "rollback", word="Дилон", vowel_number=1)
        self.assertEqual(profile_path.read_bytes(), profile_before)
        self.assertEqual(working_path.read_bytes(), working_before)

    def test_provider_lock_order_and_dictionary_sync_complete_without_deadlock(self) -> None:
        self.import_book("locks", "Глава 1.\n\nДилон читает.\n")
        PronunciationDictionary(self.root).upsert("Дилон", 1, "Ди́лон")
        provider_has_locks = threading.Event()
        release_provider = threading.Event()

        def provider_fence() -> None:
            with production_authority_lock(
                self.root,
                provider="yandex",
                book_slug="locks",
                job_id="chapter-ch001",
                profile_id="yandex_lera",
                exclusive=True,
            ):
                with working_copy_lock(self.library, "locks"):
                    provider_has_locks.set()
                    self.assertTrue(release_provider.wait(timeout=5))

        with ThreadPoolExecutor(max_workers=2) as executor:
            provider = executor.submit(provider_fence)
            self.assertTrue(provider_has_locks.wait(timeout=5))
            owner = executor.submit(synchronize_global_pronunciations, self.library, "locks")
            release_provider.set()
            provider.result(timeout=5)
            result = owner.result(timeout=5)
        self.assertTrue(result["changed"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])


if __name__ == "__main__":
    unittest.main()
