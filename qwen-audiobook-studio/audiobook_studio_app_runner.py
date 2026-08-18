#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Offline-first bridge for the universal Audiobook Studio launcher."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

STUDIO_DIR = Path(__file__).resolve().parent
QWEN_RUNNER = STUDIO_DIR / "studio_app_runner.py"
YANDEX_RUNNER = STUDIO_DIR / "yandex_backend_runner.py"
YANDEX_CONFIG = STUDIO_DIR / "yandex-config.json"

ENGINES = (
    ("qwen", "Qwen — локально"),
    ("yandex", "Yandex SpeechKit — Lera neutral 1.04"),
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
    mode.add_argument("--run-qwen", action="store_true")
    mode.add_argument("--run-yandex-demo", action="store_true")
    parser.add_argument("--engine", choices=("qwen", "yandex"), default="")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--speaker", default="")
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


def _load_yandex_offline() -> tuple[Any, str]:
    # Imports stay inside the Yandex branch so a failure in one engine cannot
    # prevent the other engine's catalog commands from starting.
    from backends.yandex_speechkit import YandexSpeechKitBackend, load_backend_config
    from yandex_backend_runner import DEMO_TEXT

    config = load_backend_config(YANDEX_CONFIG)
    return YandexSpeechKitBackend(config), DEMO_TEXT


def yandex_offline_check() -> dict[str, Any]:
    backend, _ = _load_yandex_offline()
    result = backend.validate_config(resolve_credentials=False)
    result["backend_config_ok"] = bool(result.pop("ok", False))
    result["keychain_check"] = "not_attempted_offline"
    result["remote_request_sent"] = False
    return result


def yandex_demo_estimate() -> dict[str, Any]:
    backend, demo_text = _load_yandex_offline()
    config_status = backend.validate_config(resolve_credentials=False)
    estimate = backend.estimate(demo_text)
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
        if args.engine != "qwen":
            raise RuntimeError("--list-voices currently requires --engine qwen")
        return _delegate(QWEN_RUNNER, "--list-voices")

    if args.default_speaker:
        return _delegate(QWEN_RUNNER, "--default-speaker", "--book", _require(args.book, "--book"))

    if args.yandex_check:
        print(json.dumps(yandex_offline_check(), ensure_ascii=False, indent=2))
        return 0

    if args.yandex_estimate_demo:
        _print_yandex_estimate(yandex_demo_estimate(), args.output_format)
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
