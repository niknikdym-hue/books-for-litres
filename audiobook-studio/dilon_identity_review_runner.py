#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable offline bridge for final Dilon identity human acceptance."""
from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from dilon_identity_review import (
    DilonIdentityReviewError,
    approve_current_identity,
    identity_review_status,
)
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio final Dilon identity review bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--approve", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--listened-build-identity", default="")
    parser.add_argument("--listened-audio-sha256", default="")
    parser.add_argument("--listened-path-identity", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise DilonIdentityReviewError("invalid_request", f"{option} is required")
    return value


def _blocked(error: DilonIdentityReviewError) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "BLOCKED",
        "decision": "INVALID_OR_STALE_REVIEW",
        "blockers": [error.code],
        "message": error.message,
        "identity_accepted": False,
        "human_listening_required": True,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
        "whole_book_release_ready": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = load_workspace_paths()
    try:
        book = _require(args.book, "--book")
        job = _require(args.job, "--job")
        if args.status:
            result = identity_review_status(
                workspace_root=paths.root,
                masters_root=paths.masters_root,
                identities_root=paths.root / "identities",
                book_slug=book,
                job_id=job,
            )
        else:
            result = approve_current_identity(
                workspace_root=paths.root,
                masters_root=paths.masters_root,
                identities_root=paths.root / "identities",
                book_slug=book,
                job_id=job,
                listened_build_identity=_require(
                    args.listened_build_identity, "--listened-build-identity"
                ),
                listened_audio_sha256=_require(
                    args.listened_audio_sha256, "--listened-audio-sha256"
                ),
                listened_path_identity=_require(
                    args.listened_path_identity, "--listened-path-identity"
                ),
            )
    except DilonIdentityReviewError as error:
        print(json.dumps(_blocked(error), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
