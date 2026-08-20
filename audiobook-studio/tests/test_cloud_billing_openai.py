from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloud_billing import (
    BillingError,
    BillingLedger,
    CloudBillingService,
    CloudBillingSettings,
    OPENAI_AUDIO_USAGE_ENDPOINT,
    OPENAI_COSTS_ENDPOINT,
    OpenAIAdminClient,
    save_settings,
)
from backends.openai_client import OpenAITTSBackend
from backends.openai_types import OpenAIBackendConfig


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload: dict):
        self.body = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.closed = False

    def read(self) -> bytes:
        return self.body.read()

    def close(self) -> None:
        self.closed = True


def page(results: list[dict], *, has_more: bool = False, next_page: str | None = None) -> FakeResponse:
    return FakeResponse({
        "object": "page",
        "data": [{"object": "bucket", "start_time": 1, "end_time": 2, "results": results}],
        "has_more": has_more,
        "next_page": next_page,
    })


def billing_service(
    root: Path,
    *,
    client: OpenAIAdminClient | None = None,
    settings: CloudBillingSettings | None = None,
) -> CloudBillingService:
    settings_path = root / "settings.json"
    if settings is not None:
        save_settings(settings_path, settings)
    return CloudBillingService(
        settings_path=settings_path,
        ledger_path=root / "ledger.json",
        cache_path=root / "cache.json",
        openai_client=client,
        now=lambda: NOW,
    )


