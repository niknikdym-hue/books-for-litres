"""Provider-neutral Cloud Billing contracts for Audiobook Studio.

The module never synthesizes audio. Network-capable methods are restricted to
documented, read-only billing endpoints and are injectable for offline tests.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

from backends.common import atomic_write_json


SCHEMA_VERSION = 1
PROVENANCE = {
    "provider_reported",
    "local_actual",
    "local_estimate",
    "user_confirmed",
    "unavailable",
}
PROVIDER_CURRENCIES = {"yandex": "RUB", "openai": "USD"}
YANDEX_BILLING_ENDPOINT = "https://billing.api.cloud.yandex.net/billing/v1/billingAccounts"
YANDEX_BILLING_KEYCHAIN_SERVICE = "AudiobookStudio-YandexBilling-IAM"
OPENAI_ADMIN_KEYCHAIN_SERVICE = "AudiobookStudio-OpenAI-Admin"
OPENAI_COSTS_ENDPOINT = "https://api.openai.com/v1/organization/costs"
OPENAI_AUDIO_USAGE_ENDPOINT = "https://api.openai.com/v1/organization/usage/audio_speeches"
DEFAULT_OPENAI_HARD_LIMIT_USD = Decimal("1.00")
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


def _is_dataless_file(path: Path) -> bool:
    """Return true for an iCloud placeholder whose bytes are not local yet."""
    try:
        flags = path.stat().st_flags
    except (AttributeError, OSError):
        return False
    return bool(flags & getattr(stat, "SF_DATALESS", 0x40000000))


class BillingError(RuntimeError):
    def __init__(self, message: str, *, category: str, remote_request_sent: bool = False) -> None:
        super().__init__(message)
        self.category = category
        self.remote_request_sent = remote_request_sent


def decimal_value(value: Any, field: str, *, allow_negative: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None or value == "":
        raise BillingError(f"Invalid decimal field: {field}.", category="invalid_money")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise BillingError(f"Invalid decimal field: {field}.", category="invalid_money") from error
    if not amount.is_finite() or (amount < 0 and not allow_negative):
        raise BillingError(f"Invalid decimal field: {field}.", category="invalid_money")
    return amount


def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BillingError(f"Invalid timestamp field: {field}.", category="invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BillingError(f"Invalid timestamp field: {field}.", category="invalid_timestamp") from error
    if parsed.tzinfo is None:
        raise BillingError(f"Timestamp must include timezone: {field}.", category="invalid_timestamp")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CloudBillingSettings:
    yandex_billing_account_id: str | None = None
    yandex_low_balance_threshold_rub: Decimal | None = None
    openai_confirmed_balance_usd: Decimal | None = None
    openai_confirmed_at: str | None = None
    openai_low_balance_threshold_usd: Decimal | None = None
    openai_hard_limit_usd: Decimal = DEFAULT_OPENAI_HARD_LIMIT_USD
    min_refresh_interval_seconds: int = 300
    provider_stale_after_seconds: int = 3600
    user_balance_stale_after_seconds: int = 604800

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CloudBillingSettings":
        if set(data) != {"schema_version", "yandex", "openai", "refresh"}:
            raise BillingError("Cloud Billing settings contain unsupported fields.", category="settings")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise BillingError("Unsupported Cloud Billing settings schema.", category="settings")
        yandex = data.get("yandex")
        openai = data.get("openai")
        refresh = data.get("refresh")
        if not isinstance(yandex, dict) or set(yandex) != {
            "billing_account_id", "low_balance_threshold_rub"
        }:
            raise BillingError("Invalid Yandex billing settings.", category="settings")
        if not isinstance(openai, dict) or set(openai) != {
            "user_confirmed_balance", "low_balance_threshold_usd", "hard_limit_usd"
        }:
            raise BillingError("Invalid OpenAI billing settings.", category="settings")
        if not isinstance(refresh, dict) or set(refresh) != {
            "min_interval_seconds", "provider_stale_after_seconds", "user_balance_stale_after_seconds"
        }:
            raise BillingError("Invalid billing refresh settings.", category="settings")

        account_id = yandex.get("billing_account_id")
        if account_id is not None and (
            not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id)
        ):
            raise BillingError("Invalid Yandex billing account ID.", category="settings")

        baseline = openai.get("user_confirmed_balance")
        baseline_value: Decimal | None = None
        confirmed_at: str | None = None
        if baseline is not None:
            if not isinstance(baseline, dict) or set(baseline) != {"value", "confirmed_at"}:
                raise BillingError("Invalid user-confirmed OpenAI balance.", category="settings")
            baseline_value = decimal_value(baseline.get("value"), "openai.user_confirmed_balance.value")
            confirmed_at = _iso(parse_timestamp(baseline.get("confirmed_at"), "openai.confirmed_at"))

        def optional_money(value: Any, field: str) -> Decimal | None:
            return None if value is None else decimal_value(value, field)

        min_interval = int(refresh.get("min_interval_seconds"))
        provider_stale = int(refresh.get("provider_stale_after_seconds"))
        user_stale = int(refresh.get("user_balance_stale_after_seconds"))
        if min_interval < 0 or provider_stale <= 0 or user_stale <= 0:
            raise BillingError("Invalid billing freshness interval.", category="settings")
        return cls(
            yandex_billing_account_id=account_id,
            yandex_low_balance_threshold_rub=optional_money(
                yandex.get("low_balance_threshold_rub"), "yandex.low_balance_threshold_rub"
            ),
            openai_confirmed_balance_usd=baseline_value,
            openai_confirmed_at=confirmed_at,
            openai_low_balance_threshold_usd=optional_money(
                openai.get("low_balance_threshold_usd"), "openai.low_balance_threshold_usd"
            ),
            openai_hard_limit_usd=decimal_value(openai.get("hard_limit_usd"), "openai.hard_limit_usd"),
            min_refresh_interval_seconds=min_interval,
            provider_stale_after_seconds=provider_stale,
            user_balance_stale_after_seconds=user_stale,
        )

    def to_mapping(self) -> dict[str, Any]:
        baseline = None
        if self.openai_confirmed_balance_usd is not None:
            baseline = {
                "value": decimal_text(self.openai_confirmed_balance_usd),
                "confirmed_at": self.openai_confirmed_at,
            }
        return {
            "schema_version": SCHEMA_VERSION,
            "yandex": {
                "billing_account_id": self.yandex_billing_account_id,
                "low_balance_threshold_rub": decimal_text(self.yandex_low_balance_threshold_rub),
            },
            "openai": {
                "user_confirmed_balance": baseline,
                "low_balance_threshold_usd": decimal_text(self.openai_low_balance_threshold_usd),
                "hard_limit_usd": decimal_text(self.openai_hard_limit_usd),
            },
            "refresh": {
                "min_interval_seconds": self.min_refresh_interval_seconds,
                "provider_stale_after_seconds": self.provider_stale_after_seconds,
                "user_balance_stale_after_seconds": self.user_balance_stale_after_seconds,
            },
        }


def load_settings(path: Path) -> CloudBillingSettings:
    path = Path(path)
    if not path.exists():
        return CloudBillingSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BillingError("Cannot read Cloud Billing settings.", category="settings") from error
    if not isinstance(data, dict):
        raise BillingError("Cloud Billing settings must be a JSON object.", category="settings")
    return CloudBillingSettings.from_mapping(data)


def save_settings(path: Path, settings: CloudBillingSettings) -> None:
    atomic_write_json(Path(path), settings.to_mapping())


class BillingLedger:
    """Atomic, lock-protected ledger of Studio billing events."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "transactions": []}
        if _is_dataless_file(self.path):
            raise BillingError(
                "Cloud Billing ledger must be downloaded from iCloud.",
                category="ledger_download_required",
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BillingError("Cannot read Cloud Billing ledger.", category="ledger") from error
        if not isinstance(data, dict) or set(data) != {"schema_version", "transactions"}:
            raise BillingError("Invalid Cloud Billing ledger root.", category="ledger")
        if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("transactions"), list):
            raise BillingError("Unsupported Cloud Billing ledger schema.", category="ledger")
        for transaction in data["transactions"]:
            self._validate_transaction(transaction)
        return data

    @staticmethod
    def _validate_transaction(transaction: Any) -> None:
        required = {
            "transaction_id", "provider", "job_id", "segment_id", "request_id", "profile_id",
            "timestamp", "currency", "actual_cost", "cost_source", "fingerprint",
        }
        if not isinstance(transaction, dict) or set(transaction) != required:
            raise BillingError("Invalid Cloud Billing ledger transaction.", category="ledger")
        provider = transaction.get("provider")
        if provider not in PROVIDER_CURRENCIES or transaction.get("currency") != PROVIDER_CURRENCIES[provider]:
            raise BillingError("Ledger transaction has invalid provider currency.", category="ledger")
        source = transaction.get("cost_source")
        if source not in {"local_actual", "provider_reported", "unavailable"}:
            raise BillingError("Ledger transaction has invalid cost provenance.", category="ledger")
        if transaction.get("actual_cost") is None:
            if source != "unavailable":
                raise BillingError("Missing actual cost requires unavailable provenance.", category="ledger")
        else:
            decimal_value(transaction.get("actual_cost"), "ledger.actual_cost")
            if source == "unavailable":
                raise BillingError("Available actual cost cannot use unavailable provenance.", category="ledger")
        parse_timestamp(transaction.get("timestamp"), "ledger.timestamp")
        for field in ("transaction_id", "job_id", "segment_id", "profile_id", "fingerprint"):
            if not isinstance(transaction.get(field), str) or not transaction[field]:
                raise BillingError(f"Invalid ledger field: {field}.", category="ledger")
        if transaction.get("request_id") is not None and not isinstance(transaction.get("request_id"), str):
            raise BillingError("Invalid ledger request_id.", category="ledger")

    def transactions(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._load_unlocked()["transactions"]]

    def record(
        self,
        *,
        provider: str,
        job_id: str,
        segment_id: str,
        request_id: str | None,
        profile_id: str,
        timestamp: str,
        currency: str,
        actual_cost: Decimal | None,
        cost_source: str,
        fingerprint: str,
    ) -> tuple[str, bool]:
        identity = (
            f"{provider}|request|{request_id}" if request_id
            else f"{provider}|job|{job_id}|segment|{segment_id}|fingerprint|{fingerprint}"
        )
        transaction_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        transaction = {
            "transaction_id": transaction_id,
            "provider": provider,
            "job_id": job_id,
            "segment_id": segment_id,
            "request_id": request_id,
            "profile_id": profile_id,
            "timestamp": _iso(parse_timestamp(timestamp, "ledger.timestamp")),
            "currency": currency,
            "actual_cost": decimal_text(actual_cost),
            "cost_source": cost_source,
            "fingerprint": fingerprint,
        }
        self._validate_transaction(transaction)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = self._load_unlocked()
            for existing in data["transactions"]:
                if existing["transaction_id"] == transaction_id:
                    comparable_existing = {key: value for key, value in existing.items() if key != "timestamp"}
                    comparable_new = {key: value for key, value in transaction.items() if key != "timestamp"}
                    if comparable_existing != comparable_new:
                        raise BillingError(
                            "Conflicting duplicate billing transaction.", category="duplicate_transaction"
                        )
                    return transaction_id, False
                if request_id and existing.get("provider") == provider and existing.get("request_id") == request_id:
                    raise BillingError(
                        "A provider request ID is already assigned to another transaction.",
                        category="duplicate_request",
                    )
            data["transactions"].append(transaction)
            atomic_write_json(self.path, data)
            return transaction_id, True

    def summarize(
        self,
        provider: str,
        *,
        currency: str,
        since: str | None = None,
    ) -> dict[str, Any]:
        since_value = parse_timestamp(since, "ledger.since") if since else None
        known_total = Decimal("0")
        known_count = 0
        unknown_count = 0
        last_timestamp: datetime | None = None
        for transaction in self.transactions():
            if transaction["provider"] != provider or transaction["currency"] != currency:
                continue
            timestamp = parse_timestamp(transaction["timestamp"], "ledger.timestamp")
            if since_value is not None and timestamp < since_value:
                continue
            last_timestamp = max(last_timestamp, timestamp) if last_timestamp else timestamp
            if transaction["actual_cost"] is None:
                unknown_count += 1
            else:
                known_total += decimal_value(transaction["actual_cost"], "ledger.actual_cost")
                known_count += 1
        return {
            "known_total": known_total,
            "known_count": known_count,
            "unknown_count": unknown_count,
            "as_of": _iso(last_timestamp) if last_timestamp else None,
        }


