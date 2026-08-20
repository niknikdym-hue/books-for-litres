from __future__ import annotations

import importlib.util
import http.client
import json
import sys
import tempfile
import unittest
import wave
from decimal import Decimal
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CASTING_DIR = ROOT / "casting" / "yandex-male"
RUNNER = CASTING_DIR / "run_yandex_male_casting.py"
CONFIG = CASTING_DIR / "yandex-male-casting-config.json"

SPEC = importlib.util.spec_from_file_location("yandex_male_casting", RUNNER)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def write_wav(path: Path, *, seconds: float = 1.0, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\x00\x00" * int(seconds * rate))


class YandexMaleCastingOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.casting, cls.text, cls.text_path, cls.production, cls.pricing, cls.plan = module.load_context(CONFIG)

    def test_01_exact_official_male_voice_list(self):
        self.assertEqual(self.casting["voices"], module.EXPECTED_VOICES)
        self.assertEqual(len(self.casting["voices"]), 7)

    def test_02_role_mapping_is_exact(self):
        self.assertEqual(
            [profile["role"] for profile in self.casting["voices"]],
            [None, "neutral", "neutral", "neutral", "neutral", "neutral", None],
        )

    def test_03_source_hash_is_unchanged(self):
        self.assertEqual(module.sha256_bytes(self.text_path.read_bytes()), module.EXPECTED_TEXT_SHA256)

    def test_04_speed_is_one_for_all_profiles(self):
        self.assertEqual(self.casting["speed"], "1.0")
        for profile in self.casting["voices"]:
            config = module.profile_config(
                self.production,
                profile,
                self.casting["speed"],
                Path("/tmp/yandex-male-test"),
            )
            self.assertEqual(config.profile.speed, "1.0")

    def test_05_frozen_lera_profile_is_not_changed(self):
        self.assertEqual(self.production["default_profile"], module.EXPECTED_PRODUCTION_PROFILE)
        on_disk = json.loads((ROOT / "yandex-config.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["default_profile"], module.EXPECTED_PRODUCTION_PROFILE)

    def test_06_task_scoped_pricing_passes_without_mutating_production_pricing(self):
        self.assertEqual(self.plan["planned_requests"], 42)
        self.assertEqual(self.plan["estimated_remaining_cost"], "8.88159972")
        self.assertEqual(self.plan["task_scoped_hard_limit_rub"], "10.00")
        self.assertTrue(self.plan["allowed_to_start"])
        self.assertEqual(self.pricing.demo_hard_limit_rub, Decimal("1.00"))

    def test_07_tariff_is_fresh(self):
        self.assertFalse(self.plan["price_stale"])
        self.assertEqual(self.plan["price_verified_at"], "2026-08-20")

    def test_08_request_ledger_physically_enforces_ten_ruble_cap(self):
        ledger = module.RequestLedger(
            self.pricing.unit_price,
            Decimal("10.00"),
            self.plan["maximum_network_attempts_under_cap"],
        )
        for _ in range(self.plan["maximum_network_attempts_under_cap"]):
            ledger.claim()
        self.assertLessEqual(ledger.estimated_cost_rub, Decimal("10.00"))
        with self.assertRaises(module.YandexSpeechKitError):
            ledger.claim()

    def test_09_default_role_is_omitted_from_backend_payload(self):
        no_role = module.profile_config(
            self.production,
            {"voice": "filipp", "role": None},
            "1.0",
            Path("/tmp/yandex-male-test"),
        )
        payload = module.YandexSpeechKitBackend(no_role, api_key="offline-placeholder-key-123456").build_synthesis_payload("Тест.")
        self.assertNotIn("role", {key for hint in payload["hints"] for key in hint})

    def test_10_lera_payload_semantics_remain_unchanged(self):
        production = module.YandexBackendConfig.from_mapping(self.production)
        payload = module.YandexSpeechKitBackend(
            production,
            api_key="offline-placeholder-key-123456",
        ).build_synthesis_payload("Тест.")
        self.assertIn({"role": "neutral"}, payload["hints"])
        self.assertIn({"speed": "1.04"}, payload["hints"])

    def test_11_manifest_contains_no_credentials(self):
        manifest = module.initial_manifest(
            self.casting,
            self.text_path,
            Path("/tmp/yandex-male-test"),
            self.plan,
        )
        serialized = json.dumps(manifest)
        self.assertFalse(manifest["credential_value_stored"])
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("test-secret-value-123456", serialized)

    def test_12_retry_is_bounded_and_ambiguous_is_never_retried(self):
        retryable = module.YandexSpeechKitError("retry", category="server", retryable=True)
        ambiguous = module.YandexSpeechKitError(
            "ambiguous", category="network_ambiguous", retryable=False
        )
        self.assertTrue(module.can_retry(retryable, 0, 1))
        self.assertFalse(module.can_retry(retryable, 1, 1))
        self.assertFalse(module.can_retry(ambiguous, 0, 1))

    def test_13_wav_validation_records_integrity_properties(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            write_wav(path, seconds=2)
            validation = module.validate_final_wav(path, self.casting["duration_review"])
            self.assertTrue(validation["valid"])
            self.assertEqual(validation["container"], "RIFF/WAVE")
            self.assertEqual(validation["duration_seconds"], 2.0)
            self.assertEqual(validation["sample_rate_hz"], 24000)
            self.assertEqual(validation["channels"], 1)
            self.assertEqual(validation["sample_width_bytes"], 2)
            self.assertTrue(validation["needs_review"])

    def test_14_manifest_is_atomic_valid_json(self):
        manifest = module.initial_manifest(
            self.casting,
            self.text_path,
            Path("/tmp/yandex-male-test"),
            self.plan,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CASTING-MANIFEST.json"
            module.atomic_write_json(path, manifest)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["casting_type"], "male_voice_round_1")

    def test_15_generated_output_is_outside_repo_and_gitignored_fallback_exists(self):
        output_root = Path(self.casting["output_root"]).resolve()
        self.assertFalse(output_root.is_relative_to(ROOT.parent.resolve()))
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("casting/yandex-male/output/", ignore_text)

    def test_16_incomplete_http_response_is_ambiguous_and_not_retryable(self):
        production = module.YandexBackendConfig.from_mapping(self.production)
        backend = module.YandexSpeechKitBackend(
            production,
            api_key="offline-placeholder-key-123456",
        )

        class BrokenResponse:
            headers: dict[str, str] = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"partial")

        with mock.patch("backends.yandex_client.urllib.request.urlopen", return_value=BrokenResponse()):
            with self.assertRaises(module.YandexSpeechKitError) as context:
                backend._request("Тест.", "request-test")
        self.assertEqual(context.exception.category, "network_ambiguous")
        self.assertFalse(context.exception.retryable)

    def test_17_round_request_ids_include_inflight_resume_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            job = work / "01-test"
            job.mkdir()
            (job / "MANIFEST.json").write_text(
                json.dumps({
                    "segments": {
                        "s0001": {"status": "DONE", "request_id": "one"},
                        "s0002": {"status": "IN_FLIGHT", "request_id": "two"},
                    }
                }),
                encoding="utf-8",
            )
            self.assertEqual(module.collect_round_request_ids(work), ["one", "two"])


if __name__ == "__main__":
    unittest.main()