class OpenAICloudBillingTests(unittest.TestCase):
    def test_01_missing_admin_credential_is_normal_and_sends_no_request(self):
        opener = mock.Mock(side_effect=AssertionError("network attempted"))
        client = OpenAIAdminClient(
            credential_loader=mock.Mock(side_effect=BillingError("missing", category="credential_unavailable")),
            opener=opener,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = billing_service(Path(directory), client=client).status("openai", refresh=True)
        self.assertEqual(result["provider_metadata"]["provider_costs_status"], "unavailable_admin_credential")
        self.assertFalse(result["remote_request_sent"])
        opener.assert_not_called()

    def test_02_costs_api_aggregates_usd_with_decimal(self):
        client = OpenAIAdminClient(
            credential_loader=lambda: "admin-secret",
            opener=mock.Mock(return_value=page([
                {"amount": {"value": "0.10", "currency": "usd"}},
                {"amount": {"value": "0.20", "currency": "usd"}},
            ])),
        )
        totals = client.costs(start_time=1, end_time=2)
        self.assertEqual(totals, {"USD": Decimal("0.30")})

    def test_03_costs_api_pagination_uses_documented_cursor(self):
        opener = mock.Mock(side_effect=[
            page([{"amount": {"value": "1.00", "currency": "usd"}}], has_more=True, next_page="cursor-2"),
            page([{"amount": {"value": "2.00", "currency": "usd"}}]),
        ])
        client = OpenAIAdminClient(credential_loader=lambda: "admin-secret", opener=opener)
        totals = client.costs(start_time=1, end_time=2)
        self.assertEqual(totals["USD"], Decimal("3.00"))
        self.assertEqual(opener.call_count, 2)
        self.assertIn("page=cursor-2", opener.call_args_list[1].args[0].full_url)

    def test_04_audio_speech_usage_is_aggregated(self):
        client = OpenAIAdminClient(
            credential_loader=lambda: "admin-secret",
            opener=mock.Mock(return_value=page([
                {"characters": 100, "num_model_requests": 2},
                {"characters": 50, "num_model_requests": 1},
            ])),
        )
        usage = client.audio_speech_usage(start_time=1, end_time=2)
        self.assertEqual(usage, {"characters": 150, "num_model_requests": 3})

    def test_05_provider_costs_refresh_is_additional_metadata_not_balance(self):
        def opener(request, **_kwargs):
            if request.full_url.startswith(OPENAI_COSTS_ENDPOINT):
                return page([{"amount": {"value": "4.25", "currency": "usd"}}])
            if request.full_url.startswith(OPENAI_AUDIO_USAGE_ENDPOINT):
                return page([{"characters": 400, "num_model_requests": 4}])
            raise AssertionError(request.full_url)

        with tempfile.TemporaryDirectory() as directory:
            client = OpenAIAdminClient(credential_loader=lambda: "admin-secret", opener=opener)
            result = billing_service(Path(directory), client=client).status("openai", refresh=True)
        self.assertEqual(result["provider_metadata"]["provider_costs"], {"USD": "4.25"})
        self.assertEqual(result["provider_metadata"]["provider_costs_source"], "provider_reported")
        self.assertEqual(result["provider_metadata"]["audio_speech_usage"]["characters"], 400)
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["remaining_source"], "unavailable")
        self.assertTrue(result["remote_request_sent"])

    def test_06_provider_costs_permission_failure_is_explicit_and_redacted(self):
        secret = "admin-secret-value"
        error = urllib.error.HTTPError(
            OPENAI_COSTS_ENDPOINT, 403, "Forbidden", {}, io.BytesIO(b"sensitive body")
        )
        client = OpenAIAdminClient(credential_loader=lambda: secret, opener=mock.Mock(side_effect=error))
        with self.assertRaises(BillingError) as raised:
            client.costs(start_time=1, end_time=2)
        self.assertEqual(raised.exception.category, "admin_permission_unavailable")
        self.assertTrue(raised.exception.remote_request_sent)
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("sensitive body", str(raised.exception))

    def test_07_user_confirmed_balance_becomes_local_estimate(self):
        settings = CloudBillingSettings(
            openai_confirmed_balance_usd=Decimal("10.00"),
            openai_confirmed_at="2026-08-21T09:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            billing = billing_service(root, settings=settings)
            billing.ledger.record(
                provider="openai", job_id="job", segment_id="s1", request_id="req-1",
                profile_id="openai_onyx", timestamp="2026-08-21T10:00:00+00:00", currency="USD",
                actual_cost=Decimal("2.50"), cost_source="local_actual", fingerprint="fp-1",
            )
            result = billing.status("openai")
        self.assertEqual(result["remaining"], "7.50")
        self.assertEqual(result["remaining_source"], "local_estimate")
        self.assertEqual(result["provider_metadata"]["user_confirmed_balance_source"], "user_confirmed")
        self.assertEqual(result["spent"], "2.50")
        self.assertEqual(result["spent_source"], "local_actual")

    def test_08_user_balance_warns_about_usage_outside_studio(self):
        settings = CloudBillingSettings(
            openai_confirmed_balance_usd=Decimal("10"),
            openai_confirmed_at="2026-08-21T09:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            result = billing_service(Path(directory), settings=settings).status("openai")
        self.assertIn("openai_balance_may_exclude_usage_outside_audiobook_studio", result["warnings"])

    def test_09_stale_user_baseline_is_not_marked_fresh(self):
        settings = CloudBillingSettings(
            openai_confirmed_balance_usd=Decimal("10"),
            openai_confirmed_at="2026-08-01T09:00:00+00:00",
            user_balance_stale_after_seconds=86400,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = billing_service(Path(directory), settings=settings).status("openai")
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["status"], "STALE")
        self.assertIn("user_confirmed_balance_stale", result["warnings"])

    def test_10_no_documented_exact_prepaid_balance_is_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            result = billing_service(Path(directory)).status("openai")
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["remaining_source"], "unavailable")
        self.assertEqual(
            result["provider_metadata"]["exact_prepaid_balance_status"],
            "unavailable_documented_api",
        )

    def test_11_undocumented_balance_endpoint_is_physically_forbidden(self):
        opener = mock.Mock(side_effect=AssertionError("network attempted"))
        client = OpenAIAdminClient(credential_loader=lambda: "admin-secret", opener=opener)
        with self.assertRaises(BillingError) as raised:
            client._get_pages("https://api.openai.com/dashboard/billing/credit_grants", {})
        self.assertEqual(raised.exception.category, "endpoint_forbidden")
        opener.assert_not_called()

    def test_12_provider_costs_keep_currencies_separate(self):
        client = OpenAIAdminClient(
            credential_loader=lambda: "admin-secret",
            opener=mock.Mock(return_value=page([
                {"amount": {"value": "1.25", "currency": "usd"}},
                {"amount": {"value": "3.50", "currency": "eur"}},
            ])),
        )
        totals = client.costs(start_time=1, end_time=2)
        self.assertEqual(totals, {"USD": Decimal("1.25"), "EUR": Decimal("3.50")})

    def test_13_completed_speech_without_exact_usage_records_unavailable_actual(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = BillingLedger(root / "ledger.json")
            config = OpenAIBackendConfig.from_mapping({
                "schema_version": 1, "engine": "openai_tts",
                "endpoint": "https://api.openai.com/v1/audio/speech",
                "cache_root": str(root / "cache"), "jobs_root": str(root / "jobs"),
                "paid_execution_enabled": False,
                "segmentation": {
                    "target_chars": 900, "hard_chars": 1200, "hard_utf8_bytes": 2000,
                    "api_max_input_tokens": 2000,
                },
            })
            backend = OpenAITTSBackend(config, billing_ledger=ledger)
            transaction_id = backend._record_billing_event(
                job_id="job", segment_id="s1", request_id="req-o", profile_id="openai_onyx",
                fingerprint="fp-o", timestamp="2026-08-21T10:00:00+00:00",
            )
            transaction = ledger.transactions()[0]
        self.assertIsNotNone(transaction_id)
        self.assertIsNone(transaction["actual_cost"])
        self.assertEqual(transaction["cost_source"], "unavailable")

    def test_14_unknown_spend_after_user_baseline_makes_remaining_unavailable(self):
        settings = CloudBillingSettings(
            openai_confirmed_balance_usd=Decimal("10.00"),
            openai_confirmed_at="2026-08-21T09:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            billing = billing_service(root, settings=settings)
            billing.ledger.record(
                provider="openai", job_id="job", segment_id="s1", request_id="req-unknown",
                profile_id="openai_onyx", timestamp="2026-08-21T10:00:00+00:00", currency="USD",
                actual_cost=None, cost_source="unavailable", fingerprint="fp-unknown",
            )
            result = billing.status("openai")
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["remaining_source"], "unavailable")
        self.assertIn("openai_local_spend_since_confirmation_incomplete", result["warnings"])

    def test_15_invalid_provider_payload_reports_that_request_was_sent(self):
        client = OpenAIAdminClient(
            credential_loader=lambda: "admin-secret",
            opener=mock.Mock(return_value=page([{"amount": {"value": "invalid", "currency": "usd"}}])),
        )
        with self.assertRaises(BillingError) as raised:
            client.costs(start_time=1, end_time=2)
        self.assertEqual(raised.exception.category, "provider_response")
        self.assertTrue(raised.exception.remote_request_sent)


if __name__ == "__main__":
    unittest.main()
