"""Immutable offline store for owner-gated Dilon opening-credit PREPARE plans.

The store deliberately contains no provider execution function. A future paid
executor must require both ``plan_id`` and ``plan_digest`` and revalidate price,
voice authority, and request cap before contacting Yandex.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import date
from pathlib import Path
from typing import Any

from backends.common import atomic_write_json, utc_now_iso
from backends.yandex_pricing import YandexPricingConfig
from dilon_opening_credit_prepare import prepare_opening_credit_plan
from voice_library import DEFAULT_REGISTRY_PATH


STORE_SCHEMA_VERSION = 1
PLAN_SUBDIR = "dilon-opening-credit"


class OpeningCreditPlanStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def plan_digest(plan: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(plan)).hexdigest()


def _sha_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OpeningCreditPlanStoreError("invalid_plan_identity", f"Некорректный {label}.")
    return value


def _safe_store_root(plans_root: Path) -> Path:
    root = Path(plans_root).expanduser().absolute()
    if root.is_symlink():
        raise OpeningCreditPlanStoreError("symlink_plan_root", "Paid plan root является symbolic link.")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            raise OpeningCreditPlanStoreError("symlink_plan_root", "Paid plan root содержит symbolic link.")
    root.mkdir(parents=True, exist_ok=True)
    store = root / PLAN_SUBDIR
    if store.is_symlink():
        raise OpeningCreditPlanStoreError("symlink_plan_store", "Dilon plan store является symbolic link.")
    store.mkdir(exist_ok=True)
    return store


def _regular_plan_file(path: Path, *, store: Path) -> Path:
    candidate = Path(path).absolute()
    try:
        candidate.relative_to(store)
    except ValueError as error:
        raise OpeningCreditPlanStoreError("plan_path_escape", "Plan path находится вне canonical store.") from error
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise OpeningCreditPlanStoreError("missing_plan", "Opening-credit PREPARE plan не найден.") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OpeningCreditPlanStoreError("invalid_plan_file", "Opening-credit plan должен быть обычным JSON file.")
    return candidate


class OpeningCreditPlanStore:
    def __init__(self, plans_root: Path) -> None:
        self.plans_root = Path(plans_root)

    def prepare(
        self,
        *,
        pricing: YandexPricingConfig,
        today: date | None = None,
        registry_path: Path = DEFAULT_REGISTRY_PATH,
    ) -> dict[str, Any]:
        """Prepare and persist one immutable owner-authorization plan offline."""
        plan = prepare_opening_credit_plan(
            pricing=pricing,
            today=today,
            registry_path=registry_path,
        )
        if plan.get("state") != "READY_FOR_OWNER_AUTHORIZATION":
            return {
                **plan,
                "stored": False,
                "plan_digest": None,
                "plan_path": None,
            }

        identifier = _sha_id(plan.get("plan_id"), "plan_id")
        digest = plan_digest(plan)
        store = _safe_store_root(self.plans_root)
        path = store / f"{identifier}.json"
        envelope = {
            "schema_version": STORE_SCHEMA_VERSION,
            "plan_id": identifier,
            "plan_digest": digest,
            "prepared_at": utc_now_iso(),
            "plan": plan,
        }
        if path.exists() or path.is_symlink():
            existing = self._load_envelope(path, store=store)
            if (
                existing.get("plan_id") != identifier
                or existing.get("plan_digest") != digest
                or existing.get("plan") != plan
            ):
                raise OpeningCreditPlanStoreError(
                    "plan_collision", "Existing opening-credit plan не совпадает с prepared authority."
                )
        else:
            atomic_write_json(path, envelope)
        return {
            **plan,
            "stored": True,
            "plan_digest": digest,
            "plan_path": str(path),
        }

    def _load_envelope(self, path: Path, *, store: Path) -> dict[str, Any]:
        file_path = _regular_plan_file(path, store=store)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise OpeningCreditPlanStoreError("invalid_plan_json", "Opening-credit plan JSON повреждён.") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != STORE_SCHEMA_VERSION:
            raise OpeningCreditPlanStoreError("invalid_plan_envelope", "Opening-credit plan envelope повреждён.")
        return payload

    def load(self, *, plan_id: str, expected_plan_digest: str) -> dict[str, Any]:
        """Load an exact immutable plan offline. Does not authorize execution."""
        identifier = _sha_id(plan_id, "plan_id")
        expected = _sha_id(expected_plan_digest, "plan_digest")
        store = _safe_store_root(self.plans_root)
        path = store / f"{identifier}.json"
        payload = self._load_envelope(path, store=store)
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise OpeningCreditPlanStoreError("invalid_plan_envelope", "Opening-credit plan payload отсутствует.")
        actual_digest = plan_digest(plan)
        if (
            payload.get("plan_id") != identifier
            or payload.get("plan_digest") != expected
            or actual_digest != expected
            or plan.get("plan_id") != identifier
            or plan.get("state") != "READY_FOR_OWNER_AUTHORIZATION"
            or plan.get("decision") != "OWNER_AUTHORIZATION_REQUIRED"
            or plan.get("execution_available") is not False
            or plan.get("provider_requests") != 0
            or plan.get("remote_request_sent") is not False
            or plan.get("paid_execution") is not False
            or plan.get("billing_changed") is not False
        ):
            raise OpeningCreditPlanStoreError("plan_integrity_mismatch", "Opening-credit plan authority не подтверждена.")
        return {
            **plan,
            "stored": True,
            "plan_digest": actual_digest,
            "plan_path": str(path),
        }
