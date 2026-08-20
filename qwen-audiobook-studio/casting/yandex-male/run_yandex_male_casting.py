#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backends.yandex_speechkit import (  # noqa: E402
    ENGINE_ID,
    YandexBackendConfig,
    YandexPricingConfig,
    YandexSpeechKitBackend,
    YandexSpeechKitError,
    load_pricing_config,
    price_estimate,
    read_api_key_from_keychain,
    utc_now_iso,
)
from backends.yandex_types import atomic_write_json, wav_info  # noqa: E402


EXPECTED_VOICES = [
    {"voice": "filipp", "role": None},
    {"voice": "ermil", "role": "neutral"},
    {"voice": "zahar", "role": "neutral"},
    {"voice": "alexander", "role": "neutral"},
    {"voice": "kirill", "role": "neutral"},
    {"voice": "anton", "role": "neutral"},
    {"voice": "madi_ru", "role": None},
]
EXPECTED_PRODUCTION_PROFILE = {
    "voice": "lera",
    "role": "neutral",
    "speed": "1.04",
    "output_container": "WAV",
    "loudness_normalization": "LUFS",
}
EXPECTED_SPEED = "1.0"
TASK_HARD_LIMIT_RUB = Decimal("10.00")
EXPECTED_TEXT_SHA256 = "8ae8f545b187ddf8b8363d9703a0f2408b771d7c6f019020b90c4a09cb9faa2e"


class CastingConfigError(RuntimeError):
    pass


@dataclass
class RequestLedger:
    unit_price: Decimal
    hard_limit_rub: Decimal
    max_attempts: int
    attempts: int = 0

    @property
    def estimated_cost_rub(self) -> Decimal:
        return self.unit_price * self.attempts

    def claim(self) -> int:
        next_attempt = self.attempts + 1
        next_cost = self.unit_price * next_attempt
        if next_attempt > self.max_attempts or next_cost > self.hard_limit_rub:
            raise YandexSpeechKitError(
                f"Yandex male casting cap reached: {next_cost} > {self.hard_limit_rub} RUB.",
                category="pricing_gate",
            )
        self.attempts = next_attempt
        return next_attempt


class CountingYandexBackend(YandexSpeechKitBackend):
    def __init__(
        self,
        config: YandexBackendConfig,
        *,
        api_key: str,
        ledger: RequestLedger,
    ) -> None:
        super().__init__(config, api_key=api_key)
        self._casting_ledger = ledger

    def _request(self, text: str, request_id: str) -> tuple[bytes, dict[str, str | None]]:
        self._casting_ledger.claim()
        return super()._request(text, request_id)


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise CastingConfigError(f"Expected a JSON object: {path}")
    return data


def task_pricing(pricing: YandexPricingConfig, hard_limit: Decimal) -> YandexPricingConfig:
    return replace(pricing, demo_hard_limit_rub=hard_limit)


def profile_config(
    production: Mapping[str, Any],
    profile: Mapping[str, Any],
    speed: str,
    output_root: Path,
) -> YandexBackendConfig:
    data = dict(production)
    data["output_root"] = str(output_root)
    data["default_profile"] = {
        "voice": profile["voice"],
        "role": profile["role"] or "",
        "speed": speed,
        "output_container": "WAV",
        "loudness_normalization": "LUFS",
    }
    return YandexBackendConfig.from_mapping(data)


def build_plan(
    casting: Mapping[str, Any],
    text: str,
    production: Mapping[str, Any],
    pricing: YandexPricingConfig,
) -> dict[str, Any]:
    hard_limit = Decimal(str(casting["task_scoped_hard_limit_rub"]))
    scoped_pricing = task_pricing(pricing, hard_limit)
    probe_config = profile_config(
        production,
        casting["voices"][0],
        str(casting["speed"]),
        Path(str(casting["output_root"])),
    )
    segments = YandexSpeechKitBackend(probe_config, api_key="offline-placeholder-key-123456").segment(text)
    units_per_voice = sum(max(1, math.ceil(len(segment.text) / 250)) for segment in segments)
    planned_units = units_per_voice * len(casting["voices"])
    estimate = price_estimate(
        total_units=planned_units,
        billable_remaining_units=planned_units,
        pricing=scoped_pricing,
        scope="demo",
    )
    if pricing.unit_price is None:
        maximum_attempts = 0
    else:
        maximum_attempts = int((hard_limit / pricing.unit_price).to_integral_value(rounding=ROUND_FLOOR))
    maximum_cost = pricing.unit_price * maximum_attempts if pricing.unit_price is not None else None
    return {
        **estimate,
        "planned_voices": len(casting["voices"]),
        "segments_per_voice": len(segments),
        "planned_requests": planned_units,
        "planned_billing_units": planned_units,
        "maximum_network_attempts_under_cap": maximum_attempts,
        "maximum_estimated_cost_under_cap": decimal_text(maximum_cost) if maximum_cost is not None else None,
        "task_scoped_hard_limit_rub": decimal_text(hard_limit),
    }


