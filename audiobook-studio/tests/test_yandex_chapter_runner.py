from __future__ import annotations

import contextlib
import io
import json
import unittest

from yandex_chapter_runner import main


class FakeService:
    def __init__(self) -> None:
        self.calls = []

    def prepare(self, **kwargs):
        self.calls.append(("prepare", kwargs))
        return {"decision": "READY_FOR_CONFIRMATION", "remote_request_sent": False}

    def revalidate(self, **kwargs):
        self.calls.append(("revalidate", kwargs))
        return {"decision": "READY_FOR_CONFIRMATION", "remote_request_sent": False}


class YandexChapterRunnerTests(unittest.TestCase):
    def test_prepare_delegates_offline_plan_only(self) -> None:
        service = FakeService()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([
                "--prepare", "--book", "book", "--job", "chapter-ch001",
                "--profile-id", "yandex_lera",
            ], service=service)
        self.assertEqual(code, 0)
        self.assertEqual(service.calls, [("prepare", {
            "book_id": "book", "job_id": "chapter-ch001", "profile_id": "yandex_lera",
        })])
        self.assertFalse(json.loads(output.getvalue())["remote_request_sent"])

    def test_revalidate_delegates_without_execute_surface(self) -> None:
        service = FakeService()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([
                "--revalidate", "--plan-id", "abc", "--plan-digest", "digest",
            ], service=service)
        self.assertEqual(code, 0)
        self.assertEqual(service.calls, [("revalidate", {"plan_id": "abc", "plan_digest": "digest"})])
        self.assertFalse(json.loads(output.getvalue())["remote_request_sent"])

    def test_prepare_requires_exact_selection(self) -> None:
        service = FakeService()
        with self.assertRaisesRegex(RuntimeError, "--profile-id"):
            main(["--prepare", "--book", "book", "--job", "chapter-ch001"], service=service)
        self.assertEqual(service.calls, [])

    def test_execute_flag_does_not_exist(self) -> None:
        service = FakeService()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["--execute", "--plan-id", "abc", "--plan-digest", "digest"], service=service)
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
