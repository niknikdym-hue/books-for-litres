from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dilon_identity_bridge_cli as cli
from backends.yandex_speechkit import YandexSpeechKitBackend


class DilonIdentityBridgeCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.env = dict(os.environ, AUDIOBOOK_STUDIO_HOME=str(self.workspace))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "dilon_identity_bridge_cli.py"), *args],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_prepare_command_is_offline_and_persists_exact_plan(self) -> None:
        with mock.patch.dict(os.environ, {"AUDIOBOOK_STUDIO_HOME": str(self.workspace)}), \
             mock.patch.object(
                 YandexSpeechKitBackend,
                 "_request",
                 side_effect=AssertionError("network attempted"),
             ) as request, \
             mock.patch("builtins.print") as output:
            self.assertEqual(cli.main(["--prepare-opening-credit"]), 0)
        request.assert_not_called()
        payload = json.loads(output.call_args.args[0])
        plan = payload["opening_credit_plan"]
        self.assertTrue(plan["stored"])
        self.assertEqual(plan["maximum_provider_requests"], 1)
        self.assertFalse(plan["execution_available"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])

    def test_plan_status_round_trip_over_cli_process(self) -> None:
        prepared = self._run("--prepare-opening-credit")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        plan = json.loads(prepared.stdout)["opening_credit_plan"]
        status = self._run(
            "--opening-credit-plan-status",
            "--plan-id", plan["plan_id"],
            "--plan-digest", plan["plan_digest"],
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        payload = json.loads(status.stdout)
        self.assertEqual(payload["opening_credit_plan"]["plan_id"], plan["plan_id"])
        self.assertFalse(payload["opening_credit_plan"]["execution_available"])
        self.assertEqual(payload["provider_requests"], 0)

    def test_missing_identity_returns_blocked_not_provider_action(self) -> None:
        completed = self._run(
            "--identity-status", "--book", "demo-book", "--job", "chapter-ch001"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["decision"], "IDENTITY_NOT_CURRENT")
        self.assertIsNone(payload["preview"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])

    def test_missing_required_argument_fails_closed_with_json(self) -> None:
        completed = self._run("--opening-credit-plan-status")
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["decision"], "INVALID_REQUEST")
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["paid_execution"])

    def test_parser_exposes_no_execute_or_synthesize_mode(self) -> None:
        help_text = cli.build_parser().format_help()
        self.assertNotIn("execute", help_text.lower())
        self.assertNotIn("synthesize", help_text.lower())
        self.assertNotIn("provider", help_text.lower())


if __name__ == "__main__":
    unittest.main()
