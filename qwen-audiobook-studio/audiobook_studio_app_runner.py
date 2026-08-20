#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Offline-first bridge for the universal Audiobook Studio launcher."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from voice_library import load_voice_library, normalize_qwen_profiles

STUDIO_DIR = Path(__file__).resolve().parent
QWEN_RUNNER = STUDIO_DIR / "studio_app_runner.py"
YANDEX_RUNNER = STUDIO_DIR / "yandex_backend_runner.py"
YANDEX_CONFIG = STUDIO_DIR / "yandex-config.json"
YANDEX_PRICING_CONFIG = STUDIO_DIR / "yandex-pricing.json"
USER_PRICING_CONFIG = Path.home() / "Library/Application Support/Audiobook Studio/yandex-pricing.local.json"

ENGINES = (
    ("qwen", "Qwen — локально"),
    ("yandex", "Yandex SpeechKit — Lera neutral 1.04"),
    ("openai", "OpenAI TTS — Onyx / Cedar"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio universal app bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-engines", action="store_true")
    mode.add_argument("--list-books", action="store_true")
    mode.add_argument("--list-jobs", action="store_true")
    mode.add_argument("--list-voices", action="store_true")
    mode.add_argument("--default-speaker", action="store_true")
    mode.add_argument("--yandex-check", action="store_true")
    mode.add_argument("--yandex-estimate-demo", action="store_true")
    mode.add_argument("--ui-snapshot", action="store_true")
    mode.add_argument("--yandex-local-health", action="store_true")
    mode.add_argument("--set-yandex-hard-limit", action="store_true")
    mode.add_argument("--run-qwen", action="store_true")
    mode.add_argument("--run-yandex-demo", action="store_true")
    parser.add_argument("--engine", choices=("qwen", "yandex", "openai"), default="")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--hard-limit-rub", default="")
    parser.add_argument("--format", dest="output_format", choices=("json", "tsv"), default="json")
    return parser


def _delegate(script: Path, *arguments: str) -> int:
    """Run an existing engine runner without copying its implementation."""
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
    )
    return completed.returncode


def _require(value: str, option: str) -> str:
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _load_yandex_offline() -> tuple[Any, Any, str]:
    # Imports stay inside the Yandex branch so a failure in one engine cannot
    # prevent the other engine's catalog commands from starting.
    from backends.yandex_speechkit import (
        YandexSpeechKitBackend,
        load_backend_config,
        YandexPricingConfig,
        load_pricing_config,
    )
    from yandex_backend_runner import DEMO_TEXT

    config = load_backend_config(YANDEX_CONFIG)
    base = json.loads(YANDEX_PRICING_CONFIG.read_text(encoding="utf-8"))
    if USER_PRICING_CONFIG.exists():
        try:
            override = json.loads(USER_PRICING_CONFIG.read_text(encoding="utf-8"))
            if isinstance(override, dict):
                base["hard_limit_rub"] = override.get("hard_limit_rub")
        except (OSError, ValueError):
            pass
    # Keep the load helper as the canonical validator for the repository file;
    # constructing the merged mapping avoids copying pricing rules into UI code.
    _ = load_pricing_config(YANDEX_PRICING_CONFIG)
    return YandexSpeechKitBackend(config), YandexPricingConfig.from_mapping(base), DEMO_TEXT


def _load_qwen_runtime_catalog() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    spec = importlib.util.spec_from_file_location("audiobook_studio_qwen_catalog", STUDIO_DIR / "studio.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить каталог книг Qwen.")
    studio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(studio)
    books = []
    for path in studio.list_book_profiles():
        book = studio.load_book(path)
        books.append({
            "id": path.name,
            "title": str(book.get("title", path.stem)),
            "author": str(book.get("author", "")),
        })
    return books, list(studio.load_voices())


def voice_library_listing(engine: str) -> dict[str, Any]:
    if engine == "qwen":
        _, raw_qwen_voices = _load_qwen_runtime_catalog()
        profiles = normalize_qwen_profiles(raw_qwen_voices)
    else:
        profiles = load_voice_library(provider=engine)
    return {
        "engine": engine,
        "voices": profiles,
        "remote_request_sent": False,
    }


def _print_voice_listing(result: dict[str, Any], output_format: str) -> None:
    if output_format == "tsv":
        for profile in result["voices"]:
            print(f"{profile['profile_id']}\t{profile['label']}")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def ui_snapshot() -> dict[str, Any]:
    books, raw_qwen_voices = _load_qwen_runtime_catalog()
    qwen_voices = [{"id": str(voice["id"]), "label": str(voice["id"])} for voice in raw_qwen_voices]
    profiles = load_voice_library(qwen_loader=lambda: raw_qwen_voices)
    estimate = yandex_demo_estimate()
    _, pricing, _ = _load_yandex_offline()
    return {
        "books": books,
        "qwen_voices": qwen_voices,
        "voice_library": {
            engine: [profile for profile in profiles if profile["provider"] == engine]
            for engine in ("qwen", "yandex", "openai")
        },
        "yandex_profile": {
            "voice": estimate["voice_display"],
            "role": estimate["role"],
            "speed": estimate["speed"],
        },
        "yandex_estimate": estimate,
        "yandex_settings": {"hard_limit_rub": str(pricing.hard_limit_rub) if pricing.hard_limit_rub is not None else None},
        "remote_request_sent": False,
    }


def yandex_local_health() -> dict[str, Any]:
    backend, _, _ = _load_yandex_offline()
    result = backend.healthcheck(remote=False)
    result["remote_request_sent"] = False
    return result


def set_yandex_hard_limit(value: str) -> dict[str, Any]:
    from decimal import Decimal, InvalidOperation

    normalized: str | None
    if not value.strip():
        normalized = None
    else:
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise RuntimeError("Лимит должен быть числом в рублях.") from error
        if amount < 0:
            raise RuntimeError("Лимит не может быть отрицательным.")
        normalized = format(amount, "f")
    USER_PRICING_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_PRICING_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps({"hard_limit_rub": normalized}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, USER_PRICING_CONFIG)
    return {"hard_limit_rub": normalized, "remote_request_sent": False}


def yandex_offline_check() -> dict[str, Any]:
    backend, _, _ = _load_yandex_offline()
    result = backend.validate_config(resolve_credentials=False)
    result["backend_config_ok"] = bool(result.pop("ok", False))
    result["keychain_check"] = "not_attempted_offline"
    result["remote_request_sent"] = False
    return result


def yandex_demo_estimate() -> dict[str, Any]:
    backend, pricing, demo_text = _load_yandex_offline()
    config_status = backend.validate_config(resolve_credentials=False)
    estimate = backend.estimate(demo_text, pricing=pricing, scope="demo")
    return {
        "backend_config_ok": bool(config_status["ok"]),
        "engine": estimate["engine"],
        "engine_display": "Yandex SpeechKit v3",
        "voice": backend.profile.voice,
        "voice_display": backend.profile.voice.capitalize(),
        "role": backend.profile.role,
        "speed": backend.profile.speed,
        "characters": estimate["characters"],
        "segments": estimate["segments"],
        "estimated_billing_units": estimate["estimated_billing_units"],
        "cached_segments": estimate["cached_segments"],
        "total_billing_units": estimate["total_billing_units"],
        "billable_remaining_units": estimate["billable_remaining_units"],
        "currency": estimate["currency"],
        "unit_price": estimate["unit_price"],
        "estimated_total_cost": estimate["estimated_total_cost"],
        "estimated_remaining_cost": estimate["estimated_remaining_cost"],
        "price_verified_at": estimate["price_verified_at"],
        "price_stale": estimate["price_stale"],
        "price_source": estimate["price_source"],
        "hard_limit_rub": estimate["hard_limit_rub"],
        "allowed_to_start": estimate["allowed_to_start"],
        "blocked_reason": estimate["blocked_reason"],
        "keychain_check": "not_attempted_offline",
        "remote_request_sent": False,
    }


def _print_yandex_estimate(result: dict[str, Any], output_format: str) -> None:
    if output_format == "tsv":
        print("\t".join(str(result[key]) for key in (
            "engine_display",
            "voice_display",
            "role",
            "speed",
            "characters",
            "segments",
            "estimated_billing_units",
        )))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_engines:
        for engine_id, label in ENGINES:
            print(f"{engine_id}\t{label}")
        return 0

    if args.list_books:
        return _delegate(QWEN_RUNNER, "--list-books")

    if args.list_jobs:
        return _delegate(QWEN_RUNNER, "--list-jobs", "--book", _require(args.book, "--book"))

    if args.list_voices:
        engine = _require(args.engine, "--engine")
        _print_voice_listing(voice_library_listing(engine), args.output_format)
        return 0

    if args.default_speaker:
        return _delegate(QWEN_RUNNER, "--default-speaker", "--book", _require(args.book, "--book"))

    if args.yandex_check:
        print(json.dumps(yandex_offline_check(), ensure_ascii=False, indent=2))
        return 0

    if args.yandex_estimate_demo:
        _print_yandex_estimate(yandex_demo_estimate(), args.output_format)
        return 0

    if args.ui_snapshot:
        print(json.dumps(ui_snapshot(), ensure_ascii=False, indent=2))
        return 0

    if args.yandex_local_health:
        print(json.dumps(yandex_local_health(), ensure_ascii=False, indent=2))
        return 0

    if args.set_yandex_hard_limit:
        print(json.dumps(set_yandex_hard_limit(args.hard_limit_rub), ensure_ascii=False, indent=2))
        return 0

    if args.run_qwen:
        return _delegate(
            QWEN_RUNNER,
            "--run",
            "--book", _require(args.book, "--book"),
            "--job", _require(args.job, "--job"),
            "--speaker", _require(args.speaker, "--speaker"),
        )

    if args.run_yandex_demo:
        # This is the only universal-bridge branch allowed to send SpeechKit
        # requests. Offline checks and tests never select it.
        return _delegate(YANDEX_RUNNER, "--demo")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2)
