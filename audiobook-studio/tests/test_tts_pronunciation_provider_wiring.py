from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.openai_tts import OpenAITTSBackend, load_backend_config as load_openai_config, make_fingerprint, load_approved_profile
from backends.pronunciation_markup import accented_words, openai_instruction_suffix, yandex_text_markup
from backends.yandex_speechkit import YandexSpeechKitBackend, load_backend_config as load_yandex_config
from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from content_quality_lexicon import ContentQualityLexicon
from tts_pronunciation_apply import apply_book_stress
from tts_text_review import working_copy_status


class TTSPronunciationProviderWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.library = BookLibrary(self.books)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_book(self) -> Path:
        source = self.root / "book.txt"
        source.write_text(
            "Глава 1.\n\nСтарый замок стоял на холме. Другой замок был закрыт.\n",
            encoding="utf-8",
        )
        self.library.import_text_book(
            source_file=source,
            title="Test Book",
            author="Test Author",
            slug="stress-book",
        )
        return self.books / "stress-book" / "source" / "original.txt"

    def prepare(self) -> dict:
        lexicon = ContentQualityLexicon(user_store_path=self.root / "shared" / "user-rules-v1.json")
        return BookTextPreparationService(
            self.library,
            workspace_root=self.root,
            content_quality=lexicon,
            now=lambda: "2026-09-01T00:00:00+00:00",
        ).prepare("stress-book")

    def test_book_stress_is_materialized_in_tts_copy_and_never_changes_source(self) -> None:
        source = self.import_book()
        source_before = source.read_bytes()
        ready = self.prepare()
        self.assertEqual(ready["preparation_status"], "READY")

        result = apply_book_stress(
            self.library,
            "stress-book",
            word="замок",
            vowel_number=2,
        )
        self.assertEqual(result["display"], "замо́к")
        self.assertEqual(result["matches_materialized"], 2)
        self.assertEqual(result["text"].count("замо́к"), 2)
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(result["preparation_status"], "STALE")
        self.assertFalse(result["manual_review"]["accepted"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])

    def test_yandex_adapter_translates_human_stress_to_speechkit_markup(self) -> None:
        text = "Старый замо́к стоял на холме."
        self.assertEqual(yandex_text_markup(text), "Старый зам+ок стоял на холме.")
        config = load_yandex_config(ROOT / "yandex-config.json")
        backend = YandexSpeechKitBackend(config, api_key="offline-not-used")
        payload = backend.build_synthesis_payload(text)
        self.assertEqual(payload["text"], "Старый зам+ок стоял на холме.")
        self.assertFalse(payload["unsafeMode"])

    def test_openai_adapter_adds_exact_stress_instruction_without_network(self) -> None:
        text = "Старый замо́к стоял на холме."
        self.assertEqual(accented_words(text), [{"word": "замок", "display": "замо́к"}])
        suffix = openai_instruction_suffix(text)
        self.assertIn("замо́к", suffix)
        config = load_openai_config(ROOT / "openai-config.json")
        backend = OpenAITTSBackend(config)
        profile_id = "openai_cedar"
        payload = backend.build_synthesis_payload(text, profile_id)
        self.assertEqual(payload["input"], text)
        self.assertIn("замо́к", payload["instructions"])
        self.assertIn("не меняй остальной текст", payload["instructions"])

    def test_stress_change_changes_openai_cache_fingerprint_naturally(self) -> None:
        profile = load_approved_profile("openai_cedar")
        plain = make_fingerprint("Старый замок стоял на холме.", profile)
        accented = make_fingerprint("Старый замо́к стоял на холме.", profile)
        self.assertNotEqual(plain, accented)

    def test_stress_change_changes_yandex_segment_fingerprint_naturally(self) -> None:
        config = load_yandex_config(ROOT / "yandex-config.json")
        backend = YandexSpeechKitBackend(config, api_key="offline-not-used")
        plain = backend.segment("Старый замок стоял на холме.")[0]
        accented = backend.segment("Старый замо́к стоял на холме.")[0]
        from backends.yandex_speechkit import make_fingerprint as yandex_fingerprint
        self.assertNotEqual(
            yandex_fingerprint(plain.text, backend.profile),
            yandex_fingerprint(accented.text, backend.profile),
        )

    def test_provider_markup_rejects_stray_acute_instead_of_guessing(self) -> None:
        with self.assertRaises(ValueError):
            yandex_text_markup("неверно \u0301слово")


if __name__ == "__main__":
    unittest.main()
