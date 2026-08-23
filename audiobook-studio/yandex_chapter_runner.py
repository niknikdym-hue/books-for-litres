#!/usr/bin/env python3
"""Offline CLI for Yandex chapter plan preparation and revalidation.

This runner intentionally exposes no synthesis/execute mode. Native execution is wired
only after an explicit user-confirmation gate exists in the universal Studio bridge.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from yandex_chapter_plan import YandexChapterPlanService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio — Yandex chapter plan")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--revalidate", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--profile-id", default="")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--plan-digest", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _service() -> YandexChapterPlanService:
    # Lazy import prevents catalog/test startup from loading unrelated provider
    # layers. _load_yandex_offline performs config/pricing validation only and
    # sends no provider request.
    from audiobook_studio_app_runner import BOOK_LIBRARY, WORKSPACE_PATHS, _load_yandex_offline

    backend, pricing, _ = _load_yandex_offline()
    return YandexChapterPlanService(
        library=BOOK_LIBRARY,
        backend=backend,
        pricing=pricing,
        plans_dir=WORKSPACE_PATHS.yandex_chapter_plans,
    )


def main(argv: Sequence[str] | None = None, *, service: Any | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected = service or _service()
    if args.prepare:
        result = selected.prepare(
            book_id=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            profile_id=_require(args.profile_id, "--profile-id"),
        )
    else:
        result = selected.revalidate(
            plan_id=_require(args.plan_id, "--plan-id"),
            plan_digest=_require(args.plan_digest, "--plan-digest"),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({
            "error": type(error).__name__,
            "message": str(error),
            "remote_request_sent": False,
        }, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
