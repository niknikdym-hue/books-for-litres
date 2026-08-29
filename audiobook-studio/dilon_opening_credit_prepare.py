"""Offline-only PREPARE authority for the Dilon Voices opening credit.

This module deliberately has no execution function. It binds the canonical Dilon
opening-credit text to the frozen Yandex Lera production profile, computes a
conservative local price/request cap, and returns an immutable plan that can be
shown to the owner before any paid provider action is considered.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from backends.yandex_pricing import YandexPricingConfig, price_estimate
from backends.yandex_speechkit import YandexBackendConfig, YandexSpeechKitBackend, make_fingerprint
from backends.yandex_types import YandexVoiceProfile
from dilon_identity import OPENING_CREDIT_TEXT
from voice_library import DEFAULT_REGISTRY_PATH, VoiceLibraryError, load_static_profiles


SCHEMA_VERSION = 1
PLAN_TYPE = "DILON_OPENING_CREDIT_YANDEX_PREPARE_V1"
PROFILE_ID = "yandex_lera"
EXPECTED_PROFILE = {
    "profile_id": PROFILE_ID,
    "provider": "yandex",
    "engine": "yandex_speechkit_v3",
    "voice": "lera",
    "role": "neutral",
    "speed": "1.04",
    "frozen": True,
}


class OpeningCreditPrepareError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_frozen_profile(registry_path: Path) -> dict[str, Any]:
    try:
        profiles = load_static_profiles(registry_path)
    except VoiceLibraryError as error:
        raise OpeningCreditPrepareError(
            "voice_library_invalid", "Voice Library не прошла offline validation."
        ) from error
    matches = [profile for profile in profiles if profile.get("profile_id") == PROFILE_ID]
    if len(matches) != 1:
        raise OpeningCreditPrepareError(
            "production_profile_missing", "Frozen production profile yandex_lera отсутствует."
        )
    profile = matches[0]
    if any(profile.get(key) != value for key, value in EXPECTED_PROFILE.items()):
        raise OpeningCreditPrepareError(
            "production_profile_drift", "Frozen production profile Yandex Lera изменён."
        )
    return dict(profile)


def prepare_opening_credit_plan(
    *,
    pricing: YandexPricingConfig,
    today: date | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Return a deterministic local PREPARE plan and never contact a provider."""
    profile = _load_frozen_profile(registry_path)
    voice_profile = YandexVoiceProfile.from_mapping(profile)
    backend = YandexSpeechKitBackend(
        YandexBackendConfig.from_mapping(
            {
                "output_root": "/nonexistent/offline-opening-credit-prepare",
                "default_profile": profile,
            }
        )
    )
    segments = backend.segment(OPENING_CREDIT_TEXT)
    if len(segments) != 1:
        raise OpeningCreditPrepareError(
            "opening_credit_request_cap_exceeded",
            "Canonical opening credit больше не помещается в один provider request.",
        )
    segment = segments[0]
    billing_units = max(1, math.ceil(len(segment.text) / 250))
    pricing_state = price_estimate(
        total_units=billing_units,
        billable_remaining_units=billing_units,
        pricing=pricing,
        scope="book",
        today=today,
    )
    profile_authority = {
        "profile_id": profile["profile_id"],
        "provider": profile["provider"],
        "engine": profile["engine"],
        "voice": profile["voice"],
        "role": profile["role"],
        "speed": profile["speed"],
        "frozen": profile["frozen"],
    }
    segment_authority = {
        "segment_id": segment.segment_id,
        "text": segment.text,
        "pause_after_ms": segment.pause_after_ms,
        "paragraph_index": segment.paragraph_index,
    }
    authority = {
        "schema_version": SCHEMA_VERSION,
        "plan_type": PLAN_TYPE,
        "text": OPENING_CREDIT_TEXT,
        "text_sha256": hashlib.sha256(OPENING_CREDIT_TEXT.encode("utf-8")).hexdigest(),
        "profile": profile_authority,
        "synthesis_fingerprint": make_fingerprint(segment.text, voice_profile),
        "segment": segment_authority,
        "maximum_provider_requests": 1,
        "pricing": pricing_state,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }
    plan_id = _canonical_hash(authority)
    allowed = bool(pricing_state.get("allowed_to_start"))
    return {
        **authority,
        "plan_id": plan_id,
        "state": "READY_FOR_OWNER_AUTHORIZATION" if allowed else "BLOCKED",
        "decision": "OWNER_AUTHORIZATION_REQUIRED" if allowed else "PRICING_BLOCKED",
        "authorization_required": allowed,
        "execution_available": False,
    }
