"""Read-only status/preview surface for an immutable Dilon opening-credit review candidate.

This module intentionally exposes no approval or provider-execution action.  It
revalidates the exact immutable candidate through the accepted review authority
and returns the identity a native player must bind to before any later explicit
human approval can be considered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dilon_opening_credit_review import OpeningCreditReviewError, _load_candidate


STATUS_SCHEMA_VERSION = 1


def opening_credit_review_status(
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
    historical = {
        "provider_requests": candidate["provider_requests"],
        "remote_request_sent": candidate["remote_request_sent"],
        "paid_execution": candidate["paid_execution"],
        "billing_changed": candidate["billing_changed"],
    }
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "state": "PENDING_HUMAN_REVIEW",
        "decision": "HUMAN_LISTENING_REQUIRED",
        "blockers": [],
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "candidate_digest": candidate_digest,
            "candidate_manifest_path": str(manifest_path),
            "book_slug": candidate["book_slug"],
            "job_id": candidate["job_id"],
            "text": candidate["text"],
            "plan_id": candidate["plan_id"],
            "plan_digest": candidate["plan_digest"],
            "profile": candidate["profile"],
            "automatic_status": candidate["automatic_status"],
            "automatic_qa": candidate["automatic_qa"],
            "manual_state": candidate["manual_state"],
        },
        "preview": {
            "audio_path": candidate["audio_path"],
            "audio_sha256": candidate["audio_sha256"],
            "path_identity": candidate["path_identity"],
            "synthesis_fingerprint": candidate["synthesis_fingerprint"],
            "read_only": True,
        },
        "listened_identity_required": {
            "audio_sha256": candidate["audio_sha256"],
            "path_identity": candidate["path_identity"],
            "synthesis_fingerprint": candidate["synthesis_fingerprint"],
        },
        "historical_provenance": historical,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


__all__ = [
    "OpeningCreditReviewError",
    "opening_credit_review_status",
]
