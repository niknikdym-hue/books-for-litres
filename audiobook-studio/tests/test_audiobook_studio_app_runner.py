from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audiobook_studio_app_runner as bridge
from book_library import BookLibrary
from workspace_paths import load_workspace_paths


SCRIPT_ENV: dict[str, str] | None = None


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=SCRIPT_ENV,
    )


class UniversalBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global SCRIPT_ENV
        cls.temporary = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls.temporary.name) / "workspace"
        books = cls.workspace / "books"
        books.mkdir(parents=True)
        shutil.copy2(ROOT / "books/demo-book.json", books / "demo-book.json")
        SCRIPT_ENV = dict(os.environ, AUDIOBOOK_STUDIO_HOME=str(cls.workspace))
        cls.original_paths = bridge.WORKSPACE_PATHS
        cls.original_library = bridge.BOOK_LIBRARY
        bridge.WORKSPACE_PATHS = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": str(cls.workspace)})
        bridge.BOOK_LIBRARY = BookLibrary(bridge.WORKSPACE_PATHS.books_root)

    @classmethod
    def tearDownClass(cls):
        global SCRIPT_ENV
        bridge.WORKSPACE_PATHS = cls.original_paths
        bridge.BOOK_LIBRARY = cls.original_library
        SCRIPT_ENV = None
        cls.temporary.cleanup()

    def test_engine_catalog_contains_qwen_yandex_and_openai(self):
        completed = run_script(ROOT / "audiobook_studio_app_runner.py", "--list-engines")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("qwen\tQwen — локально", completed.stdout)
        self.assertIn("yandex\tYandex SpeechKit — облако", completed.stdout)
        self.assertIn("openai\tOpenAI TTS — облако", completed.stdout)

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
            self.assertEqual(bridge.main(["--list-jobs", "--book", "demo-book.json"]), 17)
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

    def test_shared_billing_status_is_ui_ready_and_offline(self):
        completed = run_script(ROOT / "audiobook_studio_app_runner.py", "--billing-status")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(set(result["providers"]), {"yandex", "openai"})
        self.assertFalse(result["remote_request_sent"])
        for provider, currency in (("yandex", "RUB"), ("openai", "USD")):
            snapshot = result["providers"][provider]
            self.assertEqual(snapshot["currency"], currency)
            self.assertIsNone(snapshot["remaining"])
            self.assertEqual(snapshot["remaining_source"], "unavailable")

    def test_yandex_billing_preflight_reuses_cache_aware_estimate(self):
        completed = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--billing-preflight", "--provider", "yandex",
            "--book", "demo-book.json", "--job", "short-test",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["current_job_estimate_source"], "local_estimate")
        self.assertEqual(result["decision"], "BLOCK")
        self.assertEqual(result["decision_reason"], "hard_limit_missing")
        self.assertFalse(result["remote_request_sent"])

    def test_openai_billing_preflight_preserves_unknown_output_and_paid_block(self):
        completed = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--billing-preflight", "--provider", "openai",
            "--book", "demo-book.json", "--job", "short-test", "--profile-id", "openai_cedar",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertIsNone(result["current_job_estimate"])
        self.assertEqual(result["current_job_estimate_source"], "unavailable")
        self.assertEqual(result["decision"], "BLOCK")
        self.assertEqual(result["decision_reason"], "openai_paid_execution_disabled")
        self.assertFalse(result["remote_request_sent"])

    def test_ui_snapshot_contains_cloud_billing_data_contract(self):
        snapshot = bridge.ui_snapshot()
        self.assertEqual([engine["id"] for engine in snapshot["engines"]], ["qwen", "yandex", "openai"])
        self.assertIn("cloud_billing", snapshot)
        billing = snapshot["cloud_billing"]
        self.assertEqual(set(billing["providers"]), {"yandex", "openai"})
        for provider in billing["providers"].values():
            for field in (
                "spent", "spent_source", "remaining", "remaining_source",
                "current_job_estimate", "current_job_estimate_source",
                "projected_remaining", "projected_remaining_source", "freshness", "status", "warnings",
            ):
                self.assertIn(field, provider)
        self.assertFalse(billing["remote_request_sent"])

    def test_ui_snapshot_exposes_real_prepared_job_catalog(self):
        snapshot = bridge.ui_snapshot()
        demo = next(book for book in snapshot["books"] if book["id"] == "demo-book.json")
        self.assertEqual(demo["jobs"], [{
            "id": "short-test",
            "label": "Безопасный короткий тест",
            "segment_count": 1,
        }])

    def test_add_book_details_and_restart_snapshot_are_machine_readable_and_offline(self):
        source = self.workspace / "bridge-source.txt"
        source.write_text("Новая книга для bridge acceptance.\n", encoding="utf-8")
        added = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--add-book", "--source-file", str(source),
            "--title", "Bridge Book", "--author", "Author", "--slug", "bridge-book",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        result = json.loads(added.stdout)
        self.assertEqual(result["book_id"], "bridge-book.json")
        self.assertEqual(result["status"], "NO_PREPARED_JOBS")
        self.assertEqual(result["source_integrity"], "OK")
        self.assertFalse(result["remote_request_sent"])

        details = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--book-details", "--book", "bridge-book.json",
        )
        self.assertEqual(details.returncode, 0, details.stderr)
        self.assertEqual(json.loads(details.stdout)["source_integrity"], "OK")
        self.assertFalse(json.loads(details.stdout)["remote_request_sent"])

        restarted = run_script(ROOT / "audiobook_studio_app_runner.py", "--ui-snapshot")
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        snapshot = json.loads(restarted.stdout)
        imported = next(book for book in snapshot["books"] if book["id"] == "bridge-book.json")
        self.assertEqual(imported["jobs"], [])
        self.assertEqual(imported["selected_backend"], "yandex")
        self.assertEqual(imported["selected_profile_id"], "yandex_lera")
        self.assertEqual(imported["source_integrity"], "OK")
        self.assertFalse(snapshot["remote_request_sent"])

    def test_paid_plan_commands_are_separate_and_require_immutable_identity(self):
        prepared = bridge.build_parser().parse_args([
            "--prepare-paid-run", "--provider", "openai", "--book", "demo-book.json",
            "--job", "short-test", "--profile-id", "openai_onyx",
        ])
        executed = bridge.build_parser().parse_args([
            "--execute-paid-plan", "--plan-id", "abc", "--plan-digest", "digest",
        ])
        self.assertTrue(prepared.prepare_paid_run)
        self.assertFalse(prepared.execute_paid_plan)
        self.assertTrue(executed.execute_paid_plan)
        self.assertEqual(executed.plan_id, "abc")
        self.assertEqual(executed.plan_digest, "digest")

    def test_openai_hard_limit_setter_is_atomic_local_and_preserves_schema(self):
        from workspace_paths import load_workspace_paths

        with tempfile.TemporaryDirectory() as directory:
            paths = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": directory})
            with mock.patch.object(bridge, "WORKSPACE_PATHS", paths):
                result = bridge.set_billing_setting(
                    provider="openai", setting="hard_limit", value="2.75"
                )
                saved = json.loads(paths.cloud_billing_settings.read_text(encoding="utf-8"))
        self.assertEqual(result["value"], "2.75")
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(saved["openai"]["hard_limit_usd"], "2.75")
        self.assertNotIn("credential", json.dumps(saved).lower())

    def test_openai_hard_limit_setter_rejects_negative_without_writing(self):
        from workspace_paths import load_workspace_paths

        with tempfile.TemporaryDirectory() as directory:
            paths = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": directory})
            with mock.patch.object(bridge, "WORKSPACE_PATHS", paths):
                with self.assertRaises(Exception):
                    bridge.set_billing_setting(
                        provider="openai", setting="hard_limit", value="-0.01"
                    )
            self.assertFalse(paths.cloud_billing_settings.exists())


if __name__ == "__main__":
    unittest.main()
