from __future__ import annotations

from datetime import date
from decimal import Decimal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.yandex_pricing import YandexPricingConfig, price_estimate
from backends.yandex_speechkit import YandexBackendConfig, YandexSpeechKitBackend, YandexSpeechKitError
from backends.yandex_types import TextSegment


def pricing(**overrides: object) -> YandexPricingConfig:
    data: dict[str, object] = {
        "engine": "yandex_speechkit_v3",
        "currency": "RUB",
        "unit": "billing_unit",
        "unit_price": "0.21146666",
        "pricing_model": "per_250_chars_or_request_unit",
        "source_region": "published_ruble_rate",
        "verified_at": "2026-08-20",
        "source_url": "https://yandex.cloud/ru-kz/docs/speechkit/pricing",
        "max_age_days": 30,
        "hard_limit_rub": "10.00",
        "demo_hard_limit_rub": "1.00",
    }
    data.update(overrides)
    return YandexPricingConfig.from_mapping(data)


class YandexPricingTests(unittest.TestCase):
    def test_decimal_calculation_preserves_full_rate_precision(self):
        result = price_estimate(
            total_units=67,
            billable_remaining_units=43,
            pricing=pricing(),
            today=date(2026, 8, 20),
        )
        self.assertEqual(result["estimated_total_cost"], "14.16826622")
        self.assertEqual(result["estimated_remaining_cost"], "9.09306638")

    def test_one_unit_cost(self):
        result = price_estimate(
            total_units=1,
            billable_remaining_units=1,
            pricing=pricing(),
            today=date(2026, 8, 20),
        )
        self.assertEqual(result["estimated_remaining_cost"], "0.21146666")

    def test_multiple_units_cost(self):
        result = price_estimate(
            total_units=3,
            billable_remaining_units=3,
            pricing=pricing(),
            today=date(2026, 8, 20),
        )
        self.assertEqual(result["estimated_remaining_cost"], "0.63439998")

    def test_cache_aware_estimate_excludes_valid_hits_from_remaining_units(self):
        backend = YandexSpeechKitBackend(YandexBackendConfig.from_mapping({"output_root": "/tmp/pricing-test"}))
        segments = [
            TextSegment("s0001", "Первый сегмент.", 0, 0),
            TextSegment("s0002", "Второй сегмент.", 0, 0),
        ]
        with mock.patch.object(backend, "segment", return_value=segments), mock.patch.object(
            backend, "_cached_segment_ids", return_value={"s0001"}
        ):
            result = backend.estimate("ignored", pricing=pricing(), scope="book")
        self.assertEqual(result["total_billing_units"], 2)
        self.assertEqual(result["billable_remaining_units"], 1)
        self.assertEqual(result["cached_segments"], 1)
        self.assertEqual(result["estimated_remaining_cost"], "0.21146666")

    def test_stale_tariff_blocks_start(self):
        result = price_estimate(
            total_units=1,
            billable_remaining_units=1,
            pricing=pricing(verified_at="2026-07-20"),
            today=date(2026, 8, 20),
        )
        self.assertTrue(result["price_stale"])
        self.assertFalse(result["allowed_to_start"])
        self.assertEqual(result["blocked_reason"], "stale_tariff")

    def test_missing_tariff_blocks_start(self):
        result = price_estimate(
            total_units=1,
            billable_remaining_units=1,
            pricing=pricing(unit_price=None),
            today=date(2026, 8, 20),
        )
        self.assertFalse(result["allowed_to_start"])
        self.assertEqual(result["blocked_reason"], "missing_tariff")

    def test_hard_limit_passes(self):
        result = price_estimate(
            total_units=2,
            billable_remaining_units=2,
            pricing=pricing(hard_limit_rub="1.00"),
            today=date(2026, 8, 20),
        )
        self.assertTrue(result["allowed_to_start"])

    def test_hard_limit_blocks_and_job_does_not_start(self):
        cfg = YandexBackendConfig.from_mapping({"output_root": "/tmp/pricing-test"})
        backend = YandexSpeechKitBackend(cfg)
        with tempfile.TemporaryDirectory() as directory:
            job_dir = Path(directory) / "blocked-job"
            with self.assertRaises(YandexSpeechKitError) as context:
                backend.run_text_job(
                    "Короткая платная фраза.",
                    job_dir,
                    pricing=pricing(hard_limit_rub=Decimal("0.01")),
                )
            self.assertEqual(context.exception.category, "pricing_gate")
            self.assertFalse(job_dir.exists())

    def test_estimate_never_sends_network_request(self):
        backend = YandexSpeechKitBackend(YandexBackendConfig.from_mapping({"output_root": "/tmp/pricing-test"}))
        with mock.patch.object(backend, "_request", side_effect=AssertionError("network attempted")) as request:
            result = backend.estimate("Офлайн-оценка.", pricing=pricing())
        request.assert_not_called()
        self.assertEqual(result["engine"], "yandex_speechkit_v3")


if __name__ == "__main__":
    unittest.main()
