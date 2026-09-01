from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from book_sound_design import (
    CATALOG,
    SAMPLE_RATE,
    book_sound_status,
    chapter_cue_for_book,
    set_book_sound,
)


class BookSoundDesignTests(unittest.TestCase):
    def test_catalog_has_five_local_original_options_and_defaults_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = book_sound_status(root, "my-book")
            self.assertFalse(status["enabled"])
            self.assertEqual(len(status["options"]), 5)
            self.assertEqual(len(CATALOG), 5)
            self.assertEqual(status["provider_requests"], 0)
            self.assertFalse(status["remote_request_sent"])
            self.assertEqual(status["model_calls"], 0)
            self.assertFalse(status["paid_execution"])
            self.assertFalse(status["billing_changed"])
            for option in status["options"]:
                self.assertEqual(option["origin"], "STUDIO_GENERATED")
                self.assertEqual(option["rights"], "PROJECT_ORIGINAL_GENERATED_AUDIO")
                path = Path(option["path"])
                self.assertTrue(path.is_file())
                with wave.open(str(path), "rb") as source:
                    self.assertEqual(source.getframerate(), SAMPLE_RATE)
                    self.assertEqual(source.getnchannels(), 1)
                    self.assertEqual(source.getsampwidth(), 2)

    def test_choice_is_independent_per_book(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = set_book_sound(root, "first-book", enabled=True, sound_id="soft-bell")
            second = set_book_sound(root, "second-book", enabled=True, sound_id="glass-note")
            self.assertEqual(first["sound_id"], "soft-bell")
            self.assertEqual(second["sound_id"], "glass-note")
            self.assertEqual(chapter_cue_for_book(root, "first-book")["sound_id"], "soft-bell")
            self.assertEqual(chapter_cue_for_book(root, "second-book")["sound_id"], "glass-note")

    def test_disabled_book_has_no_chapter_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_book_sound(root, "book", enabled=False, sound_id="minimal-chime")
            self.assertIsNone(chapter_cue_for_book(root, "book"))


if __name__ == "__main__":
    unittest.main()
