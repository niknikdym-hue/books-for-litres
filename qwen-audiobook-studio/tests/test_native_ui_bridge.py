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


def run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "audiobook_studio_app_runner.py"), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class NativeUIBridgeTests(unittest.TestCase):
    def test_ui_snapshot_is_structured_and_never_requests_tts(self):
        with mock.patch(
            "backends.yandex_client.YandexSpeechKitBackend._request",
            side_effect=AssertionError("network request attempted"),
        ) as request:
            snapshot = bridge.ui_snapshot()
        request.assert_not_called()
        self.assertFalse(snapshot["remote_request_sent"])
        self.assertEqual(snapshot["yandex_profile"], {"voice": "Lera", "role": "neutral", "speed": "1.04"})
        self.assertTrue(snapshot["books"])
        self.assertTrue(snapshot["qwen_voices"])
        self.assertEqual(set(snapshot["voice_library"]), {"qwen", "yandex", "openai"})
        self.assertEqual(len(snapshot["voice_library"]["qwen"]), 9)
        self.assertEqual(len(snapshot["voice_library"]["yandex"]), 4)
        self.assertEqual(len(snapshot["voice_library"]["openai"]), 2)

    def test_ui_snapshot_cli_is_machine_readable(self):
        completed = run_script("--ui-snapshot")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        snapshot = json.loads(completed.stdout)
        estimate = snapshot["yandex_estimate"]
        self.assertFalse(snapshot["remote_request_sent"])
        self.assertIn("estimated_remaining_cost", estimate)
        self.assertIn("allowed_to_start", estimate)
        self.assertFalse(estimate["remote_request_sent"])

    def test_native_ui_uses_only_explicit_run_action_for_yandex(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        self.assertIn('runBridgeText(["--run-yandex-demo"])', source)
        self.assertIn("confirmationDialog", source)
        self.assertIn("--ui-snapshot", source)
        self.assertNotIn("urlopen", source)


if __name__ == "__main__":
    unittest.main()
