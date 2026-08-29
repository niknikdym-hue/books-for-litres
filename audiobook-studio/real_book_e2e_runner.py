#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable read-only first-real-chapter launch preflight."""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from real_book_e2e import CANONICAL_BOOK, CANONICAL_JOB, CANONICAL_PROFILE, real_book_e2e_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio real-book E2E launch preflight")
    parser.add_argument("--preflight", action="store_true", required=True)
    parser.add_argument("--book", default=CANONICAL_BOOK)
    parser.add_argument("--job", default=CANONICAL_JOB)
    parser.add_argument("--profile-id", default=CANONICAL_PROFILE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = real_book_e2e_preflight(
        book_name=args.book,
        job_id=args.job,
        profile_id=args.profile_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
