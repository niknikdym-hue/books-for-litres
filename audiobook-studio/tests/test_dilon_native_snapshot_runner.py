from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dilon_native_snapshot_runner as runner


class DilonNativeSnapshotRunnerTests(unittest.TestCase):
    def test_missing_selection_is_machine_readable_and_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with mock.patch.object(
                runner,
                "load_workspace_paths",
                return_value=SimpleNamespace(root=Path(directory)),
            ), contextlib.redirect_stdout(output):
                code = runner.main(["--snapshot"])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["blockers"], ["invalid_request"])
        self.assertFalse(payload["whole_book_release_ready"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])

    def test_runner_has_no_provider_or_paid_execution_mode(self) -> None:
        parser = runner.build_parser()
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertEqual(
            {"--snapshot", "--book", "--job"}.issubset(option_strings),
            True,
        )
        self.assertNotIn("--execute", option_strings)
        self.assertNotIn("--provider", option_strings)
        self.assertNotIn("--paid", option_strings)
        self.assertNotIn("--approve", option_strings)

    def test_main_preserves_offline_snapshot_contract(self) -> None:
        payload = {
            "schema_version": 1,
            "state": "READY",
            "decision": "DISPLAY_CURRENT_DILON_STATE",
            "book_slug": "demo-book",
            "job_id": "chapter-ch001",
            "dilon_status": {"state": "BLOCKED"},
            "review_candidates": [],
            "capabilities": {
                "provider_execution_available": False,
                "paid_execution_available": False,
            },
            "whole_book_release_ready": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        output = io.StringIO()
        with mock.patch.object(
            runner,
            "snapshot_for_selection",
            return_value=payload,
        ) as snapshot, contextlib.redirect_stdout(output):
            code = runner.main([
                "--snapshot",
                "--book", "demo-book",
                "--job", "chapter-ch001",
            ])
        snapshot.assert_called_once_with(
            book_name="demo-book",
            job_id="chapter-ch001",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), payload)


if __name__ == "__main__":
    unittest.main()
