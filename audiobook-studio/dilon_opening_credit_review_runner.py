#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable offline bridge for Dilon opening-credit human review.

This adapter deliberately exposes only exact candidate status and explicit human
approval.  It cannot synthesize audio, resolve provider credentials, make a
network request, execute a paid plan, or mutate billing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from dilon_opening_credit_review import (
    OpeningCreditReviewError,
    _load_candidate,
    approve_review_candidate,
)
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio Dilon opening-credit offline review bridge"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate-status", action="store_true")
    mode.add_argument("--approve-candidate", action="store_true")
    parser.add_argument("--book", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--decision", default="")
    parser.add_argument("--listened-audio-sha256", default="")
    parser.add_argument("--listened-path-identity", default="")
    parser.add_argument("--listened-synthesis-fingerprint", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def candidate_status(
    *,
    workspace_root: Path,
    book_slug: str,
    job_id: str,
    candidate_id: str,
    candidate_digest: str,
) -> dict[str, Any]:
    candidate, manifest_path = _load_candidate(
        workspace_root=workspace_root,
        book_slug=book_slug,
        job_id=job_id,
        candidate_id=candidate_id,
        candidate_digest=candidate_digest,
    )
    return {
        "schema_version": 1,
        "state": "PENDING_HUMAN_REVIEW",
        "decision": "HUMAN_LISTENING_REQUIRED",
        "book_slug": candidate["book_slug"],
        "job_id": candidate["job_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate_digest,
        "candidate_manifest_path": str(manifest_path),
        "audio_path": candidate["audio_path"],
        "audio_sha256": candidate["audio_sha256"],
        "path_identity": candidate["path_identity"],
        "synthesis_fingerprint": candidate["synthesis_fingerprint"],
        "automatic_status": candidate["automatic_status"],
        "manual_state": candidate["manual_state"],
        "profile": candidate["profile"],
        "plan_id": candidate["plan_id"],
        "plan_digest": candidate["plan_digest"],
        "historical_provenance": {
            "provider_requests": candidate["provider_requests"],
            "remote_request_sent": candidate["remote_request_sent"],
            "paid_execution": candidate["paid_execution"],
            "billing_changed": candidate["billing_changed"],
        },
        **_offline_fields(),
    }


def approve_candidate(
    *,
    workspace_root: Path,
    book_slug: str,
    job_id: str,
    candidate_id: str,
    candidate_digest: str,
    decision: str,
    listened_audio_sha256: str,
    listened_path_identity: str,
    listened_synthesis_fingerprint: str,
) -> dict[str, Any]:
    result = approve_review_candidate(
        workspace_root=workspace_root,
        book_slug=book_slug,
        job_id=job_id,
        candidate_id=candidate_id,
        candidate_digest=candidate_digest,
        decision=decision,
        listened_audio_sha256=listened_audio_sha256,
        listened_path_identity=listened_path_identity,
        listened_synthesis_fingerprint=listened_synthesis_fingerprint,
    )
    if (
        result.get("provider_requests") != 0
        or result.get("remote_request_sent") is not False
        or result.get("paid_execution") is not False
        or result.get("billing_changed") is not False
    ):
        raise OpeningCreditReviewError(
            "offline_contract_violation",
            "Opening-credit review action violated offline contract.",
        )
    return result


def _blocked(code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "BLOCKED",
        "decision": "INVALID_REQUEST",
        "blockers": [code],
        **_offline_fields(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        workspace_root = load_workspace_paths().root
        if args.candidate_status:
            result = candidate_status(
                workspace_root=workspace_root,
                book_slug=args.book,
                job_id=args.job,
                candidate_id=args.candidate_id,
                candidate_digest=args.candidate_digest,
            )
        else:
            result = approve_candidate(
                workspace_root=workspace_root,
                book_slug=args.book,
                job_id=args.job,
                candidate_id=args.candidate_id,
                candidate_digest=args.candidate_digest,
                decision=_require(args.decision, "--decision"),
                listened_audio_sha256=_require(
                    args.listened_audio_sha256, "--listened-audio-sha256"
                ),
                listened_path_identity=_require(
                    args.listened_path_identity, "--listened-path-identity"
                ),
                listened_synthesis_fingerprint=_require(
                    args.listened_synthesis_fingerprint,
                    "--listened-synthesis-fingerprint",
                ),
            )
    except (RuntimeError, OpeningCreditReviewError) as error:
        code = getattr(error, "code", "invalid_request")
        print(json.dumps(_blocked(code), ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
