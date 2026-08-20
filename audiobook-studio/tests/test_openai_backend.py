from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import wave
from datetime import date, timedelta
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.common import atomic_write_json, inspect_pcm_wav
from backends.openai_client import (
    OpenAITTSBackend,
    load_approved_profile,
    make_fingerprint,
    read_credential_from_keychain,
    segment_text,
)
from backends.openai_pricing import OpenAIPricingConfig, build_preflight
from backends.openai_types import (
    OpenAIBackendConfig,
    OpenAICredential,
    OpenAITTSError,
    PaidExecutionBlocked,
)


def wav_bytes(*, channels: int = 1, sample_rate: int = 24_000, frames: int = 240) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * channels * frames)
    return output.getvalue()


class FakeResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None, status: int = 200):
        self._body = io.BytesIO(body)
        self.headers = headers or {}
        self.status = status
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        self.closed = True


def backend_config(root: Path, *, paid: bool = False, **limits: int) -> OpenAIBackendConfig:
    segmentation = {
        "target_chars": limits.get("target_chars", 900),
        "hard_chars": limits.get("hard_chars", 1200),
        "hard_utf8_bytes": limits.get("hard_utf8_bytes", 2000),
        "api_max_input_tokens": 2000,
        "sentence_pause_ms": 350,
        "paragraph_pause_ms": 700,
    }
    return OpenAIBackendConfig.from_mapping({
        "schema_version": 1,
        "engine": "openai_tts",
        "endpoint": "https://api.openai.com/v1/audio/speech",
        "keychain_service": "AudiobookStudio-OpenAI",
        "keychain_account": "tester",
        "cache_root": str(root / "cache"),
        "jobs_root": str(root / "jobs"),
        "request_timeout_seconds": 5,
        "paid_execution_enabled": paid,
        "segmentation": segmentation,
    })


def pricing(*, verified_at: date | None = None, max_age_days: int = 30) -> OpenAIPricingConfig:
    return OpenAIPricingConfig.from_mapping({
        "schema_version": 1,
        "engine": "openai_tts",
        "model": "gpt-4o-mini-tts",
        "currency": "USD",
        "text_input_per_million_tokens": "0.60",
        "audio_output_per_million_tokens": "12.00",
        "verified_at": (verified_at or date.today()).isoformat(),
        "source_url": "https://developers.openai.com/api/docs/models/gpt-4o-mini-tts",
        "max_age_days": max_age_days,
        "output_cost_estimate": "unavailable_without_calibration",
        "actual_cost_source": "provider_billing",
    })


