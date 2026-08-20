#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from backends.yandex_speechkit import YandexSpeechKitBackend, load_backend_config
from backends.yandex_speechkit import load_pricing_config

STUDIO_DIR = Path(__file__).resolve().parent
CONFIG_PATH = STUDIO_DIR / "yandex-config.json"
PRICING_CONFIG_PATH = STUDIO_DIR / "yandex-pricing.json"

DEMO_TEXT = (
    "Иногда перемены начинаются тихо. В какой-то момент человек просто замечает: "
    "мне больше не нужно доказывать собственную ценность.\n\n"
    "Можно выбирать, пробовать, ошибаться, начинать заново — и с интересом смотреть "
    "на то, что будет дальше."
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
    backend = YandexSpeechKitBackend(cfg)

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
        joined = backend.run_text_job(
            DEMO_TEXT,
            job_dir,
            job_id="speechkit-demo",
            pricing=pricing,
            scope="demo",
        )
        print(joined)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
