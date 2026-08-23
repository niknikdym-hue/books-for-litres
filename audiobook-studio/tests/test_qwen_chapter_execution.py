from __future__ import annotations

import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

from backends.common import inspect_pcm_wav
from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from qwen_chapter_execution import QwenChapterExecutionError, QwenChapterExecutionService
from qwen_chapter_manifest import QwenChapterManifestService


def write_wav(path: Path, *, frames: int = 240) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x01\x00" * frames)


class QwenChapterExecutionTests(unittest.TestCase):
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
        BookTextPreparationService(self.library).prepare("book")
        self.manifest = QwenChapterManifestService(library=self.library, output_root=self.root / "renders")
        self.identity = {
            "model": "qwen",
            "generation": {"temperature": 0.7},
            "instruct": "read",
            "base_seed": 10,
        }
        self.calls: list[tuple[str, int]] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def service(self, *, fail_on: str | None = None) -> QwenChapterExecutionService:
        def synthesize_segment(*, text: str, output_path: Path, seed: int, segment_id: str) -> None:
            self.calls.append((segment_id, seed))
            if segment_id == fail_on:
                raise RuntimeError("synthesis failed")
            write_wav(output_path)
        return QwenChapterExecutionService(
            library=self.library,
            manifest=self.manifest,
            synthesize_segment=synthesize_segment,
        )

    def run_service(self, service: QwenChapterExecutionService):
        return service.run(
            book_id="book",
            job_id="chapter-ch001",
            profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )

    def test_run_generates_each_pending_segment_once_and_stops_before_qa_assembly(self) -> None:
        result = self.run_service(self.service())
        self.assertTrue(result["complete"])
        self.assertEqual(result["generated_segments"], result["segment_count"])
        self.assertEqual(len(self.calls), result["segment_count"])
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["chapter_assembly_performed"])
        self.assertEqual(result["next_gate"], "AUTOMATIC_QA")
        self.assertNotIn("output_path", result)
        self.assertFalse((self.root / "chapter.wav").exists())
        segment_wavs = list((Path(result["segment_job_dir"]) / "segments").glob("*.wav"))
        self.assertEqual(len(segment_wavs), result["segment_count"])
        self.assertTrue(all(inspect_pcm_wav(path).duration_seconds > 0 for path in segment_wavs))

    def test_concurrent_live_runs_are_serialized_and_never_duplicate_segments(self) -> None:
        activity_lock = threading.Lock()
        active = 0
        max_active = 0
        calls: list[str] = []
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def synthesize_segment(*, text: str, output_path: Path, seed: int, segment_id: str) -> None:
            nonlocal active, max_active
            with activity_lock:
                active += 1
                max_active = max(max_active, active)
                calls.append(segment_id)
            try:
                time.sleep(0.05)
                write_wav(output_path)
            finally:
                with activity_lock:
                    active -= 1

        services = [
            QwenChapterExecutionService(
                library=self.library,
                manifest=self.manifest,
                synthesize_segment=synthesize_segment,
            ),
            QwenChapterExecutionService(
                library=self.library,
                manifest=self.manifest,
                synthesize_segment=synthesize_segment,
            ),
        ]

        def run(service: QwenChapterExecutionService) -> None:
            try:
                results.append(self.run_service(service))
            except BaseException as error:  # capture thread failures for main assertions
                errors.append(error)

        threads = [threading.Thread(target=run, args=(service,)) for service in services]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(max_active, 1)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(sum(int(result["generated_segments"]) for result in results), len(calls))
        self.assertTrue(all(result["complete"] for result in results))

    def test_resume_skips_already_done_segments(self) -> None:
        self.manifest.prepare(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        claim = self.manifest.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        write_wav(Path(claim["output_path"]))
        self.manifest.complete(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity, segment_id=claim["id"],
        )
        result = self.run_service(self.service())
        self.assertEqual(result["generated_segments"], result["segment_count"] - 1)

    def test_failed_segment_stops_and_requires_explicit_retry(self) -> None:
        self.manifest.prepare(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        first = self.manifest.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.manifest.fail(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity, segment_id=first["id"], error="old failure",
        )
        with self.assertRaisesRegex(QwenChapterExecutionError, "explicit retry"):
            self.run_service(self.service())
        self.assertEqual(self.calls, [])

    def test_synthesis_failure_is_persisted_and_not_auto_retried(self) -> None:
        self.manifest.prepare(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        claim = self.manifest.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.manifest.recover_after_restart(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        with self.assertRaisesRegex(RuntimeError, "synthesis failed"):
            self.run_service(self.service(fail_on=claim["id"]))
        status = self.manifest.status(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        self.assertEqual(status["counts"]["FAILED"], 1)
        calls_after_failure = list(self.calls)
        with self.assertRaisesRegex(QwenChapterExecutionError, "explicit retry"):
            self.run_service(self.service())
        self.assertEqual(self.calls, calls_after_failure)

    def test_restart_recovers_valid_running_wav_without_regeneration(self) -> None:
        self.manifest.prepare(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        claim = self.manifest.claim_next(
            book_id="book", job_id="chapter-ch001", profile_id="qwen_vivian",
            synthesis_identity=self.identity,
        )
        write_wav(Path(claim["output_path"]))
        result = self.run_service(self.service())
        self.assertEqual(result["generated_segments"], result["segment_count"] - 1)
        self.assertNotIn(claim["id"], [segment_id for segment_id, _ in self.calls])


if __name__ == "__main__":
    unittest.main()
