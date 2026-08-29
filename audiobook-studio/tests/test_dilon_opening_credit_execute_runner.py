from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import dilon_opening_credit_execute_runner as runner
from dilon_opening_credit_execute import OpeningCreditExecutionError


class OpeningCreditExecuteRunnerTests(unittest.TestCase):
    def arguments(self, *, authorized: bool = False) -> list[str]:
        result = [
            "--execute-authorized",
            "--book", "demo-book",
            "--job", "chapter-ch001",
            "--plan-id", "a" * 64,
            "--plan-digest", "b" * 64,
        ]
        if authorized:
            result.append("--owner-authorized")
        return result

    def test_missing_owner_authorization_is_forwarded_fail_closed(self) -> None:
        error = OpeningCreditExecutionError("owner_authorization_required", "owner required")
        output = io.StringIO()
        with mock.patch.object(runner, "execute_from_current_runtime", side_effect=error) as execute:
            with redirect_stdout(output):
                code = runner.main(self.arguments(authorized=False))
        self.assertEqual(code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["blockers"], ["owner_authorization_required"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["whole_book_release_ready"])
        self.assertFalse(execute.call_args.kwargs["owner_authorized"])

    def test_authorized_success_remains_pending_human_review(self) -> None:
        success = {
            "schema_version": 1,
            "state": "PENDING_HUMAN_REVIEW",
            "decision": "HUMAN_LISTENING_REQUIRED",
            "provider_requests": 1,
            "remote_request_sent": True,
            "paid_execution": True,
            "billing_changed": True,
            "manual_approval_published": False,
            "whole_book_release_ready": False,
        }
        output = io.StringIO()
        with mock.patch.object(runner, "execute_from_current_runtime", return_value=success) as execute:
            with redirect_stdout(output):
                code = runner.main(self.arguments(authorized=True))
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["state"], "PENDING_HUMAN_REVIEW")
        self.assertFalse(payload["manual_approval_published"])
        self.assertFalse(payload["whole_book_release_ready"])
        self.assertTrue(execute.call_args.kwargs["owner_authorized"])

    def test_ambiguous_error_reports_no_retry_and_unknown_billing(self) -> None:
        error = OpeningCreditExecutionError(
            "provider_result_ambiguous",
            "ambiguous",
            provider_requests=1,
            remote_request_sent=True,
            paid_execution=True,
            billing_changed=None,
            retry_allowed=False,
        )
        output = io.StringIO()
        with mock.patch.object(runner, "execute_from_current_runtime", side_effect=error):
            with redirect_stdout(output):
                code = runner.main(self.arguments(authorized=True))
        self.assertEqual(code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["provider_requests"], 1)
        self.assertTrue(payload["remote_request_sent"])
        self.assertIsNone(payload["billing_changed"])
        self.assertFalse(payload["retry_allowed"])


if __name__ == "__main__":
    unittest.main()
