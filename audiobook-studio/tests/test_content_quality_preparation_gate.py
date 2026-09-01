from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from content_quality_execution import hold_current_content_quality
from content_quality_gate import ContentQualityGateError, validate_prepared_content_quality
from content_quality_lexicon import (
    PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
    ContentQualityLexicon,
    ContentQualityResolutionStore,
)


class ContentQualityPreparationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.user_store = self.root / "shared" / "user-rules-v1.json"
        self.lexicon = ContentQualityLexicon(user_store_path=self.user_store)
        self.library = BookLibrary(self.books)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_book(self, text: str, slug: str = "quality-book") -> Path:
        source = self.root / f"{slug}.txt"
        source.write_text(text, encoding="utf-8")
        self.library.import_text_book(
            source_file=source,
            title="Quality Book",
            author="Test Author",
            slug=slug,
        )
        return self.books / f"{slug}.json"

    def service(self) -> BookTextPreparationService:
        return BookTextPreparationService(
            self.library,
            workspace_root=self.root,
            content_quality=self.lexicon,
            now=lambda: "2026-09-01T00:00:00+00:00",
        )

    def test_block_stops_preparation_without_mutating_literary_text_or_publishing_jobs(self) -> None:
        profile = self.import_book("Эта книга не про контроль, а про точный выбор.\n")
        working = self.books / "quality-book" / "tts/working.txt"
        before = working.read_bytes()
        result = self.service().prepare("quality-book")
        self.assertEqual(result["preparation_status"], "BLOCKED_CONTENT_QUALITY")
        self.assertEqual(result["content_quality_state"], "BLOCKED")
        self.assertTrue(result["content_quality_evidence"]["editorial"]["blocking_findings"])
        finding = result["content_quality_evidence"]["editorial"]["blocking_findings"][0]
        self.assertIn("rule_id", finding)
        self.assertIn("matched_text", finding)
        self.assertIn("line", finding)
        self.assertIn("column", finding)
        self.assertEqual(working.read_bytes(), before)
        persisted = json.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(persisted["jobs"], {})
        self.assertNotIn("preparation", persisted)
        self.assertFalse((self.books / "quality-book" / "prepared").exists())
        self.assertEqual(result["provider_requests"], 0)
        self.assertEqual(result["model_calls"], 0)
        self.assertFalse(result["paid_execution"])

    def test_warn_is_published_as_visible_evidence_without_text_rewrite(self) -> None:
        profile = self.import_book("В комнате слышался шум вентиляции.\n")
        working = self.books / "quality-book" / "tts/working.txt"
        before = working.read_bytes()
        result = self.service().prepare("quality-book")
        self.assertEqual(result["preparation_status"], "READY")
        self.assertEqual(result["content_quality_state"], "WARN")
        self.assertEqual(working.read_bytes(), before)
        persisted = json.loads(profile.read_text(encoding="utf-8"))
        preparation = persisted["preparation"]
        evidence_path = self.books / "quality-book" / preparation["content_quality_evidence_path"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["state"], "WARN")
        self.assertTrue(evidence["editorial"]["warning_findings"])
        self.assertEqual(evidence["working_copy_sha256"], preparation["working_copy_sha256"])
        self.assertEqual(evidence["gate_version"], "1")
        self.assertEqual(evidence["gate_fingerprint"], preparation["content_quality_gate_fingerprint"])
        self.assertIsInstance(preparation["content_quality_evidence_sha256"], str)

    def test_technical_tts_block_runs_on_exact_normalized_identity(self) -> None:
        self.import_book("Глава 1. Текст\n\nTODO: удалить служебный маркер.\n")
        result = self.service().prepare("quality-book")
        self.assertEqual(result["preparation_status"], "BLOCKED_CONTENT_QUALITY")
        technical = result["content_quality_evidence"]["technical"]
        self.assertEqual(technical["state"], "BLOCKED")
        self.assertTrue(any(item["rule_id"] == "AUDIO-TTS-PLACEHOLDER-001" for item in technical["blocking_findings"]))
        self.assertEqual(technical["text_sha256"], result["normalized_sha256"])

    def test_preparation_identity_records_lexicon_fingerprint(self) -> None:
        self.import_book("Глава 1. Начало\n\nОбычный точный текст.\n")
        result = self.service().prepare("quality-book")
        self.assertEqual(result["preparation_status"], "READY")
        gate = validate_prepared_content_quality(
            library=self.library,
            workspace_root=self.root,
            book_name="quality-book",
            lexicon=self.lexicon,
        )
        self.assertEqual(gate["state"], "PASS")
        self.assertEqual(gate["gate_fingerprint"], result["content_quality_gate_fingerprint"])
        self.assertEqual(gate["provider_requests"], 0)
        self.assertEqual(gate["model_calls"], 0)
        self.assertFalse(gate["paid_execution"])

    def test_user_lexicon_change_invalidates_prepared_gate_before_new_synthesis(self) -> None:
        self.import_book("Глава 1. Начало\n\nОбычный точный текст.\n")
        self.service().prepare("quality-book")
        self.lexicon.user_store.add("точный текст", action="BLOCK")
        with self.assertRaises(ContentQualityGateError) as captured:
            validate_prepared_content_quality(
                library=self.library,
                workspace_root=self.root,
                book_name="quality-book",
                lexicon=self.lexicon,
            )
        self.assertEqual(captured.exception.code, "content_quality_lexicon_changed")

    def test_human_resolution_is_exact_sha_and_reprepare_rebinds_evidence(self) -> None:
        profile = self.import_book("Эта книга не про запреты, а про выбор.\n")
        first = self.service().prepare("quality-book")
        self.assertEqual(first["preparation_status"], "BLOCKED_CONTENT_QUALITY")
        editorial = first["content_quality_evidence"]["editorial"]
        rule_id = editorial["blocking_findings"][0]["rule_id"]
        ContentQualityResolutionStore(self.root, "quality-book").add(
            rule_id=rule_id,
            profile=PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
            text_sha256=editorial["text_sha256"],
            reason="Владелец подтвердил содержательную необходимость этого точного фрагмента.",
        )
        second = self.service().prepare("quality-book")
        self.assertIn(second["content_quality_state"], {"PASS", "WARN"})
        self.assertEqual(second["preparation_status"], "READY")
        working = self.books / "quality-book" / "tts/working.txt"
        working.write_text(working.read_text(encoding="utf-8") + "Новая редакция.\n", encoding="utf-8")
        third = self.service().prepare("quality-book")
        self.assertEqual(third["preparation_status"], "BLOCKED_CONTENT_QUALITY")
        self.assertTrue(third["content_quality_evidence"]["editorial"]["blocking_findings"])
        persisted = json.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(persisted["preparation"]["working_copy_sha256"], second["working_copy_sha256"])

    def test_corrupt_shared_store_fails_closed_without_destroying_existing_preparation(self) -> None:
        profile = self.import_book("Глава 1. Начало\n\nОбычный текст.\n")
        ready = self.service().prepare("quality-book")
        self.assertEqual(ready["preparation_status"], "READY")
        self.user_store.parent.mkdir(parents=True, exist_ok=True)
        original = b"{broken"
        self.user_store.write_bytes(original)
        with self.assertRaisesRegex(Exception, "CONTENT_QUALITY"):
            self.service().prepare("quality-book")
        self.assertEqual(self.user_store.read_bytes(), original)
        persisted = json.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(persisted["preparation"]["identity_sha256"], ready["preparation_identity"])

    def test_execution_barrier_blocks_before_provider_or_model_callback(self) -> None:
        self.import_book("Глава 1. Начало\n\nОбычный текст.\n")
        self.service().prepare("quality-book")
        callbacks = 0

        with hold_current_content_quality(
            library=self.library,
            workspace_root=self.root,
            book_name="quality-book",
            lexicon=self.lexicon,
        ) as evidence:
            self.assertIn(evidence["state"], {"PASS", "WARN"})
            callbacks += 1
        self.assertEqual(callbacks, 1)

        self.lexicon.user_store.add("Обычный текст", action="BLOCK")
        callbacks = 0
        with self.assertRaises(ContentQualityGateError) as captured:
            with hold_current_content_quality(
                library=self.library,
                workspace_root=self.root,
                book_name="quality-book",
                lexicon=self.lexicon,
            ):
                callbacks += 1  # represents the provider/model entry point
        self.assertEqual(captured.exception.code, "content_quality_lexicon_changed")
        self.assertEqual(callbacks, 0)


if __name__ == "__main__":
    unittest.main()
