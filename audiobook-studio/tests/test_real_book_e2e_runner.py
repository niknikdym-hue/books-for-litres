from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import real_book_e2e_runner as runner


class RealBookE2ERunnerTests(unittest.TestCase):
    def test_ready_returns_zero_and_machine_readable_go_gate(self) -> None:
        payload = {
            "state": "READY",
            "decision": "READY_FOR_PRODUCTION_APP_ACCEPTANCE",
            "whole_book_release_ready": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        output = io.StringIO()
        with mock.patch.object(runner, "real_book_e2e_preflight", return_value=payload) as preflight:
            with redirect_stdout(output):
                code = runner.main(["--preflight"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["decision"], "READY_FOR_PRODUCTION_APP_ACCEPTANCE")
        self.assertFalse(result["whole_book_release_ready"])
        self.assertEqual(preflight.call_args.kwargs["book_name"], runner.CANONICAL_BOOK)
        self.assertEqual(preflight.call_args.kwargs["job_id"], runner.CANONICAL_JOB)
        self.assertEqual(preflight.call_args.kwargs["profile_id"], runner.CANONICAL_PROFILE)

    def test_blocked_returns_two_without_mutation_or_false_ready(self) -> None:
        payload = {
            "state": "BLOCKED",
            "decision": "REMAINING_LAUNCH_GATES",
            "blockers": ["dilon_identity_human_listening_required"],
            "whole_book_release_ready": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        output = io.StringIO()
        with mock.patch.object(runner, "real_book_e2e_preflight", return_value=payload):
            with redirect_stdout(output):
                code = runner.main(["--preflight"])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["blockers"], ["dilon_identity_human_listening_required"])
        self.assertFalse(result["whole_book_release_ready"])

    def test_custom_selection_is_forwarded_but_canonical_contract_can_block_it(self) -> None:
        payload = {"state": "BLOCKED", "decision": "REMAINING_LAUNCH_GATES"}
        with mock.patch.object(runner, "real_book_e2e_preflight", return_value=payload) as preflight:
            code = runner.main([
                "--preflight",
                "--book", "other-book",
                "--job", "chapter-x",
                "--profile-id", "yandex_lera",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(preflight.call_args.kwargs["book_name"], "other-book")
        self.assertEqual(preflight.call_args.kwargs["job_id"], "chapter-x")


if __name__ == "__main__":
    unittest.main()
