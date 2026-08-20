"""Offline pricing policy for Yandex SpeechKit jobs.

The rate is deliberately configuration data: accounts and regions can have a
different contract price.  This module never contacts Yandex Billing or TTS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from .yandex_types import ENGINE_ID, YandexSpeechKitError


def _decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise YandexSpeechKitError(f"Некорректное значение {field} в тарифе.", category="pricing") from error
    if result < 0:
        raise YandexSpeechKitError(f"{field} не может быть отрицательным.", category="pricing")
    return result


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise YandexSpeechKitError(f"Некорректная дата {field} в тарифе.", category="pricing") from error


@dataclass(frozen=True)
class YandexPricingConfig:
    currency: str
    unit: str
    unit_price: Decimal | None
    pricing_model: str
    source_region: str
    verified_at: date | None
    source_url: str
    max_age_days: int
    hard_limit_rub: Decimal | None
    demo_hard_limit_rub: Decimal | None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "YandexPricingConfig":
        if data.get("engine", ENGINE_ID) != ENGINE_ID:
            raise YandexSpeechKitError("Тариф относится к другому TTS-движку.", category="pricing")
        max_age_days = int(data.get("max_age_days", 30))
        if max_age_days < 0:
            raise YandexSpeechKitError("max_age_days не может быть отрицательным.", category="pricing")
        return cls(
            currency=str(data.get("currency", "RUB")),
            unit=str(data.get("unit", "billing_unit")),
            unit_price=_decimal(data.get("unit_price"), "unit_price"),
            pricing_model=str(data.get("pricing_model", "per_250_chars_or_request_unit")),
            source_region=str(data.get("source_region", "")),
            verified_at=_date(data["verified_at"], "verified_at") if data.get("verified_at") else None,
            source_url=str(data.get("source_url", "")),
            max_age_days=max_age_days,
            hard_limit_rub=_decimal(data.get("hard_limit_rub"), "hard_limit_rub"),
            demo_hard_limit_rub=_decimal(data.get("demo_hard_limit_rub"), "demo_hard_limit_rub"),
        )

    def is_stale(self, *, today: date | None = None) -> bool:
        if self.unit_price is None or self.verified_at is None or not self.source_url:
            return True
        today = today or datetime.now().date()
        return (today - self.verified_at).days > self.max_age_days

    def effective_hard_limit(self, scope: str) -> Decimal | None:
        return self.demo_hard_limit_rub if scope == "demo" else self.hard_limit_rub


def load_pricing_config(path: Path) -> YandexPricingConfig:
    with Path(path).open("r", encoding="utf-8") as source:
        return YandexPricingConfig.from_mapping(json.load(source))


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def price_estimate(
    *,
    total_units: int,
    billable_remaining_units: int,
    pricing: YandexPricingConfig,
    scope: str = "book",
    today: date | None = None,
) -> dict[str, Any]:
    """Return JSON-safe pricing policy fields without any network access."""
    if total_units < 0 or billable_remaining_units < 0 or billable_remaining_units > total_units:
        raise ValueError("Invalid billing unit counts")

    stale = pricing.is_stale(today=today)
    total_cost = Decimal(total_units) * pricing.unit_price if pricing.unit_price is not None else None
    remaining_cost = Decimal(billable_remaining_units) * pricing.unit_price if pricing.unit_price is not None else None
    hard_limit = pricing.effective_hard_limit(scope)
    allowed = bool(
        pricing.unit_price is not None
        and not stale
        and hard_limit is not None
        and remaining_cost is not None
        and remaining_cost <= hard_limit
    )
    if pricing.unit_price is None:
        blocked_reason = "missing_tariff"
    elif stale:
        blocked_reason = "stale_tariff"
    elif hard_limit is None:
        blocked_reason = "missing_hard_limit"
    elif remaining_cost is not None and remaining_cost > hard_limit:
        blocked_reason = "hard_limit_exceeded"
    else:
        blocked_reason = None

    return {
        "currency": pricing.currency,
        "unit": pricing.unit,
        "unit_price": decimal_text(pricing.unit_price),
        "pricing_model": pricing.pricing_model,
        "price_source": pricing.source_url or None,
        "price_source_region": pricing.source_region or None,
        "price_verified_at": pricing.verified_at.isoformat() if pricing.verified_at else None,
        "price_max_age_days": pricing.max_age_days,
        "price_stale": stale,
        "total_billing_units": total_units,
        "billable_remaining_units": billable_remaining_units,
        "estimated_total_cost": decimal_text(total_cost),
        "estimated_remaining_cost": decimal_text(remaining_cost),
        "hard_limit_rub": decimal_text(hard_limit),
        "allowed_to_start": allowed,
        "blocked_reason": blocked_reason,
    }
