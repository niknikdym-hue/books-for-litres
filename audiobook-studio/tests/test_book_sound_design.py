from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from book_sound_design import (
    CATALOG,
    GARAGEBAND_CATALOG,
    GARAGEBAND_LICENSE,
    GARAGEBAND_LICENSE_SHA256,
    GARAGEBAND_SOURCE,
    GARAGEBAND_SOURCE_SHA256,
    SAMPLE_RATE,
    book_sound_status,
    chapter_cue_for_book,
    import_book_sound,
    set_book_sound,
    set_sound_favorite,
)


class BookSoundDesignTests(unittest.TestCase):
    def test_real_production_book_slug_is_accepted_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = book_sound_status(Path(directory), "hvatit-sebya-obestsenivat")
            self.assertEqual(status["book_slug"], "hvatit-sebya-obestsenivat")
            self.assertEqual(status["provider_requests"], 0)
            self.assertFalse(status["remote_request_sent"])

    def test_missing_garageband_library_is_safe_sound_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden")),
                mock.patch("book_sound_design._garageband_source", return_value=root / "not-installed.caf"),
            ):
                status = book_sound_status(root, "my-book")
            self.assertFalse(status["enabled"])
            self.assertEqual(status["options"], [])
            self.assertEqual(CATALOG, ())
            self.assertEqual(status["selected"]["origin"], "UNAVAILABLE")
            self.assertEqual(status["provider_requests"], 0)
            self.assertFalse(status["remote_request_sent"])
            self.assertEqual(status["model_calls"], 0)
            self.assertFalse(status["paid_execution"])
            self.assertFalse(status["billing_changed"])
    @unittest.skipUnless(
        GARAGEBAND_LICENSE.is_file()
        and all((Path("/Library/Audio/Apple Loops/Apple") / item["relative_source"]).is_file() for item in GARAGEBAND_CATALOG),
        "GarageBand catalog absent",
    )
    def test_curated_catalog_has_nine_distinct_licensed_options(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first = book_sound_status(Path(first_directory), "my-book")["options"]
            second = book_sound_status(Path(second_directory), "my-book")["options"]
            self.assertEqual(len(first), 9)
            self.assertEqual([item["sha256"] for item in first], [item["sha256"] for item in second])
            self.assertEqual(len({item["sha256"] for item in first}), 9)
            self.assertEqual(len({item["label"] for item in first}), 9)
            self.assertEqual(first[0]["label"], "Lounge Vibes 05 · любимый")
            for option in first:
                self.assertEqual(option["origin"], "APPLE_GARAGEBAND_DIGITAL_MATERIAL")
                self.assertEqual(option["rights"], "APPLE_LICENSED_AUDIO_PROJECT_USE")
                self.assertTrue(option["genres"])
                self.assertFalse(option["production_policy"]["raw_asset_export_allowed"])
                with wave.open(str(option["path"]), "rb") as source:
                    self.assertEqual(source.getframerate(), SAMPLE_RATE)
                    self.assertEqual(source.getnchannels(), 1)
                    self.assertEqual(source.getsampwidth(), 2)

    @unittest.skipUnless(GARAGEBAND_SOURCE.is_file() and GARAGEBAND_LICENSE.is_file(), "GarageBand assets absent")
    def test_choice_is_independent_per_book(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_id, second_id = (item["sound_id"] for item in GARAGEBAND_CATALOG[:2])
            first = set_book_sound(root, "first-book", enabled=True, sound_id=first_id, clip_start_seconds=1.2, clip_duration_seconds=2.4)
            second = set_book_sound(root, "second-book", enabled=True, sound_id=second_id, clip_start_seconds=0.4, clip_duration_seconds=1.8)
            self.assertEqual(first["sound_id"], first_id)
            self.assertEqual(second["sound_id"], second_id)
            self.assertEqual(first["selected"]["duration_seconds"], 2.4)
            self.assertEqual(second["selected"]["duration_seconds"], 1.8)
            self.assertEqual(chapter_cue_for_book(root, "first-book")["sound_id"], first_id)
            self.assertEqual(chapter_cue_for_book(root, "second-book")["sound_id"], second_id)

    @unittest.skipUnless(GARAGEBAND_SOURCE.is_file() and GARAGEBAND_LICENSE.is_file(), "GarageBand assets absent")
    def test_disabled_book_has_no_chapter_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_book_sound(root, "book", enabled=False, sound_id=GARAGEBAND_CATALOG[0]["sound_id"])
            self.assertIsNone(chapter_cue_for_book(root, "book"))

    @unittest.skipUnless(GARAGEBAND_SOURCE.is_file() and GARAGEBAND_LICENSE.is_file(), "GarageBand assets absent")
    def test_favorites_are_visible_and_persist_between_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_id = GARAGEBAND_CATALOG[0]["sound_id"]
            second_id = GARAGEBAND_CATALOG[1]["sound_id"]
            initial = book_sound_status(root, "book")
            self.assertTrue(next(item for item in initial["options"] if item["sound_id"] == first_id)["is_favorite"])
            set_sound_favorite(root, "book", sound_id=second_id, favorite=True)
            restarted = book_sound_status(root, "book")
            self.assertTrue(next(item for item in restarted["options"] if item["sound_id"] == second_id)["is_favorite"])
            removed = set_sound_favorite(root, "book", sound_id=first_id, favorite=False)
            self.assertFalse(next(item for item in removed["options"] if item["sound_id"] == first_id)["is_favorite"])
            self.assertEqual(removed["provider_requests"], 0)
            self.assertFalse(removed["remote_request_sent"])

    def test_custom_wav_is_copied_per_book_and_can_be_disabled_without_tts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "my-cue.wav"
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(44_100)
                output.writeframes(b"\x00\x00" * 44_100)
            with self.assertRaisesRegex(Exception, "Подтвердите"):
                import_book_sound(root, "my-book", source, label="Мой переход")
            imported = import_book_sound(
                root, "my-book", source, label="Мой переход", rights_confirmed=True
            )
            self.assertTrue(imported["enabled"])
            self.assertTrue(imported["sound_id"].startswith("custom-"))
            selected = imported["selected"]
            self.assertEqual(selected["label"], "Мой переход")
            self.assertEqual(selected["origin"], "USER_IMPORTED")
            self.assertEqual(selected["rights"], "USER_CONFIRMED_AUDIOBOOK_USE")
            self.assertTrue(selected["rights_provenance"]["confirmed"])
            self.assertEqual(selected["rights_provenance"]["source_sha256"], selected["sha256"])
            full_option = next(item for item in imported["options"] if item["sound_id"] == imported["sound_id"])
            self.assertEqual(selected["rights_provenance"]["imported_original_sha256"], full_option["sha256"])
            cue = chapter_cue_for_book(root, "my-book")
            self.assertEqual(cue["rights_provenance"]["verification_method"], "OWNER_ATTESTATION")
            self.assertFalse(cue["production_policy"]["raw_asset_export_allowed"])
            self.assertNotEqual(Path(selected["path"]), source)
            self.assertEqual(Path(full_option["path"]).read_bytes(), source.read_bytes())
            self.assertEqual(imported["provider_requests"], 0)
            self.assertFalse(imported["remote_request_sent"])
            disabled = set_book_sound(root, "my-book", enabled=False, sound_id=imported["sound_id"])
            self.assertFalse(disabled["enabled"])
            self.assertIsNone(chapter_cue_for_book(root, "my-book"))

    def test_custom_sound_rejects_non_wav(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unsafe.mp3"
            source.write_bytes(b"not audio")
            with self.assertRaisesRegex(Exception, "WAV"):
                import_book_sound(root, "my-book", source)

    @unittest.skipUnless(GARAGEBAND_SOURCE.is_file() and GARAGEBAND_LICENSE.is_file(), "GarageBand assets absent")
    def test_installed_garageband_loop_is_available_with_honest_rights(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = book_sound_status(root, "my-book")
            garageband = [
                item for item in status["options"]
                if item["origin"] == "APPLE_GARAGEBAND_DIGITAL_MATERIAL"
            ]
            self.assertEqual(len(garageband), 9)
            option = next(item for item in garageband if item["sound_id"] == GARAGEBAND_CATALOG[0]["sound_id"])
            self.assertEqual(option["source_sha256"], GARAGEBAND_SOURCE_SHA256)
            self.assertEqual(option["rights"], "APPLE_LICENSED_AUDIO_PROJECT_USE")
            self.assertNotEqual(option["rights"], "PROJECT_ORIGINAL_GENERATED_AUDIO")
            self.assertTrue(option["rights_provenance"]["verified"])
            self.assertFalse(option["rights_provenance"]["standalone_distribution"])
            self.assertFalse(option["production_policy"]["raw_asset_export_allowed"])
            self.assertEqual(status["garageband_discovery"]["requested_historical_asset"], "EXACT_SOURCE_NOT_FOUND")
            self.assertIn("не найден", status["garageband_discovery"]["message"])
            self.assertEqual(GARAGEBAND_SOURCE_SHA256, __import__("hashlib").sha256(GARAGEBAND_SOURCE.read_bytes()).hexdigest())
            self.assertEqual(GARAGEBAND_LICENSE_SHA256, __import__("hashlib").sha256(GARAGEBAND_LICENSE.read_bytes()).hexdigest())
            with wave.open(option["path"], "rb") as audio:
                self.assertEqual(audio.getframerate(), 48_000)
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
            selected = set_book_sound(root, "my-book", enabled=True, sound_id=option["sound_id"])
            self.assertEqual(selected["selected"]["source_sha256"], GARAGEBAND_SOURCE_SHA256)
            cue = chapter_cue_for_book(root, "my-book")
            self.assertEqual(cue["origin"], "APPLE_GARAGEBAND_DIGITAL_MATERIAL")
            self.assertEqual(cue["rights_provenance"]["license_sha256"], GARAGEBAND_LICENSE_SHA256)
            self.assertEqual(selected["provider_requests"], 0)
            self.assertFalse(selected["remote_request_sent"])
            original_source = __import__("book_sound_design")._garageband_source
            with mock.patch(
                "book_sound_design._garageband_source",
                side_effect=lambda item: root / "removed.caf"
                if item["sound_id"] == option["sound_id"] else original_source(item),
            ):
                with self.assertRaisesRegex(Exception, "больше недоступен"):
                    book_sound_status(root, "my-book")

    def test_garageband_source_with_symlink_component_is_never_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            source = real / "Lounge Vibes 05.caf"
            source.write_bytes(b"not a real loop")
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with mock.patch("book_sound_design._garageband_source", return_value=alias / source.name):
                status = book_sound_status(root / "workspace", "my-book")
            self.assertFalse(status["garageband_discovery"]["available"])
            self.assertFalse(any(
                item["origin"] == "APPLE_GARAGEBAND_DIGITAL_MATERIAL"
                for item in status["options"]
            ))


if __name__ == "__main__":
    unittest.main()
