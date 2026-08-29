"""Offline provider-neutral service surface for Dilon identity status and preview.

The service is intentionally UI/CLI agnostic. It exposes only safe local actions:
opening-credit PREPARE persistence/status and exact-current identity status/preview.
There is no synthesis/provider execution method.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from audio_qa_review import path_identity, sha256_file
from backends.yandex_pricing import YandexPricingConfig
from dilon_identity_build import DilonIdentityBuildError, resolve_current_identity
from dilon_opening_credit_plan_store import OpeningCreditPlanStore
from voice_library import DEFAULT_REGISTRY_PATH


BRIDGE_SCHEMA_VERSION = 1


class DilonIdentityBridgeService:
    def __init__(
        self,
        *,
        workspace_root: Path,
        identities_root: Path,
        paid_plans_root: Path,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.identities_root = Path(identities_root)
        self.plan_store = OpeningCreditPlanStore(Path(paid_plans_root))

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
        path = Path(str(output.get("path") or ""))
        try:
            digest = sha256_file(path)
            identity = path_identity(path)
        except OSError:
            return self._offline_envelope(
                {
                    "state": "BLOCKED",
                    "decision": "IDENTITY_NOT_CURRENT",
                    "blockers": ["identity_output_missing"],
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
