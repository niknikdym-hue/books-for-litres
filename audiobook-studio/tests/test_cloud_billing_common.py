from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloud_billing import (
    BillingError,
    BillingLedger,
    CloudBillingService,
    CloudBillingSettings,
    ProviderCache,
    decimal_value,
    load_settings,
    save_settings,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def paths(root: Path) -> tuple[Path, Path, Path]:
    return root / "settings.json", root / "ledger.json", root / "cache.json"


def service(root: Path, *, settings: CloudBillingSettings | None = None) -> CloudBillingService:
    settings_path, ledger_path, cache_path = paths(root)
    if settings is not None:
        save_settings(settings_path, settings)
    return CloudBillingService(
        settings_path=settings_path,
        ledger_path=ledger_path,
        cache_path=cache_path,
        now=lambda: NOW,
    )


def record(
    ledger: BillingLedger,
    *,
    provider: str,
    request_id: str,
    cost: Decimal | None,
    source: str,
    timestamp: str = "2026-08-21T10:00:00+00:00",
) -> tuple[str, bool]:
    return ledger.record(
        provider=provider,
        job_id="job-1",
        segment_id="s0001",
        request_id=request_id,
        profile_id="yandex_lera" if provider == "yandex" else "openai_onyx",
        timestamp=timestamp,
        currency="RUB" if provider == "yandex" else "USD",
        actual_cost=cost,
        cost_source=source,
        fingerprint=f"fp-{provider}-{request_id}",
    )


class CloudBillingCommonTests(unittest.TestCase):
    def test_01_decimal_money_preserves_precision(self):
        value = decimal_value("0.21146666", "money") * Decimal("3")
        self.assertEqual(value, Decimal("0.63439998"))
        self.assertNotIsInstance(value, float)

    def test_02_default_settings_are_local_safe_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / "missing.json")
        self.assertIsNone(settings.yandex_billing_account_id)
        self.assertIsNone(settings.openai_confirmed_balance_usd)
        self.assertEqual(settings.openai_hard_limit_usd, Decimal("1.00"))

    def test_03_atomic_settings_round_trip_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings" / "cloud-billing.json"
            settings = CloudBillingSettings(
                yandex_billing_account_id="billing123",
                yandex_low_balance_threshold_rub=Decimal("100.00"),
                openai_confirmed_balance_usd=Decimal("10.50"),
                openai_confirmed_at="2026-08-21T09:00:00+00:00",
                openai_low_balance_threshold_usd=Decimal("2.00"),
                openai_hard_limit_usd=Decimal("0.75"),
            )
            save_settings(path, settings)
            loaded = load_settings(path)
            raw = path.read_text(encoding="utf-8")
            leftovers = list(path.parent.glob("*.tmp"))
        self.assertEqual(loaded, settings)
        self.assertNotIn("credential", raw.lower())
        self.assertNotIn("api_key", raw.lower())
        self.assertEqual(leftovers, [])

    def test_04_settings_reject_unknown_secret_fields(self):
        mapping = CloudBillingSettings().to_mapping()
        mapping["openai"]["admin_key"] = "secret"
        with self.assertRaises(BillingError) as raised:
            CloudBillingSettings.from_mapping(mapping)
        self.assertEqual(raised.exception.category, "settings")
        self.assertNotIn("secret", str(raised.exception))

    def test_05_ledger_is_idempotent_for_exact_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BillingLedger(Path(directory) / "ledger.json")
            first_id, first_created = record(
                ledger, provider="yandex", request_id="req-1", cost=Decimal("0.21146666"), source="local_actual"
            )
            second_id, second_created = record(
                ledger, provider="yandex", request_id="req-1", cost=Decimal("0.21146666"), source="local_actual"
            )
            transactions = ledger.transactions()
        self.assertEqual(first_id, second_id)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(len(transactions), 1)

    def test_06_conflicting_duplicate_request_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BillingLedger(Path(directory) / "ledger.json")
            record(ledger, provider="yandex", request_id="req-1", cost=Decimal("1"), source="local_actual")
            with self.assertRaises(BillingError) as raised:
                ledger.record(
                    provider="yandex", job_id="job-2", segment_id="s9999", request_id="req-1",
                    profile_id="yandex_lera", timestamp="2026-08-21T11:00:00+00:00", currency="RUB",
                    actual_cost=Decimal("2"), cost_source="local_actual", fingerprint="different",
                )
        self.assertIn(raised.exception.category, {"duplicate_transaction", "duplicate_request"})

    def test_07_estimate_can_never_be_written_as_actual(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BillingLedger(Path(directory) / "ledger.json")
            with self.assertRaises(BillingError) as raised:
                record(ledger, provider="openai", request_id="req-1", cost=Decimal("0.01"), source="local_estimate")
        self.assertEqual(raised.exception.category, "ledger")

    def test_08_unavailable_actual_event_makes_spent_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            billing = service(root)
            record(billing.ledger, provider="openai", request_id="req-1", cost=None, source="unavailable")
            result = billing.status("openai")
        self.assertIsNone(result["spent"])
        self.assertEqual(result["spent_source"], "unavailable")
        self.assertEqual(result["unknown_cost_events"], 1)
        self.assertIn("local_actual_spend_incomplete", result["warnings"])

    def test_09_unavailable_remaining_is_null_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            result = service(Path(directory)).status("yandex")
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["remaining_source"], "unavailable")
        self.assertEqual(result["status"], "BALANCE_UNKNOWN")

    def test_10_projected_remaining_has_local_estimate_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = CloudBillingSettings(yandex_billing_account_id="account1")
            billing = service(root, settings=settings)
            ProviderCache(paths(root)[2]).update("yandex", {
                "remaining": "10.00", "currency": "RUB", "remaining_source": "provider_reported",
                "last_successful_refresh": "2026-08-21T11:30:00+00:00", "last_attempt": "2026-08-21T11:30:00+00:00",
                "status": "current", "reason": None,
            })
            result = billing.preflight(
                "yandex", current_job_estimate=Decimal("3.25"),
                current_job_estimate_source="local_estimate", hard_limit=Decimal("5"),
                paid_execution_enabled=True,
            )
        self.assertEqual(result["remaining"], "10.00")
        self.assertEqual(result["remaining_source"], "provider_reported")
        self.assertEqual(result["projected_remaining"], "6.75")
        self.assertEqual(result["projected_remaining_source"], "local_estimate")
        self.assertEqual(result["decision"], "ALLOW")

    def test_11_stale_provider_value_keeps_value_and_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = replace(
                CloudBillingSettings(yandex_billing_account_id="account1"),
                provider_stale_after_seconds=60,
            )
            billing = service(root, settings=settings)
            ProviderCache(paths(root)[2]).update("yandex", {
                "remaining": "9.00", "currency": "RUB", "remaining_source": "provider_reported",
                "last_successful_refresh": "2026-08-21T10:00:00+00:00", "last_attempt": "2026-08-21T10:00:00+00:00",
                "status": "current", "reason": None,
            })
            result = billing.status("yandex")
        self.assertEqual(result["remaining"], "9.00")
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["remaining_as_of"], "2026-08-21T10:00:00+00:00")

    def test_12_low_balance_warning_is_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = CloudBillingSettings(
                yandex_billing_account_id="account1",
                yandex_low_balance_threshold_rub=Decimal("5"),
            )
            billing = service(root, settings=settings)
            ProviderCache(paths(root)[2]).update("yandex", {
                "remaining": "4.99", "currency": "RUB", "remaining_source": "provider_reported",
                "last_successful_refresh": "2026-08-21T11:30:00+00:00", "last_attempt": "2026-08-21T11:30:00+00:00",
                "status": "current", "reason": None,
            })
            result = billing.status("yandex")
        self.assertIn("low_balance", result["warnings"])
        self.assertEqual(result["status"], "LOW_BALANCE")

    def test_13_multi_currency_ledgers_never_mix(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = BillingLedger(Path(directory) / "ledger.json")
            record(ledger, provider="yandex", request_id="req-y", cost=Decimal("7.50"), source="local_actual")
            record(ledger, provider="openai", request_id="req-o", cost=Decimal("0.25"), source="local_actual")
            rub = ledger.summarize("yandex", currency="RUB")
            usd = ledger.summarize("openai", currency="USD")
        self.assertEqual(rub["known_total"], Decimal("7.50"))
        self.assertEqual(usd["known_total"], Decimal("0.25"))

    def test_14_snapshot_rejects_missing_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            billing = service(Path(directory))
            with self.assertRaises(BillingError) as raised:
                billing.status(
                    "yandex", current_job_estimate=Decimal("1"),
                    current_job_estimate_source="provider_reported",
                )
        self.assertEqual(raised.exception.category, "provenance")

    def test_15_refresh_interval_prevents_repeated_network_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = CloudBillingSettings(
                yandex_billing_account_id="account1",
                min_refresh_interval_seconds=300,
            )
            settings_path, ledger_path, cache_path = paths(root)
            save_settings(settings_path, settings)
            ProviderCache(cache_path).update("yandex", {
                "remaining": "10", "currency": "RUB", "remaining_source": "provider_reported",
                "last_successful_refresh": "2026-08-21T11:59:00+00:00",
                "last_attempt": "2026-08-21T11:59:00+00:00", "status": "current", "reason": None,
            })
            client = type("NeverCall", (), {"get_account": lambda *_: (_ for _ in ()).throw(
                AssertionError("network attempted")
            )})()
            billing = CloudBillingService(
                settings_path=settings_path,
                ledger_path=ledger_path,
                cache_path=cache_path,
                yandex_client=client,
                now=lambda: NOW,
            )
            result = billing.status("yandex", refresh=True)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(result["remaining"], "10")


if __name__ == "__main__":
    unittest.main()
