"""Offline provider-neutral service surface for Dilon identity status and preview.

The service is intentionally UI/CLI agnostic. It exposes only safe local actions:
opening-credit PREPARE persistence/status and exact-current identity status/preview.
There is no synthesis/provider execution method.
"""

from __future__ import annotations

import stat
from datetime import date
from pathlib import Path
from typing import Any

from audio_qa_review import path_identity, sha256_file
from backends.yandex_pricing import YandexPricingConfig
from dilon_identity_build import DilonIdentityBuildError, resolve_current_identity
from dilon_opening_credit_plan_store import OpeningCreditPlanStore
from voice_library import DEFAULT_REGISTRY_PATH


BRIDGE_SCHEMA_VERSION = 1


class DilonIdentityBridgeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _workspace_root(path: Path) -> Path:
    requested = Path(path).expanduser().absolute()
    if requested.is_symlink():
        raise DilonIdentityBridgeError("symlink_workspace_root", "Workspace root является symbolic link.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise DilonIdentityBridgeError("missing_workspace", "Workspace root не найден.") from error


def _canonical_root(path: Path, *, expected: Path, code: str, label: str) -> Path:
    requested = Path(path).expanduser().absolute()
    if requested != expected:
        raise DilonIdentityBridgeError(code, f"{label} не совпадает с canonical workspace path.")
    current = expected.parent
    if current.is_symlink() or requested.is_symlink():
        raise DilonIdentityBridgeError(code, f"{label} содержит symbolic link.")
    return requested


def _preview_file(path: Path, *, workspace: Path, identities: Path) -> Path:
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(identities)
    except ValueError as error:
        raise DilonIdentityBridgeError(
            "identity_preview_path_invalid", "Identity preview находится вне canonical identities root."
        ) from error
    current = identities
    if current.is_symlink():
        raise DilonIdentityBridgeError("identity_preview_path_invalid", "Identity root является symbolic link.")
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise DilonIdentityBridgeError("identity_preview_path_invalid", "Identity preview не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise DilonIdentityBridgeError("identity_preview_path_invalid", "Identity preview содержит symbolic link.")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(workspace)
    except (OSError, ValueError) as error:
        raise DilonIdentityBridgeError("identity_preview_path_invalid", "Identity preview path не подтверждён.") from error
    if not resolved.is_file():
        raise DilonIdentityBridgeError("identity_preview_path_invalid", "Identity preview должен быть обычным file.")
    return resolved


class DilonIdentityBridgeService:
    def __init__(
        self,
        *,
        workspace_root: Path,
        identities_root: Path,
        paid_plans_root: Path,
    ) -> None:
        self.workspace_root = _workspace_root(workspace_root)
        self.identities_root = _canonical_root(
            identities_root,
            expected=self.workspace_root / "identities",
            code="noncanonical_identity_root",
            label="Identity root",
        )
        canonical_plans = self.workspace_root / "runtime" / "paid-run-plans"
        plans_root = _canonical_root(
            paid_plans_root,
            expected=canonical_plans,
            code="noncanonical_plan_root",
            label="Paid plan root",
        )
        self.plan_store = OpeningCreditPlanStore(plans_root)

    @staticmethod
    def _offline_envelope(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            **payload,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }

    def prepare_opening_credit(
        self,
        *,
        pricing: YandexPricingConfig,
        today: date | None = None,
        registry_path: Path = DEFAULT_REGISTRY_PATH,
    ) -> dict[str, Any]:
        result = self.plan_store.prepare(
            pricing=pricing,
            today=today,
            registry_path=registry_path,
        )
        return self._offline_envelope({"opening_credit_plan": result})

    def opening_credit_plan_status(
        self, *, plan_id: str, plan_digest: str
    ) -> dict[str, Any]:
        plan = self.plan_store.load(
            plan_id=plan_id,
            expected_plan_digest=plan_digest,
        )
        return self._offline_envelope({"opening_credit_plan": plan})

    def identity_status(
        self,
        *,
        book_slug: str,
        job_id: str,
        expected_build_identity: str | None = None,
    ) -> dict[str, Any]:
        try:
            manifest = resolve_current_identity(
                workspace_root=self.workspace_root,
                identities_root=self.identities_root,
                book_slug=book_slug,
                job_id=job_id,
                expected_build_identity=expected_build_identity,
            )
        except DilonIdentityBuildError as error:
            return self._offline_envelope(
                {
                    "state": "BLOCKED",
                    "decision": "IDENTITY_NOT_CURRENT",
                    "blockers": [error.code],
                    "identity": None,
                    "preview": None,
                }
            )

        output = manifest.get("output")
        if not isinstance(output, dict):
            return self._offline_envelope(
                {
                    "state": "BLOCKED",
                    "decision": "IDENTITY_NOT_CURRENT",
                    "blockers": ["identity_output_missing"],
                    "identity": None,
                    "preview": None,
                }
            )
        try:
            path = _preview_file(
                Path(str(output.get("path") or "")),
                workspace=self.workspace_root,
                identities=self.identities_root,
            )
            digest = sha256_file(path)
            identity = path_identity(path)
        except (DilonIdentityBridgeError, OSError) as error:
            code = error.code if isinstance(error, DilonIdentityBridgeError) else "identity_output_missing"
            return self._offline_envelope(
                {
                    "state": "BLOCKED",
                    "decision": "IDENTITY_NOT_CURRENT",
                    "blockers": [code],
                    "identity": None,
                    "preview": None,
                }
            )
        if output.get("sha256") != digest:
            return self._offline_envelope(
                {
                    "state": "BLOCKED",
                    "decision": "IDENTITY_NOT_CURRENT",
                    "blockers": ["identity_output_sha_mismatch"],
                    "identity": None,
                    "preview": None,
                }
            )

        return self._offline_envelope(
            {
                "state": "READY",
                "decision": "READY_TO_PREVIEW",
                "blockers": [],
                "identity": {
                    "build_identity": manifest.get("build_identity"),
                    "preflight_plan_id": manifest.get("preflight_plan_id"),
                    "book_slug": manifest.get("book_slug"),
                    "job_id": manifest.get("job_id"),
                    "output_sha256": digest,
                },
                "preview": {
                    "audio_path": str(path),
                    "audio_sha256": digest,
                    "path_identity": identity,
                    "read_only": True,
                },
            }
        )
