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
from pronunciation_dictionary import PronunciationDictionary
from tts_pronunciation_apply import apply_book_stress
from tts_text_review import TTSTextReviewError, working_copy_status


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
            "Глава 1.\n\nДилон увидела старый замок. Потом Дилон закрыла другой замок.\n",
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
            word="Дилон",
            vowel_number=1,
        )
        self.assertEqual(result["display"], "Ди́лон")
        self.assertEqual(result["matches_materialized"], 2)
        self.assertEqual(result["text"].count("Ди́лон"), 2)
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
            word="Дилон",
            vowel_number=1,
        )
        self.assertEqual(first["text"].count("Ди́лон"), 2)
        override_id = first["pronunciation_entry"]["override_id"]
        revision = first["pronunciation_revision"]

        corrected = apply_book_stress(
            self.library,
            "stress-book",
            word="Дилон",
            vowel_number=2,
        )
        self.assertEqual(corrected["text"].count("Дило́н"), 2)
        self.assertNotIn("Ди́лон", corrected["text"])
        self.assertEqual(corrected["pronunciation_entry"]["override_id"], override_id)
        self.assertEqual(corrected["pronunciation_entry"]["vowel_number"], 2)
        self.assertGreater(corrected["pronunciation_revision"], revision)
        global_entry = PronunciationDictionary(self.root).snapshot()["entries"][0]
        self.assertEqual(global_entry["mode"], "REVIEW_REQUIRED")
        self.assertEqual(
            {variant["display"] for variant in global_entry["variants"]},
            {"Ди́лон", "Дило́н"},
        )

    def test_owner_correction_is_remembered_and_applied_to_a_new_book_only_in_working_copy(self) -> None:
        self.import_book()
        correction = apply_book_stress(
            self.library,
            "stress-book",
            word="Дилон",
            vowel_number=1,
        )
        self.assertEqual(correction["confirmation_message"], "Ди́лон добавлено в Словарь ударений")
        self.assertEqual(correction["dictionary_entry"]["mode"], "AUTO")

        new_source = self.root / "new-book.txt"
        original = "Глава 1.\n\nДилон и недилон.\n"
        new_source.write_text(original, encoding="utf-8")
        self.library.import_text_book(
            source_file=new_source,
            title="New Book",
            author="Author",
            slug="new-book",
        )
        immutable = self.books / "new-book/source/original.txt"
        working = self.books / "new-book/tts/working.txt"
        self.assertEqual(immutable.read_text(encoding="utf-8"), original)
        self.assertIn("Ди́лон", working.read_text(encoding="utf-8"))
        self.assertNotEqual(immutable.read_bytes(), working.read_bytes())

    def test_existing_book_rule_has_priority_over_global_auto_during_prepare(self) -> None:
        self.import_book()
        PronunciationDictionary(self.root).upsert("Дилон", 2, "Дило́н")
        result = apply_book_stress(
            self.library,
            "stress-book",
            word="Дилон",
            vowel_number=1,
        )
        self.assertTrue(result["dictionary_conflict"])
        prepared = self.prepare()
        self.assertEqual(prepared["preparation_status"], "READY")
        execution = self.library.load_book_for_execution("stress-book")
        chapter_text = " ".join(
            segment["text"]
            for segment in execution["jobs"]["chapter-ch001"]["segments"]
        )
        self.assertIn("Ди́лон", chapter_text)
        self.assertNotIn("Дило́н", chapter_text)

    def test_known_homograph_choices_materialize_only_selected_occurrences(self) -> None:
        source = self.import_book()
        source_before = source.read_bytes()
        before = working_copy_status(self.library, "stress-book")
        first_start = before["text"].index("замок")
        first = apply_book_stress(
            self.library,
            "stress-book",
            word="замок",
            vowel_number=1,
            scope="OCCURRENCE",
            start=first_start,
            end=first_start + len("замок"),
            expected_sha256=before["working_copy_sha256"],
        )
        self.assertIn("старый за́мок", first["text"])
        self.assertIn("другой замок", first["text"])
        self.assertEqual(first["dictionary_entry"]["mode"], "REVIEW_REQUIRED")
        self.assertIsNone(first["dictionary_entry"]["preferred"])
        self.assertIn("Для этого места сохранено: за́мок", first["confirmation_message"])

        second_start = first["text"].rindex("замок")
        second = apply_book_stress(
            self.library,
            "stress-book",
            word="замок",
            vowel_number=2,
            scope="OCCURRENCE",
            start=second_start,
            end=second_start + len("замок"),
            expected_sha256=first["working_copy_sha256"],
        )
        self.assertIn("старый за́мок", second["text"])
        self.assertIn("другой замо́к", second["text"])
        current_entries = [
            entry for entry in second["pronunciation_entries"]
            if entry["scope"] == "OCCURRENCE"
        ]
        self.assertEqual(len(current_entries), 2)
        self.assertEqual(
            {entry["text_sha256"] for entry in current_entries},
            {second["working_copy_sha256"]},
        )
        self.assertEqual(source.read_bytes(), source_before)

        corrected_start = second["text"].index("за́мок")
        corrected = apply_book_stress(
            self.library,
            "stress-book",
            word="за́мок",
            vowel_number=2,
            scope="OCCURRENCE",
            start=corrected_start,
            end=corrected_start + len("за́мок"),
            expected_sha256=second["working_copy_sha256"],
        )
        self.assertIn("старый замо́к", corrected["text"])
        self.assertNotIn("старый за́мок", corrected["text"])
        self.assertEqual(corrected["pronunciation_entry"]["vowel_number"], 2)
        self.assertEqual(source.read_bytes(), source_before)

    def test_occurrence_requires_exact_sha_even_with_emoji_before_word(self) -> None:
        source = self.root / "emoji.txt"
        source.write_text("Глава 1.\n\n🔒 замок и замок.\n", encoding="utf-8")
        self.library.import_text_book(
            source_file=source, title="Emoji", author="Author", slug="emoji-book"
        )
        before = working_copy_status(self.library, "emoji-book")
        start = before["text"].index("замок")
        with self.assertRaises(TTSTextReviewError):
            apply_book_stress(
                self.library,
                "emoji-book",
                word="замок",
                vowel_number=2,
                scope="OCCURRENCE",
                start=start,
                end=start + len("замок"),
                expected_sha256="0" * 64,
            )
        result = apply_book_stress(
            self.library,
            "emoji-book",
            word="замок",
            vowel_number=2,
            scope="OCCURRENCE",
            start=start,
            end=start + len("замок"),
            expected_sha256=before["working_copy_sha256"],
        )
        self.assertIn("🔒 замо́к и замок", result["text"])

    def test_yandex_adapter_translates_human_stress_to_speechkit_markup(self) -> None:
        text = "Старый замо́к стоял на холме."
        self.assertEqual(yandex_text_markup(text), "Старый зам+ок стоял на холме.")
        self.assertEqual(yandex_text_markup("Старый за́мок."), "Старый з+амок.")
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
        self.assertIn("за́мок", openai_instruction_suffix("Старый за́мок."))
        contextual = openai_instruction_suffix("Старый за́мок. Дверной замо́к.")
        self.assertIn("сохраняй ударение по написанию в каждом месте", contextual)
        self.assertIn("«за́мок» / «замо́к»", contextual)
        self.assertNotIn("«замок» произноси как", contextual)
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
