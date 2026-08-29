from __future__ import annotations

from datetime import date
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_speechkit import YandexSpeechKitBackend
import dilon_opening_credit_plan_store as store_module
from dilon_opening_credit_plan_store import (
    OpeningCreditPlanStore,
    OpeningCreditPlanStoreError,
)


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


class OpeningCreditPlanStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "plans"
        self.store = OpeningCreditPlanStore(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_ready_plan_is_persisted_and_exactly_reloadable(self) -> None:
        with mock.patch.object(
            YandexSpeechKitBackend,
            "_request",
            side_effect=AssertionError("network attempted"),
        ) as request:
            prepared = self.store.prepare(
                pricing=pricing(), today=date(2026, 8, 29)
            )
            loaded = self.store.load(
                plan_id=prepared["plan_id"],
                expected_plan_digest=prepared["plan_digest"],
            )
        request.assert_not_called()
        self.assertTrue(prepared["stored"])
        self.assertEqual(loaded["plan_id"], prepared["plan_id"])
        self.assertEqual(loaded["plan_digest"], prepared["plan_digest"])
        self.assertEqual(loaded["maximum_provider_requests"], 1)
        self.assertEqual(loaded["pricing"]["estimated_remaining_cost"], "0.21146666")
        self.assertFalse(loaded["execution_available"])
        self.assertEqual(loaded["provider_requests"], 0)
        self.assertFalse(loaded["remote_request_sent"])
        self.assertFalse(loaded["paid_execution"])
        self.assertFalse(loaded["billing_changed"])

    def test_prepare_is_idempotent_for_same_exact_authority(self) -> None:
        first = self.store.prepare(pricing=pricing(), today=date(2026, 8, 29))
        first_bytes = Path(first["plan_path"]).read_bytes()
        second = self.store.prepare(pricing=pricing(), today=date(2026, 8, 29))
        self.assertEqual(second["plan_id"], first["plan_id"])
        self.assertEqual(second["plan_digest"], first["plan_digest"])
        self.assertEqual(Path(second["plan_path"]).read_bytes(), first_bytes)

    def test_blocked_pricing_is_not_persisted(self) -> None:
        blocked = self.store.prepare(
            pricing=pricing(verified_at="2026-07-01"),
            today=date(2026, 8, 29),
        )
        self.assertEqual(blocked["state"], "BLOCKED")
        self.assertFalse(blocked["stored"])
        self.assertIsNone(blocked["plan_digest"])
        self.assertIsNone(blocked["plan_path"])
        self.assertFalse(self.root.exists())

    def test_tampered_plan_fails_digest_load(self) -> None:
        prepared = self.store.prepare(pricing=pricing(), today=date(2026, 8, 29))
        path = Path(prepared["plan_path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["plan"]["maximum_provider_requests"] = 2
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(OpeningCreditPlanStoreError) as caught:
            self.store.load(
                plan_id=prepared["plan_id"],
                expected_plan_digest=prepared["plan_digest"],
            )
        self.assertEqual(caught.exception.code, "plan_integrity_mismatch")

    def test_symlinked_plan_file_is_rejected_without_following(self) -> None:
        prepared = self.store.prepare(pricing=pricing(), today=date(2026, 8, 29))
        path = Path(prepared["plan_path"])
        outside = path.parent / "outside.json"
        outside.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(OpeningCreditPlanStoreError) as caught:
            self.store.load(
                plan_id=prepared["plan_id"],
                expected_plan_digest=prepared["plan_digest"],
            )
        self.assertEqual(caught.exception.code, "invalid_plan_file")
        self.assertTrue(outside.is_file())

    def test_store_exposes_no_execute_path(self) -> None:
        self.assertFalse(hasattr(self.store, "execute"))
        self.assertFalse(hasattr(store_module, "execute_opening_credit_plan"))


if __name__ == "__main__":
    unittest.main()
