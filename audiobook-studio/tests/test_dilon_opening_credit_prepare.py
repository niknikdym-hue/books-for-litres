from __future__ import annotations

from datetime import date
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dilon_opening_credit_prepare as prepare_module
from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_speechkit import YandexSpeechKitBackend
from dilon_identity import OPENING_CREDIT_TEXT
from dilon_opening_credit_prepare import OpeningCreditPrepareError, prepare_opening_credit_plan


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


class DilonOpeningCreditPrepareTests(unittest.TestCase):
    def test_canonical_plan_is_one_request_and_owner_gated(self) -> None:
        plan = prepare_opening_credit_plan(
            pricing=pricing(), today=date(2026, 8, 29)
        )
        self.assertEqual(plan["text"], OPENING_CREDIT_TEXT)
        self.assertEqual(plan["profile"]["profile_id"], "yandex_lera")
        self.assertEqual(plan["profile"]["voice"], "lera")
        self.assertEqual(plan["profile"]["role"], "neutral")
        self.assertEqual(plan["profile"]["speed"], "1.04")
        self.assertTrue(plan["profile"]["frozen"])
        self.assertEqual(plan["maximum_provider_requests"], 1)
        self.assertEqual(plan["pricing"]["estimated_remaining_cost"], "0.21146666")
        self.assertEqual(plan["pricing"]["hard_limit_rub"], "10.00")
        self.assertEqual(plan["state"], "READY_FOR_OWNER_AUTHORIZATION")
        self.assertEqual(plan["decision"], "OWNER_AUTHORIZATION_REQUIRED")
        self.assertTrue(plan["authorization_required"])
        self.assertFalse(plan["execution_available"])
        self.assertEqual(plan["provider_requests"], 0)
        self.assertFalse(plan["remote_request_sent"])
        self.assertFalse(plan["paid_execution"])
        self.assertFalse(plan["billing_changed"])

    def test_prepare_is_deterministic_and_never_calls_network(self) -> None:
        with mock.patch.object(
            YandexSpeechKitBackend,
            "_request",
            side_effect=AssertionError("network attempted"),
        ) as request:
            first = prepare_opening_credit_plan(
                pricing=pricing(), today=date(2026, 8, 29)
            )
            second = prepare_opening_credit_plan(
                pricing=pricing(), today=date(2026, 8, 29)
            )
        request.assert_not_called()
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(first["synthesis_fingerprint"], second["synthesis_fingerprint"])

    def test_stale_or_over_limit_pricing_blocks_owner_authorization(self) -> None:
        stale = prepare_opening_credit_plan(
            pricing=pricing(verified_at="2026-07-01"), today=date(2026, 8, 29)
        )
        self.assertEqual(stale["state"], "BLOCKED")
        self.assertEqual(stale["decision"], "PRICING_BLOCKED")
        self.assertEqual(stale["pricing"]["blocked_reason"], "stale_tariff")
        self.assertFalse(stale["authorization_required"])

        over_limit = prepare_opening_credit_plan(
            pricing=pricing(hard_limit_rub="0.01"), today=date(2026, 8, 29)
        )
        self.assertEqual(over_limit["state"], "BLOCKED")
        self.assertEqual(over_limit["pricing"]["blocked_reason"], "hard_limit_exceeded")
        self.assertFalse(over_limit["authorization_required"])

    def test_frozen_lera_profile_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "voice-library.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "profiles": [
                            {
                                "profile_id": "yandex_lera",
                                "provider": "yandex",
                                "engine": "yandex_speechkit_v3",
                                "label": "Lera",
                                "voice_source": "builtin",
                                "voice": "lera",
                                "language": "ru",
                                "status": "approved",
                                "role": "neutral",
                                "speed": "1.00",
                                "frozen": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(OpeningCreditPrepareError) as caught:
                prepare_opening_credit_plan(
                    pricing=pricing(),
                    today=date(2026, 8, 29),
                    registry_path=registry,
                )
        self.assertEqual(caught.exception.code, "production_profile_drift")

    def test_module_exposes_no_paid_execution_function(self) -> None:
        self.assertFalse(hasattr(prepare_module, "execute_opening_credit_plan"))
        self.assertFalse(hasattr(prepare_module, "synthesize_opening_credit"))


if __name__ == "__main__":
    unittest.main()
