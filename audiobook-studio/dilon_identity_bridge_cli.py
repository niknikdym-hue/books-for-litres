#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Offline CLI adapter for the accepted DilonIdentityBridgeService.

No command in this module can synthesize or execute a provider request.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from backends.yandex_pricing import load_pricing_config
from dilon_identity_bridge import DilonIdentityBridgeError, DilonIdentityBridgeService
from dilon_opening_credit_plan_store import OpeningCreditPlanStoreError
from workspace_paths import load_workspace_paths


STUDIO_DIR = Path(__file__).resolve().parent
YANDEX_PRICING_CONFIG = STUDIO_DIR / "yandex-pricing.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio Dilon identity offline bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-opening-credit", action="store_true")
    mode.add_argument("--opening-credit-plan-status", action="store_true")
    mode.add_argument("--identity-status", action="store_true")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--plan-digest", default="")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--expected-build-identity", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _service() -> DilonIdentityBridgeService:
    paths = load_workspace_paths()
    return DilonIdentityBridgeService(
        workspace_root=paths.root,
        identities_root=paths.root / "identities",
        paid_plans_root=paths.paid_run_plans,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        service = _service()
        if args.prepare_opening_credit:
            result = service.prepare_opening_credit(
                pricing=load_pricing_config(YANDEX_PRICING_CONFIG)
            )
        elif args.opening_credit_plan_status:
            result = service.opening_credit_plan_status(
                plan_id=_require(args.plan_id, "--plan-id"),
                plan_digest=_require(args.plan_digest, "--plan-digest"),
            )
        else:
            result = service.identity_status(
                book_slug=_require(args.book, "--book"),
                job_id=_require(args.job, "--job"),
                expected_build_identity=(args.expected_build_identity or None),
            )
    except (RuntimeError, DilonIdentityBridgeError, OpeningCreditPlanStoreError) as error:
        code = getattr(error, "code", "invalid_request")
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "state": "BLOCKED",
                    "decision": "INVALID_REQUEST",
                    "blockers": [code],
                    "provider_requests": 0,
                    "remote_request_sent": False,
                    "paid_execution": False,
                    "billing_changed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
