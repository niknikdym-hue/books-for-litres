from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import wave
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASTING_DIR = ROOT / "casting" / "openai"
RUNNER_PATH = CASTING_DIR / "run_openai_casting.py"
CONFIG_PATH = CASTING_DIR / "openai-casting-config.json"

SPEC = importlib.util.spec_from_file_location("openai_casting_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def wav_bytes(*, seconds: float = 1.0, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b"\x00" * int(seconds * rate * channels * width))
    return buffer.getvalue()


class OpenAICastingOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config, cls.text, cls.text_path = module.load_and_validate(CONFIG_PATH)

    def test_01_voice_list_is_exact_and_complete(self):
        self.assertEqual(self.config["voices"], module.EXPECTED_VOICES)
        self.assertEqual(len(self.config["voices"]), 13)

    def test_02_config_contract_is_exact(self):
        self.assertEqual(self.config["model"], "gpt-4o-mini-tts")
        self.assertEqual(self.config["endpoint"], "https://api.openai.com/v1/audio/speech")
        self.assertEqual(self.config["response_format"], "wav")

    def test_03_casting_text_hash_matches_saved_hash(self):
        self.assertEqual(module.sha256_bytes(self.text_path.read_bytes()), self.config["text_sha256"])
        self.assertEqual(
            self.config["text_sha256"],
            "8ae8f545b187ddf8b8363d9703a0f2408b771d7c6f019020b90c4a09cb9faa2e",
        )

    def test_04_every_voice_gets_identical_instructions(self):
        instructions = {
            module.build_payload(self.config, self.text, voice)["instructions"]
            for voice in self.config["voices"]
        }
        self.assertEqual(instructions, {self.config["instructions"]})

    def test_05_payload_contains_only_approved_speech_fields(self):
        payload = module.build_payload(self.config, self.text, "alloy")
        self.assertEqual(
            set(payload),
            {"model", "voice", "input", "instructions", "response_format"},
        )
        self.assertEqual(payload["input"], self.text)

    def test_06_payload_requests_wav(self):
        for voice in self.config["voices"]:
            self.assertEqual(module.build_payload(self.config, self.text, voice)["response_format"], "wav")

    def test_07_manifest_never_receives_or_serializes_credential_value(self):
        plan = module.build_cost_plan(self.config, self.text)
        manifest = module.initial_manifest(
            self.config,
            self.text_path,
            Path("/tmp/casting-test"),
            "environment",
            plan,
        )
        serialized = json.dumps(manifest)
        self.assertNotIn("test-secret-value-123456789", serialized)
        self.assertFalse(manifest["credential_value_stored"])
        self.assertNotIn("api_key", serialized.lower())

    def test_08_global_request_cap_physically_blocks_fourteenth_claim(self):
        ledger = module.AttemptLedger(13, Decimal("1.00"), Decimal("0.05"))
        for _ in range(13):
            ledger.claim()
        with self.assertRaises(module.BudgetError):
            ledger.claim()

    def test_09_budget_cap_blocks_unsafe_reservation(self):
        ledger = module.AttemptLedger(13, Decimal("0.10"), Decimal("0.05"))
        ledger.claim()
        ledger.claim()
        with self.assertRaises(module.BudgetError):
            ledger.claim()

    def test_10_retry_is_bounded_to_one_per_voice(self):
        error = module.RetryableRequestError("safe retry")
        self.assertTrue(
            module.can_retry(
                error,
                retries_used=0,
                max_retries_per_voice=1,
                ledger_remaining=2,
                unattempted_voices=0,
            )
        )
        self.assertFalse(
            module.can_retry(
                error,
                retries_used=1,
                max_retries_per_voice=1,
                ledger_remaining=2,
                unattempted_voices=0,
            )
        )

    def test_11_ambiguous_request_is_never_retried(self):
        self.assertFalse(
            module.can_retry(
                module.AmbiguousRequestError("unknown server state"),
                retries_used=0,
                max_retries_per_voice=1,
                ledger_remaining=10,
                unattempted_voices=0,
            )
        )

    def test_12_current_plan_has_no_retry_slot_that_sacrifices_a_voice(self):
        error = module.RetryableRequestError("safe retry")
        self.assertFalse(
            module.can_retry(
                error,
                retries_used=0,
                max_retries_per_voice=1,
                ledger_remaining=12,
                unattempted_voices=12,
            )
        )

    def test_13_wav_validation_records_required_properties(self):
        validation = module.validate_wav_bytes(wav_bytes(seconds=45), self.config["duration_review"])
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["container"], "RIFF/WAVE")
        self.assertEqual(validation["parser"], "python-wave")
        self.assertEqual(validation["sample_rate_hz"], 24000)
        self.assertEqual(validation["channels"], 1)
        self.assertEqual(validation["sample_width_bytes"], 2)

    def test_14_invalid_audio_creates_no_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "01-alloy.wav"
            with self.assertRaises(module.CastingError):
                module.write_validated_wav(output, b"not a wav", self.config["duration_review"])
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".wav.part").exists())

    def test_15_anomalous_duration_is_marked_needs_review(self):
        validation = module.validate_wav_bytes(wav_bytes(seconds=1), self.config["duration_review"])
        self.assertTrue(validation["needs_review"])

    def test_16_manifest_is_written_as_valid_json(self):
        plan = module.build_cost_plan(self.config, self.text)
        manifest = module.initial_manifest(
            self.config,
            self.text_path,
            Path("/tmp/casting-test"),
            "macos_keychain",
            plan,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CASTING-MANIFEST.json"
            module.atomic_write_json(path, manifest)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["model"], "gpt-4o-mini-tts")

    def test_17_output_names_are_stable_and_voice_specific(self):
        plan = module.build_cost_plan(self.config, self.text)
        manifest = module.initial_manifest(
            self.config,
            self.text_path,
            Path("/tmp/casting-test"),
            "environment",
            plan,
        )
        self.assertEqual(manifest["samples"][0]["output_filename"], "01-alloy.wav")
        self.assertEqual(manifest["samples"][-1]["output_filename"], "13-cedar.wav")

    def test_18_cost_plan_is_exactly_thirteen_and_well_below_hard_cap(self):
        plan = module.build_cost_plan(self.config, self.text)
        self.assertEqual(plan["planned_requests"], 13)
        self.assertTrue(plan["allowed_to_start"])
        self.assertLess(Decimal(plan["estimated_total_cost_usd"]), Decimal("0.50"))
        self.assertEqual(Decimal(plan["reserved_total_cost_usd"]), Decimal("0.650000"))
        self.assertEqual(Decimal(plan["hard_cap_usd"]), Decimal("1.00"))

    def test_19_output_root_is_outside_repository(self):
        output_root = Path(self.config["output_root"]).resolve()
        self.assertFalse(output_root.is_relative_to(ROOT.parent.resolve()))

    def test_20_repository_fallback_output_is_gitignored(self):
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("casting/openai/output/", ignore_text)

    def test_21_environment_credential_reports_only_source_type(self):
        credential = module.read_credential(
            self.config,
            env={"OPENAI_API_KEY": "test-secret-value-123456789"},
        )
        self.assertEqual(credential.source_type, "environment")
        self.assertNotIn(credential.value, repr(credential.source_type))

    def test_22_offline_checks_do_not_call_network(self):
        original = module.urllib.request.urlopen
        try:
            module.urllib.request.urlopen = lambda *args, **kwargs: self.fail("network attempted")
            config, text, _ = module.load_and_validate(CONFIG_PATH)
            plan = module.build_cost_plan(config, text)
            self.assertTrue(plan["allowed_to_start"])
        finally:
            module.urllib.request.urlopen = original


if __name__ == "__main__":
    unittest.main()
