from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audiobook_studio_app_runner as bridge


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


class UniversalBridgeTests(unittest.TestCase):
    def test_engine_catalog_contains_qwen_yandex_and_openai(self):
        completed = run_script(ROOT / "audiobook_studio_app_runner.py", "--list-engines")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("qwen\tQwen — локально", completed.stdout)
        self.assertIn("yandex\tYandex SpeechKit — Lera neutral 1.04", completed.stdout)
        self.assertIn("openai\tOpenAI TTS — Onyx / Cedar", completed.stdout)

    def test_qwen_catalog_commands_preserve_delegate_output(self):
        universal = ROOT / "audiobook_studio_app_runner.py"
        qwen = ROOT / "studio_app_runner.py"
        cases = (
            (("--list-books",), ("--list-books",)),
            (("--list-jobs", "--book", "demo-book.json"),
             ("--list-jobs", "--book", "demo-book.json")),
            (("--default-speaker", "--book", "demo-book.json"),
             ("--default-speaker", "--book", "demo-book.json")),
        )
        for universal_args, qwen_args in cases:
            with self.subTest(command=universal_args[0]):
                actual = run_script(universal, *universal_args)
                expected = run_script(qwen, *qwen_args)
                self.assertEqual(actual.returncode, expected.returncode)
                self.assertEqual(actual.stdout, expected.stdout)
                self.assertEqual(actual.stderr, expected.stderr)

    def test_yandex_profile_is_lera_neutral_104(self):
        result = bridge.yandex_demo_estimate()
        self.assertTrue(result["backend_config_ok"])
        self.assertEqual(result["voice"], "lera")
        self.assertEqual(result["role"], "neutral")
        self.assertEqual(result["speed"], "1.04")

    def test_yandex_demo_estimate_does_not_request_network(self):
        with mock.patch(
            "backends.yandex_client.YandexSpeechKitBackend._request",
            side_effect=AssertionError("network request attempted"),
        ) as request:
            result = bridge.yandex_demo_estimate()
        request.assert_not_called()
        self.assertFalse(result["remote_request_sent"])
        self.assertGreater(result["characters"], 0)
        self.assertGreater(result["segments"], 0)
        self.assertGreater(result["estimated_billing_units"], 0)

    def test_yandex_check_does_not_read_keychain(self):
        with mock.patch(
            "backends.yandex_client.YandexSpeechKitBackend._get_api_key",
            side_effect=AssertionError("Keychain read attempted"),
        ) as get_api_key:
            result = bridge.yandex_offline_check()
        get_api_key.assert_not_called()
        self.assertTrue(result["backend_config_ok"])
        self.assertEqual(result["keychain_check"], "not_attempted_offline")
        self.assertFalse(result["remote_request_sent"])

    def test_real_yandex_run_has_a_separate_explicit_cli_mode(self):
        args = bridge.build_parser().parse_args(["--run-yandex-demo"])
        self.assertTrue(args.run_yandex_demo)
        self.assertFalse(args.yandex_check)
        self.assertFalse(args.yandex_estimate_demo)

    def test_qwen_error_does_not_touch_yandex_configuration(self):
        before = bridge.YANDEX_CONFIG.read_bytes()
        with mock.patch.object(bridge, "_delegate", return_value=17):
            self.assertEqual(bridge.main(["--list-books"]), 17)
        self.assertEqual(bridge.YANDEX_CONFIG.read_bytes(), before)
        self.assertTrue(bridge.yandex_demo_estimate()["backend_config_ok"])

    def test_json_estimate_is_machine_readable_and_offline(self):
        completed = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--yandex-estimate-demo",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(result["engine_display"], "Yandex SpeechKit v3")

    def test_openai_status_and_pricing_are_available_through_universal_bridge(self):
        for mode in ("--openai-status", "--openai-pricing-status"):
            with self.subTest(mode=mode):
                completed = run_script(ROOT / "audiobook_studio_app_runner.py", mode)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertFalse(result["remote_request_sent"])
                self.assertEqual(result["engine"], "openai_tts")

    def test_openai_preflight_is_cache_aware_and_offline_through_bridge(self):
        completed = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--openai-preflight",
            "--book", "demo-book.json",
            "--job", "short-test",
            "--profile-id", "openai_onyx",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["remote_request_sent"])
        self.assertIn("segment_plan", result)
        self.assertFalse(result["allowed_to_start"])

    def test_openai_run_is_explicit_and_fail_closed_through_bridge(self):
        completed = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--run-openai",
            "--book", "demo-book.json",
            "--job", "short-test",
            "--profile-id", "openai_cedar",
        )
        self.assertEqual(completed.returncode, 2)
        result = json.loads(completed.stderr)
        self.assertEqual(result["error"], "paid_execution_gate")
        self.assertFalse(result["remote_request_sent"])

    def test_openai_bridge_passes_canonical_selection_only(self):
        with mock.patch.object(bridge, "_delegate", return_value=0) as delegate:
            self.assertEqual(bridge.main([
                "--openai-preflight", "--book", "demo-book.json",
                "--job", "short-test", "--profile-id", "openai_onyx",
            ]), 0)
        delegate.assert_called_once_with(
            bridge.OPENAI_RUNNER,
            "--preflight",
            "--book", "demo-book.json",
            "--job", "short-test",
            "--profile-id", "openai_onyx",
        )


if __name__ == "__main__":
    unittest.main()
