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
    ProviderCache,
    YANDEX_BILLING_ENDPOINT,
    YandexBillingClient,
    save_settings,
)
from backends.yandex_client import YandexSpeechKitBackend
from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_types import TextSegment, YandexBackendConfig


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload: dict):
        self.body = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.closed = False

    def read(self) -> bytes:
        return self.body.read()

    def close(self) -> None:
        self.closed = True


def billing_service(root: Path, client: YandexBillingClient) -> CloudBillingService:
    settings_path = root / "settings.json"
    save_settings(settings_path, CloudBillingSettings(yandex_billing_account_id="billing123"))
    return CloudBillingService(
        settings_path=settings_path,
        ledger_path=root / "ledger.json",
        cache_path=root / "cache.json",
        yandex_client=client,
        now=lambda: NOW,
    )


class YandexCloudBillingTests(unittest.TestCase):
    def test_01_billing_account_get_parses_provider_balance(self):
        response = FakeResponse({
            "id": "billing123", "currency": "RUB", "balance": "123.4500"
        })
        opener = mock.Mock(return_value=response)
        client = YandexBillingClient(credential_loader=lambda: "iam-secret-token", opener=opener)
        result = client.get_account("billing123")
        request = opener.call_args.args[0]
        self.assertEqual(result["balance"].as_tuple().exponent, -4)
        self.assertEqual(result["currency"], "RUB")
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, f"{YANDEX_BILLING_ENDPOINT}/billing123")
        self.assertTrue(request.get_header("Authorization").startswith("Bearer "))
        self.assertTrue(response.closed)

    def test_02_successful_refresh_is_provider_reported_rub(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = YandexBillingClient(
                credential_loader=lambda: "iam-secret-token",
                opener=mock.Mock(return_value=FakeResponse({
                    "id": "billing123", "currency": "RUB", "balance": "50.25"
                })),
            )
            result = billing_service(root, client).status("yandex", refresh=True)
        self.assertEqual(result["remaining"], "50.25")
        self.assertEqual(result["remaining_source"], "provider_reported")
        self.assertEqual(result["freshness"], "current")
        self.assertTrue(result["remote_request_sent"])

    def test_03_permission_denied_is_explicit_and_secret_is_redacted(self):
        secret = "iam-secret-token-value"
        error = urllib.error.HTTPError(
            f"{YANDEX_BILLING_ENDPOINT}/billing123", 403, "Forbidden", {}, io.BytesIO(b"secret body")
        )
        client = YandexBillingClient(credential_loader=lambda: secret, opener=mock.Mock(side_effect=error))
        with self.assertRaises(BillingError) as raised:
            client.get_account("billing123")
        self.assertEqual(raised.exception.category, "billing_permission_unavailable")
        self.assertTrue(raised.exception.remote_request_sent)
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("secret body", str(raised.exception))

    def test_04_network_failure_is_safe(self):
        client = YandexBillingClient(
            credential_loader=lambda: "iam-secret-token",
            opener=mock.Mock(side_effect=urllib.error.URLError("offline")),
        )
        with self.assertRaises(BillingError) as raised:
            client.get_account("billing123")
        self.assertEqual(raised.exception.category, "billing_network_error")
        self.assertTrue(raised.exception.remote_request_sent)

    def test_05_network_failure_keeps_last_value_only_as_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = YandexBillingClient(
                credential_loader=lambda: "iam-secret-token",
                opener=mock.Mock(side_effect=urllib.error.URLError("offline")),
            )
            billing = billing_service(root, client)
            ProviderCache(root / "cache.json").update("yandex", {
                "remaining": "20.00", "currency": "RUB", "remaining_source": "provider_reported",
                "last_successful_refresh": "2026-08-21T10:00:00+00:00",
                "last_attempt": "2026-08-21T10:00:00+00:00", "status": "current", "reason": None,
            })
            result = billing.status("yandex", refresh=True)
        self.assertEqual(result["remaining"], "20.00")
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["provider_metadata"]["provider_balance_status"], "billing_network_error")
        self.assertTrue(result["remote_request_sent"])

    def test_06_invalid_balance_is_rejected(self):
        client = YandexBillingClient(
            credential_loader=lambda: "iam-secret-token",
            opener=mock.Mock(return_value=FakeResponse({
                "id": "billing123", "currency": "RUB", "balance": "not-money"
            })),
        )
        with self.assertRaises(BillingError) as raised:
            client.get_account("billing123")
        self.assertEqual(raised.exception.category, "billing_response")

    def test_07_account_not_found_is_explicit(self):
        error = urllib.error.HTTPError(
            f"{YANDEX_BILLING_ENDPOINT}/missing", 404, "Not Found", {}, io.BytesIO(b"")
        )
        client = YandexBillingClient(
            credential_loader=lambda: "iam-secret-token", opener=mock.Mock(side_effect=error)
        )
        with self.assertRaises(BillingError) as raised:
            client.get_account("missing")
        self.assertEqual(raised.exception.category, "billing_account_not_found")

    def test_08_missing_iam_credential_sends_no_request(self):
        opener = mock.Mock(side_effect=AssertionError("network attempted"))
        client = YandexBillingClient(
            credential_loader=mock.Mock(side_effect=BillingError("missing", category="credential_unavailable")),
            opener=opener,
        )
        with self.assertRaises(BillingError) as raised:
            client.get_account("billing123")
        self.assertEqual(raised.exception.category, "billing_iam_credential_unavailable")
        self.assertFalse(raised.exception.remote_request_sent)
        opener.assert_not_called()

    def test_09_existing_speechkit_key_is_not_misrepresented_as_billing_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = billing_service(
                root,
                YandexBillingClient(credential_loader=lambda: "unused", opener=mock.Mock()),
            ).status("yandex")
        metadata = result["provider_metadata"]
        self.assertFalse(metadata["existing_speechkit_api_key_compatible"])
        self.assertEqual(metadata["billing_auth_contract"], "iam_bearer_token")
        self.assertEqual(metadata["minimum_read_only_role"], "billing.accounts.viewer")
        self.assertFalse(result["remote_request_sent"])

    def test_10_completed_studio_request_records_local_actual_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BillingLedger(Path(directory) / "ledger.json")
            backend = YandexSpeechKitBackend(
                YandexBackendConfig.from_mapping({"output_root": directory}),
                billing_ledger=ledger,
            )
            pricing = YandexPricingConfig.from_mapping({
                "engine": "yandex_speechkit_v3", "currency": "RUB", "unit_price": "0.25",
                "verified_at": "2026-08-21", "source_url": "https://example.test/pricing",
                "hard_limit_rub": "1", "demo_hard_limit_rub": "1",
            })
            transaction_id = backend._record_billing_event(
                job_id="job", segment=TextSegment("s1", "Текст", 0, 1), request_id="req-y",
                fingerprint="fp-y", timestamp="2026-08-21T10:00:00+00:00",
                pricing=pricing, cost_known=True,
            )
            summary = ledger.summarize("yandex", currency="RUB")
        self.assertIsNotNone(transaction_id)
        self.assertEqual(summary["known_total"], Decimal("0.25"))


if __name__ == "__main__":
    unittest.main()
