from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
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
        self.assertIn("executionSelectionGeneration &+= 1", invalidation)
        self.assertIn("paidPlan = nil", invalidation)
        self.assertIn("invalidateOpenAIIntent()", reload_body)
        self.assertIn("invalidateOpenAIIntent()", cancel_body)

    def test_native_build_compiles_shared_contract_file(self):
        build = (ROOT / "native" / "build_native_app.sh").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/StudioContracts.swift"', build)
        self.assertIn('"$script_dir/AudioQAContracts.swift"', build)
        self.assertIn('"$script_dir/EmbeddedAudioPlayer.swift"', build)
        self.assertIn('"$script_dir/AudiobookStudioApp.swift"', build)
        self.assertIn("-framework AVFoundation", build)

    def test_native_audio_qa_is_wired_to_current_authority_and_exact_review_identity(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        decide = swift_function_body(source, "func decideAudioQA(_ decision:")
        downstream = swift_function_body(source, "private func refreshAudioQADownstream(")
        open_current = swift_function_body(source, "func openCurrentAudioForQA()")
        open_target = swift_function_body(source, "func openOpenAIQATarget(")
        load_targets = swift_function_body(source, "private func loadOpenAIQATargets(")
        load_audio = swift_function_body(
            source,
            "private func loadAudioQA(\n        provider: String,\n        bookID:",
        )
        regenerate = decide[decide.index('decision == "REGENERATE_REQUESTED"') :]

        self.assertIn('"--audio-qa-current"', source)
        self.assertIn('"--audio-qa-decide"', source)
        self.assertIn('"--audio-qa-downstream"', source)
        self.assertIn('Button("Открыть готовое аудио для проверки")', source)
        self.assertIn('playTitle: "Прослушать точный WAV"', source)
        self.assertIn('Button("Одобрить")', source)
        self.assertIn('Button("Отклонить", role: .destructive)', source)
        self.assertIn('Button("Запросить перегенерацию")', source)
        self.assertIn("audioQAPlaybackIdentity == envelope.record.identity", decide)
        self.assertIn("audioPlayer.validateLoadedIdentity(rehash: true)", decide)
        self.assertIn("audioQASelectionMatches", decide)
        self.assertNotIn("selectedBookID == envelope.authority.bookSlug", decide)
        self.assertIn('"--reviewed-audio-sha256", sha', decide)
        self.assertIn('"--reviewed-path-identity", envelope.record.identity.pathIdentity', decide)
        self.assertIn('"--reviewed-fingerprint", fingerprint', decide)
        self.assertIn("AudioPlaybackBinding(", source)
        self.assertIn('role: "qa-source"', source)
        self.assertIn("audioPlayer.loadAndPlay(binding)", source)
        self.assertIn("audioPlayer.clear()", source)
        self.assertNotIn("NSWorkspace.shared.open(url)", source)
        self.assertIn("guard !result.remoteRequestSent", source)
        self.assertNotIn("--prepare-paid-run", regenerate)
        self.assertNotIn("--prepare-yandex-chapter-run", regenerate)
        self.assertNotIn("--execute-paid-plan", regenerate)
        self.assertNotIn("--execute-yandex-chapter-plan", regenerate)
        for operation in (open_current, open_target, decide):
            self.assertIn(
                "let expectedSelectionGeneration = executionSelectionGeneration",
                operation,
            )
        self.assertIn("audioPlayer.clear()", open_current)
        self.assertIn("audioPlayer.clear()", open_target)
        self.assertGreaterEqual(
            load_targets.count(
                "executionSelectionGeneration == expectedSelectionGeneration"
            ),
            3,
        )
        self.assertGreaterEqual(
            load_audio.count(
                "executionSelectionGeneration == expectedSelectionGeneration"
            ),
            4,
        )
        self.assertGreaterEqual(
            decide.count("executionSelectionGeneration == expectedSelectionGeneration"),
            3,
        )
        self.assertGreaterEqual(
            source.count("expectedSelectionGeneration: expectedSelectionGeneration"),
            8,
        )
        self.assertIn("let expectedEngine = engine", downstream)
        self.assertIn("let expectedBookSlug = selectedBook?.slug", downstream)
        self.assertGreaterEqual(downstream.count("engine == expectedEngine"), 2)
        self.assertGreaterEqual(downstream.count("selectedBook?.slug == expectedBookSlug"), 2)
        self.assertGreaterEqual(
            downstream.count(
                "executionSelectionGeneration == expectedSelectionGeneration"
            ),
            2,
        )
        self.assertIn("result.authority == authority", downstream)

    def test_qwen_current_authority_discovers_canonical_profile_directory(self):
        producer = (ROOT / "studio.py").read_text(encoding="utf-8")
        self.assertIn("canonical_book_slug = book_path.stem", producer)
        self.assertIn(
            "create_unique_output(cfg, canonical_book_slug, job_id, speaker)",
            producer,
        )
        profile_path = bridge.WORKSPACE_PATHS.books_root / "demo-book.json"
        original = profile_path.read_bytes()
        try:
            profile = json.loads(original)
            profile.pop("slug", None)
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            job = profile["jobs"]["short-test"]
            config = json.loads((ROOT / "studio-config.json").read_text(encoding="utf-8"))
            output_dir = bridge.WORKSPACE_PATHS.qwen_output_root / "demo-book/20260827-test"
            audio_path = output_dir / "demo-book__short-test__Vivian.wav"
            output_dir.mkdir(parents=True, exist_ok=True)
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24_000)
                audio.writeframes(b"\x00\x10" * 24_000)
            report_path = output_dir / "RUN-REPORT.json"
            report_path.write_text(json.dumps({
                "book_profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                "job": "short-test",
                "job_label": job["label"],
                "speaker": "Vivian",
                "model": config["model"],
                "generation": config["default_generation"],
                "audiobook_instruct": profile["audiobook_instruct"],
                "segments": [{"id": segment["id"], "seed": 1} for segment in job["segments"]],
                "segment_count": len(job["segments"]),
                "sample_rate": 24_000,
                "joined_wav": audio_path.name,
            }, ensure_ascii=False), encoding="utf-8")

            authority = bridge._audio_qa_authority(
                provider="qwen",
                book_name="demo-book.json",
                job_id="short-test",
                profile_id="qwen_vivian",
            )
            self.assertEqual(authority.book_slug, "demo-book")
            self.assertEqual(authority.manifest_path, report_path.resolve())
            self.assertEqual(authority.audio_path, audio_path.resolve())
        finally:
            profile_path.write_bytes(original)

    def test_yandex_current_bridge_discovers_real_historical_root_before_symlink_alias(self):
        from backends.yandex_speechkit import (
            YandexSpeechKitBackend,
            load_backend_config,
            make_fingerprint,
        )

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            books = workspace / "books"
            books.mkdir(parents=True)
            shutil.copy2(ROOT / "books/demo-book.json", books / "demo-book.json")
            env = dict(
                os.environ,
                AUDIOBOOK_STUDIO_HOME=str(workspace),
                PYTHONDONTWRITEBYTECODE="1",
            )
            with mock.patch.dict(os.environ, env, clear=True):
                backend = YandexSpeechKitBackend(load_backend_config(ROOT / "yandex-config.json"))

            library = BookLibrary(books)
            book = library.load_book_for_execution("demo-book.json")
            job = book["jobs"]["short-test"]
            text = "\n\n".join(segment["text"].strip() for segment in job["segments"])
            segments = backend.segment(text)

            historical_root = workspace / "runtime/studio-workspace/renders-yandex"
            run_dir = historical_root / "demo-book/short-test/yandex_lera"
            audio_path = run_dir / "short-test__lera-neutral-1.04.wav"
            run_dir.mkdir(parents=True)
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(22_050)
                audio.writeframes(b"\x00\x10" * (22_050 * 5))

            manifest_path = run_dir / "MANIFEST.json"
            manifest_path.write_text(json.dumps({
                "schema_version": 1,
                "engine": "yandex_speechkit_v3",
                "job_id": "short-test",
                "status": "DONE",
                "profile": {
                    "voice": backend.profile.voice,
                    "role": backend.profile.role,
                    "speed": str(backend.profile.speed),
                },
                "segmentation": backend.manifest_segmentation(),
                "request_routing": backend.request_routing_identity(),
                "segments": {
                    segment.segment_id: {
                        "status": "DONE",
                        "fingerprint": make_fingerprint(segment.text, backend.profile),
                        "text": segment.text,
                        "result": {"sample_rate_hz": 22_050},
                    }
                    for segment in segments
                },
                "joined_wav": audio_path.name,
            }, ensure_ascii=False), encoding="utf-8")

            configured_parent = workspace / "renders"
            configured_parent.mkdir()
            (configured_parent / "yandex").symlink_to(
                Path("../runtime/studio-workspace/renders-yandex"),
                target_is_directory=True,
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audiobook_studio_app_runner.py"),
                    "--audio-qa-current",
                    "--provider", "yandex",
                    "--book", "demo-book.json",
                    "--job", "short-test",
                    "--profile-id", "yandex_lera",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["authority"]["manifest_path"], str(manifest_path.resolve()))
            self.assertEqual(result["authority"]["audio_path"], str(audio_path.resolve()))
            self.assertEqual(result["authority"]["profile_id"], "yandex_lera")
            self.assertFalse(result["remote_request_sent"])

            # The compatibility decision is valid for the whole authority
            # operation, not merely at its first path check. Replacing the
            # alias while the resolver runs must invalidate the result even
            # when the replacement still reaches the historical directory.
            paths = load_workspace_paths(env=env)
            real_resolver = bridge.resolve_yandex_authority

            def mutate_alias_then_resolve(**kwargs):
                (configured_parent / "yandex").unlink()
                (configured_parent / "yandex").symlink_to(
                    Path("../runtime/studio-workspace/./renders-yandex"),
                    target_is_directory=True,
                )
                return real_resolver(**kwargs)

            with (
                mock.patch.object(bridge, "WORKSPACE_PATHS", paths),
                mock.patch.object(bridge, "BOOK_LIBRARY", library),
                mock.patch.object(
                    bridge,
                    "_load_yandex_offline",
                    return_value=(backend, None, None),
                ),
                mock.patch.object(
                    bridge,
                    "resolve_yandex_authority",
                    side_effect=mutate_alias_then_resolve,
                ),
            ):
                with self.assertRaisesRegex(
                    bridge.AudioQAAuthorityError,
                    "changed during authority resolution",
                ):
                    bridge._audio_qa_authority(
                        provider="yandex",
                        book_name="demo-book.json",
                        job_id="short-test",
                        profile_id="yandex_lera",
                    )

            # Restore the exact direct compatibility link for the remaining
            # subprocess scenarios.
            (configured_parent / "yandex").unlink()
            (configured_parent / "yandex").symlink_to(
                Path("../runtime/studio-workspace/renders-yandex"),
                target_is_directory=True,
            )

            # Reaching the historical root through another symlink is not the
            # one supported direct alias identity and must fail closed.
            (configured_parent / "yandex").unlink()
            intermediate = workspace / "external-hop"
            intermediate.symlink_to(historical_root, target_is_directory=True)
            (configured_parent / "yandex").symlink_to(
                Path("../external-hop"),
                target_is_directory=True,
            )
            multi_hop = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audiobook_studio_app_runner.py"),
                    "--audio-qa-current",
                    "--provider", "yandex",
                    "--book", "demo-book.json",
                    "--job", "short-test",
                    "--profile-id", "yandex_lera",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(multi_hop.returncode, 2)
            self.assertIn("symlink components", multi_hop.stderr)
            (configured_parent / "yandex").unlink()
            intermediate.unlink()

            # A canonical-looking leaf alias reached through a symlinked
            # parent is not the known workspace entry. Parent components are
            # part of the compatibility identity and must fail closed.
            configured_parent.rmdir()
            external_parent = workspace / "external-renders"
            external_parent.mkdir()
            (external_parent / "yandex").symlink_to(
                Path("../runtime/studio-workspace/renders-yandex"),
                target_is_directory=True,
            )
            configured_parent.symlink_to(external_parent, target_is_directory=True)
            symlinked_parent = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audiobook_studio_app_runner.py"),
                    "--audio-qa-current",
                    "--provider", "yandex",
                    "--book", "demo-book.json",
                    "--job", "short-test",
                    "--profile-id", "yandex_lera",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(symlinked_parent.returncode, 2)
            self.assertIn("parent cannot contain symlink components", symlinked_parent.stderr)
            configured_parent.unlink()
            (external_parent / "yandex").unlink()
            external_parent.rmdir()
            configured_parent.mkdir()

            # A different symlink target is not the known compatibility alias
            # and must not fall back to the valid historical artifact.
            external_root = workspace / "external-yandex"
            external_root.mkdir()
            (configured_parent / "yandex").symlink_to(
                Path("../external-yandex"),
                target_is_directory=True,
            )
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audiobook_studio_app_runner.py"),
                    "--audio-qa-current",
                    "--provider", "yandex",
                    "--book", "demo-book.json",
                    "--job", "short-test",
                    "--profile-id", "yandex_lera",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("symlink components", rejected.stderr)

            # If a newer real configured output exists as well, it must take
            # precedence over the supported historical fallback.
            (configured_parent / "yandex").unlink()
            current_dir = configured_parent / "yandex/demo-book/short-test/yandex_lera"
            current_dir.mkdir(parents=True)
            missing_current = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audiobook_studio_app_runner.py"),
                    "--audio-qa-current",
                    "--provider", "yandex",
                    "--book", "demo-book.json",
                    "--job", "short-test",
                    "--profile-id", "yandex_lera",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(missing_current.returncode, 2)
            self.assertIn("manifest was not found", missing_current.stderr)
            current_audio = current_dir / audio_path.name
            shutil.copy2(audio_path, current_audio)
            current_manifest = current_dir / "MANIFEST.json"
            shutil.copy2(manifest_path, current_manifest)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audiobook_studio_app_runner.py"),
                    "--audio-qa-current",
                    "--provider", "yandex",
                    "--book", "demo-book.json",
                    "--job", "short-test",
                    "--profile-id", "yandex_lera",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            current_result = json.loads(completed.stdout)
            self.assertEqual(
                current_result["authority"]["manifest_path"],
                str(current_manifest.resolve()),
            )
            self.assertEqual(
                current_result["authority"]["audio_path"],
                str(current_audio.resolve()),
            )
            self.assertFalse(current_result["remote_request_sent"])

    def test_native_openai_cache_only_requires_explicit_exact_target_when_ambiguous(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        contracts = (ROOT / "native" / "StudioContracts.swift").read_text(encoding="utf-8")
        execute = swift_function_body(source, "private func executePaidPlan(")
        select = swift_function_body(source, "func openOpenAIQATarget(")
        reopen = swift_function_body(source, "private func loadOpenAIQATargets(")
        self.assertIn("let qaTargets: [OpenAIQATarget]?", contracts)
        self.assertIn("struct OpenAIQATargetList: Codable", contracts)
        self.assertIn("targets.count == 1", execute)
        self.assertIn("targets.count > 1", execute)
        self.assertIn("openAIQATargets.contains(target)", select)
        self.assertIn("expectedTarget: target", select)
        self.assertIn('"--audio-qa-openai-targets"', reopen)
        self.assertIn("guard !result.remoteRequestSent", reopen)
        self.assertIn("currentOpenAISelection() == selection", reopen)
        self.assertIn(
            "if model.engine == .openai, model.openAIQATargets.count > 1 {",
            source,
        )
        self.assertIn('Button("Обновить список из manifest")', source)
        self.assertIn("Проверить сегмент", source)

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

    def test_openai_chapter_assembly_reports_incomplete_approved_set_without_publish(self):
        authority = SimpleNamespace(
            audio_path=self.workspace / "jobs/s0001.wav",
            manifest_path=self.workspace / "jobs/MANIFEST.json",
        )
        segment_set = SimpleNamespace(
            expected_segment_ids=("s0001", "s0002", "s0003"),
            produced_segment_ids=("s0001",),
            authorities=(authority,),
            blockers=({"segment_id": "s0002", "reason": "missing_or_stale_output"},),
            prepared_text_identity="prepared-identity",
            complete=False,
        )
        qa = {
            "authority": {"audio_path": str(authority.audio_path)},
            "record": {"manual_state": "APPROVED"},
            "eligible": True,
        }
        resolution = SimpleNamespace(to_dict=lambda: {
            "available": False, "path": None, "version": None, "source": "unavailable"
        })
        service = SimpleNamespace(_resolution=lambda: resolution)
        backend = SimpleNamespace(config=SimpleNamespace(jobs_root=self.workspace / "jobs"))
        with mock.patch("backends.openai_tts.OpenAITTSBackend", return_value=backend), mock.patch(
            "audiobook_studio_app_runner.resolve_openai_segment_set", return_value=segment_set
        ), mock.patch("audiobook_studio_app_runner.audio_qa_current", return_value=qa), mock.patch(
            "audiobook_studio_app_runner._chapter_assembly_service", return_value=service
        ):
            result = bridge.chapter_assembly_current(
                action="assemble",
                provider="openai",
                book_name="demo-book",
                job_id="short-test",
                profile_id="openai_cedar",
            )
        self.assertEqual(result["assembly"]["decision"], "BLOCKED")
        self.assertEqual(result["assembly"]["blockers"], ["incomplete_approved_segment_set"])
        self.assertEqual(result["assembly"]["segment_counts"], {
            "expected": 3, "produced": 1, "approved": 1, "blocked": 2,
        })
        self.assertEqual(result["provider_requests"], 0)

    def test_openai_chapter_assembly_requires_qa_for_every_produced_segment(self):
        authorities = tuple(SimpleNamespace(
            audio_path=self.workspace / f"jobs/s{index:04d}.wav",
            manifest_path=self.workspace / "jobs/MANIFEST.json",
        ) for index in range(1, 4))
        segment_set = SimpleNamespace(
            expected_segment_ids=("s0001", "s0002", "s0003"),
            produced_segment_ids=("s0001", "s0002", "s0003"),
            authorities=authorities,
            blockers=(),
            prepared_text_identity="prepared-identity",
            complete=True,
        )
        qa_items = [{
            "authority": {"segment_id": f"s{index:04d}", "audio_path": str(authority.audio_path)},
            "record": {"manual_state": "APPROVED" if index != 2 else "UNREVIEWED"},
            "eligible": index != 2,
        } for index, authority in enumerate(authorities, start=1)]
        resolution = SimpleNamespace(to_dict=lambda: {
            "available": False, "path": None, "version": None, "source": "unavailable"
        })
        service = SimpleNamespace(_resolution=lambda: resolution)
        backend = SimpleNamespace(config=SimpleNamespace(jobs_root=self.workspace / "jobs"))
        with mock.patch("backends.openai_tts.OpenAITTSBackend", return_value=backend), mock.patch(
            "audiobook_studio_app_runner.resolve_openai_segment_set", return_value=segment_set
        ), mock.patch("audiobook_studio_app_runner.audio_qa_current", side_effect=qa_items), mock.patch(
            "audiobook_studio_app_runner._chapter_assembly_service", return_value=service
        ):
            result = bridge.chapter_assembly_current(
                action="status", provider="openai", book_name="demo-book",
                job_id="short-test", profile_id="openai_cedar",
            )
        self.assertEqual(result["assembly"]["segment_counts"]["approved"], 2)
        self.assertEqual(result["assembly"]["decision"], "BLOCKED")
        self.assertEqual(result["assembly"]["segment_blockers"], [{
            "segment_id": "s0002", "reason": "qa_not_currently_approved",
        }])

    def test_native_chapter_assembly_passes_exact_selected_audio_identity(self):
        source = (ROOT / "native" / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        refresh = swift_function_body(source, "private func refreshChapterAssembly(")
        assemble = swift_function_body(source, "func assembleCurrentChapter()")
        for body in (refresh, assemble):
            self.assertIn('"--audio-path", authority.audioPath', body)
            self.assertIn('"--manifest-path", authority.manifestPath', body)


if __name__ == "__main__":
    unittest.main()