def load_context(config_path: Path) -> tuple[
    dict[str, Any], str, Path, dict[str, Any], YandexPricingConfig, dict[str, Any]
]:
    casting = load_json(config_path)
    if casting.get("engine") != ENGINE_ID or casting.get("provider") != "yandex":
        raise CastingConfigError("Unexpected casting provider or engine.")
    if casting.get("voices") != EXPECTED_VOICES:
        raise CastingConfigError("Male voice list or role mapping differs from the approved official set.")
    if casting.get("speed") != EXPECTED_SPEED:
        raise CastingConfigError("All casting profiles must use speed 1.0.")
    if Decimal(str(casting.get("task_scoped_hard_limit_rub"))) != TASK_HARD_LIMIT_RUB:
        raise CastingConfigError("Task-scoped hard limit must be exactly 10.00 RUB.")
    if int(casting.get("max_retries_per_voice", -1)) != 1:
        raise CastingConfigError("Retry policy must be bounded to one retry per voice.")

    text_path = (config_path.parent / str(casting["source_text"])).resolve()
    text_bytes = text_path.read_bytes()
    text_hash = sha256_bytes(text_bytes)
    if text_hash != EXPECTED_TEXT_SHA256 or text_hash != casting.get("source_text_sha256"):
        raise CastingConfigError(f"Casting source SHA-256 mismatch: {text_hash}")
    text = text_bytes.decode("utf-8")

    production_path = (config_path.parent / str(casting["production_backend_config"])).resolve()
    production = load_json(production_path)
    if production.get("default_profile") != EXPECTED_PRODUCTION_PROFILE:
        raise CastingConfigError("Frozen production Lera profile changed; casting is blocked.")
    pricing_path = (config_path.parent / str(casting["production_pricing_config"])).resolve()
    pricing = load_pricing_config(pricing_path)
    plan = build_plan(casting, text, production, pricing)
    if plan["price_stale"] or not plan["allowed_to_start"]:
        raise CastingConfigError(f"Pricing gate blocked casting: {plan['blocked_reason']}")
    if plan["planned_voices"] != 7 or plan["segments_per_voice"] != 6 or plan["planned_requests"] != 42:
        raise CastingConfigError("Casting request plan differs from the approved 7 x 6 = 42 checkpoint.")
    if Decimal(plan["estimated_remaining_cost"]) > TASK_HARD_LIMIT_RUB:
        raise CastingConfigError("Estimated casting cost exceeds 10.00 RUB.")
    return casting, text, text_path, production, pricing, plan


def can_retry(error: YandexSpeechKitError, retries_used: int, maximum: int) -> bool:
    return (
        error.retryable
        and error.category != "network_ambiguous"
        and retries_used < maximum
    )


def validate_final_wav(path: Path, duration_review: Mapping[str, Any]) -> dict[str, Any]:
    duration, rate, channels, width = wav_info(path)
    size = path.stat().st_size
    if size <= 44:
        raise YandexSpeechKitError("Casting WAV is empty.", category="audio_integrity")
    data = path.read_bytes()
    needs_review = (
        duration < float(duration_review["needs_review_below_seconds"])
        or duration > float(duration_review["needs_review_above_seconds"])
    )
    return {
        "valid": True,
        "parser": "python-wave",
        "container": "RIFF/WAVE",
        "size_bytes": size,
        "duration_seconds": round(duration, 3),
        "sample_rate_hz": rate,
        "channels": channels,
        "sample_width_bytes": width,
        "sha256": sha256_bytes(data),
        "needs_review": needs_review,
    }


