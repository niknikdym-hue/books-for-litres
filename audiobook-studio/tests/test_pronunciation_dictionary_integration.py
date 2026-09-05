from __future__ import annotations

import json
import os
import subprocess
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
from pronunciation_dictionary import (
    PronunciationDictionary,
    PronunciationDictionaryError,
    contextual_review_items,
    migrate_book_rules,
)
from tts_pronunciation_apply import apply_book_stress, synchronize_global_pronunciations
from tts_text_review import (
    add_pronunciation_override,
    working_copy_lock,
    working_copy_status,
)


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

    def test_contextual_publish_holds_book_lock_through_exact_rollback(self) -> None:
        self.import_book("context-rollback", "Глава 1.\n\nСтарый замок.\n")
        before = working_copy_status(self.library, "context-rollback")
        start = before["text"].index("замок")
        processes: list[subprocess.Popen[str]] = []
        concurrent_text = before["text"] + "Новая параллельная правка.\n"
        code = (
            "import sys; from pathlib import Path; from book_library import BookLibrary; "
            "from tts_text_review import save_working_copy; "
            "save_working_copy(BookLibrary(Path(sys.argv[1])/'books'), 'context-rollback', "
            "text=sys.argv[2], expected_sha256=sys.argv[3])"
        )

        def fail_after_starting_editor(*_args, **_kwargs):
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(self.root), concurrent_text, before["working_copy_sha256"]],
                env=dict(os.environ, PYTHONPATH=str(ROOT)),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
            with self.assertRaises(subprocess.TimeoutExpired):
                process.wait(timeout=0.1)
            raise PronunciationDictionaryError("injected", "injected failure")

        with mock.patch(
            "tts_pronunciation_apply.PronunciationDictionary.upsert",
            side_effect=fail_after_starting_editor,
        ):
            with self.assertRaises(PronunciationDictionaryError):
                apply_book_stress(
                    self.library,
                    "context-rollback",
                    word="замок",
                    vowel_number=2,
                    scope="OCCURRENCE",
                    start=start,
                    end=start + len("замок"),
                    expected_sha256=before["working_copy_sha256"],
                )
        stdout, stderr = processes[0].communicate(timeout=2)
        self.assertEqual(processes[0].returncode, 0, stdout + stderr)
        after = working_copy_status(self.library, "context-rollback")
        self.assertEqual(after["text"], concurrent_text)

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

    def test_realistic_legacy_zamok_repair_preserves_book_and_occurrence_authority(self) -> None:
        self.import_book("legacy", "Глава 1.\n\nСтарый замок и дверной замок.\n")
        before = working_copy_status(self.library, "legacy")
        first_start = before["text"].index("замок")
        add_pronunciation_override(
            self.library,
            "legacy",
            word="замок",
            vowel_number=2,
            scope="OCCURRENCE",
            start=first_start,
            end=first_start + len("замок"),
        )
        add_pronunciation_override(
            self.library,
            "legacy",
            word="замок",
            vowel_number=2,
            scope="BOOK",
        )
        profile_path = self.books / "legacy.json"
        profile_before = profile_path.read_bytes()
        working_before = (self.books / "legacy/tts/working.txt").read_bytes()
        source_before = (self.books / "legacy/source/original.txt").read_bytes()

        store = PronunciationDictionary(self.root)
        store.upsert("замок", 2, "замо́к")
        # Simulate the exact unsafe intermediate-version record that existed
        # before the homograph authority landed.
        document = json.loads(store.path.read_text(encoding="utf-8"))
        entry = document["entries"][0]
        entry["mode"] = "AUTO"
        entry["preferred"] = next(
            variant for variant in entry["variants"] if variant["vowel_number"] == 2
        )
        entry["variants"] = [entry["preferred"]]
        store.path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        store.path.chmod(0o600)

        migrated = migrate_book_rules(self.library, store)
        self.assertTrue(migrated["contextual_repair_changed"])
        repaired = store.snapshot()["entries"][0]
        self.assertEqual(repaired["mode"], "REVIEW_REQUIRED")
        self.assertIsNone(repaired["preferred"])
        self.assertEqual(
            {variant["display"] for variant in repaired["variants"]},
            {"за́мок", "замо́к"},
        )
        self.assertEqual(profile_path.read_bytes(), profile_before)
        self.assertEqual((self.books / "legacy/tts/working.txt").read_bytes(), working_before)
        self.assertEqual((self.books / "legacy/source/original.txt").read_bytes(), source_before)
        revision = store.snapshot()["revision"]
        repeated = migrate_book_rules(self.library, store)
        self.assertFalse(repeated["contextual_repair_changed"])
        self.assertEqual(store.snapshot()["revision"], revision)

    def test_new_book_keeps_known_homograph_plain_and_surfaces_each_context(self) -> None:
        PronunciationDictionary(self.root).upsert("замок", 2, "замо́к")
        self.import_book("fresh", "Глава 1.\n\nСтарый замок и дверной замок.\n")
        source = (self.books / "fresh/source/original.txt").read_text(encoding="utf-8")
        working = (self.books / "fresh/tts/working.txt").read_text(encoding="utf-8")
        self.assertEqual(working, source)
        items = contextual_review_items(
            working,
            working_copy_sha256=working_copy_status(self.library, "fresh")["working_copy_sha256"],
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(
            {variant["display"] for variant in items[0]["variants"]},
            {"за́мок", "замо́к"},
        )

    def test_contextual_occurrence_change_preserves_unrelated_segment_identity(self) -> None:
        self.import_book(
            "context-segments",
            "Глава 1. Первая\n\nСтарый замок закрыт.\n\n"
            "Глава 2. Вторая\n\nСовсем другой неизменный текст.\n",
        )
        self.prepare("context-segments")
        before_execution = self.library.load_book_for_execution("context-segments")
        before_second = [
            segment["source_text_sha256"]
            for segment in before_execution["jobs"]["chapter-ch002"]["segments"]
        ]
        before = working_copy_status(self.library, "context-segments")
        start = before["text"].index("замок")
        apply_book_stress(
            self.library,
            "context-segments",
            word="замок",
            vowel_number=1,
            scope="OCCURRENCE",
            start=start,
            end=start + len("замок"),
            expected_sha256=before["working_copy_sha256"],
        )
        self.prepare("context-segments")
        after_execution = self.library.load_book_for_execution("context-segments")
        after_second = [
            segment["source_text_sha256"]
            for segment in after_execution["jobs"]["chapter-ch002"]["segments"]
        ]
        self.assertEqual(after_second, before_second)


if __name__ == "__main__":
    unittest.main()
