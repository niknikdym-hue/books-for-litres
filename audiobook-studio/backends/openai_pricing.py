"""Offline pricing metadata and honest OpenAI TTS preflight labeling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .openai_types import ENGINE_ID, OpenAITTSError


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise OpenAITTSError(f"Invalid OpenAI pricing field: {field}.", category="pricing") from error
    if result < 0:
        raise OpenAITTSError(f"OpenAI pricing field cannot be negative: {field}.", category="pricing")
    return result


@dataclass(frozen=True)
class OpenAIPricingConfig:
    model: str
    currency: str
    text_input_per_million_tokens: Decimal
    audio_output_per_million_tokens: Decimal
    verified_at: date
    source_url: str
    max_age_days: int
    output_cost_estimate: str
    actual_cost_source: str

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "OpenAIPricingConfig":
        if data.get("engine", ENGINE_ID) != ENGINE_ID or int(data.get("schema_version", 0)) != 1:
            raise OpenAITTSError("OpenAI pricing metadata has an invalid contract.", category="pricing")
        try:
            verified_at = date.fromisoformat(str(data["verified_at"]))
        except (KeyError, ValueError) as error:
            raise OpenAITTSError("OpenAI pricing verified_at is invalid.", category="pricing") from error
        max_age_days = int(data.get("max_age_days", 30))
        if max_age_days < 0:
            raise OpenAITTSError("OpenAI pricing max_age_days is invalid.", category="pricing")
        source_url = str(data.get("source_url") or "")
        if not source_url.startswith("https://"):
            raise OpenAITTSError("OpenAI pricing source URL is missing.", category="pricing")
        return cls(
            model=str(data.get("model") or ""),
            currency=str(data.get("currency") or "USD"),
            text_input_per_million_tokens=_decimal(
                data.get("text_input_per_million_tokens"), "text_input_per_million_tokens"
            ),
            audio_output_per_million_tokens=_decimal(
                data.get("audio_output_per_million_tokens"), "audio_output_per_million_tokens"
            ),
            verified_at=verified_at,
            source_url=source_url,
            max_age_days=max_age_days,
            output_cost_estimate=str(data.get("output_cost_estimate") or "unavailable"),
            actual_cost_source=str(data.get("actual_cost_source") or "provider_billing"),
        )

    def is_stale(self, *, today: date | None = None) -> bool:
        current = today or datetime.now().date()
        return (current - self.verified_at).days > self.max_age_days


def load_pricing_config(path: Path) -> OpenAIPricingConfig:
    return OpenAIPricingConfig.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def build_preflight(
    segment_texts: Iterable[str],
    *,
    cached_segment_indexes: Iterable[int] = (),
    instructions: str,
    pricing: OpenAIPricingConfig,
    paid_execution_enabled: bool,
    today: date | None = None,
) -> dict[str, Any]:
    texts = list(segment_texts)
    cached_indexes = set(cached_segment_indexes)
    if any(index < 0 or index >= len(texts) for index in cached_indexes):
        raise ValueError("Invalid OpenAI cached segment index.")
    remaining = [text for index, text in enumerate(texts) if index not in cached_indexes]
    input_characters = sum(len(text) for text in texts)
    remaining_characters = sum(len(text) for text in remaining)
    # Without a tokenizer dependency, UTF-8 bytes are used as a deliberately
    # conservative token upper bound, not as an exact token count.
    token_upper_bound = sum(len((text + instructions).encode("utf-8")) for text in remaining)
    input_cost_upper_bound = (
        Decimal(token_upper_bound)
        * pricing.text_input_per_million_tokens
        / Decimal(1_000_000)
    )
    stale = pricing.is_stale(today=today)
    return {
        "engine": ENGINE_ID,
        "model": pricing.model,
        "pricing_status": "stale" if stale else "current",
        "pricing": {
            "currency": pricing.currency,
            "text_input_per_million_tokens": decimal_text(pricing.text_input_per_million_tokens),
            "audio_output_per_million_tokens": decimal_text(pricing.audio_output_per_million_tokens),
            "verified_at": pricing.verified_at.isoformat(),
            "source": pricing.source_url,
            "max_age_days": pricing.max_age_days,
            "stale": stale,
        },
        "known": {
            "input_characters": input_characters,
            "remaining_input_characters": remaining_characters,
            "segments": len(texts),
            "cache_hits": len(cached_indexes),
            "remaining_segments": len(remaining),
        },
        "estimated": {
            "label": "estimate",
            "input_token_upper_bound": token_upper_bound,
            "input_cost_upper_bound_usd": decimal_text(input_cost_upper_bound),
        },
        "unknown": {
            "label": "unavailable",
            "exact_output_audio_tokens": None,
            "exact_output_charge_usd": None,
        },
        "actual": {
            "label": "actual",
            "status": "unavailable",
            "total_charge_usd": None,
            "source": pricing.actual_cost_source,
        },
        "paid_execution_enabled": paid_execution_enabled,
        "allowed_to_start": bool(paid_execution_enabled and not stale),
        "blocked_reason": None if paid_execution_enabled and not stale else (
            "stale_pricing" if stale else "cloud_billing_gate_pending"
        ),
        "remote_request_sent": False,
    }
