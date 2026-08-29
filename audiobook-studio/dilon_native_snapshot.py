"""Offline aggregate snapshot for the native Dilon Voices workflow.

This module is deliberately read-only. It combines the accepted current Dilon
identity status with an explicitly validated catalog of immutable opening-credit
review candidates and, only for an exact-current identity, a separately validated
preview binding. It never prepares or executes a provider request, never approves
a candidate, and never mutates billing or release authority.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any, Mapping

from dilon_identity_bridge import DilonIdentityBridgeService
from dilon_identity_status import current_dilon_identity_status
from dilon_opening_credit_review import (
    CURRENT_SCHEMA_VERSION,
    OpeningCreditReviewError,
    _load_candidate,
    _regular,
    _safe_id,
    _safe_slug,
    _sha_id,
    _workspace,
    review_root,
)


NATIVE_SNAPSHOT_SCHEMA_VERSION = 1


class DilonNativeSnapshotError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def _candidate_directory(
    *, workspace_root: Path, book_slug: str, job_id: str
) -> Path | None:
    root = _workspace(workspace_root)
    candidate_root = review_root(
        workspace_root=root,
        book_slug=book_slug,
        job_id=job_id,
    ) / "candidates"
    if not (candidate_root.exists() or candidate_root.is_symlink()):
        return None
    try:
        relative = candidate_root.absolute().relative_to(root)
    except ValueError as error:
        raise DilonNativeSnapshotError(
            "review_candidate_catalog_unsafe",
            "Review candidate catalog находится вне workspace.",
        ) from error
    current = root
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_unsafe",
                "Review candidate catalog недоступен.",
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_unsafe",
                "Review candidate catalog содержит небезопасный path component.",
            )
    return candidate_root


def _load_approved_candidate(
    *, workspace_root: Path, book_slug: str, job_id: str
) -> tuple[str, str] | None:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    current = review_root(workspace_root=root, book_slug=slug, job_id=job) / "CURRENT.json"
    if not (current.exists() or current.is_symlink()):
        return None
    path = _regular(current, root=root, label="Opening-credit CURRENT.json")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise DilonNativeSnapshotError(
            "opening_credit_current_invalid", "Opening-credit CURRENT.json повреждён."
        ) from error
    if not isinstance(envelope, Mapping):
        raise DilonNativeSnapshotError(
            "opening_credit_current_invalid", "Opening-credit CURRENT envelope некорректен."
        )
    try:
        identifier = _sha_id(envelope.get("candidate_id"), "candidate_id")
        digest = _sha_id(envelope.get("candidate_digest"), "candidate_digest")
    except OpeningCreditReviewError as error:
        raise DilonNativeSnapshotError(
            "opening_credit_current_invalid", "Opening-credit CURRENT identity некорректна."
        ) from error
    expected_manifest = (
        review_root(workspace_root=root, book_slug=slug, job_id=job)
        / "candidates"
        / identifier
        / "REVIEW.json"
    )
    listened = envelope.get("listened_identity")
    opening_credit = envelope.get("opening_credit")
    if (
        envelope.get("schema_version") != CURRENT_SCHEMA_VERSION
        or envelope.get("book_slug") != slug
        or envelope.get("job_id") != job
        or envelope.get("candidate_manifest_path") != str(expected_manifest)
        or not isinstance(listened, Mapping)
        or not isinstance(opening_credit, Mapping)
        or opening_credit.get("manual_state") != "APPROVED"
        or opening_credit.get("reviewed_identity") != listened
    ):
        raise DilonNativeSnapshotError(
            "opening_credit_current_invalid", "Opening-credit CURRENT authority не подтверждена."
        )
    try:
        candidate, manifest_path = _load_candidate(
            workspace_root=root,
            book_slug=slug,
            job_id=job,
            candidate_id=identifier,
            candidate_digest=digest,
        )
    except OpeningCreditReviewError as error:
        raise DilonNativeSnapshotError(
            "opening_credit_current_invalid", "Approved review candidate больше не подтверждён."
        ) from error
    if (
        manifest_path != expected_manifest
        or listened.get("audio_sha256") != candidate.get("audio_sha256")
        or listened.get("path_identity") != candidate.get("path_identity")
        or listened.get("synthesis_fingerprint") != candidate.get("synthesis_fingerprint")
    ):
        raise DilonNativeSnapshotError(
            "opening_credit_current_invalid", "Approved listened identity не совпадает с candidate."
        )
    return identifier, digest


def list_review_candidates(
    *, workspace_root: Path, book_slug: str, job_id: str
) -> list[dict[str, Any]]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    catalog = _candidate_directory(
        workspace_root=root,
        book_slug=slug,
        job_id=job,
    )
    if catalog is None:
        return []
    approved = _load_approved_candidate(
        workspace_root=root,
        book_slug=slug,
        job_id=job,
    )
    results: list[dict[str, Any]] = []
    for entry in sorted(catalog.iterdir(), key=lambda item: item.name):
        if entry.name.startswith("."):
            continue
        try:
            identifier = _sha_id(entry.name, "candidate_id")
        except OpeningCreditReviewError:
            continue
        try:
            metadata = entry.lstat()
        except OSError as error:
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_invalid", "Review candidate directory недоступна."
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_invalid", "Review candidate path небезопасен."
            )
        manifest_path = _regular(
            entry / "REVIEW.json",
            root=root,
            label="Opening-credit REVIEW.json",
        )
        try:
            envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
            digest = _sha_id(
                envelope.get("candidate_digest") if isinstance(envelope, Mapping) else None,
                "candidate_digest",
            )
        except (OSError, ValueError, TypeError, OpeningCreditReviewError) as error:
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_invalid", "Review candidate manifest некорректен."
            ) from error
        if not isinstance(envelope, Mapping) or envelope.get("candidate_id") != identifier:
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_invalid", "Review candidate id не совпадает с directory."
            )
        try:
            candidate, validated_manifest = _load_candidate(
                workspace_root=root,
                book_slug=slug,
                job_id=job,
                candidate_id=identifier,
                candidate_digest=digest,
            )
        except OpeningCreditReviewError as error:
            raise DilonNativeSnapshotError(
                "review_candidate_catalog_invalid", "Review candidate authority не подтверждена."
            ) from error
        results.append({
            "candidate_id": identifier,
            "candidate_digest": digest,
            "candidate_manifest_path": str(validated_manifest),
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
            "is_current_approved": approved == (identifier, digest),
        })
    return results


def _identity_preview(
    *,
    workspace_root: Path,
    identities_root: Path,
    status: Mapping[str, Any],
    book_slug: str,
    job_id: str,
) -> dict[str, Any] | None:
    identity = status.get("identity")
    if not isinstance(identity, Mapping) or identity.get("current") is not True:
        return None
    expected_build_identity = identity.get("build_identity")
    status_audio_path = identity.get("output_path")
    status_audio_sha256 = identity.get("output_sha256")
    if (
        not isinstance(expected_build_identity, str)
        or not expected_build_identity
        or not isinstance(status_audio_path, str)
        or not status_audio_path
        or not isinstance(status_audio_sha256, str)
        or not status_audio_sha256
    ):
        raise DilonNativeSnapshotError(
            "identity_preview_not_current", "Current Dilon identity не имеет exact output authority."
        )
    service = DilonIdentityBridgeService(
        workspace_root=workspace_root,
        identities_root=identities_root,
        paid_plans_root=workspace_root / "runtime" / "paid-run-plans",
    )
    bridge = service.identity_status(
        book_slug=book_slug,
        job_id=job_id,
        expected_build_identity=expected_build_identity,
    )
    if (
        bridge.get("provider_requests") != 0
        or bridge.get("remote_request_sent") is not False
        or bridge.get("paid_execution") is not False
        or bridge.get("billing_changed") is not False
    ):
        raise DilonNativeSnapshotError(
            "offline_contract_violation", "Identity preview bridge нарушил offline contract."
        )
    preview = bridge.get("preview")
    bridge_identity = bridge.get("identity")
    if (
        bridge.get("state") != "READY"
        or bridge.get("decision") != "READY_TO_PREVIEW"
        or not isinstance(preview, Mapping)
        or not isinstance(bridge_identity, Mapping)
        or bridge_identity.get("build_identity") != expected_build_identity
        or bridge_identity.get("book_slug") != book_slug
        or bridge_identity.get("job_id") != job_id
        or preview.get("read_only") is not True
        or preview.get("audio_path") != status_audio_path
        or preview.get("audio_sha256") != status_audio_sha256
        or not isinstance(preview.get("path_identity"), str)
        or not preview.get("path_identity")
    ):
        raise DilonNativeSnapshotError(
            "identity_preview_not_current",
            "Current Dilon identity не прошёл exact preview revalidation.",
        )
    return {
        "build_identity": expected_build_identity,
        "audio_path": preview["audio_path"],
        "audio_sha256": preview["audio_sha256"],
        "path_identity": preview["path_identity"],
        "read_only": True,
    }


def current_native_snapshot(
    *,
    workspace_root: Path,
    masters_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    try:
        status = current_dilon_identity_status(
            workspace_root=root,
            masters_root=masters_root,
            identities_root=identities_root,
            book_slug=slug,
            job_id=job,
        )
        candidates = list_review_candidates(
            workspace_root=root,
            book_slug=slug,
            job_id=job,
        )
    except OpeningCreditReviewError as error:
        raise DilonNativeSnapshotError(error.code, error.message) from error
    if (
        status.get("provider_requests") != 0
        or status.get("remote_request_sent") is not False
        or status.get("paid_execution") is not False
        or status.get("billing_changed") is not False
    ):
        raise DilonNativeSnapshotError(
            "offline_contract_violation", "Dilon current status нарушил offline contract."
        )
    preview = _identity_preview(
        workspace_root=root,
        identities_root=identities_root,
        status=status,
        book_slug=slug,
        job_id=job,
    )
    return {
        "schema_version": NATIVE_SNAPSHOT_SCHEMA_VERSION,
        "state": "READY",
        "decision": "DISPLAY_CURRENT_DILON_STATE",
        "book_slug": slug,
        "job_id": job,
        "dilon_status": status,
        "review_candidates": candidates,
        "identity_preview": preview,
        "capabilities": {
            "prepare_opening_credit_offline": True,
            "review_candidate_offline": True,
            "identity_preview_offline": True,
            "provider_execution_available": False,
            "paid_execution_available": False,
            "automatic_review_approval": False,
        },
        "whole_book_release_ready": False,
        **_offline_fields(),
    }
