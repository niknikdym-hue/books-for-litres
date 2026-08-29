#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable read-only runner for Dilon opening-credit human review."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from dilon_opening_credit_review import OpeningCreditReviewError
from dilon_opening_credit_review_status import opening_credit_review_status
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio Dilon opening-credit read-only review status"
    )
    parser.add_argument("--status", action="store_true", required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-digest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = load_workspace_paths()
        result = opening_credit_review_status(
            workspace_root=paths.root,
            book_slug=args.book,
            job_id=args.job,
            candidate_id=args.candidate_id,
            candidate_digest=args.candidate_digest,
        )
    except OpeningCreditReviewError as error:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "state": "BLOCKED",
                    "decision": "REVIEW_CANDIDATE_NOT_CURRENT",
                    "blockers": [error.code],
                    "candidate": None,
                    "preview": None,
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
