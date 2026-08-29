"""Offline current-state orchestration for the Dilon Voices identity layer.

The status operation itself is strictly network-free and billing-neutral.  It may
consume a reviewed opening-credit authority that was produced historically by an
explicit paid provider action; historical production provenance must not be
misrepresented as a new request made by this read-only status call.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

from book_library import BookLibraryError, normalize_slug
from dilon_identity import (
    DILON_BRAND,
    DILON_DESCRIPTION,
    OPENING_CREDIT_TEXT,
    DilonIdentityError,
    build_identity_preflight,
)
from dilon_identity_build import (
    DilonIdentityBuildError,
    prepare_identity_build,
    resolve_current_identity,
)
from dilon_identity_qa import DilonIdentityQAError, run_identity_technical_qa
from mastering_export import MasteringExportError, resolve_current_master


STATUS_SCHEMA_VERSION = 1
OPENING_CREDIT_AUTHORITY_SCHEMA_VERSION = 1


class DilonIdentityStatusError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_slug(value: Any) -> str:
    try:
        return normalize_slug(str(value or ""))
    except BookLibraryError as error:
        raise DilonIdentityStatusError("invalid_book_slug", "Некорректный book_slug.") from error


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise DilonIdentityStatusError("invalid_identity", f"Некорректный {label}.")
    return value


def _workspace_root(value: Path) -> Path:
    requested = Path(value).expanduser().absolute()
    if requested.is_symlink():
        raise DilonIdentityStatusError("symlink_workspace_root", "Workspace root является ссылкой.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise DilonIdentityStatusError("missing_workspace", "Workspace root не найден.") from error


def _regular(path: Path, *, root: Path, label: str) -> Path:
    boundary = _workspace_root(root)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise DilonIdentityStatusError("path_escape", f"{label} находится вне workspace.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise DilonIdentityStatusError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise DilonIdentityStatusError("symlink_input", f"{label} содержит symlink.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise DilonIdentityStatusError("invalid_input", f"{label} должен быть обычным файлом.")
    return resolved


def opening_credit_authority_path(*, workspace_root: Path, book_slug: str, job_id: str) -> Path:
    root = _workspace_root(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    return root / "runtime" / "dilon-opening-credit" / slug / job / "CURRENT.json"


def _load_opening_credit_authority(
    *, workspace_root: Path, book_slug: str, job_id: str
) -> tuple[dict[str, Any] | None, Path]:
    """Load exact reviewed credit authority without falsifying historical billing facts.

    `provider_requests`, `remote_request_sent`, `paid_execution`, and
    `billing_changed` may describe the historical production that created the
    credit.  They are deliberately not required to be zero here.  The status
    response itself always reports zero/false for the current read-only call.
    """
    expected = opening_credit_authority_path(
        workspace_root=workspace_root, book_slug=book_slug, job_id=job_id
    )
    if not (expected.exists() or expected.is_symlink()):
        return None, expected
    path = _regular(expected, root=workspace_root, label="Opening credit authority")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise DilonIdentityStatusError(
            "opening_credit_authority_invalid", "Opening credit authority повреждена."
        ) from error
    if not isinstance(payload, Mapping):
        raise DilonIdentityStatusError(
            "opening_credit_authority_invalid", "Opening credit authority имеет неверный формат."
        )
    try:
        same_slug = _safe_slug(payload.get("book_slug")) == _safe_slug(book_slug)
        same_job = _safe_id(payload.get("job_id"), "job_id") == _safe_id(job_id, "job_id")
    except DilonIdentityStatusError as error:
        raise DilonIdentityStatusError(
            "opening_credit_authority_invalid", "Opening credit authority не совпадает с selection."
        ) from error
    if (
        payload.get("schema_version") != OPENING_CREDIT_AUTHORITY_SCHEMA_VERSION
        or not same_slug
        or not same_job
    ):
        raise DilonIdentityStatusError(
            "opening_credit_authority_invalid", "Opening credit authority не совпадает с canonical envelope."
        )
    record = payload.get("opening_credit")
    if not isinstance(record, Mapping):
        raise DilonIdentityStatusError(
            "opening_credit_authority_invalid", "Opening credit record отсутствует."
        )
    return dict(record), path


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def _blocked(
    *,
    slug: str,
    job: str,
    blockers: list[str],
    master: Mapping[str, Any] | None,
    authority_path: Path,
    opening_credit: Mapping[str, Any] | None,
    opening_credit_prepare: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "state": "BLOCKED",
        "decision": "BLOCKED",
        "brand": DILON_BRAND,
        "description": DILON_DESCRIPTION,
        "book_slug": slug,
        "job_id": job,
        "opening_credit_text": OPENING_CREDIT_TEXT,
        "clean_master": dict(master) if isinstance(master, Mapping) else None,
        "opening_credit": dict(opening_credit) if isinstance(opening_credit, Mapping) else None,
        "opening_credit_authority_path": str(authority_path),
        "opening_credit_prepare": dict(opening_credit_prepare) if isinstance(opening_credit_prepare, Mapping) else None,
        "identity": None,
        "technical_qa": None,
        "signature_state": "OMITTED_CANONICAL_NO_MUSIC",
        "human_listening_required": True,
        "technical_ready": False,
        "whole_book_release_ready": False,
        "blockers": list(dict.fromkeys(blockers)),
        **_offline_fields(),
    }


def current_dilon_identity_status(
    *,
    workspace_root: Path,
    masters_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
    opening_credit_prepare: Mapping[str, Any] | None = None,
    master_resolver: Callable[..., Mapping[str, Any]] = resolve_current_master,
) -> dict[str, Any]:
    """Return exact-current Dilon identity state without provider execution."""
    root = _workspace_root(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    authority_path = opening_credit_authority_path(
        workspace_root=root, book_slug=slug, job_id=job
    )

    try:
        master = dict(master_resolver(
            workspace_root=root,
            masters_root=masters_root,
            book_slug=slug,
            job_id=job,
        ))
    except (MasteringExportError, OSError, ValueError, TypeError, KeyError):
        return _blocked(
            slug=slug,
            job=job,
            blockers=["clean_master_missing_or_stale"],
            master=None,
            authority_path=authority_path,
            opening_credit=None,
            opening_credit_prepare=opening_credit_prepare,
        )

    try:
        opening_credit, authority_path = _load_opening_credit_authority(
            workspace_root=root, book_slug=slug, job_id=job
        )
    except DilonIdentityStatusError as error:
        return _blocked(
            slug=slug,
            job=job,
            blockers=[error.code],
            master=master,
            authority_path=authority_path,
            opening_credit=None,
            opening_credit_prepare=opening_credit_prepare,
        )

    try:
        preflight = build_identity_preflight(
            master,
            workspace_root=root,
            opening_credit_text=OPENING_CREDIT_TEXT,
            opening_credit=opening_credit,
            signature_asset=None,
        )
    except DilonIdentityError as error:
        return _blocked(
            slug=slug,
            job=job,
            blockers=[error.code],
            master=master,
            authority_path=authority_path,
            opening_credit=opening_credit,
            opening_credit_prepare=opening_credit_prepare,
        )
    if preflight.get("state") != "READY":
        return _blocked(
            slug=slug,
            job=job,
            blockers=list(preflight.get("blockers") or ["identity_preflight_blocked"]),
            master=master,
            authority_path=authority_path,
            opening_credit=opening_credit,
            opening_credit_prepare=opening_credit_prepare,
        )

    try:
        plan = prepare_identity_build(
            preflight,
            workspace_root=root,
            identities_root=identities_root,
        )
    except DilonIdentityBuildError as error:
        return _blocked(
            slug=slug,
            job=job,
            blockers=[error.code],
            master=master,
            authority_path=authority_path,
            opening_credit=opening_credit,
            opening_credit_prepare=opening_credit_prepare,
        )

    expected_identity = str(plan["build_identity"])
    try:
        manifest = resolve_current_identity(
            workspace_root=root,
            identities_root=identities_root,
            book_slug=slug,
            job_id=job,
            expected_build_identity=expected_identity,
        )
    except DilonIdentityBuildError:
        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "state": "READY_TO_BUILD",
            "decision": "READY_TO_BUILD_OFFLINE",
            "brand": DILON_BRAND,
            "description": DILON_DESCRIPTION,
            "book_slug": slug,
            "job_id": job,
            "opening_credit_text": OPENING_CREDIT_TEXT,
            "clean_master": master,
            "opening_credit": opening_credit,
            "opening_credit_authority_path": str(authority_path),
            "opening_credit_prepare": dict(opening_credit_prepare) if isinstance(opening_credit_prepare, Mapping) else None,
            "identity": {
                "build_identity": expected_identity,
                "output_path": str(Path(str(plan.get("output_dir") or "")) / "identity.wav"),
                "current": False,
            },
            "technical_qa": None,
            "signature_state": "OMITTED_CANONICAL_NO_MUSIC",
            "human_listening_required": True,
            "technical_ready": False,
            "whole_book_release_ready": False,
            "blockers": ["identity_output_missing"],
            **_offline_fields(),
        }

    try:
        qa = run_identity_technical_qa(
            workspace_root=root,
            identities_root=identities_root,
            book_slug=slug,
            job_id=job,
            opening_credit_authority=opening_credit or {},
            clean_master_authority=master,
            expected_build_identity=expected_identity,
        )
    except DilonIdentityQAError as error:
        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "state": "CURRENT_QA_BLOCKED",
            "decision": "TECHNICAL_QA_BLOCKED",
            "brand": DILON_BRAND,
            "description": DILON_DESCRIPTION,
            "book_slug": slug,
            "job_id": job,
            "opening_credit_text": OPENING_CREDIT_TEXT,
            "clean_master": master,
            "opening_credit": opening_credit,
            "opening_credit_authority_path": str(authority_path),
            "opening_credit_prepare": dict(opening_credit_prepare) if isinstance(opening_credit_prepare, Mapping) else None,
            "identity": {
                "build_identity": manifest.get("build_identity"),
                "output_path": (manifest.get("output") or {}).get("path"),
                "output_sha256": (manifest.get("output") or {}).get("sha256"),
                "current": True,
            },
            "technical_qa": None,
            "signature_state": "OMITTED_CANONICAL_NO_MUSIC",
            "human_listening_required": True,
            "technical_ready": False,
            "whole_book_release_ready": False,
            "blockers": [error.code],
            **_offline_fields(),
        }

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "state": "CURRENT_TECHNICAL_QA_PASS",
        "decision": "HUMAN_LISTENING_REQUIRED",
        "brand": DILON_BRAND,
        "description": DILON_DESCRIPTION,
        "book_slug": slug,
        "job_id": job,
        "opening_credit_text": OPENING_CREDIT_TEXT,
        "clean_master": master,
        "opening_credit": opening_credit,
        "opening_credit_authority_path": str(authority_path),
        "opening_credit_prepare": dict(opening_credit_prepare) if isinstance(opening_credit_prepare, Mapping) else None,
        "identity": {
            "build_identity": manifest.get("build_identity"),
            "output_path": qa.get("output_path"),
            "output_sha256": qa.get("output_sha256"),
            "current": True,
        },
        "technical_qa": qa,
        "signature_state": "OMITTED_CANONICAL_NO_MUSIC",
        "human_listening_required": True,
        "technical_ready": True,
        "whole_book_release_ready": False,
        "blockers": [],
        **_offline_fields(),
    }
