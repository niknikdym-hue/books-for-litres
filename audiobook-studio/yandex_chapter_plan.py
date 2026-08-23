"""Immutable Yandex chapter confirmation plans with one-shot execution safety.

The service freezes the current prepared chapter identity, cache-aware remaining provider
work, pricing identity and a maximum number of new provider requests. Execution exists at
the service layer only; bridge/native wiring must provide the separate explicit user
confirmation before calling it.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from book_library import BookLibrary, BookLibraryError
from chapter_production import ChapterProductionError, ChapterProductionService


SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 600
PLAN_STATES = {"PREPARED", "CONSUMING", "CONSUMED", "BLOCKED", "EXPIRED"}
PLAN_DECISIONS = {"READY_FOR_CONFIRMATION", "CACHE_ONLY", "BLOCKED"}
IMMUTABLE_PLAN_KEYS = (
    "schema_version",
    "plan_id",
    "created_at",
    "expires_at",
    "provider",
    "book_id",
    "job_id",
    "profile_id",
    "chapter_production_identity",
    "preparation_identity",
    "preparation_revision",
    "backend_identity",
    "provider_segments",
    "cached_segments",
    "max_network_requests",
    "pricing_identity",
    "estimated_remaining_cost",
    "billable_remaining_units",
    "hard_limit_rub",
    "decision",
    "blockers",
    "estimate",
    "job_dir",
    "confirmation_scope",
)


class YandexChapterPlanError(RuntimeError):
    def __init__(self, message: str, *, category: str = "yandex_chapter_plan_blocked") -> None:
        super().__init__(message)
        self.category = category


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan_digest(plan: Mapping[str, Any]) -> str:
    return _canonical_hash({key: plan.get(key) for key in IMMUTABLE_PLAN_KEYS})


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise YandexChapterPlanError("Plan timestamp has no timezone.", category="invalid_plan")
    return parsed.astimezone(timezone.utc)


class YandexChapterPlanStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, plan_id: str) -> Path:
        if not plan_id or any(character not in "0123456789abcdef-" for character in plan_id):
            raise YandexChapterPlanError("Invalid chapter plan ID.", category="invalid_plan")
        return self.root / f"{plan_id}.json"

    def load(self, plan_id: str) -> dict[str, Any]:
        path = self.path(plan_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise YandexChapterPlanError("Chapter plan was not found or is unreadable.", category="plan_not_found") from error
        if not isinstance(payload, dict):
            raise YandexChapterPlanError("Chapter plan is invalid.", category="invalid_plan")
        return payload

    def save(self, plan: Mapping[str, Any]) -> None:
        path = self.path(str(plan.get("plan_id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(plan, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def locked(self, plan_id: str):
        store = self

        class Lock:
            def __enter__(self) -> "Lock":
                path = store.path(plan_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.handle = path.with_suffix(".lock").open("a+")
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
                return self

            def __exit__(self, *_: object) -> None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                self.handle.close()

        return Lock()


class YandexChapterPlanService:
    """Create, revalidate and one-shot consume Yandex chapter confirmation plans."""

    def __init__(
        self,
        *,
        library: BookLibrary,
        backend: Any,
        pricing: Any,
        plans_dir: Path,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Chapter plan TTL must be positive.")
        self.library = library
        self.chapter_production = ChapterProductionService(library)
        self.backend = backend
        self.pricing = pricing
        self.store = YandexChapterPlanStore(plans_dir)
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _load_job_text(self, book_id: str, job_id: str) -> tuple[dict[str, Any], str]:
        try:
            book = self.library.load_book_for_execution(book_id)
        except BookLibraryError as error:
            raise YandexChapterPlanError(str(error), category="invalid_book_job") from error
        jobs = book.get("jobs") if isinstance(book.get("jobs"), dict) else {}
        job = jobs.get(job_id)
        if not isinstance(job, dict) or job.get("kind") != "chapter":
            raise YandexChapterPlanError("Prepared chapter job not found.", category="invalid_book_job")
        segments = job.get("segments")
        if not isinstance(segments, list) or not segments:
            raise YandexChapterPlanError("Prepared chapter job is empty.", category="invalid_book_job")
        texts: list[str] = []
        for segment in segments:
            value = segment.get("text") if isinstance(segment, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise YandexChapterPlanError("Prepared chapter contains invalid text.", category="invalid_book_job")
            texts.append(value.strip())
        return book, "\n\n".join(texts)

    def _pricing_identity(self) -> dict[str, Any]:
        verified_at = getattr(self.pricing, "verified_at", None)
        return {
            "currency": str(getattr(self.pricing, "currency", "RUB")),
            "unit": str(getattr(self.pricing, "unit", "billing_unit")),
            "unit_price": None if getattr(self.pricing, "unit_price", None) is None else str(self.pricing.unit_price),
            "pricing_model": str(getattr(self.pricing, "pricing_model", "")),
            "source_region": str(getattr(self.pricing, "source_region", "")),
            "verified_at": verified_at.isoformat() if verified_at is not None else None,
            "source_url": str(getattr(self.pricing, "source_url", "")),
            "max_age_days": int(getattr(self.pricing, "max_age_days", 0)),
            "hard_limit_rub": None if getattr(self.pricing, "hard_limit_rub", None) is None else str(self.pricing.hard_limit_rub),
            "demo_hard_limit_rub": None if getattr(self.pricing, "demo_hard_limit_rub", None) is None else str(self.pricing.demo_hard_limit_rub),
        }

    def _backend_identity(self) -> dict[str, Any]:
        profile = self.backend.profile
        config = self.backend.config
        return {
            "endpoint": str(getattr(config, "endpoint", "")),
            "keychain_service": str(getattr(config, "keychain_service", "")),
            "keychain_account": str(getattr(config, "keychain_account", "")),
            "output_root": str(getattr(config, "output_root", "")),
            "segmentation": {
                "max_chars": int(getattr(config, "max_chars", 0)),
                "max_words": int(getattr(config, "max_words", 0)),
                "sentence_pause_ms": int(getattr(config, "sentence_pause_ms", 0)),
                "paragraph_pause_ms": int(getattr(config, "paragraph_pause_ms", 0)),
            },
            "profile": {
                "voice": str(getattr(profile, "voice", "")),
                "role": str(getattr(profile, "role", "")),
                "speed": str(getattr(profile, "speed", "")),
                "output_container": str(getattr(profile, "output_container", "")),
                "loudness_normalization": str(getattr(profile, "loudness_normalization", "")),
            },
        }

    def _analyze(self, *, book_id: str, job_id: str, profile_id: str) -> dict[str, Any]:
        try:
            chapter = self.chapter_production.plan(
                book_id=book_id,
                job_id=job_id,
                engine="yandex",
                profile_id=profile_id,
            )
        except ChapterProductionError as error:
            raise YandexChapterPlanError(str(error), category="invalid_book_job") from error

        expected_profile = f"yandex_{str(self.backend.profile.voice).lower()}"
        blockers: list[str] = []
        if profile_id != expected_profile:
            blockers.append("profile_mismatch")

        book, text = self._load_job_text(book_id, job_id)
        slug = str(book.get("slug") or chapter["book_id"])
        job_dir = self.backend.config.output_root / slug / job_id / "yandex" / profile_id
        estimate = self.backend.estimate(
            text,
            pricing=self.pricing,
            job_dir=job_dir,
            scope="chapter",
        )
        provider_segments = int(estimate.get("segments") or 0)
        cached_segments = int(estimate.get("cached_segments") or 0)
        if provider_segments <= 0 or cached_segments < 0 or cached_segments > provider_segments:
            blockers.append("invalid_provider_estimate")
        max_network_requests = max(0, provider_segments - cached_segments)

        # Keep parity with the current Yandex backend: even CACHE_ONLY
        # materialization goes through run_text_job(), whose pricing gate must be
        # satisfied. A future dedicated cache-only materializer can relax this
        # without ever authorizing a provider request.
        if not estimate.get("allowed_to_start"):
            blockers.append(str(estimate.get("blocked_reason") or "pricing_gate"))

        blockers = list(dict.fromkeys(blockers))
        if blockers:
            decision = "BLOCKED"
        elif max_network_requests == 0:
            decision = "CACHE_ONLY"
        else:
            decision = "READY_FOR_CONFIRMATION"

        critical = {
            "schema_version": SCHEMA_VERSION,
            "provider": "yandex",
            "book_id": chapter["book_id"],
            "job_id": job_id,
            "profile_id": profile_id,
            "chapter_production_identity": chapter["chapter_production_identity"],
            "preparation_identity": chapter["preparation_identity"],
            "preparation_revision": chapter["preparation_revision"],
            "backend_identity": self._backend_identity(),
            "provider_segments": provider_segments,
            "cached_segments": cached_segments,
            "max_network_requests": max_network_requests,
            "pricing_identity": self._pricing_identity(),
            "estimated_remaining_cost": estimate.get("estimated_remaining_cost"),
            "billable_remaining_units": estimate.get("billable_remaining_units"),
            "hard_limit_rub": estimate.get("hard_limit_rub"),
        }
        return {
            "critical": critical,
            "chapter": chapter,
            "estimate": estimate,
            "job_dir": job_dir,
            "text": text,
            "decision": decision,
            "blockers": blockers,
        }

    def prepare(self, *, book_id: str, job_id: str, profile_id: str) -> dict[str, Any]:
        analysis = self._analyze(book_id=book_id, job_id=job_id, profile_id=profile_id)
        created = self._now().astimezone(timezone.utc)
        critical = analysis["critical"]
        plan = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": str(uuid.uuid4()),
            "state": "BLOCKED" if analysis["decision"] == "BLOCKED" else "PREPARED",
            "created_at": _iso(created),
            "expires_at": _iso(created + timedelta(seconds=self.ttl_seconds)),
            **critical,
            "decision": analysis["decision"],
            "blockers": analysis["blockers"],
            "estimate": analysis["estimate"],
            "job_dir": str(analysis["job_dir"]),
            "confirmation_scope": "chapter",
            "remote_request_sent": False,
        }
        plan["plan_digest"] = _plan_digest(plan)
        self.store.save(plan)
        return plan

    def _validate_prepared_plan(self, plan_id: str, plan_digest: str) -> tuple[dict[str, Any], dict[str, Any]]:
        plan = self.store.load(plan_id)
        if plan.get("schema_version") != SCHEMA_VERSION or plan.get("state") not in PLAN_STATES:
            raise YandexChapterPlanError("Chapter plan schema is invalid.", category="invalid_plan")
        if plan.get("plan_digest") != plan_digest:
            raise YandexChapterPlanError("Chapter plan digest does not match.", category="plan_digest_mismatch")
        if _plan_digest(plan) != plan_digest:
            raise YandexChapterPlanError("Persisted chapter plan immutable fields were modified.", category="plan_integrity")
        if plan.get("state") != "PREPARED":
            raise YandexChapterPlanError("Chapter plan has already been consumed or is blocked.", category="plan_not_prepared")
        if self._now().astimezone(timezone.utc) >= _parse_time(str(plan.get("expires_at"))):
            plan["state"] = "EXPIRED"
            self.store.save(plan)
            raise YandexChapterPlanError("Chapter plan has expired.", category="plan_expired")

        analysis = self._analyze(
            book_id=str(plan["book_id"]),
            job_id=str(plan["job_id"]),
            profile_id=str(plan["profile_id"]),
        )
        if analysis["decision"] != plan.get("decision") or analysis["blockers"]:
            raise YandexChapterPlanError("Chapter execution facts are no longer eligible.", category="execution_facts_changed")
        current = dict(plan)
        current.update(analysis["critical"])
        current["decision"] = analysis["decision"]
        current["blockers"] = analysis["blockers"]
        current["estimate"] = analysis["estimate"]
        current["job_dir"] = str(analysis["job_dir"])
        if _plan_digest(current) != plan_digest:
            raise YandexChapterPlanError("Chapter execution facts changed after confirmation plan.", category="execution_facts_changed")
        return plan, analysis

    def revalidate(self, *, plan_id: str, plan_digest: str) -> dict[str, Any]:
        plan, _ = self._validate_prepared_plan(plan_id, plan_digest)
        return {
            "plan_id": plan_id,
            "plan_digest": plan_digest,
            "decision": plan["decision"],
            "max_network_requests": plan["max_network_requests"],
            "chapter_production_identity": plan["chapter_production_identity"],
            "remote_request_sent": False,
        }

    def execute(self, *, plan_id: str, plan_digest: str) -> dict[str, Any]:
        """Consume one confirmed plan and run at most its frozen request cap.

        The native/bridge layer is responsible for obtaining explicit chapter
        confirmation before calling this method. This method itself is fail-closed
        and one-shot, and never retries automatically.
        """
        with self.store.locked(plan_id):
            plan, analysis = self._validate_prepared_plan(plan_id, plan_digest)
            if plan.get("decision") not in {"READY_FOR_CONFIRMATION", "CACHE_ONLY"}:
                raise YandexChapterPlanError("Chapter plan is not executable.", category="plan_not_executable")
            cap = int(plan.get("max_network_requests") or 0)
            if cap < 0:
                raise YandexChapterPlanError("Chapter request cap is invalid.", category="invalid_plan")
            plan["state"] = "CONSUMING"
            plan["consuming_at"] = _iso(self._now())
            self.store.save(plan)

        request_slots = 0
        network_requests = 0
        original_request = getattr(self.backend, "_request", None)
        if not callable(original_request):
            with self.store.locked(plan_id):
                final_plan = self.store.load(plan_id)
                final_plan["state"] = "CONSUMED"
                final_plan["consumed_at"] = _iso(self._now())
                final_plan["request_slots"] = 0
                final_plan["network_requests"] = 0
                final_plan["remote_request_sent"] = False
                self.store.save(final_plan)
            raise YandexChapterPlanError("Yandex backend request hook is unavailable.", category="backend_contract")

        def capped_request(text: str, request_id: str):
            nonlocal request_slots, network_requests
            if request_slots >= cap:
                try:
                    from backends.yandex_speechkit import YandexSpeechKitError
                except ImportError:
                    raise YandexChapterPlanError("Confirmed chapter request cap was exhausted.", category="request_cap_exceeded")
                raise YandexSpeechKitError(
                    "Confirmed chapter request cap was exhausted before network.",
                    category="request_cap_exceeded",
                    retryable=False,
                    request_id=request_id,
                )
            request_slots += 1
            try:
                result = original_request(text, request_id)
            except Exception as error:
                category = getattr(error, "category", None)
                if category not in {"credential", "config", "input", "segment_limit"}:
                    network_requests += 1
                raise
            network_requests += 1
            return result

        try:
            setattr(self.backend, "_request", capped_request)
            joined = self.backend.run_text_job(
                analysis["text"],
                analysis["job_dir"],
                job_id=str(plan["job_id"]),
                pricing=self.pricing,
                scope="chapter",
            )
            if request_slots > cap or network_requests > cap:
                raise YandexChapterPlanError("Yandex chapter exceeded its confirmed request cap.", category="request_cap_exceeded")
            result = {
                "plan_id": plan_id,
                "plan_digest": plan_digest,
                "state": "CONSUMED",
                "decision": plan["decision"],
                "chapter_production_identity": plan["chapter_production_identity"],
                "output_path": str(joined),
                "request_slots": request_slots,
                "network_requests": network_requests,
                "max_network_requests": cap,
                "remote_request_sent": network_requests > 0,
            }
        finally:
            setattr(self.backend, "_request", original_request)
            with self.store.locked(plan_id):
                final_plan = self.store.load(plan_id)
                final_plan["state"] = "CONSUMED"
                final_plan["consumed_at"] = _iso(self._now())
                final_plan["request_slots"] = request_slots
                final_plan["network_requests"] = network_requests
                final_plan["remote_request_sent"] = network_requests > 0
                self.store.save(final_plan)
        return result