def initial_manifest(
    casting: Mapping[str, Any],
    text_path: Path,
    output_dir: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    samples = []
    for index, profile in enumerate(casting["voices"], start=1):
        samples.append({
            "ordinal": index,
            "voice": profile["voice"],
            "role": profile["role"],
            "speed": casting["speed"],
            "status": "PENDING",
            "attempts": 0,
            "retry_count": 0,
            "billing_units": 0,
            "estimated_cost_rub": "0",
            "request_ids": [],
            "output_filename": f"{index:02d}-{profile['voice']}.wav",
            "wav_validation": None,
            "error": None,
        })
    return {
        "schema_version": 1,
        "provider": "yandex",
        "engine": ENGINE_ID,
        "casting_type": casting["casting_type"],
        "source_text_path": str(text_path),
        "source_text_sha256": casting["source_text_sha256"],
        "speed": casting["speed"],
        "voice_profiles": list(casting["voices"]),
        "pricing_plan": dict(plan),
        "credential_source_type": "macos_keychain",
        "credential_value_stored": False,
        "output_folder": str(output_dir),
        "created_at": utc_now_iso(),
        "completed_at": None,
        "actual_requests": 0,
        "retry_count": 0,
        "actual_estimated_cost_rub": "0",
        "samples": samples,
    }


def collect_request_ids(job_manifest_path: Path) -> list[str]:
    if not job_manifest_path.exists():
        return []
    job_manifest = load_json(job_manifest_path)
    result: list[str] = []
    for segment_id in sorted(job_manifest.get("segments", {})):
        request_id = job_manifest["segments"][segment_id].get("request_id")
        if request_id:
            result.append(str(request_id))
    return result


def collect_round_request_ids(work_root: Path) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for manifest_path in sorted(work_root.glob("*/MANIFEST.json")):
        for request_id in collect_request_ids(manifest_path):
            if request_id not in seen:
                result.append(request_id)
                seen.add(request_id)
    return result


def write_summary(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    lines = [
        "Yandex Russian male voice casting — round 1",
        "",
        f"Source SHA-256: {manifest['source_text_sha256']}",
        f"Speed: {manifest['speed']}",
        f"Actual requests: {manifest['actual_requests']}",
        f"Retries: {manifest['retry_count']}",
        f"Estimated cost: {manifest['actual_estimated_cost_rub']} RUB",
        f"Task cap: {manifest['pricing_plan']['task_scoped_hard_limit_rub']} RUB",
        "",
        "voice | role | file | status | duration | sample rate | channels | sample width",
    ]
    for sample in manifest["samples"]:
        validation = sample.get("wav_validation") or {}
        lines.append(" | ".join([
            sample["voice"],
            sample["role"] or "default/no role",
            sample["output_filename"] if validation else "-",
            sample["status"],
            str(validation.get("duration_seconds", "-")),
            str(validation.get("sample_rate_hz", "-")),
            str(validation.get("channels", "-")),
            str(validation.get("sample_width_bytes", "-")),
        ]))
    lines.extend(["", "No casting winner is selected by this runner."])
    (output_dir / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_casting(
    casting: dict[str, Any],
    text: str,
    text_path: Path,
    production: dict[str, Any],
    pricing: YandexPricingConfig,
    plan: dict[str, Any],
    *,
    resume_output: Path | None = None,
) -> Path:
    output_root = Path(str(casting["output_root"])).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if resume_output is None:
        output_dir = output_root / timestamp_slug()
        output_dir.mkdir(parents=False, exist_ok=False)
        work_root = output_dir / "work"
        work_root.mkdir()
    else:
        output_dir = resume_output.expanduser().resolve()
        if output_dir.parent != output_root or not output_dir.is_dir():
            raise CastingConfigError("Resume output must be an existing direct child of casting output_root.")
        work_root = output_dir / "work"
        if not work_root.is_dir():
            raise CastingConfigError("Resume work directory is missing.")
    manifest_path = output_dir / "CASTING-MANIFEST.json"
    if resume_output is None:
        manifest = initial_manifest(casting, text_path, output_dir, plan)
        atomic_write_json(manifest_path, manifest)
    else:
        manifest = load_json(manifest_path)
        if (
            manifest.get("source_text_sha256") != casting["source_text_sha256"]
            or manifest.get("voice_profiles") != casting["voices"]
            or manifest.get("speed") != casting["speed"]
        ):
            raise CastingConfigError("Resume manifest does not match the approved casting contract.")

    if pricing.unit_price is None:
        raise CastingConfigError("Pricing unit is missing after pricing gate.")
    known_request_ids = collect_round_request_ids(work_root)
    ledger = RequestLedger(
        unit_price=pricing.unit_price,
        hard_limit_rub=TASK_HARD_LIMIT_RUB,
        max_attempts=int(plan["maximum_network_attempts_under_cap"]),
        attempts=max(int(manifest.get("actual_requests", 0)), len(known_request_ids)),
    )
    manifest["actual_requests"] = ledger.attempts
    manifest["actual_estimated_cost_rub"] = decimal_text(ledger.estimated_cost_rub)
    if resume_output is not None:
        manifest["resumed_at"] = utc_now_iso()
    atomic_write_json(manifest_path, manifest)
    scoped_pricing = task_pricing(pricing, TASK_HARD_LIMIT_RUB)
    production_backend = YandexBackendConfig.from_mapping(production)
    api_key = read_api_key_from_keychain(
        production_backend.keychain_service,
        production_backend.keychain_account,
    )

    for sample, profile in zip(manifest["samples"], casting["voices"]):
        if sample.get("status") in {"DONE", "NEEDS_REVIEW", "FAILED", "AMBIGUOUS"}:
            continue
        voice_job_dir = work_root / f"{sample['ordinal']:02d}-{sample['voice']}"
        backend_config = profile_config(production, profile, casting["speed"], output_root)
        backend = CountingYandexBackend(backend_config, api_key=api_key, ledger=ledger)
        sample["status"] = "IN_FLIGHT"
        atomic_write_json(manifest_path, manifest)

        retries_used = 0
        errors: list[dict[str, Any]] = []
        while True:
            sample["attempts"] += 1
            try:
                joined = backend.run_text_job(
                    text,
                    voice_job_dir,
                    job_id=f"yandex-male-{sample['voice']}",
                    pricing=scoped_pricing,
                    scope="demo",
                )
                output_path = output_dir / sample["output_filename"]
                shutil.copy2(joined, output_path)
                validation = validate_final_wav(output_path, casting["duration_review"])
                sample["wav_validation"] = validation
                sample["status"] = "NEEDS_REVIEW" if validation["needs_review"] else "DONE"
                sample["error"] = errors or None
                break
            except YandexSpeechKitError as error:
                errors.append(error.to_dict())
                if error.category in {"network_ambiguous", "resume_ambiguous"}:
                    sample["status"] = "AMBIGUOUS"
                    sample["error"] = errors
                    break
                if can_retry(error, retries_used, int(casting["max_retries_per_voice"])):
                    retries_used += 1
                    sample["retry_count"] = retries_used
                    manifest["retry_count"] += 1
                    time.sleep(2)
                    continue
                sample["status"] = "FAILED"
                sample["error"] = errors
                break

        sample["request_ids"] = collect_request_ids(voice_job_dir / "MANIFEST.json")
        sample["billing_units"] = len(sample["request_ids"])
        sample["estimated_cost_rub"] = decimal_text(pricing.unit_price * sample["billing_units"])
        round_request_count = len(collect_round_request_ids(work_root))
        manifest["actual_requests"] = max(ledger.attempts, round_request_count)
        manifest["actual_estimated_cost_rub"] = decimal_text(ledger.estimated_cost_rub)
        atomic_write_json(manifest_path, manifest)

    manifest["completed_at"] = utc_now_iso()
    manifest["actual_requests"] = ledger.attempts
    manifest["actual_estimated_cost_rub"] = decimal_text(ledger.estimated_cost_rub)
    atomic_write_json(manifest_path, manifest)
    write_summary(output_dir, manifest)
    return output_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded Yandex male voice casting runner.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("yandex-male-casting-config.json"),
    )
    parser.add_argument("--check", action="store_true", help="Offline config/text/pricing gate only.")
    parser.add_argument("--run", action="store_true", help="Run the paid bounded casting round.")
    parser.add_argument("--confirm-paid-casting", action="store_true")
    parser.add_argument(
        "--resume-output",
        type=Path,
        help="Resume only the named existing runtime folder without repeating terminal samples.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        context = load_context(args.config.resolve())
        casting, text, text_path, production, pricing, plan = context
        if args.run:
            if not args.confirm_paid_casting:
                raise CastingConfigError("--run requires --confirm-paid-casting.")
            print(json.dumps({
                "gate": "PASS",
                "planned_voices": plan["planned_voices"],
                "planned_requests": plan["planned_requests"],
                "estimated_cost_rub": plan["estimated_remaining_cost"],
                "hard_limit_rub": plan["task_scoped_hard_limit_rub"],
            }))
            output = run_casting(
                casting,
                text,
                text_path,
                production,
                pricing,
                plan,
                resume_output=args.resume_output,
            )
            print(json.dumps({"casting_complete": True, "output_folder": str(output)}))
            return 0
        print(json.dumps({
            "offline_check": "PASS",
            "voices": casting["voices"],
            "speed": casting["speed"],
            "source_text_path": str(text_path),
            "source_text_sha256": casting["source_text_sha256"],
            "pricing_plan": plan,
            "network_requests_made": 0,
        }, ensure_ascii=False, indent=2))
        return 0
    except (CastingConfigError, YandexSpeechKitError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
