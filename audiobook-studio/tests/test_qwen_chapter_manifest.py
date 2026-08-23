from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from qwen_chapter_manifest import QwenChapterManifestError, QwenChapterManifestService


def write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x00" * 240)


class QwenChapterManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        books = self.root / "books"
        books.mkdir()
        source = self.root / "source.txt"
        source.write_text(
            "Глава 1. Начало\n\nПервое. Второе.\n\nГлава 2. Далее\n\nТретье. Четвёрто.\n",
            encoding="utf-8",
        )
        self.library = BookLibrary(books)
        self.library.import_text_book(source_file=source, title="Книга", author="Автор", slug="book")
        self.preparation = BookTextPreparationService(
            self.library,
            now=lambda: "2026-08-23T12:00:00+00:00",
        )
        self.preparation.prepare("book")
        self.service = QwenChapterManifestService(
            library=self.library,
            output_root=self.root / "renders",
        )
        self.identity = {
            "model": "qwen",
            "generation": {"temperature": 0.7},
            "instruct": "read",
            "base_seed": 10,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prepare(self):
        return self.service.prepare(
            book_id="book",
            job_id="chapter-ch001",
            profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )

    def test_prepare_creates_persistent_pending_manifest_without_network(self) -> None:
        status = self.prepare()
        self.assertGreater(status["segment_count"], 0)
        self.assertEqual(status["counts"]["PENDING"], status["segment_count"])
        self.assertFalse(status["remote_request_sent"])
        self.assertTrue((Path(status["job_dir"]) / "MANIFEST.json").is_file())

    def test_claim_marks_one_segment_running(self) -> None:
        self.prepare()
        claim = self.service.claim_next(
            book_id="book",
            job_id="chapter-ch001",
            profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(claim["state"], "RUNNING")
        status = self.service.status(
            book_id="book",
            job_id="chapter-ch001",
            profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(status["counts"]["RUNNING"], 1)

    def test_running_missing_wav_recovers_to_pending_after_restart(self) -> None:
        self.prepare()
        self.service.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        status = self.service.recover_after_restart(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(status["counts"]["RUNNING"], 0)
        self.assertEqual(status["counts"]["PENDING"], status["segment_count"])

    def test_running_valid_wav_recovers_to_done(self) -> None:
        self.prepare()
        claim = self.service.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        write_wav(Path(claim["output_path"]))
        status = self.service.recover_after_restart(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(status["counts"]["DONE"], 1)

    def test_done_missing_wav_returns_to_pending(self) -> None:
        self.prepare()
        claim = self.service.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        write_wav(Path(claim["output_path"]))
        self.service.complete(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity, segment_id=claim["id"],
        )
        Path(claim["output_path"]).unlink()
        status = self.service.status(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(status["counts"]["DONE"], 0)
        self.assertEqual(status["counts"]["PENDING"], status["segment_count"])

    def test_failed_requires_explicit_retry(self) -> None:
        self.prepare()
        claim = self.service.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        status = self.service.fail(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity, segment_id=claim["id"], error="boom",
        )
        self.assertEqual(status["counts"]["FAILED"], 1)
        status = self.service.status(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(status["counts"]["FAILED"], 1)
        retried = self.service.retry_failed(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity, segment_id=claim["id"],
        )
        self.assertEqual(retried["counts"]["FAILED"], 0)

    def test_reprepare_archives_old_manifest_and_changes_identity(self) -> None:
        before = self.prepare()
        working = self.root / "books/book/tts/working.txt"
        working.write_text(
            working.read_text(encoding="utf-8").replace("Первое.", "Изменённое."),
            encoding="utf-8",
        )
        self.preparation.prepare("book")
        after = self.prepare()
        self.assertNotEqual(before["production_identity"], after["production_identity"])
        history = list((Path(after["job_dir"]) / "history").glob("MANIFEST__*.json"))
        self.assertEqual(len(history), 1)

    def test_config_change_invalidates_status_until_explicit_prepare(self) -> None:
        self.prepare()
        changed = {**self.identity, "model": "qwen-v2"}
        with self.assertRaisesRegex(QwenChapterManifestError, "invalidated"):
            self.service.status(
                book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
                synthesis_identity=changed,
            )
        after = self.service.prepare(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=changed,
        )
        self.assertTrue(after["production_identity"])


if __name__ == "__main__":
    unittest.main()
