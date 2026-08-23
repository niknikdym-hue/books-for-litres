from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qwen_chapter_runner import _profile_id, main


class FakeManifest:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = []

    def _job_dir(self, book, job, profile):
        return self.root / book / job / profile

    def prepare(self, **kwargs):
        self.calls.append(("prepare", kwargs))
        return {"complete": False, "remote_request_sent": False}

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return {"complete": False, "remote_request_sent": False}

    def retry_failed(self, **kwargs):
        self.calls.append(("retry", kwargs))
        return {"complete": False, "remote_request_sent": False}


class FakeExecution:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def run(self, **kwargs):
        FakeExecution.last_run = kwargs
        return {"complete": True, "remote_request_sent": False}


class QwenChapterRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library = object()
        self.studio = SimpleNamespace(BOOK_LIBRARY=self.library)
        self.cfg = {"output_root": str(self.root / "renders")}
        self.book_payload = {"title": "Book"}
        self.identity = {
            "model": "model",
            "speaker": "Vivian",
            "language": "ru",
            "instruct": "read",
            "generation": {},
            "pronunciation_overrides": {},
            "base_seed": 10,
        }
        self.manifest = FakeManifest(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def runtime(self, book, job, speaker):
        return self.studio, self.cfg, self.book_payload, "book.json", dict(self.identity)

    def test_profile_id_is_stable(self):
        self.assertEqual(_profile_id("Vivian"), "qwen_vivian")
        self.assertEqual(_profile_id("Uncle_Fu"), "qwen_uncle_fu")

    def test_prepare_is_manifest_only(self):
        output = io.StringIO()
        with patch("qwen_chapter_runner._manifest_service", return_value=self.manifest):
            with contextlib.redirect_stdout(output):
                code = main(["--prepare", "--book", "book", "--job", "chapter-ch001", "--speaker", "Vivian"], runtime_factory=self.runtime)
        self.assertEqual(code, 0)
        self.assertEqual(self.manifest.calls[0][0], "prepare")
        self.assertFalse(json.loads(output.getvalue())["remote_request_sent"])

    def test_status_does_not_build_execution(self):
        output = io.StringIO()
        with patch("qwen_chapter_runner._manifest_service", return_value=self.manifest):
            with patch("qwen_chapter_runner.QwenChapterExecutionService", side_effect=AssertionError("must not build")):
                with contextlib.redirect_stdout(output):
                    main(["--status", "--book", "book", "--job", "chapter-ch001", "--speaker", "Vivian"], runtime_factory=self.runtime)
        self.assertEqual(self.manifest.calls[0][0], "status")

    def test_retry_requires_exact_segment_and_is_explicit(self):
        with patch("qwen_chapter_runner._manifest_service", return_value=self.manifest):
            with self.assertRaisesRegex(RuntimeError, "--segment-id"):
                main(["--retry-failed", "--book", "book", "--job", "chapter-ch001", "--speaker", "Vivian"], runtime_factory=self.runtime)
        self.assertEqual(self.manifest.calls, [])

    def test_run_is_separate_explicit_mode(self):
        output = io.StringIO()
        with patch("qwen_chapter_runner._manifest_service", return_value=self.manifest):
            with patch("qwen_chapter_runner._build_synthesizer", return_value=lambda **_: None):
                with patch("qwen_chapter_runner.QwenChapterExecutionService", FakeExecution):
                    with contextlib.redirect_stdout(output):
                        code = main(["--run", "--book", "book", "--job", "chapter-ch001", "--speaker", "Vivian"], runtime_factory=self.runtime)
        self.assertEqual(code, 0)
        self.assertEqual(FakeExecution.last_run["book_id"], "book")
        self.assertEqual(FakeExecution.last_run["profile_id"], "qwen_vivian")
        self.assertFalse(json.loads(output.getvalue())["remote_request_sent"])


if __name__ == "__main__":
    unittest.main()
