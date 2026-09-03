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

    def test_owner_can_correct_existing_stress_after_listening(self) -> None:
        self.import_book()
        first = apply_book_stress(
            self.library,
            "stress-book",
            word="замок",
            vowel_number=2,
        )
        self.assertEqual(first["text"].count("замо́к"), 2)
        override_id = first["pronunciation_entry"]["override_id"]
        revision = first["pronunciation_revision"]

        corrected = apply_book_stress(
            self.library,
            "stress-book",
            word="замок",
            vowel_number=1,
        )
        self.assertEqual(corrected["text"].count("за́мок"), 2)
        self.assertNotIn("замо́к", corrected["text"])
        self.assertEqual(corrected["pronunciation_entry"]["override_id"], override_id)
        self.assertEqual(corrected["pronunciation_entry"]["vowel_number"], 1)
        self.assertGreater(corrected["pronunciation_revision"], revision)

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

    def test_author_pronunciation_reaches_both_provider_payloads_without_mutating_source(self) -> None:
        source = self.root / "author-book.txt"
        source_text = "Глава 1.\n\nКнигу написала Елена Дымова.\n"
        source.write_text(source_text, encoding="utf-8")
        self.library.import_text_book(
            source_file=source,
            title="Author Book",
            author="Елена Дымова",
            author_pronunciation="Еле́на Ды́мова",
            slug="author-book",
        )
        immutable_source = self.books / "author-book/source/original.txt"
        working_copy = self.books / "author-book/tts/working.txt"
        source_before = immutable_source.read_bytes()
        working_before = working_copy.read_bytes()

        lexicon = ContentQualityLexicon(user_store_path=self.root / "shared" / "user-rules-v1.json")
        result = BookTextPreparationService(
            self.library,
            workspace_root=self.root,
            content_quality=lexicon,
            now=lambda: "2026-09-01T00:00:00+00:00",
        ).prepare("author-book")
        self.assertEqual(result["preparation_status"], "READY")
        prepared = self.library.load_book_for_execution("author-book")
        prepared_text = prepared["jobs"]["chapter-ch001"]["segments"][0]["text"]
        self.assertIn("Еле́на Ды́мова", prepared_text)
        self.assertNotIn("Елена Дымова", prepared_text)
        self.assertEqual(immutable_source.read_bytes(), source_before)
        self.assertEqual(working_copy.read_bytes(), working_before)

        yandex = YandexSpeechKitBackend(
            load_yandex_config(ROOT / "yandex-config.json"),
            api_key="offline-not-used",
        ).build_synthesis_payload(prepared_text)
        self.assertIn("Ел+ена Д+ымова", yandex["text"])

        openai_backend = OpenAITTSBackend(load_openai_config(ROOT / "openai-config.json"))
        openai = openai_backend.build_synthesis_payload(prepared_text, "openai_cedar")
        self.assertIn("Еле́на Ды́мова", openai["input"])
        self.assertIn("Еле́на", openai["instructions"])
        self.assertIn("Ды́мова", openai["instructions"])

        profile_path = self.books / "author-book.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["author_pronunciation"] = "Е́лена Дымова"
        self.library.replace_book_profile("author-book", profile)
        self.assertEqual(self.library.book_details("author-book")["preparation_status"], "STALE")


if __name__ == "__main__":
    unittest.main()
