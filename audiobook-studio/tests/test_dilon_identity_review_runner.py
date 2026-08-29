from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import dilon_identity_review_runner as runner
from dilon_identity_review import DilonIdentityReviewError


class DilonIdentityReviewRunnerTests(unittest.TestCase):
    @staticmethod
    def base_args(mode: str) -> list[str]:
        return [mode, "--book", "demo-book", "--job", "chapter-ch001"]

    def test_status_is_machine_readable_and_offline(self) -> None:
        payload = {
            "schema_version": 1,
            "state": "PENDING_HUMAN_REVIEW",
            "decision": "HUMAN_LISTENING_REQUIRED",
            "identity_accepted": False,
            "human_listening_required": True,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
            "whole_book_release_ready": False,
        }
        output = io.StringIO()
        with mock.patch.object(runner, "identity_review_status", return_value=payload):
            with redirect_stdout(output):
                code = runner.main(self.base_args("--status"))
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["whole_book_release_ready"])

    def test_approve_requires_all_listened_identity_fields(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = runner.main(self.base_args("--approve"))
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["provider_requests"], 0)
        self.assertTrue(result["human_listening_required"])

    def test_approve_forwards_exact_listened_identity(self) -> None:
        payload = {
            "schema_version": 1,
            "state": "APPROVED",
            "decision": "IDENTITY_REVIEW_COMPLETE",
            "identity_accepted": True,
            "human_listening_required": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
            "whole_book_release_ready": False,
        }
        args = self.base_args("--approve") + [
            "--listened-build-identity", "a" * 64,
            "--listened-audio-sha256", "b" * 64,
            "--listened-path-identity", "c" * 64,
        ]
        output = io.StringIO()
        with mock.patch.object(runner, "approve_current_identity", return_value=payload) as approve:
            with redirect_stdout(output):
                code = runner.main(args)
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["identity_accepted"])
        self.assertEqual(approve.call_args.kwargs["listened_build_identity"], "a" * 64)
        self.assertEqual(approve.call_args.kwargs["listened_audio_sha256"], "b" * 64)
        self.assertEqual(approve.call_args.kwargs["listened_path_identity"], "c" * 64)

    def test_stale_review_error_reports_no_provider_activity(self) -> None:
        error = DilonIdentityReviewError("identity_review_stale", "stale")
        output = io.StringIO()
        with mock.patch.object(runner, "identity_review_status", side_effect=error):
            with redirect_stdout(output):
                code = runner.main(self.base_args("--status"))
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["blockers"], ["identity_review_stale"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["paid_execution"])


if __name__ == "__main__":
    unittest.main()
