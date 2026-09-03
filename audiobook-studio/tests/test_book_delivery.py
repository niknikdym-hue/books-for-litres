from __future__ import annotations

import base64
import json
import struct
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_qa_review import path_identity, sha256_file
from backends.common import inspect_pcm_wav
from book_delivery import BookDeliveryError, BookDeliveryService, DELIVERY_PROFILES
from mastering_export import MasteringExportError
from media_tools import resolve_ffmpeg


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class BookDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = (Path(self.temporary.name) / "workspace").resolve()
        self.workspace.mkdir()
        (self.workspace / "exports").mkdir()
        (self.workspace / "masters").mkdir()
        self.service = BookDeliveryService(
            workspace_root=self.workspace,
            exports_root=self.workspace / "exports",
            masters_root=self.workspace / "masters",
        )
        self.book_slug = "demo-book"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _fixture(self):
        audio = self.workspace / "fixture" / "chapter.wav"
        audio.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(b"".join(struct.pack("<h", 900 if index % 2 else -900) for index in range(4_800)))
        cover = self.workspace / "fixture" / "cover.png"
        cover.write_bytes(PNG_1X1)
        book = {
            "slug": self.book_slug,
            "title": "Демонстрационная книга",
            "author": "Автор",
            "cover": {"path": str(cover), "sha256": sha256_file(cover)},
        }
        chapter = {
            "position": 1,
            "job_id": "chapter-ch001",
            "chapter_id": "ch001",
            "title": "Глава 1",
            "master_identity": "a" * 64,
            "master_manifest_sha256": "b" * 64,
            "audio_path": str(audio),
            "audio_sha256": sha256_file(audio),
            "path_identity": path_identity(audio),
            "wav": inspect_pcm_wav(audio).to_dict(),
        }
        release = {
            "status": "RELEASE_READY",
            "whole_book": {"ready": True, "expected_chapters": 1, "ready_chapters": 1, "blockers": []},
        }
        return book, [chapter], release

    def test_no_default_and_selection_is_isolated_per_book(self) -> None:
        first = self.service.selection_status("first-book")
        second = self.service.selection_status("second-book")
        self.assertIsNone(first["selected_profile_id"])
        self.assertEqual(first["decision"], "SELECTION_REQUIRED")
        self.assertIsNone(second["selected_profile_id"])

        self.service.set_selected_profile("first-book", "m4b")
        restarted = BookDeliveryService(
            workspace_root=self.workspace,
            exports_root=self.workspace / "exports",
            masters_root=self.workspace / "masters",
        )
        self.assertEqual(restarted.selected_profile("first-book"), "m4b")
        self.assertIsNone(restarted.selected_profile("second-book"))
        with self.assertRaises(BookDeliveryError):
            restarted.set_selected_profile("first-book", "unknown")

    def test_user_facing_profile_copy_has_no_vendor_name(self) -> None:
        self.assertEqual([item["id"] for item in DELIVERY_PROFILES], ["chapters", "m4b", "mp3", "hq_archive"])
        visible = json.dumps([
            {key: item.get(key) for key in ("title", "description", "detail")}
            for item in DELIVERY_PROFILES
        ], ensure_ascii=False)
        self.assertNotIn("ЛитРес", visible)
        self.assertIn("По главам", visible)
        self.assertIn("Одним файлом M4B", visible)
        self.assertIn("Одним файлом MP3", visible)
        self.assertIn("Архив высокого качества", visible)

    def test_whole_book_formats_block_until_complete_but_chapters_can_progress(self) -> None:
        incomplete = {
            "status": "INCOMPLETE",
            "whole_book": {"ready": False, "expected_chapters": 16, "ready_chapters": 1, "blockers": ["missing_chapters"]},
        }
        self.service.set_selected_profile(self.book_slug, "m4b")
        status = self.service.status(self.book_slug, incomplete)
        self.assertEqual(status["decision"], "BOOK_INCOMPLETE")
        self.assertEqual((status["ready_chapters"], status["expected_chapters"]), (1, 16))
        self.service.set_selected_profile(self.book_slug, "chapters")
        self.assertEqual(self.service.status(self.book_slug, incomplete)["decision"], "CHAPTERS_SELECTED")

    def test_atomic_m4b_publication_and_restart_status_are_offline(self) -> None:
        book, chapters, release = self._fixture()
        self.service.set_selected_profile(self.book_slug, "m4b")

        def encode(**kwargs):
            kwargs["output"].write_bytes(b"fake-m4b")
            return ({"streams": [{"codec_type": "audio"}], "chapters": [{}]}, {"name": "fake-ffmpeg"})

        with mock.patch.object(self.service, "_validated_release", return_value=(book, chapters)), \
             mock.patch.object(self.service, "_encode_audio", side_effect=encode):
            result = self.service.export(self.book_slug, release)
        self.assertEqual(result["decision"], "ALREADY_EXPORTED")
        delivery = result["delivery"]
        self.assertEqual(delivery["profile_id"], "m4b")
        self.assertTrue(Path(delivery["output"]["path"]).is_file())
        self.assertEqual(delivery["provider_requests"], 0)
        self.assertFalse(delivery["remote_request_sent"])
        self.assertFalse(delivery["paid_execution"])
        self.assertFalse(delivery["billing_changed"])

    def test_status_never_reports_old_delivery_for_changed_current_release(self) -> None:
        book, chapters, release = self._fixture()
        self.service.set_selected_profile(self.book_slug, "m4b")

        def encode(**kwargs):
            kwargs["output"].write_bytes(b"fake-m4b")
            return ({"streams": [{"codec_type": "audio"}], "chapters": [{}]}, {"name": "fake-ffmpeg"})

        with mock.patch.object(self.service, "_validated_release", return_value=(book, chapters)), \
             mock.patch.object(self.service, "_encode_audio", side_effect=encode):
            exported = self.service.export(self.book_slug, release)
        old_identity = exported["delivery"]["delivery_identity"]

        changed_chapters = json.loads(json.dumps(chapters))
        changed_chapters[0]["master_identity"] = "c" * 64
        restarted = BookDeliveryService(
            workspace_root=self.workspace,
            exports_root=self.workspace / "exports",
            masters_root=self.workspace / "masters",
        )
        with mock.patch.object(
            restarted, "_validated_release", return_value=(book, changed_chapters)
        ):
            status = restarted.status(self.book_slug, release)

        self.assertNotEqual(
            old_identity,
            restarted._identity("m4b", book, changed_chapters),
        )
        self.assertEqual(status["decision"], "READY_TO_EXPORT")
        self.assertIsNone(status["delivery"])
        self.assertEqual(status["provider_requests"], 0)
        self.assertFalse(status["remote_request_sent"])

    def test_status_hides_old_delivery_when_current_master_is_missing(self) -> None:
        book, chapters, release = self._fixture()
        self.service.set_selected_profile(self.book_slug, "m4b")

        def encode(**kwargs):
            kwargs["output"].write_bytes(b"old-intact-m4b")
            return ({"streams": [{"codec_type": "audio"}], "chapters": [{}]}, {"name": "fake-ffmpeg"})

        with mock.patch.object(self.service, "_validated_release", return_value=(book, chapters)), \
             mock.patch.object(self.service, "_encode_audio", side_effect=encode):
            exported = self.service.export(self.book_slug, release)
        delivery_output = Path(exported["delivery"]["output"]["path"])
        Path(chapters[0]["audio_path"]).unlink()

        def validate_after_master_removed(_release):
            if not Path(chapters[0]["audio_path"]).is_file():
                raise MasteringExportError(
                    "master_identity_mismatch", "Точная identity master не подтверждена."
                )
            return book, chapters

        restarted = BookDeliveryService(
            workspace_root=self.workspace,
            exports_root=self.workspace / "exports",
            masters_root=self.workspace / "masters",
        )
        with mock.patch.object(restarted, "_validated_release", side_effect=validate_after_master_removed):
            status = restarted.status(self.book_slug, release)

        self.assertTrue(delivery_output.is_file(), "The historical delivery itself remains intact.")
        self.assertEqual(status["decision"], "BOOK_INCOMPLETE")
        self.assertFalse(status["book_ready"])
        self.assertIn("master_identity_mismatch", status["blockers"])
        self.assertIsNone(status["delivery"])
        self.assertEqual(status["provider_requests"], 0)
        self.assertFalse(status["remote_request_sent"])

    def test_high_quality_archive_contains_exact_master_and_book_index(self) -> None:
        book, chapters, release = self._fixture()
        self.service.set_selected_profile(self.book_slug, "hq_archive")
        with mock.patch.object(self.service, "_validated_release", return_value=(book, chapters)):
            result = self.service.export(self.book_slug, release)
        output = Path(result["delivery"]["output"]["path"])
        with zipfile.ZipFile(output, "r") as archive:
            names = archive.namelist()
            self.assertIn("book.json", names)
            self.assertIn("cover.png", names)
            wav_name = next(name for name in names if name.startswith("chapters/") and name.endswith(".wav"))
            self.assertEqual(archive.read(wav_name), Path(chapters[0]["audio_path"]).read_bytes())

    def test_real_m4b_and_mp3_are_decodable_and_keep_chapter_metadata(self) -> None:
        if not resolve_ffmpeg(self.workspace).available:
            self.skipTest("Real media integration requires an installed FFmpeg toolchain.")
        book, chapters, release = self._fixture()
        for profile_id in ("m4b", "mp3"):
            with self.subTest(profile_id=profile_id):
                self.service.set_selected_profile(self.book_slug, profile_id)
                with mock.patch.object(self.service, "_validated_release", return_value=(book, chapters)):
                    result = self.service.export(self.book_slug, release)
                artifact = result["delivery"]
                self.assertEqual(artifact["profile_id"], profile_id)
                self.assertTrue(Path(artifact["output"]["path"]).is_file())
                self.assertEqual(len(artifact["verification"].get("chapters") or []), 1)
                self.assertEqual(artifact["provider_requests"], 0)
                self.assertFalse(artifact["remote_request_sent"])


if __name__ == "__main__":
    unittest.main()
