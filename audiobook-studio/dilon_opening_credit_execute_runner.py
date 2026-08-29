#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Explicit owner-gated CLI for one Dilon opening-credit Yandex execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from audiobook_studio_app_runner import WORKSPACE_PATHS, _billing_service
from backends.yandex_speechkit import YandexSpeechKitBackend, load_backend_config
from dilon_identity_bridge_cli import _opening_credit_pricing
from dilon_opening_credit_execute import (
    OpeningCreditExecutionError,
    OpeningCreditExternalExecutionService,
)

STUDIO_DIR = Path(__file__).resolve().parent
YANDEX_CONFIG = STUDIO_DIR / "yandex-config.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio Dilon opening-credit owner-gated executor"
    )
    parser.add_argument("--execute-authorized", action="store_true", required=True)
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--plan-digest", default="")
    parser.add_argument("--owner-authorized", action="store_true")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise OpeningCreditExecutionError("invalid_request", f"{option} is required")
    return value


def _blocked(error: OpeningCreditExecutionError) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "BLOCKED",
        "decision": "OWNER_OR_EXECUTION_BLOCKED",
        "blockers": [error.code],
        "message": error.message,
        "provider_requests": error.provider_requests,
        "remote_request_sent": error.remote_request_sent,
        "paid_execution": error.paid_execution,
        "billing_changed": error.billing_changed,
        "retry_allowed": error.retry_allowed,
        "whole_book_release_ready": False,
    }


def execute_from_current_runtime(
    *,
    book_slug: str,
    job_id: str,
    plan_id: str,
    plan_digest: str,
    owner_authorized: bool,
) -> dict[str, Any]:
    pricing = _opening_credit_pricing()
    billing = _billing_service()
    backend = YandexSpeechKitBackend(
        load_backend_config(YANDEX_CONFIG),
        billing_ledger=billing.ledger,
    )
    service = OpeningCreditExternalExecutionService(
        workspace_root=WORKSPACE_PATHS.root,
        plans_root=WORKSPACE_PATHS.paid_run_plans,
        pricing=pricing,
        backend=backend,
        billing_transactions=billing.ledger.transactions,
    )
    return service.execute_authorized(
        book_slug=book_slug,
        job_id=job_id,
        plan_id=plan_id,
        plan_digest=plan_digest,
        owner_authorized=owner_authorized,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute_from_current_runtime(
            book_slug=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            plan_id=_require(args.plan_id, "--plan-id"),
            plan_digest=_require(args.plan_digest, "--plan-digest"),
            owner_authorized=args.owner_authorized,
        )
    except OpeningCreditExecutionError as error:
        print(json.dumps(_blocked(error), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
