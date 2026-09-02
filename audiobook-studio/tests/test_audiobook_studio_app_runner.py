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
        with mock.patch.object(bridge, "_yandex_chapter_service_for_profile", return_value=service) as for_profile, \
             mock.patch.object(bridge, "_yandex_chapter_service_for_plan", return_value=service) as for_plan:
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
                for_profile.assert_called_once_with("yandex_lera")
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
                for_plan.assert_called_once_with("a" * 32)

    def test_approved_yandex_voice_selection_persists_per_book_offline(self):
        for profile_id in ("yandex_lera", "yandex_ermil", "yandex_kirill", "yandex_anton"):
            with self.subTest(profile_id=profile_id), mock.patch(
                "backends.yandex_client.YandexSpeechKitBackend._request",
                side_effect=AssertionError("network request attempted"),
            ) as request:
                result = bridge.set_book_voice(book_name="demo-book", profile_id=profile_id)
                saved = bridge.BOOK_LIBRARY.load_book_profile("demo-book")
                self.assertEqual(saved["selected_profile_id"], profile_id)
                self.assertEqual(result["selected_profile_id"], profile_id)
                self.assertEqual(result["provider_requests"], 0)
                self.assertFalse(result["remote_request_sent"])
                self.assertFalse(result["paid_execution"])
                self.assertFalse(result["billing_changed"])
                request.assert_not_called()

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
        service = mock.Mock()
        service.quarantine_release_authority.return_value = {
            "release_authority_revoked": True,
        }

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
             mock.patch.object(bridge, "_litres_export_service", return_value=service), \
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

    def test_all_release_authorities_invalidate_disabled_profile_without_failure(self):
        profile_path = bridge.WORKSPACE_PATHS.books_root / "disabled-book.json"
        profile = json.loads((ROOT / "books" / "demo-book.json").read_text(encoding="utf-8"))
        profile["slug"] = "disabled-book"
        profile["enabled"] = False
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        profile_root = (
            bridge.WORKSPACE_PATHS.exports_root
            / "disabled-book" / "litres_author_v1"
        )
        profile_root.mkdir(parents=True)
        pointer = profile_root / "CURRENT.json"
        pointer.write_text("forensic-current", encoding="utf-8")
        try:
            result = bridge.reconcile_all_litres_release_authorities()
        finally:
            profile_path.unlink(missing_ok=True)
            shutil.rmtree(profile_root.parent, ignore_errors=True)
        disabled = next(
            item for item in result["results"]
            if item["book_slug"] == "disabled-book"
        )
        self.assertNotIn("disabled-book.json", result["failed_book_ids"])
        self.assertEqual(disabled["state"], "INVALIDATED")
        self.assertTrue(disabled["profile_disabled"])
        self.assertFalse(pointer.exists())
        self.assertEqual(disabled["provider_requests"], 0)
        self.assertFalse(disabled["remote_request_sent"])
        self.assertFalse(disabled["billing_changed"])

    def test_all_release_authorities_quarantine_malformed_profile_pointer(self):
        profile_path = bridge.WORKSPACE_PATHS.books_root / "malformed-book.json"
        profile_path.write_text("{not-json", encoding="utf-8")
        profile_root = (
            bridge.WORKSPACE_PATHS.exports_root
            / "malformed-book" / "litres_author_v1"
        )
        profile_root.mkdir(parents=True)
        pointer = profile_root / "CURRENT.json"
        pointer.write_text("forensic-release-ready", encoding="utf-8")
        try:
            result = bridge.reconcile_all_litres_release_authorities()
        finally:
            profile_path.unlink(missing_ok=True)
            shutil.rmtree(profile_root.parent, ignore_errors=True)
        self.assertIn("malformed-book.json", result["failed_book_ids"])
        self.assertIn("malformed-book.json", result["quarantined_book_ids"])
        self.assertNotIn(
            "malformed-book.json", result["quarantine_failed_book_ids"],
        )
        self.assertFalse(pointer.exists())
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["billing_changed"])

    def test_all_release_authorities_quarantine_orphaned_release_pointer(self):
        orphan_slug = "orphaned-release-book"
        book_root = bridge.WORKSPACE_PATHS.exports_root / orphan_slug
        profile_root = book_root / "litres_author_v1"
        profile_root.mkdir(parents=True)
        pointer = profile_root / "CURRENT.json"
        pointer.write_text("forensic-orphan-release", encoding="utf-8")
        try:
            result = bridge.reconcile_all_litres_release_authorities()
        finally:
            shutil.rmtree(book_root, ignore_errors=True)
        self.assertIn(f"{orphan_slug}.json", result["quarantined_book_ids"])
        self.assertNotIn(orphan_slug, result["quarantine_failed_book_ids"])
        self.assertFalse(pointer.exists())
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["billing_changed"])

    def test_orphan_symlink_roots_are_unlinked_without_target_traversal(self):
        exports_root = bridge.WORKSPACE_PATHS.exports_root
        outside = self.workspace / "outside-release-authority"
        (outside / "litres_author_v1").mkdir(parents=True)
        outside_pointer = outside / "litres_author_v1" / "CURRENT.json"
        outside_pointer.write_text("must-survive", encoding="utf-8")
        book_root = exports_root / "orphan-book-link"
        book_root.symlink_to(outside, target_is_directory=True)
        result = bridge.reconcile_all_litres_release_authorities()
        self.assertFalse(book_root.exists())
        self.assertEqual(outside_pointer.read_text(encoding="utf-8"), "must-survive")
        self.assertIn("orphan-book-link.json", result["quarantined_book_ids"])

        real_book = exports_root / "orphan-profile-link"
        real_book.mkdir()
        profile_link = real_book / "litres_author_v1"
        profile_link.symlink_to(outside / "litres_author_v1", target_is_directory=True)
        result = bridge.reconcile_all_litres_release_authorities()
        self.assertFalse(profile_link.exists())
        self.assertEqual(outside_pointer.read_text(encoding="utf-8"), "must-survive")
        self.assertIn("orphan-profile-link.json", result["quarantined_book_ids"])

    def test_symlinked_exports_root_fails_closed_without_target_traversal(self):
        isolated_root = self.workspace / "symlinked-exports-workspace"
        isolated_root.mkdir()
        outside = self.workspace / "outside-entire-exports-root"
        pointer = outside / "orphan" / "litres_author_v1" / "CURRENT.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text("must-survive", encoding="utf-8")
        (isolated_root / "exports").symlink_to(outside, target_is_directory=True)
        isolated_paths = load_workspace_paths(
            env={"AUDIOBOOK_STUDIO_HOME": str(isolated_root)},
        )
        library = mock.Mock()
        library.list_book_profiles.return_value = []
        with mock.patch.object(bridge, "WORKSPACE_PATHS", isolated_paths), \
             mock.patch.object(bridge, "BOOK_LIBRARY", library):
            result = bridge.reconcile_all_litres_release_authorities()
        self.assertEqual(
            result["quarantine_failed_book_ids"], ["__exports_root__"],
        )
        self.assertEqual(pointer.read_text(encoding="utf-8"), "must-survive")
        self.assertTrue((isolated_root / "exports").is_symlink())
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["billing_changed"])

    def test_invalid_profile_name_does_not_block_orphan_pointer_cleanup(self):
        invalid_profile = bridge.WORKSPACE_PATHS.books_root / "bad name.json"
        invalid_profile.write_text("{}", encoding="utf-8")
        orphan_slug = "second-orphaned-release-book"
        book_root = bridge.WORKSPACE_PATHS.exports_root / orphan_slug
        profile_root = book_root / "litres_author_v1"
        profile_root.mkdir(parents=True)
        pointer = profile_root / "CURRENT.json"
        pointer.write_text("forensic-orphan-release", encoding="utf-8")
        try:
            result = bridge.reconcile_all_litres_release_authorities()
        finally:
            invalid_profile.unlink(missing_ok=True)
            shutil.rmtree(book_root, ignore_errors=True)
        self.assertIn("bad name.json", result["failed_book_ids"])
        self.assertIn("bad name.json", result["quarantine_failed_book_ids"])
        self.assertIn(f"{orphan_slug}.json", result["quarantined_book_ids"])
        self.assertFalse(pointer.exists())
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["billing_changed"])

    def test_orphan_pointer_quarantine_failure_is_reported_for_native_guard(self):
        orphan_slug = "unremovable-orphaned-release-book"
        book_root = bridge.WORKSPACE_PATHS.exports_root / orphan_slug
        profile_root = book_root / "litres_author_v1"
        profile_root.mkdir(parents=True)
        (profile_root / "CURRENT.json").write_text(
            "forensic-orphan-release", encoding="utf-8",
        )
        service = mock.Mock()
        service.quarantine_release_authority.side_effect = OSError("read-only")
        try:
            with mock.patch.object(
                bridge.BOOK_LIBRARY, "list_book_profiles", return_value=[],
            ), mock.patch.object(
                bridge, "_litres_export_service", return_value=service,
            ):
                result = bridge.reconcile_all_litres_release_authorities()
        finally:
            shutil.rmtree(book_root, ignore_errors=True)
        self.assertIn(orphan_slug, result["quarantine_failed_book_ids"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["billing_changed"])

    def test_quarantine_slug_comes_from_enumerated_case_variant_path(self):
        library = mock.Mock()
        library.list_book_profiles.return_value = [Path("Demo-Book.JSON")]
        service = mock.Mock()
        service.quarantine_release_authority.return_value = {
            "release_authority_revoked": True,
        }
        with mock.patch.object(bridge, "BOOK_LIBRARY", library), \
             mock.patch.object(
                 bridge, "reconcile_litres_release_authority",
                 side_effect=bridge.BookLibraryError("malformed"),
             ), \
             mock.patch.object(bridge, "_litres_export_service", return_value=service):
            result = bridge.reconcile_all_litres_release_authorities()
        self.assertEqual(result["failed_book_ids"], ["Demo-Book.JSON"])
        self.assertEqual(result["quarantined_book_ids"], ["Demo-Book.JSON"])
        service.quarantine_release_authority.assert_called_once()
        self.assertEqual(
            service.quarantine_release_authority.call_args.args[0], "demo-book",
        )
        library.resolve_book_profile.assert_not_called()

    def test_quarantine_revalidation_prefers_recovered_canonical_profile(self):
        library = mock.Mock()
        library.list_book_profiles.return_value = [Path("Demo-Book.JSON")]
        recovered = {
            "enabled": True,
            "rights_provenance": {
                "third_party_assets": ["music"],
                "verified": True,
            },
        }
        library.load_book_profile.return_value = recovered
        service = mock.Mock()

        def quarantine(
            book_slug, *, revalidate_quarantine, revalidate_recovered_book,
        ):
            self.assertEqual(book_slug, "demo-book")
            revoked = revalidate_quarantine()
            self.assertEqual(revalidate_recovered_book()["slug"], "demo-book")
            return {"release_authority_revoked": revoked}

        service.quarantine_release_authority.side_effect = quarantine
        with mock.patch.object(bridge, "BOOK_LIBRARY", library), \
             mock.patch.object(
                 bridge, "reconcile_litres_release_authority",
                 side_effect=bridge.BookLibraryError("renamed while waiting for lock"),
             ), \
             mock.patch.object(bridge, "_litres_export_service", return_value=service):
            result = bridge.reconcile_all_litres_release_authorities()
        self.assertEqual(result["failed_book_ids"], ["Demo-Book.JSON"])
        self.assertEqual(result["quarantined_book_ids"], [])
        self.assertEqual(result["quarantine_failed_book_ids"], [])
        self.assertEqual(
            library.load_book_profile.call_args_list,
            [
                mock.call("demo-book.json", allow_disabled=True),
                mock.call("demo-book.json", allow_disabled=True),
            ],
        )

    def test_quarantine_retries_canonical_profile_after_fallback_rename_race(self):
        library = mock.Mock()
        recovered = {
            "enabled": True,
            "rights_provenance": {
                "third_party_assets": ["music"],
                "verified": True,
            },
        }
        library.load_book_profile.side_effect = [
            bridge.BookLibraryError("canonical name not present yet"),
            bridge.BookLibraryError("case variant renamed away"),
            recovered,
        ]
        with mock.patch.object(bridge, "BOOK_LIBRARY", library):
            self.assertFalse(
                bridge._profile_requires_release_quarantine(
                    "Demo-Book.JSON", "demo-book",
                )
            )
        self.assertEqual(
            [call.args[0] for call in library.load_book_profile.call_args_list],
            ["demo-book.json", "Demo-Book.JSON", "demo-book.json"],
        )

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
