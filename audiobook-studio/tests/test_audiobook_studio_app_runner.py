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
from book_text_preparation import BookTextPreparationService
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
        SCRIPT_ENV = dict(
            os.environ,
            AUDIOBOOK_STUDIO_HOME=str(cls.workspace),
            HOME=str(Path(cls.temporary.name) / "home"),
        )
        cls.original_paths = bridge.WORKSPACE_PATHS
        cls.original_library = bridge.BOOK_LIBRARY
        cls.original_preparation = bridge.BOOK_TEXT_PREPARATION
        bridge.WORKSPACE_PATHS = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": str(cls.workspace)})
        bridge.BOOK_LIBRARY = BookLibrary(bridge.WORKSPACE_PATHS.books_root)
        bridge.BOOK_TEXT_PREPARATION = BookTextPreparationService(bridge.BOOK_LIBRARY)

    @classmethod
    def tearDownClass(cls):
        global SCRIPT_ENV
        bridge.WORKSPACE_PATHS = cls.original_paths
        bridge.BOOK_LIBRARY = cls.original_library
        bridge.BOOK_TEXT_PREPARATION = cls.original_preparation
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

    def test_yandex_chapter_prepare_and_execute_are_separate_plan_commands(self):
        service = mock.Mock()
        service.prepare.return_value = {"decision": "READY_FOR_CONFIRMATION", "remote_request_sent": False}
        service.execute.return_value = {"state": "CONSUMED", "remote_request_sent": True}
        with mock.patch.object(bridge, "_yandex_chapter_service", return_value=service):
            with mock.patch("builtins.print"):
                self.assertEqual(bridge.main([
                    "--prepare-yandex-chapter-run",
                    "--book", "chapter-book",
                    "--job", "chapter-ch001",
                    "--profile-id", "yandex_lera",
                ]), 0)
                service.prepare.assert_called_once_with(
                    book_name="chapter-book",
                    job_id="chapter-ch001",
                    profile_id="yandex_lera",
                )
                service.execute.assert_not_called()

                self.assertEqual(bridge.main([
                    "--execute-yandex-chapter-plan",
                    "--plan-id", "a" * 32,
                    "--plan-digest", "b" * 64,
                ]), 0)
                service.execute.assert_called_once_with(
                    plan_id="a" * 32,
                    plan_digest="b" * 64,
                )

    def test_mastering_and_litres_export_commands_are_separate_offline_actions(self):
        mastering_result = {"mastering": {"decision": "ALREADY_MASTERED"}, "provider_requests": 0, "remote_request_sent": False}
        export_result = {"export": {"decision": "ALREADY_EXPORTED"}, "provider_requests": 0, "remote_request_sent": False}
        common = [
            "--provider", "yandex", "--book", "demo-book",
            "--job", "chapter-ch001", "--profile-id", "yandex_lera",
        ]
        with mock.patch.object(bridge, "mastering_current", return_value=mastering_result) as mastering, \
             mock.patch.object(bridge, "litres_export_current", return_value=export_result) as export, \
             mock.patch("builtins.print"):
            self.assertEqual(bridge.main(["--mastering-status", *common]), 0)
            self.assertEqual(bridge.main(["--prepare-master", *common]), 0)
            self.assertEqual(bridge.main(["--create-master", *common]), 0)
            self.assertEqual(bridge.main(["--litres-export-status", *common]), 0)
            self.assertEqual(bridge.main(["--create-litres-export", *common]), 0)
        self.assertEqual([call.kwargs["action"] for call in mastering.call_args_list], ["status", "prepare", "master"])
        self.assertEqual([call.kwargs["action"] for call in export.call_args_list], ["status", "export"])

    def test_release_authority_reconciliation_is_a_separate_offline_action(self):
        result = {
            "state": "SAFE_NO_CURRENT", "provider_requests": 0,
            "remote_request_sent": False, "billing_changed": False,
        }
        with mock.patch.object(
            bridge, "reconcile_litres_release_authority", return_value=result
        ) as reconcile, mock.patch("builtins.print"):
            self.assertEqual(bridge.main([
                "--reconcile-litres-release-authority",
                "--book", "demo-book",
            ]), 0)
        reconcile.assert_called_once_with(book_name="demo-book")

    def test_release_authority_reconciliation_uses_profile_not_execution_loader(self):
        profile = ROOT / "books" / "demo-book.json"
        book = json.loads(profile.read_text(encoding="utf-8"))
        service = mock.Mock()

        def reconcile(value, *, revalidate_book):
            self.assertEqual(value["slug"], "demo-book")
            self.assertEqual(revalidate_book()["slug"], "demo-book")
            return {"state": "SAFE_NO_CURRENT", "provider_requests": 0}

        service.reconcile_release_authority.side_effect = reconcile
        library = mock.Mock()
        library.resolve_book_profile.return_value = profile
        library.load_book_profile.return_value = book
        with mock.patch.object(bridge, "BOOK_LIBRARY", library), \
             mock.patch.object(bridge, "_litres_export_service", return_value=service):
            result = bridge.reconcile_litres_release_authority(book_name="demo-book")
        self.assertEqual(result["state"], "SAFE_NO_CURRENT")
        self.assertEqual(library.load_book_profile.call_count, 2)
        library.load_book_for_execution.assert_not_called()

    def test_all_release_authorities_continue_past_one_malformed_profile(self):
        profiles = [Path("good.json"), Path("broken.json"), Path("also-good.json")]
        library = mock.Mock()
        library.list_book_profiles.return_value = profiles

        def reconcile(*, book_name):
            if book_name == "broken.json":
                raise bridge.BookLibraryError("malformed")
            return {
                "book_slug": Path(book_name).stem,
                "provider_requests": 0,
                "remote_request_sent": False,
                "billing_changed": False,
            }

        with mock.patch.object(bridge, "BOOK_LIBRARY", library), \
             mock.patch.object(
                 bridge, "reconcile_litres_release_authority", side_effect=reconcile
             ):
            result = bridge.reconcile_all_litres_release_authorities()
        self.assertEqual(result["processed_books"], 2)
        self.assertEqual(result["failed_book_ids"], ["broken.json"])
        self.assertEqual([item["book_slug"] for item in result["results"]], ["good", "also-good"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["billing_changed"])

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

    def test_prepare_book_text_status_and_snapshot_are_offline_and_restart_safe(self):
        source = self.workspace / "text-preparation-source.txt"
        source.write_text(
            "Глава 1. Начало\n\nПервое предложение. Второе предложение.\n\n"
            "Глава 2 — Финал\n\nЗаключительный абзац.\n",
            encoding="utf-8",
        )
        added = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--add-book", "--source-file", str(source),
            "--title", "Text Preparation", "--author", "Author", "--slug", "text-prep-bridge",
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        before = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--book-preparation-status", "--book", "text-prep-bridge",
        )
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(json.loads(before.stdout)["preparation_status"], "NOT_PREPARED")

        prepared = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--prepare-book-text", "--book", "text-prep-bridge",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        result = json.loads(prepared.stdout)
        self.assertEqual(result["preparation_status"], "READY")
        self.assertEqual(result["chapter_count"], 2)
        self.assertGreaterEqual(result["segment_count"], 2)
        self.assertFalse(result["remote_request_sent"])

        restarted = run_script(ROOT / "audiobook_studio_app_runner.py", "--ui-snapshot")
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        imported = next(
            book for book in json.loads(restarted.stdout)["books"]
            if book["id"] == "text-prep-bridge.json"
        )
        self.assertEqual(imported["preparation_status"], "READY")
        self.assertEqual(imported["chapter_count"], 2)
        self.assertEqual(imported["jobs"][0]["id"], "short-test")

        working = self.workspace / "books/text-prep-bridge/tts/working.txt"
        working.write_text(working.read_text(encoding="utf-8") + "\nРедакционная правка.\n", encoding="utf-8")
        stale = run_script(
            ROOT / "audiobook_studio_app_runner.py",
            "--book-preparation-status", "--book", "text-prep-bridge",
        )
        stale_result = json.loads(stale.stdout)
        self.assertEqual(stale_result["preparation_status"], "STALE")
        self.assertEqual(stale_result["jobs"], [])
        self.assertFalse(stale_result["remote_request_sent"])

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