def read_keychain_secret(
    service: str,
    account: str = "",
    *,
    runner: Callable[..., Any] = subprocess.run,
    username_loader: Callable[..., str] = subprocess.check_output,
) -> str:
    if not account:
        try:
            account = username_loader(["/usr/bin/id", "-un"], text=True).strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise BillingError("Unable to determine Keychain account.", category="credential_unavailable") from error
    try:
        result = runner(
            ["/usr/bin/security", "find-generic-password", "-a", account, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise BillingError("macOS Keychain is unavailable.", category="credential_unavailable") from error
    value = result.stdout.strip() if result.returncode == 0 else ""
    if not value or any(character.isspace() for character in value):
        raise BillingError("Billing credential is unavailable.", category="credential_unavailable")
    return value


class YandexBillingClient:
    def __init__(
        self,
        *,
        credential_loader: Callable[[], str] | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout_seconds: int = 30,
    ) -> None:
        self._credential_loader = credential_loader or (
            lambda: read_keychain_secret(YANDEX_BILLING_KEYCHAIN_SERVICE)
        )
        self._opener = opener
        self.timeout_seconds = timeout_seconds

    def credential_available(self) -> bool:
        try:
            self._credential_loader()
        except BillingError:
            return False
        return True

    def get_account(self, account_id: str) -> dict[str, Any]:
        if not _ACCOUNT_ID.fullmatch(account_id):
            raise BillingError("Invalid Yandex billing account ID.", category="settings")
        try:
            token = self._credential_loader()
        except BillingError as error:
            raise BillingError(
                "Yandex Billing IAM credential is unavailable.",
                category="billing_iam_credential_unavailable",
            ) from error
        request = urllib.request.Request(
            f"{YANDEX_BILLING_ENDPOINT}/{urllib.parse.quote(account_id, safe='')}",
            method="GET",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
            try:
                try:
                    payload = json.loads(response.read().decode("utf-8"), parse_float=Decimal)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise BillingError(
                        "Invalid Yandex Billing JSON response.",
                        category="billing_response",
                        remote_request_sent=True,
                    ) from error
            finally:
                response.close()
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            category = {
                401: "billing_auth_unavailable",
                403: "billing_permission_unavailable",
                404: "billing_account_not_found",
            }.get(code, "billing_http_error")
            raise BillingError(
                f"Yandex Billing HTTP {code}.", category=category, remote_request_sent=True
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise BillingError(
                "Yandex Billing network request failed.",
                category="billing_network_error",
                remote_request_sent=True,
            ) from error
        if not isinstance(payload, dict):
            raise BillingError(
                "Invalid Yandex Billing response.", category="billing_response", remote_request_sent=True
            )
        currency = str(payload.get("currency") or "").upper()
        if currency not in {"RUB", "USD", "KZT"}:
            raise BillingError(
                "Invalid Yandex Billing currency.", category="billing_response", remote_request_sent=True
            )
        try:
            balance = decimal_value(payload.get("balance"), "yandex.balance", allow_negative=True)
        except BillingError as error:
            raise BillingError(
                "Invalid Yandex Billing balance.", category="billing_response", remote_request_sent=True
            ) from error
        return {
            "account_id": str(payload.get("id") or account_id),
            "currency": currency,
            "balance": balance,
        }


class OpenAIAdminClient:
    def __init__(
        self,
        *,
        credential_loader: Callable[[], str] | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout_seconds: int = 30,
    ) -> None:
        self._credential_loader = credential_loader or (
            lambda: read_keychain_secret(OPENAI_ADMIN_KEYCHAIN_SERVICE)
        )
        self._opener = opener
        self.timeout_seconds = timeout_seconds

    def credential_available(self) -> bool:
        try:
            self._credential_loader()
        except BillingError:
            return False
        return True

    def _get_pages(self, endpoint: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
        if endpoint not in {OPENAI_COSTS_ENDPOINT, OPENAI_AUDIO_USAGE_ENDPOINT}:
            raise BillingError("Undocumented OpenAI billing endpoint is forbidden.", category="endpoint_forbidden")
        try:
            credential = self._credential_loader()
        except BillingError as error:
            raise BillingError(
                "OpenAI Admin credential is unavailable.", category="unavailable_admin_credential"
            ) from error
        page: str | None = None
        seen_pages: set[str] = set()
        results: list[dict[str, Any]] = []
        for _ in range(100):
            query = dict(parameters)
            if page:
                query["page"] = page
            request = urllib.request.Request(
                f"{endpoint}?{urllib.parse.urlencode(query)}",
                method="GET",
                headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
            )
            try:
                response = self._opener(request, timeout=self.timeout_seconds)
                try:
                    try:
                        payload = json.loads(response.read().decode("utf-8"), parse_float=Decimal)
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise BillingError(
                            "Invalid OpenAI Organization API JSON response.",
                            category="provider_response",
                            remote_request_sent=True,
                        ) from error
                finally:
                    response.close()
            except urllib.error.HTTPError as error:
                code = error.code
                error.close()
                category = (
                    "unavailable_admin_credential" if code == 401
                    else "admin_permission_unavailable" if code == 403
                    else "provider_costs_unavailable"
                )
                raise BillingError(
                    f"OpenAI Organization API HTTP {code}.",
                    category=category,
                    remote_request_sent=True,
                ) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise BillingError(
                    "OpenAI Organization API network request failed.",
                    category="provider_network_error",
                    remote_request_sent=True,
                ) from error
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise BillingError(
                    "Invalid OpenAI Organization API response.",
                    category="provider_response",
                    remote_request_sent=True,
                )
            results.extend(payload["data"])
            if not payload.get("has_more"):
                return results
            next_page = payload.get("next_page")
            if not isinstance(next_page, str) or not next_page or next_page in seen_pages:
                raise BillingError(
                    "Invalid OpenAI pagination cursor.",
                    category="provider_response",
                    remote_request_sent=True,
                )
            seen_pages.add(next_page)
            page = next_page
        raise BillingError(
            "OpenAI pagination exceeded the safety limit.",
            category="provider_response",
            remote_request_sent=True,
        )

    def costs(self, *, start_time: int, end_time: int) -> dict[str, Decimal]:
        buckets = self._get_pages(OPENAI_COSTS_ENDPOINT, {
            "start_time": start_time,
            "end_time": end_time,
            "bucket_width": "1d",
            "limit": 180,
        })
        totals: dict[str, Decimal] = {}
        for bucket in buckets:
            if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list):
                raise BillingError(
                    "Invalid OpenAI costs bucket.", category="provider_response", remote_request_sent=True
                )
            for result in bucket["results"]:
                amount = result.get("amount") if isinstance(result, dict) else None
                if not isinstance(amount, dict):
                    raise BillingError(
                        "Invalid OpenAI cost amount.", category="provider_response", remote_request_sent=True
                    )
                currency = str(amount.get("currency") or "").upper()
                if not currency:
                    raise BillingError(
                        "Invalid OpenAI cost currency.", category="provider_response", remote_request_sent=True
                    )
                try:
                    value = decimal_value(amount.get("value"), "openai.cost")
                except BillingError as error:
                    raise BillingError(
                        "Invalid OpenAI cost value.", category="provider_response", remote_request_sent=True
                    ) from error
                totals[currency] = totals.get(currency, Decimal("0")) + value
        return totals

    def audio_speech_usage(self, *, start_time: int, end_time: int) -> dict[str, int]:
        buckets = self._get_pages(OPENAI_AUDIO_USAGE_ENDPOINT, {
            "start_time": start_time,
            "end_time": end_time,
            "bucket_width": "1d",
            "limit": 31,
        })
        characters = 0
        requests = 0
        for bucket in buckets:
            if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list):
                raise BillingError(
                    "Invalid OpenAI audio usage bucket.",
                    category="provider_response",
                    remote_request_sent=True,
                )
            for result in bucket["results"]:
                if not isinstance(result, dict):
                    raise BillingError(
                        "Invalid OpenAI audio usage result.",
                        category="provider_response",
                        remote_request_sent=True,
                    )
                character_value = result.get("characters", 0)
                request_value = result.get("num_model_requests", 0)
                if not isinstance(character_value, int) or not isinstance(request_value, int):
                    raise BillingError(
                        "Invalid OpenAI audio usage values.",
                        category="provider_response",
                        remote_request_sent=True,
                    )
                if character_value < 0 or request_value < 0:
                    raise BillingError(
                        "Negative OpenAI audio usage values.",
                        category="provider_response",
                        remote_request_sent=True,
                    )
                characters += character_value
                requests += request_value
        return {"characters": characters, "num_model_requests": requests}


class ProviderCache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "providers": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BillingError("Cannot read billing provider cache.", category="provider_cache") from error
        if (
            not isinstance(data, dict)
            or set(data) != {"schema_version", "providers"}
            or data.get("schema_version") != SCHEMA_VERSION
            or not isinstance(data.get("providers"), dict)
        ):
            raise BillingError("Invalid billing provider cache.", category="provider_cache")
        return data

    def update(self, provider: str, values: Mapping[str, Any]) -> None:
        data = self.load()
        current = dict(data["providers"].get(provider) or {})
        current.update(values)
        data["providers"][provider] = current
        atomic_write_json(self.path, data)


class CloudBillingService:
    def __init__(
        self,
        *,
        settings_path: Path,
        ledger_path: Path,
        cache_path: Path,
        yandex_client: YandexBillingClient | None = None,
        openai_client: OpenAIAdminClient | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings_path = Path(settings_path)
        self.settings = load_settings(self.settings_path)
        self.ledger = BillingLedger(ledger_path)
        self.cache = ProviderCache(cache_path)
        self.yandex_client = yandex_client or YandexBillingClient()
        self.openai_client = openai_client or OpenAIAdminClient()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _cache_entry(self, provider: str) -> dict[str, Any]:
        return dict(self.cache.load()["providers"].get(provider) or {})

    def _refresh_due(self, entry: Mapping[str, Any]) -> bool:
        attempt = entry.get("last_attempt")
        if not attempt:
            return True
        return self._now() - parse_timestamp(attempt, "cache.last_attempt") >= timedelta(
            seconds=self.settings.min_refresh_interval_seconds
        )

    def refresh(self, provider: str) -> bool:
        if provider not in PROVIDER_CURRENCIES:
            raise BillingError("Unsupported billing provider.", category="provider")
        entry = self._cache_entry(provider)
        if not self._refresh_due(entry):
            return False
        attempted_at = _iso(self._now())
        try:
            if provider == "yandex":
                account_id = self.settings.yandex_billing_account_id
                if not account_id:
                    raise BillingError("Yandex billing account ID is not configured.", category="billing_account_id_missing")
                result = self.yandex_client.get_account(account_id)
                self.cache.update("yandex", {
                    "remaining": decimal_text(result["balance"]),
                    "currency": result["currency"],
                    "remaining_source": "provider_reported",
                    "last_successful_refresh": attempted_at,
                    "last_attempt": attempted_at,
                    "status": "current",
                    "reason": None,
                })
            else:
                end_time = int(self._now().timestamp())
                start_time = int((self._now() - timedelta(days=30)).timestamp())
                costs = self.openai_client.costs(start_time=start_time, end_time=end_time)
                usage = self.openai_client.audio_speech_usage(start_time=start_time, end_time=end_time)
                self.cache.update("openai", {
                    "provider_costs": {currency: decimal_text(value) for currency, value in costs.items()},
                    "provider_costs_source": "provider_reported",
                    "provider_costs_period_start": datetime.fromtimestamp(start_time, timezone.utc).isoformat(),
                    "provider_costs_period_end": datetime.fromtimestamp(end_time, timezone.utc).isoformat(),
                    "audio_speech_usage": usage,
                    "last_successful_refresh": attempted_at,
                    "last_attempt": attempted_at,
                    "status": "current",
                    "reason": None,
                })
            return True
        except BillingError as error:
            self.cache.update(provider, {
                "last_attempt": attempted_at,
                "status": "error",
                "reason": error.category,
            })
            return error.remote_request_sent

    def _spent_fields(self, provider: str, now_text: str) -> tuple[dict[str, Any], list[str]]:
        currency = PROVIDER_CURRENCIES[provider]
        try:
            summary = self.ledger.summarize(provider, currency=currency)
        except BillingError as error:
            if error.category != "ledger_download_required":
                raise
            return ({
                "spent": None,
                "spent_source": "unavailable",
                "spent_as_of": now_text,
                "known_local_actual_spend": None,
                "unknown_cost_events": None,
            }, ["billing_ledger_download_required", "local_actual_spend_unavailable"])
        warnings: list[str] = []
        if summary["unknown_count"]:
            warnings.append("local_actual_spend_incomplete")
            return ({
                "spent": None,
                "spent_source": "unavailable",
                "spent_as_of": summary["as_of"] or now_text,
                "known_local_actual_spend": decimal_text(summary["known_total"]),
                "unknown_cost_events": summary["unknown_count"],
            }, warnings)
        return ({
            "spent": decimal_text(summary["known_total"]),
            "spent_source": "local_actual",
            "spent_as_of": summary["as_of"] or now_text,
            "known_local_actual_spend": decimal_text(summary["known_total"]),
            "unknown_cost_events": 0,
        }, warnings)

    def status(
        self,
        provider: str,
        *,
        refresh: bool = False,
        current_job_estimate: Decimal | None = None,
        current_job_estimate_source: str = "unavailable",
        hard_limit: Decimal | None = None,
        paid_execution_enabled: bool = True,
        job_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if provider not in PROVIDER_CURRENCIES:
            raise BillingError("Unsupported billing provider.", category="provider")
        if current_job_estimate_source not in PROVENANCE:
            raise BillingError("Invalid job estimate provenance.", category="provenance")
        if current_job_estimate is None and current_job_estimate_source != "unavailable":
            raise BillingError("Missing estimate requires unavailable provenance.", category="provenance")
        if current_job_estimate is not None:
            current_job_estimate = decimal_value(current_job_estimate, "current_job_estimate")
            if current_job_estimate_source != "local_estimate":
                raise BillingError("Job estimate must use local_estimate provenance.", category="provenance")
        remote_request_sent = self.refresh(provider) if refresh else False
        now = self._now()
        now_text = _iso(now)
        currency = PROVIDER_CURRENCIES[provider]
        spent, warnings = self._spent_fields(provider, now_text)
        entry = self._cache_entry(provider)

        remaining: Decimal | None = None
        remaining_source = "unavailable"
        remaining_as_of: str | None = None
        freshness = "unavailable"
        reason = entry.get("reason")

        if provider == "yandex" and entry.get("remaining") is not None:
            cached_currency = str(entry.get("currency") or "")
            if cached_currency == currency:
                remaining = decimal_value(entry["remaining"], "cache.remaining", allow_negative=True)
                remaining_source = "provider_reported"
                remaining_as_of = entry.get("last_successful_refresh")
                success_at = parse_timestamp(remaining_as_of, "cache.last_successful_refresh")
                stale_by_age = (now - success_at).total_seconds() > self.settings.provider_stale_after_seconds
                freshness = "stale" if stale_by_age or entry.get("status") != "current" else "current"
                if freshness == "stale":
                    warnings.append("provider_balance_stale")
        elif provider == "openai" and self.settings.openai_confirmed_balance_usd is not None:
            since = self.settings.openai_confirmed_at
            warnings.append("openai_balance_may_exclude_usage_outside_audiobook_studio")
            try:
                summary = self.ledger.summarize("openai", currency="USD", since=since)
            except BillingError as error:
                if error.category != "ledger_download_required":
                    raise
                warnings.append("openai_local_spend_since_confirmation_unavailable")
            else:
                if summary["unknown_count"]:
                    warnings.append("openai_local_spend_since_confirmation_incomplete")
                else:
                    remaining = self.settings.openai_confirmed_balance_usd - summary["known_total"]
                    remaining_source = "local_estimate"
                    remaining_as_of = now_text
                    confirmed = parse_timestamp(since, "openai.confirmed_at")
                    stale = (now - confirmed).total_seconds() > self.settings.user_balance_stale_after_seconds
                    freshness = "stale" if stale else "current"
                    if stale:
                        warnings.append("user_confirmed_balance_stale")

        if remaining is None:
            warnings.append("remaining_unavailable")

        projected: Decimal | None = None
        projected_source = "unavailable"
        if remaining is not None and current_job_estimate is not None:
            projected = remaining - current_job_estimate
            projected_source = "local_estimate"

        threshold = (
            self.settings.yandex_low_balance_threshold_rub
            if provider == "yandex" else self.settings.openai_low_balance_threshold_usd
        )
        if threshold is not None and remaining is not None and remaining <= threshold:
            warnings.append("low_balance")
        if threshold is not None and projected is not None and projected <= threshold:
            warnings.append("projected_low_balance")

        status = "BALANCE_UNKNOWN" if remaining is None else "AVAILABLE"
        if freshness == "stale":
            status = "STALE"
        if "low_balance" in warnings:
            status = "LOW_BALANCE"

        if provider == "openai":
            provider_costs_status = reason or "unavailable_admin_credential"
            if entry.get("provider_costs"):
                costs_as_of = entry.get("last_successful_refresh")
                costs_stale = entry.get("status") != "current"
                if costs_as_of:
                    costs_stale = costs_stale or (
                        now - parse_timestamp(costs_as_of, "cache.last_successful_refresh")
                    ).total_seconds() > self.settings.provider_stale_after_seconds
                provider_costs_status = "stale" if costs_stale else "available"
                if costs_stale:
                    warnings.append("provider_costs_stale")
            provider_metadata = {
                "provider_costs": entry.get("provider_costs"),
                "provider_costs_source": entry.get("provider_costs_source", "unavailable"),
                "provider_costs_status": provider_costs_status,
                "provider_costs_period_start": entry.get("provider_costs_period_start"),
                "provider_costs_period_end": entry.get("provider_costs_period_end"),
                "audio_speech_usage": entry.get("audio_speech_usage"),
                "exact_prepaid_balance_status": "unavailable_documented_api",
                "user_confirmed_balance": decimal_text(self.settings.openai_confirmed_balance_usd),
                "user_confirmed_balance_source": (
                    "user_confirmed" if self.settings.openai_confirmed_balance_usd is not None else "unavailable"
                ),
                "user_confirmed_at": self.settings.openai_confirmed_at,
            }
        else:
            provider_metadata = {
                "billing_account_id_configured": self.settings.yandex_billing_account_id is not None,
                "billing_auth_contract": "iam_bearer_token",
                "existing_speechkit_api_key_compatible": False,
                "minimum_read_only_role": "billing.accounts.viewer",
                "provider_balance_status": reason or ("available" if remaining is not None else "unavailable"),
            }

        result = {
            "schema_version": SCHEMA_VERSION,
            "provider": provider,
            "currency": currency,
            **spent,
            "remaining": decimal_text(remaining),
            "remaining_source": remaining_source,
            "remaining_as_of": remaining_as_of,
            "current_job_estimate": decimal_text(current_job_estimate),
            "current_job_estimate_source": current_job_estimate_source,
            "projected_remaining": decimal_text(projected),
            "projected_remaining_source": projected_source,
            "freshness": freshness,
            "status": status,
            "warnings": sorted(set(warnings)),
            "low_balance_threshold": decimal_text(threshold),
            "hard_limit": decimal_text(hard_limit),
            "last_successful_refresh": entry.get("last_successful_refresh"),
            "last_attempt": entry.get("last_attempt"),
            "stale_after_seconds": (
                self.settings.user_balance_stale_after_seconds
                if provider == "openai" and remaining_source == "local_estimate"
                else self.settings.provider_stale_after_seconds
            ),
            "provider_metadata": provider_metadata,
            "job_metadata": dict(job_metadata or {}),
            "paid_execution_enabled": paid_execution_enabled,
            "remote_request_sent": remote_request_sent,
        }
        self._validate_snapshot(result)
        return result

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
        for value_field, source_field in (
            ("spent", "spent_source"),
            ("remaining", "remaining_source"),
            ("current_job_estimate", "current_job_estimate_source"),
            ("projected_remaining", "projected_remaining_source"),
        ):
            source = snapshot.get(source_field)
            if source not in PROVENANCE:
                raise BillingError(f"Missing provenance: {source_field}.", category="provenance")
            if snapshot.get(value_field) is None and source != "unavailable":
                raise BillingError(f"Unavailable value has invalid provenance: {value_field}.", category="provenance")
            if snapshot.get(value_field) is not None:
                decimal_value(snapshot[value_field], value_field, allow_negative=value_field in {
                    "remaining", "projected_remaining"
                })
                if source == "unavailable":
                    raise BillingError(f"Available value has unavailable provenance: {value_field}.", category="provenance")

    def preflight(
        self,
        provider: str,
        *,
        current_job_estimate: Decimal | None,
        current_job_estimate_source: str,
        hard_limit: Decimal | None,
        paid_execution_enabled: bool,
        job_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = self.status(
            provider,
            current_job_estimate=current_job_estimate,
            current_job_estimate_source=current_job_estimate_source,
            hard_limit=hard_limit,
            paid_execution_enabled=paid_execution_enabled,
            job_metadata=job_metadata,
        )
        estimate = current_job_estimate
        remaining = (
            decimal_value(snapshot["remaining"], "remaining", allow_negative=True)
            if snapshot["remaining"] is not None else None
        )
        if provider == "openai" and not paid_execution_enabled:
            decision, reason = "BLOCK", "openai_paid_execution_disabled"
        elif estimate is None:
            decision, reason = "BALANCE_UNKNOWN", "current_job_cost_unavailable"
        elif hard_limit is None:
            decision, reason = "BLOCK", "hard_limit_missing"
        elif estimate > hard_limit:
            decision, reason = "BLOCK", "hard_limit_exceeded"
        elif remaining is None:
            decision, reason = "BALANCE_UNKNOWN", "remaining_unavailable"
        elif remaining < estimate:
            decision, reason = "BLOCK", "insufficient_balance"
        elif "projected_low_balance" in snapshot["warnings"]:
            decision, reason = "REQUIRES_CONFIRMATION", "projected_low_balance"
        else:
            decision, reason = "ALLOW", None
        snapshot["decision"] = decision
        snapshot["decision_reason"] = reason
        return snapshot
