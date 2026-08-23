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


def swift_function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unterminated Swift function: {signature}")


def run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "audiobook_studio_app_runner.py"), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=SCRIPT_ENV,
    )


class NativeUIBridgeTests(unittest.TestCase):
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

    def test_native_ui_uses_only_immutable_plan_execution_for_yandex(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        self.assertNotIn('runBridgeText(["--run-yandex-demo"])', source)
        self.assertIn('"--prepare-yandex-chapter-run"', source)
        self.assertIn('"--execute-yandex-chapter-plan"', source)
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

    def test_native_openai_paid_plan_contract_has_job_picker_and_exact_confirmation(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        snapshot = bridge.ui_snapshot()
        self.assertTrue(snapshot["books"][0]["jobs"])
        self.assertIn('"--prepare-paid-run", "--provider", "openai"', source)
        self.assertIn('"--execute-paid-plan", "--plan-id", plan.planID', source)
        self.assertIn("Подтвердить 1 платный запрос", source)
        self.assertIn("Использовать готовое аудио", source)
        self.assertIn("Новых платных запросов: максимум 1", source)
        self.assertIn("Точная будущая стоимость: Недоступно", source)
        self.assertIn("OpenAI balance:", source)
        self.assertIn("Для книги нет подготовленных задач.", source)
        self.assertIn("Автоматический повтор запрещён.", contracts)
        self.assertIn('decision == "READY_FOR_CONFIRMATION"', contracts)
        self.assertIn('decision == "CACHE_ONLY"', contracts)
        self.assertNotIn("Больше не спрашивать", source)
        self.assertNotIn("Всегда разрешать", source)
        self.assertNotIn("Автоматически подтверждать", source)

    def test_native_openai_prepare_requires_explicit_one_shot_confirmation(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        begin = swift_function_body(source, "func begin()")
        request_prepare = swift_function_body(source, "private func requestOpenAIPrepareConfirmation()")
        confirm_prepare = swift_function_body(source, "func confirmOpenAIPrepare()")
        prepare = swift_function_body(source, "private func preparePaidRun(")

        self.assertIn("requestOpenAIPrepareConfirmation()", begin)
        self.assertNotIn("preparePaidRun(", begin)
        self.assertNotIn("--prepare-paid-run", begin)
        self.assertNotIn("runBridge", begin)

        self.assertIn("openAIIntentGate.arm()", request_prepare)
        self.assertIn("showPrepareConfirmation = true", request_prepare)
        self.assertNotIn("runBridge", request_prepare)
        self.assertIn("openAIIntentGate.consume(pendingOpenAIIntentToken)", confirm_prepare)
        self.assertIn("clearConsumedOpenAIIntent()", confirm_prepare)
        self.assertIn("preparePaidRun(authorizedBy: authorization", confirm_prepare)
        self.assertLess(
            confirm_prepare.index("openAIIntentGate.consume"),
            confirm_prepare.index("preparePaidRun(authorizedBy:"),
        )
        self.assertEqual(source.count("preparePaidRun(authorizedBy: authorization"), 1)
        self.assertIn('"--prepare-paid-run", "--provider", "openai"', prepare)

        self.assertIn("struct OneShotIntentGate", contracts)
        self.assertIn("mutating func arm() -> OneShotIntentToken", contracts)
        self.assertIn("mutating func consume(_ token: OneShotIntentToken?)", contracts)
        self.assertIn("mutating func cancel()", contracts)
        self.assertIn('"Подготовить OpenAI-план?"', source)
        self.assertIn('Button("Подготовить план") { model.confirmOpenAIPrepare() }', source)
        self.assertIn("Подготовка плана не отправляет TTS-запрос", source)

    def test_native_openai_prepare_and_paid_confirmations_remain_separate(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        confirm_paid = swift_function_body(source, "func confirmPaidRequest()")
        confirm_cache = swift_function_body(source, "func confirmCacheOnlyMaterialization()")
        execute = swift_function_body(source, "private func executePaidPlan(")

        self.assertIn('"Подтвердить платный OpenAI TTS-запрос?"', source)
        self.assertIn(
            'Button("Подтвердить 1 платный запрос") { model.confirmPaidRequest() }',
            source,
        )
        self.assertIn('paidPlan?.decision == "READY_FOR_CONFIRMATION"', confirm_paid)
        self.assertIn("executePaidPlan(authorizedBy: .paidConfirmation)", confirm_paid)
        self.assertNotIn("confirmOpenAIPrepare", confirm_paid)

        self.assertIn("openAIIntentGate.consume(pendingOpenAIIntentToken)", confirm_cache)
        self.assertIn('paidPlan?.decision == "CACHE_ONLY"', confirm_cache)
        self.assertIn("executePaidPlan(authorizedBy: .cacheOnly(authorization))", confirm_cache)
        self.assertIn('"--execute-paid-plan", "--plan-id", plan.planID', execute)
        self.assertNotIn('runBridgeText(["--run-openai"]', source)

    def test_native_execution_selection_changes_invalidate_prepare_intent(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        invalidation = swift_function_body(source, "private func executionSelectionDidChange()")
        reload_body = swift_function_body(source, "func reload(preferredBookID:")
        cancel_body = swift_function_body(source, "func cancelOpenAIIntent()")

        for selection in ("selectedBookID", "selectedJobID", "selectedProfileID", "engine"):
            declaration = source.index(f"@Published var {selection}")
            observer = source[declaration : declaration + 220]
            self.assertIn("executionSelectionDidChange()", observer)
        self.assertIn("invalidateOpenAIIntent()", invalidation)
        self.assertIn("paidPlan = nil", invalidation)
        self.assertIn("invalidateOpenAIIntent()", reload_body)
        self.assertIn("invalidateOpenAIIntent()", cancel_body)

    def test_native_build_compiles_shared_contract_file(self):
        build = (ROOT / "native" / "build_native_app.sh").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/StudioContracts.swift"', build)
        self.assertIn('"$script_dir/AudiobookStudioApp.swift"', build)

    def test_native_add_book_uses_file_importer_and_offline_bridge_only(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        add_book = swift_function_body(source, "func addBook(sourceURL:")
        self.assertIn('Label("Добавить книгу", systemImage: "plus")', source)
        self.assertNotIn("Добавить книгу — скоро", source)
        self.assertIn(".fileImporter(", source)
        self.assertIn("allowedContentTypes: [.plainText]", source)
        self.assertIn('TextField("Название"', source)
        self.assertIn('TextField("Автор"', source)
        self.assertIn('TextField("ID / slug"', source)
        self.assertIn('"--add-book", "--source-file", sourceURL.path', add_book)
        self.assertIn("await reload(preferredBookID: result.bookID)", add_book)
        self.assertNotIn("--prepare-paid-run", add_book)
        self.assertNotIn("--execute-paid-plan", add_book)
        self.assertNotIn("--run-", add_book)
        self.assertIn("Подготовленных задач пока нет", source)
        self.assertIn("Source SHA-256", source)
        self.assertIn("Source integrity", source)
        self.assertIn("TTS working copy", source)
        self.assertIn("struct BookImportResult", contracts)
        self.assertIn('case sourceSHA256 = "source_sha256"', contracts)

    def test_native_book_text_preparation_has_local_gate_and_offline_bridge_only(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        request = swift_function_body(source, "func requestBookTextPreparation()")
        confirm = swift_function_body(source, "func confirmBookTextPreparation()")

        self.assertIn('Button("Подготовить текст") { model.requestBookTextPreparation() }', source)
        self.assertIn('Button("Подготовить заново") { model.requestBookTextPreparation() }', source)
        self.assertIn('"Подготовить текст книги?"', source)
        self.assertIn("Исходный файл не изменится", source)
        self.assertIn("только TTS working copy", source)
        self.assertIn("Платных и provider-запросов нет", source)
        self.assertIn("showBookTextPreparationConfirmation = true", request)
        self.assertNotIn("runBridge", request)
        self.assertIn('"--prepare-book-text", "--book", bookID', confirm)
        self.assertIn("!result.remoteRequestSent", confirm)
        self.assertNotIn("--prepare-paid-run", confirm)
        self.assertNotIn("--execute-paid-plan", confirm)
        self.assertNotIn("--run-", confirm)
        self.assertIn("Подготовка устарела", source)
        self.assertIn("Текст подготовлен", source)
        self.assertIn("struct BookTextPreparationResult", contracts)
        self.assertIn('case preparationStatus = "preparation_status"', contracts)

    def test_native_yandex_chapter_production_uses_separate_plan_and_confirmation(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        begin = swift_function_body(source, "func begin()")
        prepare = swift_function_body(source, "private func prepareYandexChapterRun()")
        execute = swift_function_body(source, "func confirmYandexChapterRun()")

        self.assertIn("prepareYandexChapterRun()", begin)
        self.assertNotIn("--execute-yandex-chapter-plan", begin)
        self.assertIn('"--prepare-yandex-chapter-run"', prepare)
        self.assertIn("!plan.remoteRequestSent", prepare)
        self.assertIn("currentYandexChapterSelection() == selection", prepare)
        self.assertIn("yandexChapterPlanSelection = selection", prepare)
        self.assertIn("showYandexChapterConfirmation = true", prepare)
        self.assertIn('"--execute-yandex-chapter-plan"', execute)
        self.assertIn('"--plan-digest", plan.planDigest', execute)
        self.assertIn("currentYandexChapterSelection() == plannedSelection", execute)
        self.assertIn("yandexChapterPlanSelection = nil", execute)
        self.assertIn('yandexChapterStatusText = ""', execute)
        self.assertIn("showYandexChapterConfirmation = false", execute)
        self.assertIn('"Озвучить подготовленную главу?"', source)
        self.assertIn("Новых запросов: максимум", source)
        self.assertIn("struct YandexChapterRunPlan", contracts)
        self.assertIn("struct YandexChapterRunResult", contracts)
        self.assertIn("Автоматический повтор запрещён", contracts)
        self.assertIn("if engine == .yandex, let plan = yandexChapterPlan", source)
        self.assertIn("return plan.billing", source)


if __name__ == "__main__":
    unittest.main()
