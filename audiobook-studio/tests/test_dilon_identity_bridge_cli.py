from __future__ import annotations

from datetime import date
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dilon_identity_bridge_cli as cli
from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_speechkit import YandexSpeechKitBackend


def pricing(*, verified_at: str = "2026-08-20", max_age_days: int = 30) -> YandexPricingConfig:
    return YandexPricingConfig.from_mapping(
        {
            "engine": "yandex_speechkit_v3",
            "currency": "RUB",
            "unit": "billing_unit",
            "unit_price": "0.21146666",
            "pricing_model": "per_250_chars_or_request_unit",
            "source_region": "published_ruble_rate",
            "verified_at": verified_at,
            "source_url": "https://yandex.cloud/ru-kz/docs/speechkit/pricing",
            "max_age_days": max_age_days,
            "hard_limit_rub": "10.00",
            "demo_hard_limit_rub": "1.00",
        }
    )


class DilonOpeningCreditBridgeCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run_main(
        self,
        args: list[str],
        *,
        pricing_config: YandexPricingConfig | None = None,
    ) -> tuple[int, dict[str, object]]:
        patches = [
            mock.patch.dict(
                os.environ,
                {"AUDIOBOOK_STUDIO_HOME": str(self.workspace)},
            ),
            mock.patch("builtins.print"),
        ]
        if pricing_config is not None:
            patches.append(
                mock.patch.object(
                    cli,
                    "load_pricing_config",
                    return_value=pricing_config,
                )
            )
        with patches[0], patches[1] as output:
            if len(patches) == 3:
                with patches[2]:
                    return_code = cli.main(args)
            else:
                return_code = cli.main(args)
        return return_code, json.loads(output.call_args.args[0])

    def test_prepare_command_is_offline_and_persists_exact_plan(self) -> None:
        with mock.patch.object(
            YandexSpeechKitBackend,
            "_request",
            side_effect=AssertionError("network attempted"),
        ) as request:
            return_code, payload = self._run_main(
                ["--prepare-opening-credit"],
                pricing_config=pricing(),
            )
        request.assert_not_called()
        self.assertEqual(return_code, 0)
        plan = payload["opening_credit_plan"]
        self.assertTrue(plan["stored"])
        self.assertTrue(Path(plan["plan_path"]).is_file())
        self.assertEqual(plan["maximum_provider_requests"], 1)
        self.assertEqual(plan["pricing"]["estimated_remaining_cost"], "0.21146666")
        self.assertFalse(plan["execution_available"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])

    def test_plan_status_round_trip_uses_exact_persisted_identity(self) -> None:
        prepared_code, prepared_payload = self._run_main(
            ["--prepare-opening-credit"],
            pricing_config=pricing(),
        )
        self.assertEqual(prepared_code, 0)
        plan = prepared_payload["opening_credit_plan"]
        status_code, status_payload = self._run_main(
            [
                "--opening-credit-plan-status",
                "--plan-id", str(plan["plan_id"]),
                "--plan-digest", str(plan["plan_digest"]),
            ]
        )
        self.assertEqual(status_code, 0)
        status = status_payload["opening_credit_plan"]
        self.assertEqual(status["plan_id"], plan["plan_id"])
        self.assertEqual(status["plan_digest"], plan["plan_digest"])
        self.assertEqual(status["plan_path"], plan["plan_path"])
        self.assertFalse(status["execution_available"])
        self.assertEqual(status_payload["provider_requests"], 0)
        self.assertFalse(status_payload["remote_request_sent"])
        self.assertFalse(status_payload["paid_execution"])
        self.assertFalse(status_payload["billing_changed"])

    def test_stale_pricing_is_preserved_as_safe_blocker_not_test_bypassed(self) -> None:
        return_code, payload = self._run_main(
            ["--prepare-opening-credit"],
            pricing_config=pricing(verified_at="2026-07-01", max_age_days=7),
        )
        self.assertEqual(return_code, 0)
        plan = payload["opening_credit_plan"]
        self.assertEqual(plan["state"], "BLOCKED")
        self.assertEqual(plan["decision"], "PRICING_BLOCKED")
        self.assertEqual(plan["pricing"]["blocked_reason"], "stale_tariff")
        self.assertFalse(plan["stored"])
        self.assertIsNone(plan["plan_path"])
        self.assertFalse(plan["authorization_required"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["paid_execution"])

    def test_missing_required_argument_fails_closed_with_json(self) -> None:
        return_code, payload = self._run_main(
            ["--opening-credit-plan-status"]
        )
        self.assertEqual(return_code, 2)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["decision"], "INVALID_REQUEST")
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])

    def test_parser_exposes_only_prepare_and_plan_status_modes(self) -> None:
        help_text = cli.build_parser().format_help().lower()
        self.assertIn("prepare-opening-credit", help_text)
        self.assertIn("opening-credit-plan-status", help_text)
        self.assertNotIn("identity-status", help_text)
        self.assertNotIn("execute", help_text)
        self.assertNotIn("synthesize", help_text)
        self.assertNotIn("provider", help_text)


if __name__ == "__main__":
    unittest.main()
