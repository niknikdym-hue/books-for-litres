"""Fail-closed chapter production plans for the primary Yandex workflow."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from backends.yandex_speechkit import YandexSpeechKitError
from book_library import BookLibrary, BookLibraryError
from cloud_billing import CloudBillingService, decimal_text, decimal_value
from paid_run import PaidRunPlanStore


SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 10 * 60
PROFILE_ID = "yandex_lera"
MAX_CHAPTER_NETWORK_REQUESTS = 200
PLAN_STATES = {"PREPARED", "CONSUMING", "CONSUMED", "EXPIRED", "BLOCKED"}
PLAN_DECISIONS = {"READY_FOR_CONFIRMATION", "CACHE_ONLY", "BLOCKED"}


class ChapterProductionError(RuntimeError):
    def __init__(self, message: str, *, category: str = "chapter_production_blocked") -> None:
        super().__init__(message)
        self.category = category


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plan_digest(
    critical: Mapping[str, Any],
    *,
    plan_id: str,
    created_at: str,
    expires_at: str,
) -> str:
    return _canonical_hash({
        "critical": critical,
        "plan_id": plan_id,
        "created_at": created_at,
        "expires_at": expires_at,
    })


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ChapterProductionError("Chapter plan timestamp is invalid.", category="invalid_plan") from error
    if parsed.tzinfo is None:
        raise ChapterProductionError("Chapter plan timestamp has no timezone.", category="invalid_plan")
    return parsed.astimezone(timezone.utc)


class YandexChapterProductionService:
    """Prepare and consume one immutable plan for one prepared chapter.

    PREPARE is local-only. EXECUTE may send several provider requests, but the
    immutable plan fixes an upper bound equal to the current cache misses.
    """

    def __init__(
        self,
        *,
        backend: Any,
        pricing: Any,
        billing: CloudBillingService,
        books_dir: Path,
        plans_dir: Path,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Chapter plan TTL must be positive.")
        self.backend = backend
        self.pricing = pricing
        self.billing = billing
        self.library = BookLibrary(books_dir)
        self.store = PaidRunPlanStore(plans_dir)
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _load_chapter(self, book_name: str, job_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], str]:
        try:
            profile_path = self.library.resolve_book_profile(book_name)
            book = self.library.load_book_for_execution(book_name)
        except BookLibraryError as error:
            raise ChapterProductionError("Book preparation is not READY.", category="invalid_book_job") from error
        job = (book.get("jobs") or {}).get(job_id) if isinstance(book, dict) else None
        if not isinstance(job, dict) or job.get("kind") != "chapter":
            raise ChapterProductionError("Only a prepared chapter job can enter chapter production.", category="invalid_book_job")
        segments = job.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ChapterProductionError("Prepared chapter job is empty.", category="invalid_book_job")
        texts: list[str] = []
        for segment in segments:
            text = segment.get("text") if isinstance(segment, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ChapterProductionError("Prepared chapter contains invalid text.", category="invalid_book_job")
            texts.append(text.strip())
        return profile_path, book, job, "\n\n".join(texts)

    def _job_dir(self, book: Mapping[str, Any], job_id: str) -> Path:
        slug = str(book.get("slug") or "book")
        return Path(self.backend.config.output_root) / slug / job_id / PROFILE_ID

    def _manifest_blockers(self, job_dir: Path, *, job_id: str) -> list[str]:
        path = job_dir / "MANIFEST.json"
        if not path.exists():
            return []
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ["manifest_mismatch"]
        profile = manifest.get("profile") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("engine") != "yandex_speechkit_v3"
            or manifest.get("job_id") != job_id
            or not isinstance(profile, dict)
            or profile.get("voice") != self.backend.profile.voice
            or profile.get("role") != self.backend.profile.role
            or str(profile.get("speed")) != str(self.backend.profile.speed)
            or not isinstance(manifest.get("segments"), dict)
        ):
            return ["manifest_mismatch"]
        blockers: list[str] = []
        for entry in manifest["segments"].values():
            state = entry.get("status") if isinstance(entry, dict) else None
            if state in {"AMBIGUOUS", "IN_FLIGHT"}:
                blockers.append("ambiguous_segment_requires_resolution")
            elif state == "FAILED":
                blockers.append("failed_segment_requires_resolution")
        return list(dict.fromkeys(blockers))

    def _analyze(self, book_name: str, job_id: str, profile_id: str) -> dict[str, Any]:
        if profile_id != PROFILE_ID:
            raise ChapterProductionError("Yandex chapter production V1 supports only yandex_lera.", category="invalid_profile")
        profile_path, book, job, text = self._load_chapter(book_name, job_id)
        if self.backend.profile.voice != "lera":
            raise ChapterProductionError("Configured Yandex production voice is not Lera.", category="invalid_profile")
        job_dir = self._job_dir(book, job_id)
        estimate = self.backend.estimate(text, pricing=self.pricing, job_dir=job_dir, scope="book")
        total_segments = int(estimate.get("segments") or 0)
        cached_segments = int(estimate.get("cached_segments") or 0)
        request_cap = max(0, total_segments - cached_segments)
        blockers = self._manifest_blockers(job_dir, job_id=job_id)
        blocked_reason = estimate.get("blocked_reason")
        if request_cap and not estimate.get("allowed_to_start"):
            blockers.append(str(blocked_reason or "pricing_blocked"))
        if request_cap > MAX_CHAPTER_NETWORK_REQUESTS:
            blockers.append("chapter_request_cap_exceeded")

        credential_available = False
        if request_cap:
            try:
                credential_available = bool(self.backend.validate_config(resolve_credentials=True).get("credentials_present"))
            except YandexSpeechKitError:
                blockers.append("missing_credential")
        estimated_cost_value = estimate.get("estimated_remaining_cost")
        estimated_cost = (
            decimal_value(estimated_cost_value, "yandex.current_job_estimate")
            if estimated_cost_value is not None else None
        )
        billing = self.billing.preflight(
            "yandex",
            current_job_estimate=estimated_cost,
            current_job_estimate_source="local_estimate" if estimated_cost is not None else "unavailable",
            hard_limit=self.pricing.hard_limit_rub,
            paid_execution_enabled=True,
            job_metadata={
                "book": book.get("slug"),
                "job_id": job_id,
                "profile_id": profile_id,
                "preparation_identity": (book.get("preparation") or {}).get("identity_sha256"),
            },
        )
        if request_cap and billing.get("decision") == "BLOCK":
            blockers.append(str(billing.get("decision_reason") or "billing_blocked"))
        blockers = list(dict.fromkeys(blockers))
        decision = "BLOCKED" if blockers else ("CACHE_ONLY" if request_cap == 0 else "READY_FOR_CONFIRMATION")
        warnings = list(billing.get("warnings") or [])
        if billing.get("decision") == "BALANCE_UNKNOWN":
            warnings.append("provider_balance_unavailable")
        preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else {}
        critical = {
            "provider": "yandex",
            "book_id": str(book.get("slug") or profile_path.stem),
            "book_file": profile_path.name,
            "preparation_identity": preparation.get("identity_sha256"),
            "working_copy_sha256": preparation.get("working_copy_sha256"),
            "job_id": job_id,
            "job_text_sha256": _text_hash(text),
            "profile_id": profile_id,
            "voice": self.backend.profile.voice,
            "role": self.backend.profile.role,
            "speed": str(self.backend.profile.speed),
            "total_segments": total_segments,
            "cached_segments": cached_segments,
            "max_network_requests": request_cap,
            "estimated_remaining_cost": decimal_text(estimated_cost),
            "hard_limit": decimal_text(self.pricing.hard_limit_rub),
            "currency": self.pricing.currency,
            "pricing_verified_at": self.pricing.verified_at.isoformat() if self.pricing.verified_at else None,
            "pricing_source": self.pricing.source_url,
            "billing_identity": {
                "decision": billing.get("decision"),
                "decision_reason": billing.get("decision_reason"),
                "remaining": billing.get("remaining"),
                "remaining_source": billing.get("remaining_source"),
                "remaining_as_of": billing.get("remaining_as_of"),
                "status": billing.get("status"),
                "warnings": billing.get("warnings"),
            },
        }
        return {
            "profile_path": profile_path,
            "book": book,
            "job": job,
            "text": text,
            "job_dir": job_dir,
            "estimate": estimate,
            "billing": billing,
            "blockers": blockers,
            "warnings": list(dict.fromkeys(warnings)),
            "credential_available": credential_available,
            "decision": decision,
            "critical": critical,
        }

    def prepare(self, *, book_name: str, job_id: str, profile_id: str) -> dict[str, Any]:
        analysis = self._analyze(book_name, job_id, profile_id)
        created = self._now().astimezone(timezone.utc)
        critical = analysis["critical"]
        plan_id = uuid.uuid4().hex
        created_at = _iso(created)
        expires_at = _iso(created + timedelta(seconds=self.ttl_seconds))
        plan = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan_id,
            "plan_digest": _plan_digest(
                critical,
                plan_id=plan_id,
                created_at=created_at,
                expires_at=expires_at,
            ),
            "state": "BLOCKED" if analysis["decision"] == "BLOCKED" else "PREPARED",
            "created_at": created_at,
            "expires_at": expires_at,
            "provider": "yandex",
            "book_id": critical["book_id"],
            "book_file": critical["book_file"],
            "book_title": str(analysis["book"].get("title") or critical["book_id"]),
            "job_id": critical["job_id"],
            "job_label": str(analysis["job"].get("label") or critical["job_id"]),
            "profile_id": profile_id,
            "voice": critical["voice"],
            "role": critical["role"],
            "speed": critical["speed"],
            "characters": int(analysis["estimate"].get("characters") or 0),
            "total_segments": critical["total_segments"],
            "cached_segments": critical["cached_segments"],
            "max_network_requests": critical["max_network_requests"],
            "estimated_remaining_cost": critical["estimated_remaining_cost"],
            "hard_limit": critical["hard_limit"],
            "currency": critical["currency"],
            "pricing_verified_at": critical["pricing_verified_at"],
            "pricing_stale": bool(analysis["estimate"].get("price_stale")),
            "credential_available": analysis["credential_available"],
            "warnings": analysis["warnings"],
            "blockers": analysis["blockers"],
            "decision": analysis["decision"],
            "billing": analysis["billing"],
            "remote_request_sent": False,
        }
        self.store.save(plan)
        return plan

    def execute(self, *, plan_id: str, plan_digest: str) -> dict[str, Any]:
        with self.store.locked(plan_id):
            plan = self.store.load(plan_id)
            if (
                plan.get("schema_version") != SCHEMA_VERSION
                or plan.get("provider") != "yandex"
                or plan.get("state") not in PLAN_STATES
                or plan.get("decision") not in PLAN_DECISIONS
            ):
                raise ChapterProductionError("Chapter production plan is invalid.", category="invalid_plan")
            if plan.get("plan_digest") != plan_digest:
                raise ChapterProductionError("Chapter plan digest does not match.", category="plan_digest_mismatch")
            if plan.get("state") != "PREPARED":
                raise ChapterProductionError("Chapter plan is no longer executable.", category="plan_not_prepared")
            if self._now().astimezone(timezone.utc) >= _parse_time(str(plan.get("expires_at"))):
                plan["state"] = "EXPIRED"
                self.store.save(plan)
                raise ChapterProductionError("Chapter plan has expired.", category="plan_expired")
            try:
                analysis = self._analyze(
                    str(plan["book_file"]),
                    str(plan["job_id"]),
                    str(plan["profile_id"]),
                )
            except ChapterProductionError as error:
                raise ChapterProductionError(
                    "Chapter execution facts changed.",
                    category="execution_facts_changed",
                ) from error
            if analysis["decision"] != plan.get("decision") or analysis["blockers"]:
                raise ChapterProductionError("Chapter execution facts changed.", category="execution_facts_changed")
            expected_digest = _plan_digest(
                analysis["critical"],
                plan_id=str(plan["plan_id"]),
                created_at=str(plan["created_at"]),
                expires_at=str(plan["expires_at"]),
            )
            if expected_digest != plan_digest:
                raise ChapterProductionError("Chapter execution facts changed.", category="execution_facts_changed")
            request_cap = int(analysis["critical"]["max_network_requests"])
            if request_cap < 0 or int(plan.get("max_network_requests") or 0) != request_cap:
                raise ChapterProductionError("Chapter request cap is invalid.", category="invalid_plan")
            plan["state"] = "CONSUMING"
            plan["consuming_at"] = _iso(self._now())
            self.store.save(plan)

        network_requests = 0
        original_request = self.backend._request

        def capped_request(text: str, request_id: str) -> Any:
            nonlocal network_requests
            if network_requests >= request_cap:
                raise ChapterProductionError("Chapter request cap was exhausted.", category="request_cap_exceeded")
            network_requests += 1
            return original_request(text, request_id)

        self.backend._request = capped_request
        try:
            output_path = self.backend.run_text_job(
                analysis["text"],
                analysis["job_dir"],
                job_id=str(plan["job_id"]),
                pricing=self.pricing,
                scope="book",
            )
            if network_requests > request_cap:
                raise ChapterProductionError("Chapter request cap was exceeded.", category="request_cap_exceeded")
            result = {
                "schema_version": SCHEMA_VERSION,
                "plan_id": plan_id,
                "state": "CONSUMED",
                "decision": plan["decision"],
                "manifest": str(analysis["job_dir"] / "MANIFEST.json"),
                "output_path": str(output_path),
                "network_requests": network_requests,
                "max_network_requests": request_cap,
                "remote_request_sent": network_requests > 0,
            }
        finally:
            self.backend._request = original_request
            with self.store.locked(plan_id):
                final_plan = self.store.load(plan_id)
                final_plan["state"] = "CONSUMED"
                final_plan["consumed_at"] = _iso(self._now())
                final_plan["network_requests"] = network_requests
                final_plan["remote_request_sent"] = network_requests > 0
                self.store.save(final_plan)
        return result
