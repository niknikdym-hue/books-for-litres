#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from backends.yandex_speechkit import (
    YandexPricingConfig,
    YandexSpeechKitBackend,
    load_backend_config,
    load_pricing_config,
    shared_cache_execution_lock,
)
from cloud_billing import BillingLedger
from workspace_paths import load_workspace_paths

STUDIO_DIR = Path(__file__).resolve().parent
CONFIG_PATH = STUDIO_DIR / "yandex-config.json"
PRICING_CONFIG_PATH = STUDIO_DIR / "yandex-pricing.json"

DEMO_TEXT = (
    "Иногда перемены начинаются тихо. В какой-то момент человек просто замечает: "
    "мне больше не нужно доказывать собственную ценность.\n\n"
    "Можно выбирать, пробовать, ошибаться, начинать заново — и с интересом смотреть "
    "на то, что будет дальше."
)


def run_demo(backend: YandexSpeechKitBackend, *, pricing: YandexPricingConfig, job_dir: Path) -> Path:
    """Run the paid legacy demo under the global Yandex cache writer lock."""
    with shared_cache_execution_lock(backend.config.output_root):
        return backend.run_text_job(
            DEMO_TEXT,
            job_dir,
            job_id="speechkit-demo",
            pricing=pricing,
            scope="demo",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audiobook Studio — Yandex SpeechKit backend")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Локальная проверка без платного API-запроса")
    mode.add_argument("--demo", action="store_true", help="Короткий реальный тест SpeechKit")
    parser.add_argument("--job-dir", default="", help="Каталог существующего job для Resume")
    args = parser.parse_args()

    cfg = load_backend_config(CONFIG_PATH)
    pricing = load_pricing_config(PRICING_CONFIG_PATH)
    backend = YandexSpeechKitBackend(
        cfg,
        billing_ledger=BillingLedger(load_workspace_paths().billing_ledger),
    )

    if args.check:
        print(json.dumps(backend.healthcheck(remote=False), ensure_ascii=False, indent=2))
        print(json.dumps(backend.estimate(DEMO_TEXT, pricing=pricing, scope="demo"), ensure_ascii=False, indent=2))
        return 0

    if args.demo:
        if args.job_dir:
            job_dir = Path(args.job_dir).expanduser()
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            job_dir = cfg.output_root / "demo" / stamp
        joined = run_demo(backend, pricing=pricing, job_dir=job_dir)
        print(joined)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
