"""Offline exact-listened human acceptance for the final Dilon identity WAV.

This authority is downstream of immutable identity build + independent technical
QA. It never synthesizes audio, never calls a provider, and never modifies the
identity output. Approval is accepted only for the exact current build/SHA/path
that was fully listened by the native player.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from backends.common import atomic_write_json, utc_now_iso
from book_library import BookLibraryError, normalize_slug
from dilon_identity_build import DilonIdentityBuildError, resolve_current_identity
from dilon_identity_qa import DilonIdentityQAError, run_identity_technical_qa
from dilon_identity_status import DilonIdentityStatusError, _load_opening_credit_authority
from mastering_export import MasteringExportError, resolve_current_master

REVIEW_SCHEMA_VERSION = 1


class DilonIdentityReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _slug(value: Any) -> str:
    try:
        return normalize_slug(str(value or ""))
    except BookLibraryError as error:
        raise DilonIdentityReviewError("invalid_book_slug", "Некорректный book_slug.") from error


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise DilonIdentityReviewError("invalid_identity", f"Некорректный {label}.")
    return value


def _workspace(path: Path) -> Path:
    requested = Path(path).expanduser().absolute()
    if requested.is_symlink():
        raise DilonIdentityReviewError("symlink_workspace_root", "Workspace root является symlink.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise DilonIdentityReviewError("missing_workspace", "Workspace root не найден.") from error


def _safe_dir(path: Path, *, root: Path) -> Path:
    boundary = _workspace(root)
    candidate = Path(path).expanduser().absolute()
    try:
        parts = candidate.relative_to(boundary).parts
    except ValueError as error:
        raise DilonIdentityReviewError("review_path_escape", "Identity review path вне workspace.") from error
    current = boundary
    for part in parts:
        current /= part
        if current.exists() or current.is_symlink():
            meta = current.lstat()
            if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
                raise DilonIdentityReviewError("review_path_unsafe", "Identity review path небезопасен.")
        else:
            current.mkdir()
    return candidate


def _regular(path: Path, *, root: Path, label: str) -> Path:
    boundary = _workspace(root)
    candidate = Path(path).expanduser().absolute()
    try:
        parts = candidate.relative_to(boundary).parts
    except ValueError as error:
        raise DilonIdentityReviewError("review_path_escape", f"{label} вне workspace.") from error
    current = boundary
    for part in parts:
        current /= part
        try:
            meta = current.lstat()
        except OSError as error:
            raise DilonIdentityReviewError("review_missing", f"{label} не найден.") from error
        if stat.S_ISLNK(meta.st_mode):
            raise DilonIdentityReviewError("review_symlink", f"{label} содержит symlink.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise DilonIdentityReviewError("review_invalid", f"{label} должен быть обычным файлом.")
    return resolved


def _load_json(path: Path, *, root: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(_regular(path, root=root, label=label).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise DilonIdentityReviewError("review_invalid", f"{label} повреждён.") from error
    if not isinstance(payload, dict):
        raise DilonIdentityReviewError("review_invalid", f"{label} имеет неверный формат.")
    return payload


def identity_review_root(*, workspace_root: Path, book_slug: str, job_id: str) -> Path:
    root = _workspace(workspace_root)
    return root / "runtime" / "dilon-identity-review" / _slug(book_slug) / _safe_id(job_id, "job_id")


def current_identity_subject(
    *,
    workspace_root: Path,
    masters_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
) -> dict[str, Any]:
    """Independently bind review to exact-current identity + current technical QA."""
    root = _workspace(workspace_root)
    slug = _slug(book_slug)
    job = _safe_id(job_id, "job_id")
    try:
        master = dict(
            resolve_current_master(
                workspace_root=root,
                masters_root=masters_root,
                book_slug=slug,
                job_id=job,
            )
        )
        opening_credit, _ = _load_opening_credit_authority(
            workspace_root=root,
            book_slug=slug,
            job_id=job,
        )
        if not isinstance(opening_credit, Mapping):
            raise DilonIdentityReviewError(
                "opening_credit_not_approved", "Reviewed opening credit отсутствует."
            )
        manifest = resolve_current_identity(
            workspace_root=root,
            identities_root=identities_root,
            book_slug=slug,
            job_id=job,
        )
        build_identity = _safe_id(manifest.get("build_identity"), "build_identity")
        qa = run_identity_technical_qa(
            workspace_root=root,
            identities_root=identities_root,
            book_slug=slug,
            job_id=job,
            opening_credit_authority=opening_credit,
            clean_master_authority=master,
            expected_build_identity=build_identity,
        )
    except DilonIdentityReviewError:
        raise
    except (
        MasteringExportError,
        DilonIdentityStatusError,
        DilonIdentityBuildError,
        DilonIdentityQAError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        raise DilonIdentityReviewError(
            "identity_not_reviewable",
            "Exact-current Dilon identity и technical QA не подтверждены.",
        ) from error

    output = manifest.get("output")
    if not isinstance(output, Mapping):
        raise DilonIdentityReviewError("identity_not_reviewable", "Identity output metadata отсутствует.")
    audio_path = _regular(
        Path(str(output.get("path") or "")),
        root=root,
        label="Dilon identity WAV",
    )
    digest = sha256_file(audio_path)
    identity_path = path_identity(audio_path)
    if (
        qa.get("status") != "PASS"
        or qa.get("build_identity") != build_identity
        or qa.get("output_path") != str(audio_path)
        or qa.get("output_sha256") != digest
        or output.get("sha256") != digest
        or output.get("path_identity") != identity_path
        or qa.get("provider_requests") != 0
        or qa.get("remote_request_sent") is not False
        or qa.get("paid_execution") is not False
        or qa.get("billing_changed") is not False
    ):
        raise DilonIdentityReviewError(
            "identity_technical_qa_not_current",
            "Dilon identity technical QA больше не совпадает с exact-current output.",
        )
    return {
        "book_slug": slug,
        "job_id": job,
        "build_identity": build_identity,
        "audio_path": str(audio_path),
        "audio_sha256": digest,
        "path_identity": identity_path,
        "technical_qa": {
            "status": "PASS",
            "output_sha256": digest,
            "opening_credit_sha256": qa.get("opening_credit_sha256"),
            "clean_master_sha256": qa.get("clean_master_sha256"),
            "frame_count": qa.get("frame_count"),
            "gap_frames": qa.get("gap_frames"),
        },
    }


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
        "whole_book_release_ready": False,
    }


def identity_review_status(
    *,
    workspace_root: Path,
    masters_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    subject = current_identity_subject(
        workspace_root=root,
        masters_root=masters_root,
        identities_root=identities_root,
        book_slug=book_slug,
        job_id=job_id,
    )
    review_root = identity_review_root(
        workspace_root=root,
        book_slug=subject["book_slug"],
        job_id=subject["job_id"],
    )
    current = review_root / "CURRENT.json"
    if not (current.exists() or current.is_symlink()):
        return {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "state": "PENDING_HUMAN_REVIEW",
            "decision": "HUMAN_LISTENING_REQUIRED",
            "identity_accepted": False,
            "human_listening_required": True,
            "subject": subject,
            "review_authority_path": str(current),
            **_offline_fields(),
        }
    pointer = _load_json(current, root=root, label="Dilon identity review CURRENT.json")
    expected_manifest = (
        review_root / "approvals" / subject["build_identity"] / "REVIEW.json"
    )
    if pointer.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise DilonIdentityReviewError("review_pointer_invalid", "Identity review CURRENT schema invalid.")
    if pointer.get("build_identity") != subject["build_identity"]:
        return {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "state": "PENDING_HUMAN_REVIEW",
            "decision": "HUMAN_LISTENING_REQUIRED",
            "identity_accepted": False,
            "human_listening_required": True,
            "stale_previous_review": True,
            "subject": subject,
            "review_authority_path": str(current),
            **_offline_fields(),
        }
    if pointer.get("review_manifest_path") != str(expected_manifest):
        raise DilonIdentityReviewError("review_pointer_invalid", "Identity review pointer path invalid.")
    envelope = _load_json(
        expected_manifest,
        root=root,
        label="Dilon identity REVIEW.json",
    )
    listened = envelope.get("listened_identity")
    if (
        envelope.get("schema_version") != REVIEW_SCHEMA_VERSION
        or envelope.get("subject") != subject
        or not isinstance(listened, Mapping)
        or listened.get("build_identity") != subject["build_identity"]
        or listened.get("audio_sha256") != subject["audio_sha256"]
        or listened.get("path_identity") != subject["path_identity"]
        or pointer.get("audio_sha256") != subject["audio_sha256"]
        or pointer.get("path_identity") != subject["path_identity"]
    ):
        raise DilonIdentityReviewError(
            "identity_review_stale",
            "Persisted Dilon identity review больше не совпадает с current output.",
        )
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "state": "APPROVED",
        "decision": "IDENTITY_REVIEW_COMPLETE",
        "identity_accepted": True,
        "human_listening_required": False,
        "subject": subject,
        "listened_identity": dict(listened),
        "review_manifest_path": str(expected_manifest),
        "review_authority_path": str(current),
        **_offline_fields(),
    }


def approve_current_identity(
    *,
    workspace_root: Path,
    masters_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
    listened_build_identity: str,
    listened_audio_sha256: str,
    listened_path_identity: str,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    subject = current_identity_subject(
        workspace_root=root,
        masters_root=masters_root,
        identities_root=identities_root,
        book_slug=book_slug,
        job_id=job_id,
    )
    listened = {
        "build_identity": _safe_id(listened_build_identity, "listened_build_identity"),
        "audio_sha256": _safe_id(listened_audio_sha256, "listened_audio_sha256"),
        "path_identity": _safe_id(listened_path_identity, "listened_path_identity"),
    }
    if (
        listened["build_identity"] != subject["build_identity"]
        or listened["audio_sha256"] != subject["audio_sha256"]
        or listened["path_identity"] != subject["path_identity"]
    ):
        raise DilonIdentityReviewError(
            "listened_identity_mismatch",
            "Human review не совпадает с exact Dilon identity, прослушанной player-ом.",
        )

    review_root = identity_review_root(
        workspace_root=root,
        book_slug=subject["book_slug"],
        job_id=subject["job_id"],
    )
    approval_dir = _safe_dir(
        review_root / "approvals" / subject["build_identity"],
        root=root,
    )
    manifest_path = approval_dir / "REVIEW.json"
    if manifest_path.is_symlink():
        raise DilonIdentityReviewError("review_symlink", "Identity REVIEW.json является symlink.")
    if manifest_path.exists():
        existing = _load_json(manifest_path, root=root, label="Dilon identity REVIEW.json")
        if (
            existing.get("schema_version") != REVIEW_SCHEMA_VERSION
            or existing.get("subject") != subject
            or existing.get("listened_identity") != listened
        ):
            raise DilonIdentityReviewError("review_collision", "Existing identity review не совпадает.")
    else:
        atomic_write_json(
            manifest_path,
            {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "approved_at": utc_now_iso(),
                "subject": subject,
                "listened_identity": listened,
            },
        )

    current = _safe_dir(review_root, root=root) / "CURRENT.json"
    if current.is_symlink():
        raise DilonIdentityReviewError("review_symlink", "Identity review CURRENT.json является symlink.")
    atomic_write_json(
        current,
        {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "book_slug": subject["book_slug"],
            "job_id": subject["job_id"],
            "build_identity": subject["build_identity"],
            "audio_sha256": subject["audio_sha256"],
            "path_identity": subject["path_identity"],
            "review_manifest_path": str(manifest_path),
        },
    )
    return identity_review_status(
        workspace_root=root,
        masters_root=masters_root,
        identities_root=identities_root,
        book_slug=subject["book_slug"],
        job_id=subject["job_id"],
    )
