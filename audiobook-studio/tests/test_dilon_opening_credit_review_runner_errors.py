from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dilon_opening_credit_review_runner as runner


class DilonOpeningCreditReviewRunnerErrorTests(unittest.TestCase):
    def test_missing_candidate_arguments_return_machine_readable_offline_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with mock.patch.object(
                runner,
                "load_workspace_paths",
                return_value=SimpleNamespace(root=Path(directory)),
            ), contextlib.redirect_stdout(output):
                code = runner.main([
                    "--candidate-status",
                    "--book", "demo-book",
                    "--job", "chapter-ch001",
                ])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["decision"], "INVALID_REQUEST")
        self.assertEqual(payload["blockers"], ["invalid_request"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])


if __name__ == "__main__":
    unittest.main()
