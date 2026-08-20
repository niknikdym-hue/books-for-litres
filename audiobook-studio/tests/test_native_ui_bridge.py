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
        self.assertEqual([engine["id"] for engine in snapshot["engines"]], ["qwen", "yandex", "openai"])
        self.assertEqual(snapshot["yandex_profile"], {"voice": "Lera", "role": "neutral", "speed": "1.04"})
        self.assertTrue(snapshot["books"])
        self.assertTrue(snapshot["qwen_voices"])
        self.assertEqual(set(snapshot["voice_library"]), {"qwen", "yandex", "openai"})
        self.assertEqual(len(snapshot["voice_library"]["qwen"]), 9)
        self.assertEqual(len(snapshot["voice_library"]["yandex"]), 4)
        self.assertEqual(len(snapshot["voice_library"]["openai"]), 2)
        self.assertEqual(
            [profile["profile_id"] for profile in snapshot["voice_library"]["openai"]],
            ["openai_onyx", "openai_cedar"],
        )
        self.assertEqual(
            snapshot["cloud_billing"]["providers"]["yandex"]["current_job_estimate_source"],
            "local_estimate",
        )

    def test_ui_snapshot_cli_is_machine_readable(self):
        completed = run_script("--ui-snapshot")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        snapshot = json.loads(completed.stdout)
        estimate = snapshot["yandex_estimate"]
        self.assertFalse(snapshot["remote_request_sent"])
        self.assertEqual([engine["id"] for engine in snapshot["engines"]], ["qwen", "yandex", "openai"])
        self.assertIn("estimated_remaining_cost", estimate)
        self.assertIn("allowed_to_start", estimate)
        self.assertFalse(estimate["remote_request_sent"])

    def test_native_ui_uses_only_explicit_run_action_for_yandex(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        self.assertIn('runBridgeText(["--run-yandex-demo"])', source)
        self.assertIn("confirmationDialog", source)
        self.assertIn("--ui-snapshot", source)
        self.assertIn("AUDIOBOOK_STUDIO_HOME", source)
        self.assertIn("settings/workspace-paths.json", source)
        self.assertNotIn("qwen3-tts", source.lower())
        self.assertNotIn("urlopen", source)
        self.assertIn("case openai", contracts)
        self.assertIn('case .openai: "OpenAI TTS — облако"', contracts)
        self.assertIn('return "Недоступно"', contracts)
        self.assertIn('source == "local_estimate"', contracts)
        self.assertIn('model.engine == .openai', source)
        self.assertIn('AUDIOBOOK_STUDIO_INITIAL_ENGINE', source)
        self.assertIn('AUDIOBOOK_STUDIO_INITIAL_PROFILE', source)
        self.assertIn('AUDIOBOOK_STUDIO_OPEN_SETTINGS_ON_LAUNCH', source)
        self.assertIn('AUDIOBOOK_STUDIO_SETTINGS_FOCUS', source)
        self.assertIn('"--billing-status", "--provider", provider.rawValue, "--refresh"', source)
        self.assertNotIn('runBridgeText(["--run-openai"]', source)

    def test_native_build_compiles_shared_contract_file(self):
        build = (ROOT / "native" / "build_native_app.sh").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/StudioContracts.swift"', build)
        self.assertIn('"$script_dir/AudiobookStudioApp.swift"', build)


if __name__ == "__main__":
    unittest.main()