class OpenAIBackendTests(unittest.TestCase):
    def test_01_approved_profiles_are_onyx_and_cedar(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = OpenAITTSBackend(backend_config(Path(directory)))
            self.assertEqual(
                [profile["profile_id"] for profile in backend.list_voices()],
                ["openai_onyx", "openai_cedar"],
            )

    def test_02_nonapproved_profile_is_rejected(self):
        with self.assertRaises(OpenAITTSError) as raised:
            load_approved_profile("openai_female")
        self.assertEqual(raised.exception.category, "profile")

    def test_03_keychain_mock_success(self):
        result = subprocess.CompletedProcess([], 0, "sk-test-key-12345678901234567890\n", "")
        credential = read_credential_from_keychain(
            "AudiobookStudio-OpenAI", "tester", runner=mock.Mock(return_value=result)
        )
        self.assertEqual(credential.source_type, "macos_keychain")
        self.assertTrue(credential.value.startswith("sk-test"))

    def test_04_keychain_missing_is_safe(self):
        result = subprocess.CompletedProcess([], 44, "", "not found")
        with self.assertRaises(OpenAITTSError) as raised:
            read_credential_from_keychain(
                "AudiobookStudio-OpenAI", "tester", runner=mock.Mock(return_value=result)
            )
        self.assertEqual(raised.exception.category, "credentials")
        self.assertNotIn("not found", str(raised.exception))

    def test_05_request_payload_has_exact_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = OpenAITTSBackend(backend_config(Path(directory)))
            payload = backend.build_synthesis_payload("  Привет   миру.  ", "openai_onyx")
        self.assertEqual(set(payload), {"model", "input", "voice", "instructions", "response_format"})
        self.assertEqual(payload["model"], "gpt-4o-mini-tts")
        self.assertEqual(payload["input"], "Привет миру.")
        self.assertEqual(payload["voice"], "onyx")
        self.assertEqual(payload["response_format"], "wav")

    def test_06_stable_instructions_come_from_voice_library(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = OpenAITTSBackend(backend_config(Path(directory)))
            payload = backend.build_synthesis_payload("Текст.", "openai_cedar")
        self.assertEqual(payload["instructions"], load_approved_profile("openai_cedar")["instructions"])
        self.assertIn("professional audiobook narrator", payload["instructions"])

    def test_07_segmentation_prefers_paragraph_and_sentence_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            config = backend_config(Path(directory), target_chars=25, hard_chars=45, hard_utf8_bytes=100)
            segments = segment_text("Первое предложение. Второе предложение.\n\nНовый абзац.", config)
        self.assertGreaterEqual(len(segments), 3)
        self.assertEqual(segments[-1].pause_after_ms, 0)
        self.assertEqual(segments[-1].paragraph_index, 2)

    def test_08_segmentation_respects_character_and_utf8_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            config = backend_config(Path(directory), target_chars=35, hard_chars=45, hard_utf8_bytes=70)
            segments = segment_text(" ".join(["слово"] * 80), config)
        self.assertTrue(segments)
        self.assertTrue(all(len(item.text) <= 45 for item in segments))
        self.assertTrue(all(len(item.text.encode("utf-8")) <= 70 for item in segments))

    def test_09_segmentation_never_cuts_words(self):
        with tempfile.TemporaryDirectory() as directory:
            config = backend_config(Path(directory), target_chars=12, hard_chars=15, hard_utf8_bytes=30)
            source_words = ["один", "два", "три", "четыре", "пять"]
            segments = segment_text(" ".join(source_words), config)
        self.assertEqual(" ".join(item.text for item in segments).split(), source_words)

    def test_10_single_oversized_word_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = backend_config(Path(directory), target_chars=10, hard_chars=12, hard_utf8_bytes=24)
            with self.assertRaises(OpenAITTSError) as raised:
                segment_text("сверхдлинноесловобезпробелов", config)
        self.assertEqual(raised.exception.category, "segment_limit")

    def test_11_fingerprint_is_stable_after_space_normalization(self):
        profile = load_approved_profile("openai_onyx")
        self.assertEqual(make_fingerprint("Точный  текст", profile), make_fingerprint(" Точный текст ", profile))

    def test_12_fingerprint_changes_for_every_contract_field(self):
        profile = load_approved_profile("openai_onyx")
        baseline = make_fingerprint("Текст", profile)
        self.assertNotEqual(baseline, make_fingerprint("Другой текст", profile))
        for field, value in (
            ("voice", "cedar"),
            ("model", "different-model"),
            ("instructions", profile["instructions"] + " Extra."),
            ("response_format", "mp3"),
        ):
            changed = dict(profile)
            changed[field] = value
            self.assertNotEqual(baseline, make_fingerprint("Текст", changed), field)

    def test_13_valid_cache_hit_sends_zero_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = backend_config(root)
            profile = load_approved_profile("openai_onyx")
            fingerprint = make_fingerprint("Текст", profile)
            config.cache_root.mkdir(parents=True)
            (config.cache_root / f"{fingerprint}.wav").write_bytes(wav_bytes())
            opener = mock.Mock(side_effect=AssertionError("network attempted"))
            credential = mock.Mock(side_effect=AssertionError("credential read"))
            result = OpenAITTSBackend(config, opener=opener, credential_loader=credential).synthesize_segment(
                "Текст", root / "out.wav", profile_id="openai_onyx"
            )
            self.assertTrue(result.cached)
            inspect_pcm_wav(root / "out.wav")
            opener.assert_not_called()
            credential.assert_not_called()

    def test_14_corrupt_cache_is_a_miss_and_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = backend_config(root, paid=True)
            profile = load_approved_profile("openai_onyx")
            fingerprint = make_fingerprint("Текст", profile)
            config.cache_root.mkdir(parents=True)
            cache_path = config.cache_root / f"{fingerprint}.wav"
            cache_path.write_bytes(b"broken")
            opener = mock.Mock(return_value=FakeResponse(wav_bytes()))
            backend = OpenAITTSBackend(
                config, opener=opener,
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            result = backend.synthesize_segment("Текст", root / "out.wav", profile_id="openai_onyx")
            self.assertFalse(result.cached)
            self.assertEqual(opener.call_count, 1)
            inspect_pcm_wav(cache_path)

    def test_15_paid_gate_fails_before_credential_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            credential = mock.Mock(side_effect=AssertionError("credential read"))
            opener = mock.Mock(side_effect=AssertionError("network attempted"))
            backend = OpenAITTSBackend(backend_config(Path(directory)), credential_loader=credential, opener=opener)
            with self.assertRaises(PaidExecutionBlocked):
                backend.synthesize_segment("Текст", Path(directory) / "out.wav", profile_id="openai_onyx")
            credential.assert_not_called()
            opener.assert_not_called()

    def test_16_preflight_is_cache_aware_and_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = backend_config(root)
            profile = load_approved_profile("openai_onyx")
            fingerprint = make_fingerprint("Первый текст.", profile)
            config.cache_root.mkdir(parents=True)
            (config.cache_root / f"{fingerprint}.wav").write_bytes(wav_bytes())
            backend = OpenAITTSBackend(
                config,
                credential_loader=mock.Mock(side_effect=AssertionError("credential read")),
                opener=mock.Mock(side_effect=AssertionError("network attempted")),
            )
            result = backend.preflight("Первый текст.", profile_id="openai_onyx", pricing=pricing())
        self.assertEqual(result["known"]["cache_hits"], 1)
        self.assertEqual(result["segment_plan"][0]["cache_status"], "HIT")
        self.assertFalse(result["remote_request_sent"])

    def test_17_manifest_creation_has_required_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = OpenAITTSBackend(backend_config(root))
            manifest, preflight = backend.prepare_job(
                "Текст.", root / "job", job_id="short-test", profile_id="openai_cedar", pricing=pricing()
            )
            persisted = json.loads((root / "job" / "MANIFEST.json").read_text(encoding="utf-8"))
        entry = persisted["segments"]["s0001"]
        self.assertEqual(manifest["automatic_retry_count"], 0)
        self.assertEqual(entry["state"], "PENDING")
        self.assertTrue({
            "segment_id", "text_sha256", "fingerprint", "provider", "profile_id", "model", "voice",
            "state", "cache_status", "output_path", "request_id", "attempt_count", "started_at",
            "finished_at", "error_category",
        } <= set(entry))
        self.assertFalse(preflight["allowed_to_start"])

    def test_18_resume_succeeded_valid_output_skips_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = backend_config(root, paid=True)
            backend = OpenAITTSBackend(config, opener=mock.Mock(side_effect=AssertionError("network attempted")))
            manifest, _ = backend.prepare_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            entry = manifest["segments"]["s0001"]
            Path(entry["output_path"]).write_bytes(wav_bytes())
            entry["state"] = "SUCCEEDED"
            atomic_write_json(root / "job" / "MANIFEST.json", manifest)
            path = backend.run_text_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["state"], "SUCCEEDED")

    def test_19_resume_inflight_with_valid_output_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = OpenAITTSBackend(backend_config(root, paid=True))
            manifest, _ = backend.prepare_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            entry = manifest["segments"]["s0001"]
            Path(entry["output_path"]).write_bytes(wav_bytes())
            entry["state"] = "IN_FLIGHT"
            atomic_write_json(root / "job" / "MANIFEST.json", manifest)
            path = backend.run_text_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["segments"]["s0001"]["state"], "SUCCEEDED")

    def test_20_resume_inflight_without_artifact_becomes_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = OpenAITTSBackend(backend_config(root, paid=True))
            manifest, _ = backend.prepare_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            manifest["segments"]["s0001"]["state"] = "IN_FLIGHT"
            atomic_write_json(root / "job" / "MANIFEST.json", manifest)
            with self.assertRaises(OpenAITTSError) as raised:
                backend.run_text_job(
                    "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
                )
            persisted = json.loads((root / "job" / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(raised.exception.state, "AMBIGUOUS")
        self.assertEqual(persisted["segments"]["s0001"]["state"], "AMBIGUOUS")

    def test_21_existing_ambiguous_is_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opener = mock.Mock(side_effect=AssertionError("network attempted"))
            backend = OpenAITTSBackend(backend_config(root, paid=True), opener=opener)
            manifest, _ = backend.prepare_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            manifest["segments"]["s0001"]["state"] = "AMBIGUOUS"
            atomic_write_json(root / "job" / "MANIFEST.json", manifest)
            with self.assertRaises(OpenAITTSError) as raised:
                backend.run_text_job(
                    "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
                )
        self.assertEqual(raised.exception.state, "AMBIGUOUS")
        opener.assert_not_called()

    def test_22_timeout_is_ambiguous_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opener = mock.Mock(side_effect=TimeoutError("timeout"))
            backend = OpenAITTSBackend(
                backend_config(root, paid=True), opener=opener,
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            with self.assertRaises(OpenAITTSError) as raised:
                backend.synthesize_segment("Текст", root / "out.wav", profile_id="openai_onyx")
        self.assertEqual(raised.exception.state, "AMBIGUOUS")
        self.assertEqual(opener.call_count, 1)
        self.assertFalse((root / "out.wav").exists())

    def test_23_truncated_stream_is_ambiguous_and_part_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = wav_bytes()
            response = FakeResponse(body, headers={"Content-Length": str(len(body) + 5), "x-request-id": "req-truncated"})
            backend = OpenAITTSBackend(
                backend_config(root, paid=True), opener=mock.Mock(return_value=response),
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            with self.assertRaises(OpenAITTSError) as raised:
                backend.synthesize_segment("Текст", root / "out.wav", profile_id="openai_onyx")
            self.assertFalse((root / "out.wav.part").exists())
            self.assertFalse((root / "out.wav").exists())
        self.assertEqual(raised.exception.state, "AMBIGUOUS")
        self.assertEqual(raised.exception.request_id, "req-truncated")

    def test_23b_truncated_wav_without_content_length_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = wav_bytes()
            backend = OpenAITTSBackend(
                backend_config(root, paid=True),
                opener=mock.Mock(return_value=FakeResponse(body[:-8], headers={"x-request-id": "req-eof"})),
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            with self.assertRaises(OpenAITTSError) as raised:
                backend.synthesize_segment("Текст", root / "out.wav", profile_id="openai_onyx")
        self.assertEqual(raised.exception.state, "AMBIGUOUS")
        self.assertEqual(raised.exception.category, "truncated_response")
        self.assertEqual(raised.exception.request_id, "req-eof")

    def test_24_deterministic_http_client_error_is_failed_and_key_is_not_exposed(self):
        secret = "sk-secret-12345678901234567890"
        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/audio/speech", 401, "Unauthorized",
            {"x-request-id": "req-401"}, io.BytesIO(b""),
        )
        with tempfile.TemporaryDirectory() as directory:
            backend = OpenAITTSBackend(
                backend_config(Path(directory), paid=True), opener=mock.Mock(side_effect=error),
                credential_loader=lambda *_: OpenAICredential(secret),
            )
            with self.assertRaises(OpenAITTSError) as raised:
                backend.synthesize_segment("Текст", Path(directory) / "out.wav", profile_id="openai_onyx")
        diagnostic = json.dumps(raised.exception.to_dict())
        self.assertEqual(raised.exception.state, "FAILED")
        self.assertEqual(raised.exception.request_id, "req-401")
        self.assertNotIn(secret, diagnostic)

    def test_25_invalid_wav_is_rejected_without_final_or_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = backend_config(root, paid=True)
            backend = OpenAITTSBackend(
                config, opener=mock.Mock(return_value=FakeResponse(b"not a wav")),
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            with self.assertRaises(OpenAITTSError) as raised:
                backend.synthesize_segment("Текст", root / "out.wav", profile_id="openai_onyx")
            self.assertFalse((root / "out.wav").exists())
            self.assertEqual(list(config.cache_root.glob("*.wav")), [])
        self.assertEqual(raised.exception.category, "audio_integrity")

    def test_26_valid_response_is_atomically_finalized_with_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = OpenAITTSBackend(
                backend_config(root, paid=True), opener=mock.Mock(return_value=FakeResponse(wav_bytes(channels=2))),
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            result = backend.synthesize_segment("Текст", root / "out.wav", profile_id="openai_cedar")
            self.assertTrue((root / "out.wav").is_file())
            self.assertFalse((root / "out.wav.part").exists())
            self.assertEqual(result.wav_metadata["channels"], 2)

    def test_27_request_id_is_persisted_in_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = OpenAITTSBackend(
                backend_config(root, paid=True),
                opener=mock.Mock(return_value=FakeResponse(wav_bytes(), headers={"x-request-id": "req-success"})),
                credential_loader=lambda *_: OpenAICredential("sk-test-12345678901234567890"),
            )
            path = backend.run_text_job(
                "Текст.", root / "job", job_id="job", profile_id="openai_onyx", pricing=pricing()
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["segments"]["s0001"]["request_id"], "req-success")
        self.assertEqual(manifest["segments"]["s0001"]["attempt_count"], 1)

    def test_28_pricing_freshness_and_stale_state(self):
        current = pricing(verified_at=date.today(), max_age_days=30)
        stale = pricing(verified_at=date.today() - timedelta(days=31), max_age_days=30)
        self.assertFalse(current.is_stale())
        self.assertTrue(stale.is_stale())

    def test_29_preflight_labels_estimate_actual_and_unavailable_honestly(self):
        result = build_preflight(
            ["Текст"], instructions="Instruction", pricing=pricing(), paid_execution_enabled=True
        )
        self.assertEqual(result["estimated"]["label"], "estimate")
        self.assertEqual(result["unknown"]["label"], "unavailable")
        self.assertEqual(result["actual"]["label"], "actual")
        self.assertEqual(result["actual"]["status"], "unavailable")
        self.assertIsNone(result["actual"]["total_charge_usd"])
        self.assertEqual(result["actual"]["source"], "provider_billing")

    def test_30_stale_pricing_blocks_even_when_paid_flag_is_true(self):
        result = build_preflight(
            ["Текст"], instructions="Instruction",
            pricing=pricing(verified_at=date.today() - timedelta(days=31)),
            paid_execution_enabled=True,
        )
        self.assertFalse(result["allowed_to_start"])
        self.assertEqual(result["blocked_reason"], "stale_pricing")

    def test_31_runner_status_and_preflight_are_offline(self):
        status = subprocess.run(
            [sys.executable, str(ROOT / "openai_backend_runner.py"), "--status"],
            check=False, capture_output=True, text=True,
        )
        preflight = subprocess.run(
            [
                sys.executable, str(ROOT / "openai_backend_runner.py"), "--preflight",
                "--book", "demo-book.json", "--job", "short-test", "--profile-id", "openai_onyx",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        self.assertFalse(json.loads(status.stdout)["remote_request_sent"])
        result = json.loads(preflight.stdout)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["allowed_to_start"])

    def test_32_runner_paid_execution_is_blocked_before_manifest(self):
        completed = subprocess.run(
            [
                sys.executable, str(ROOT / "openai_backend_runner.py"), "--run",
                "--book", "demo-book.json", "--job", "short-test", "--profile-id", "openai_cedar",
            ],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stderr)["error"], "paid_execution_gate")
        self.assertFalse(json.loads(completed.stderr)["remote_request_sent"])


if __name__ == "__main__":
    unittest.main()
