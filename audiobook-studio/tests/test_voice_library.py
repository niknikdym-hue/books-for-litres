from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audiobook_studio_app_runner as bridge
import voice_library


def run_bridge(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "audiobook_studio_app_runner.py"), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def write_registry(path: Path, profiles: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": profiles}, ensure_ascii=False),
        encoding="utf-8",
    )


class VoiceLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = voice_library.load_static_profiles()

    def test_01_schema_loads(self):
        self.assertEqual(len(self.profiles), 6)
        self.assertTrue(all(voice_library.REQUIRED_FIELDS <= set(profile) for profile in self.profiles))

    def test_02_profile_ids_are_unique(self):
        profile_ids = [profile["profile_id"] for profile in self.profiles]
        self.assertEqual(len(profile_ids), len(set(profile_ids)))

    def test_03_duplicate_profile_id_is_rejected(self):
        profiles = copy.deepcopy(self.profiles)
        duplicate = dict(profiles[0])
        duplicate["voice"] = "duplicate"
        profiles.append(duplicate)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            write_registry(path, profiles)
            with self.assertRaises(voice_library.VoiceLibraryError):
                voice_library.load_static_profiles(path)

    def test_04_unknown_profile_field_is_rejected(self):
        profiles = copy.deepcopy(self.profiles)
        profiles[0]["unexpected"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            write_registry(path, profiles)
            with self.assertRaises(voice_library.VoiceLibraryError):
                voice_library.load_static_profiles(path)

    def test_05_invalid_provider_engine_relationship_is_rejected(self):
        profiles = copy.deepcopy(self.profiles)
        profiles[0]["engine"] = "openai_tts"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            write_registry(path, profiles)
            with self.assertRaises(voice_library.VoiceLibraryError):
                voice_library.load_static_profiles(path)

    def test_05b_non_approved_static_profile_is_rejected(self):
        profiles = copy.deepcopy(self.profiles)
        profiles[0]["status"] = "candidate"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            write_registry(path, profiles)
            with self.assertRaises(voice_library.VoiceLibraryError):
                voice_library.load_static_profiles(path)

    def test_06_four_approved_yandex_profiles_are_exact(self):
        profiles = voice_library.load_voice_library(provider="yandex")
        self.assertEqual(
            [profile["profile_id"] for profile in profiles],
            ["yandex_lera", "yandex_ermil", "yandex_kirill", "yandex_anton"],
        )
        self.assertTrue(all(profile["status"] == "approved" for profile in profiles))

    def test_07_only_selected_yandex_voices_are_present(self):
        voices = {profile["voice"] for profile in voice_library.load_voice_library(provider="yandex")}
        self.assertEqual(voices, {"lera", "ermil", "kirill", "anton"})
        self.assertTrue({"filipp", "zahar", "alexander", "madi_ru"}.isdisjoint(voices))

    def test_08_two_approved_openai_profiles_are_exact(self):
        profiles = voice_library.load_voice_library(provider="openai")
        self.assertEqual(
            [profile["profile_id"] for profile in profiles],
            ["openai_onyx", "openai_cedar"],
        )
        self.assertTrue(all(profile["status"] == "approved" for profile in profiles))

    def test_09_only_onyx_and_cedar_are_present(self):
        voices = {profile["voice"] for profile in voice_library.load_voice_library(provider="openai")}
        self.assertEqual(voices, {"onyx", "cedar"})

    def test_10_no_openai_female_placeholder_exists(self):
        profile_ids = {profile["profile_id"] for profile in self.profiles}
        self.assertNotIn("openai_female", profile_ids)

    def test_11_lera_is_frozen_at_104(self):
        lera = next(profile for profile in self.profiles if profile["profile_id"] == "yandex_lera")
        self.assertTrue(lera["frozen"])
        self.assertEqual(lera["role"], "neutral")
        self.assertEqual(lera["speed"], "1.04")

    def test_12_selected_yandex_male_speeds_are_one(self):
        profiles = {profile["profile_id"]: profile for profile in self.profiles}
        for profile_id in ("yandex_ermil", "yandex_kirill", "yandex_anton"):
            self.assertEqual(profiles[profile_id]["speed"], "1.0")
            self.assertEqual(profiles[profile_id]["role"], "neutral")

    def test_13_openai_model_and_voice_source_are_exact(self):
        for profile in voice_library.load_voice_library(provider="openai"):
            self.assertEqual(profile["model"], "gpt-4o-mini-tts")
            self.assertEqual(profile["voice_source"], "builtin")
            self.assertEqual(profile["response_format"], "wav")
            self.assertIn("professional audiobook narrator", profile["instructions"])

    def test_14_provider_filtering(self):
        profiles = voice_library.load_voice_library(provider="yandex")
        self.assertTrue(profiles)
        self.assertEqual({profile["provider"] for profile in profiles}, {"yandex"})

    def test_15_engine_filtering(self):
        profiles = voice_library.load_voice_library(engine="openai_tts")
        self.assertEqual({profile["profile_id"] for profile in profiles}, {"openai_onyx", "openai_cedar"})

    def test_16_generic_bridge_lists_yandex_offline(self):
        completed = run_bridge("--list-voices", "--engine", "yandex")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual([voice["label"] for voice in result["voices"]], ["Lera", "Ermil", "Kirill", "Anton"])

    def test_17_generic_bridge_lists_openai_offline(self):
        completed = run_bridge("--list-voices", "--engine", "openai")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual([voice["label"] for voice in result["voices"]], ["Onyx", "Cedar"])

    def test_18_existing_qwen_catalog_remains_intact(self):
        original = subprocess.run(
            [sys.executable, str(ROOT / "studio_app_runner.py"), "--list-voices"],
            check=False,
            capture_output=True,
            text=True,
        )
        generic = run_bridge("--list-voices", "--engine", "qwen")
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(generic.returncode, 0, generic.stderr)
        original_ids = [line.split("\t", 1)[0] for line in original.stdout.splitlines()]
        normalized_ids = [profile["voice"] for profile in json.loads(generic.stdout)["voices"]]
        self.assertEqual(normalized_ids, original_ids)
        self.assertEqual(len(normalized_ids), 9)

    def test_19_ui_snapshot_keeps_old_keys_and_adds_voice_library(self):
        snapshot = bridge.ui_snapshot()
        for key in ("qwen_voices", "yandex_profile", "yandex_estimate"):
            self.assertIn(key, snapshot)
        self.assertEqual(set(snapshot["voice_library"]), {"qwen", "yandex", "openai"})
        self.assertEqual(len(snapshot["voice_library"]["qwen"]), 9)
        self.assertEqual(len(snapshot["voice_library"]["yandex"]), 4)
        self.assertEqual(len(snapshot["voice_library"]["openai"]), 2)

    def test_20_voice_library_operations_never_request_network(self):
        with mock.patch(
            "backends.yandex_client.urllib.request.urlopen",
            side_effect=AssertionError("remote request attempted"),
        ) as urlopen:
            for engine in ("qwen", "yandex", "openai"):
                self.assertFalse(bridge.voice_library_listing(engine)["remote_request_sent"])
            self.assertFalse(bridge.ui_snapshot()["remote_request_sent"])
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
