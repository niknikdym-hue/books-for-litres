"""One-time, immutable authorization plans for paid OpenAI TTS segments."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from backends.common import inspect_pcm_wav
from backends.openai_tts import (
    OpenAITTSBackend,
    OpenAITTSError,
    load_approved_profile,
    make_fingerprint,
    normalize_input_text,
    text_sha256,
)
from cloud_billing import BillingLedger, CloudBillingService, decimal_text
from book_library import BookLibrary, BookLibraryError
from production_authority_lock import production_authority_lock


SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 600
PLAN_STATES = {"PREPARED", "CONSUMING", "CONSUMED", "EXPIRED", "BLOCKED"}
PLAN_DECISIONS = {"READY_FOR_CONFIRMATION", "CACHE_ONLY", "BLOCKED"}
MAX_NETWORK_REQUESTS = 1


class PaidRunError(RuntimeError):
    def __init__(self, message: str, *, category: str = "paid_run_blocked") -> None:
        super().__init__(message)
        self.category = category


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PaidRunError("Paid run timestamp has no timezone.", category="invalid_plan")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _valid_wav(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        inspect_pcm_wav(path)
    except Exception:
        return False
    return True


class PaidRunPlanStore:
    """Atomic JSON storage with a per-plan lock for one-time consumption."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, plan_id: str) -> Path:
        if not plan_id or any(character not in "0123456789abcdef-" for character in plan_id):
            raise PaidRunError("Invalid paid run plan ID.", category="invalid_plan")
        return self.root / f"{plan_id}.json"

    def load(self, plan_id: str) -> dict[str, Any]:
        path = self.path(plan_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PaidRunError("Paid run plan was not found or is unreadable.", category="plan_not_found") from error
        if not isinstance(value, dict):
            raise PaidRunError("Paid run plan is invalid.", category="invalid_plan")
        return value

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


class PaidRunService:
    def __init__(
        self,
        *,
        backend: OpenAITTSBackend,
        pricing: Any,
        billing: CloudBillingService,
        books_dir: Path,
        plans_dir: Path,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.backend = backend
        self.pricing = pricing
        self.billing = billing
        self.books_dir = Path(books_dir)
        self.workspace_root = self.books_dir.resolve().parent
        self.book_library = BookLibrary(self.books_dir)
        self.store = PaidRunPlanStore(plans_dir)
        self.ttl_seconds = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))
        if ttl_seconds <= 0:
            raise ValueError("Paid run plan TTL must be positive.")

    def job_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": summary["id"],
                "title": summary["title"],
                "author": summary["author"],
                "jobs": summary["jobs"],
            }
            for summary in self.book_library.list_book_summaries()
        ]

    def _load_source(self, book_name: str, job_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], str]:
        try:
            path = self.book_library.resolve_book_profile(book_name)
            book = self.book_library.load_book_for_execution(book_name)
        except BookLibraryError as error:
            raise PaidRunError("Book profile is invalid.", category="invalid_book_job") from error
        jobs = book.get("jobs") if isinstance(book, dict) else None
        job = jobs.get(job_id) if isinstance(jobs, dict) else None
        source_segments = job.get("segments") if isinstance(job, dict) else None
        if not isinstance(source_segments, list) or not source_segments:
            raise PaidRunError("Prepared job not found or empty.", category="invalid_book_job")
        texts: list[str] = []
        for segment in source_segments:
            value = segment.get("text") if isinstance(segment, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise PaidRunError("Prepared job contains invalid text.", category="invalid_book_job")
            texts.append(value.strip())
        return path, book, job, "\n\n".join(texts)

    def _job_dir(
        self,
        book: Mapping[str, Any],
        job_id: str,
        profile_id: str,
        *,
        canonical_book_slug: str | None = None,
    ) -> Path:
        slug = canonical_book_slug or str(book.get("slug") or "book")
        return self.backend.config.jobs_root / slug / job_id / "openai" / profile_id

    def _manifest_entries(self, job_dir: Path, *, job_id: str, profile_id: str) -> tuple[dict[str, Any], list[str]]:
        path = job_dir / "MANIFEST.json"
        if not path.exists():
            return {}, []
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}, ["manifest_mismatch"]
        if not isinstance(manifest, dict) or (
            manifest.get("schema_version") != 1
            or manifest.get("provider") != "openai"
            or manifest.get("job_id") != job_id
            or manifest.get("profile_id") != profile_id
            or not isinstance(manifest.get("segments"), dict)
        ):
            return {}, ["manifest_mismatch"]
        return dict(manifest["segments"]), []

    def _analyze(self, book_name: str, job_id: str, profile_id: str) -> dict[str, Any]:
        source_path, book, job, text = self._load_source(book_name, job_id)
        profile = load_approved_profile(profile_id)
        segments = self.backend.segment(text)
        if not segments:
            raise PaidRunError("Prepared job produces no TTS segments.", category="invalid_book_job")
        canonical_book_slug = source_path.stem
        job_dir = self._job_dir(
            book,
            job_id,
            profile_id,
            canonical_book_slug=canonical_book_slug,
        )
        entries, blockers = self._manifest_entries(job_dir, job_id=job_id, profile_id=profile_id)
        counts = {"succeeded": 0, "cached": 0, "pending": 0, "ambiguous": 0, "failed": 0}
        eligible: list[tuple[Any, str]] = []

        for segment in segments:
            normalized = normalize_input_text(segment.text)
            fingerprint = make_fingerprint(normalized, profile)
            entry = entries.get(segment.segment_id)
            if entry is not None and (
                not isinstance(entry, dict)
                or entry.get("fingerprint") != fingerprint
                or entry.get("text_sha256") != text_sha256(normalized)
            ):
                blockers.append("source_hash_mismatch")
                continue
            entry = entry if isinstance(entry, dict) else {}
            output_value = entry.get("output_path")
            output_path = Path(output_value) if isinstance(output_value, str) else None
            cache_path = self.backend.config.cache_root / f"{fingerprint}.wav"
            cache_valid = _valid_wav(cache_path)
            output_valid = _valid_wav(output_path)
            state = str(entry.get("state") or "PENDING")

            if state == "AMBIGUOUS":
                counts["ambiguous"] += 1
                blockers.append("ambiguous_segment_requires_resolution")
                continue
            if state == "FAILED":
                counts["failed"] += 1
                blockers.append("failed_segment_requires_resolution")
                continue
            if cache_valid:
                counts["cached"] += 1
                if state == "SUCCEEDED" or output_valid:
                    counts["succeeded"] += 1
                continue
            if state == "SUCCEEDED" and output_valid:
                counts["succeeded"] += 1
                continue
            if state == "IN_FLIGHT":
                if output_valid:
                    counts["succeeded"] += 1
                else:
                    counts["ambiguous"] += 1
                    blockers.append("ambiguous_segment_requires_resolution")
                continue
            if state != "PENDING":
                blockers.append("manifest_mismatch")
                continue
            counts["pending"] += 1
            eligible.append((segment, fingerprint))

        pricing_stale = self.pricing.is_stale()
        hard_limit = self.billing.settings.openai_hard_limit_usd
        if pricing_stale and eligible:
            blockers.append("stale_pricing")
        if hard_limit is None:
            blockers.append("missing_hard_limit")
        elif hard_limit <= Decimal("0"):
            blockers.append("hard_limit_not_positive")
        credential_available = self.backend.credential_available() if eligible else False
        if eligible and not credential_available:
            blockers.append("missing_credential")
        if len(eligible) > counts["pending"]:
            blockers.append("execution_segment_not_unique")

        blockers = list(dict.fromkeys(blockers))
        selected = eligible[0] if eligible and not blockers else None
        decision = "BLOCKED" if blockers else (
            "READY_FOR_CONFIRMATION" if selected is not None else "CACHE_ONLY"
        )
        billing_snapshot = self.billing.status(
            "openai",
            current_job_estimate=None,
            current_job_estimate_source="unavailable",
            hard_limit=hard_limit,
            paid_execution_enabled=False,
        )
        selected_segment = selected[0] if selected else None
        selected_fingerprint = selected[1] if selected else None
        instruction_hash = text_sha256(str(profile["instructions"]))
        critical = {
            "provider": "openai",
            "book_id": canonical_book_slug,
            "book_file": source_path.name,
            "book_source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "job_id": job_id,
            "job_text_sha256": text_sha256(normalize_input_text(text)),
            "profile_id": profile_id,
            "model": profile["model"],
            "voice": profile["voice"],
            "response_format": profile["response_format"],
            "instructions_sha256": instruction_hash,
            "selected_segment_id": selected_segment.segment_id if selected_segment else None,
            "selected_segment_text_sha256": (
                text_sha256(normalize_input_text(selected_segment.text)) if selected_segment else None
            ),
            "selected_segment_fingerprint": selected_fingerprint,
            "hard_limit": decimal_text(hard_limit),
            "currency": "USD",
            "pricing_identity": {
                "model": self.pricing.model,
                "verified_at": self.pricing.verified_at.isoformat(),
                "source": self.pricing.source_url,
                "text_input_per_million_tokens": decimal_text(self.pricing.text_input_per_million_tokens),
                "audio_output_per_million_tokens": decimal_text(self.pricing.audio_output_per_million_tokens),
            },
            "max_network_requests": MAX_NETWORK_REQUESTS,
        }
        return {
            "critical": critical,
            "book": book,
            "job": job,
            "text": text,
            "job_dir": job_dir,
            "profile": profile,
            "selected_segment": selected_segment,
            "counts": counts,
            "pricing_stale": pricing_stale,
            "credential_available": credential_available,
            "billing": billing_snapshot,
            "warnings": list(dict.fromkeys([
                *billing_snapshot.get("warnings", []),
                "exact_future_audio_cost_unavailable",
            ])),
            "blockers": blockers,
            "decision": decision,
        }

    def prepare(self, *, book_name: str, job_id: str, profile_id: str) -> dict[str, Any]:
        analysis = self._analyze(book_name, job_id, profile_id)
        created = self._now().astimezone(timezone.utc)
        critical = analysis["critical"]
        selected = analysis["selected_segment"]
        counts = analysis["counts"]
        plan = {
            "schema_version": SCHEMA_VERSION,
            "plan_id": str(uuid.uuid4()),
            "plan_digest": _canonical_hash(critical),
            "state": "BLOCKED" if analysis["decision"] == "BLOCKED" else "PREPARED",
            "created_at": _iso(created),
            "expires_at": _iso(created + timedelta(seconds=self.ttl_seconds)),
            "provider": "openai",
            "book_id": critical["book_id"],
            "book_file": critical["book_file"],
            "book_title": str(analysis["book"].get("title") or critical["book_id"]),
            "book_source_sha256": critical["book_source_sha256"],
            "job_id": job_id,
            "job_label": str(analysis["job"].get("label") or job_id),
            "profile_id": profile_id,
            "model": critical["model"],
            "voice": critical["voice"],
            "response_format": critical["response_format"],
            "instructions_sha256": critical["instructions_sha256"],
            "job_text_sha256": critical["job_text_sha256"],
            "selected_segment_id": critical["selected_segment_id"],
            "selected_segment_text_sha256": critical["selected_segment_text_sha256"],
            "selected_segment_fingerprint": critical["selected_segment_fingerprint"],
            "selected_segment_characters": len(selected.text) if selected else 0,
            "selected_segment_utf8_bytes": len(selected.text.encode("utf-8")) if selected else 0,
            "selected_segment_number": (
                next((index for index, item in enumerate(self.backend.segment(analysis["text"]), 1)
                      if selected and item.segment_id == selected.segment_id), None)
            ),
            "total_segments": len(self.backend.segment(analysis["text"])),
            "succeeded_segments": counts["succeeded"],
            "cached_segments": counts["cached"],
            "pending_segments": counts["pending"],
            "ambiguous_segments": counts["ambiguous"],
            "failed_segments": counts["failed"],
            "network_miss_count_for_this_plan": 1 if selected else 0,
            "max_network_requests": MAX_NETWORK_REQUESTS,
            "hard_limit": critical["hard_limit"],
            "currency": "USD",
            "pricing_verified_at": self.pricing.verified_at.isoformat(),
            "pricing_stale": analysis["pricing_stale"],
            "credential_available": analysis["credential_available"],
            "cost_estimate": None,
            "cost_estimate_source": "unavailable",
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
            if plan.get("schema_version") != SCHEMA_VERSION or plan.get("state") not in PLAN_STATES:
                raise PaidRunError("Paid run plan schema is invalid.", category="invalid_plan")
            if plan.get("plan_digest") != plan_digest:
                raise PaidRunError("Paid run plan digest does not match.", category="plan_digest_mismatch")
            if plan.get("state") != "PREPARED":
                raise PaidRunError("Paid run plan has already been consumed or is blocked.", category="plan_not_prepared")
            if self._now().astimezone(timezone.utc) >= _parse_time(str(plan.get("expires_at"))):
                plan["state"] = "EXPIRED"
                self.store.save(plan)
                raise PaidRunError("Paid run plan has expired.", category="plan_expired")

            analysis = self._analyze(str(plan["book_file"]), str(plan["job_id"]), str(plan["profile_id"]))
            if analysis["decision"] != plan.get("decision") or analysis["blockers"]:
                raise PaidRunError("Paid run execution facts are no longer eligible.", category="execution_facts_changed")
            if _canonical_hash(analysis["critical"]) != plan_digest:
                raise PaidRunError("Paid run execution facts changed after confirmation.", category="execution_facts_changed")
            if plan.get("max_network_requests") != MAX_NETWORK_REQUESTS:
                raise PaidRunError("Paid run request cap is invalid.", category="invalid_plan")
            plan["state"] = "CONSUMING"
            plan["consuming_at"] = _iso(self._now())
            self.store.save(plan)

        network_requests = 0
        try:
            def one_request_opener(*args: Any, **kwargs: Any) -> Any:
                nonlocal network_requests
                if network_requests >= MAX_NETWORK_REQUESTS:
                    raise PaidRunError("Paid run request cap was exhausted.", category="request_cap_exceeded")
                network_requests += 1
                return self.backend._opener(*args, **kwargs)

            temporary_backend = OpenAITTSBackend(
                replace(self.backend.config, paid_execution_enabled=True),
                credential_loader=self.backend._credential_loader,
                opener=one_request_opener,
                billing_ledger=self.backend._billing_ledger,
            )
            with production_authority_lock(
                self.workspace_root,
                provider="openai",
                book_slug=str(plan["book_id"]),
                job_id=str(plan["job_id"]),
                profile_id=str(plan["profile_id"]),
                exclusive=True,
            ):
                manifest_path, result = temporary_backend.run_approved_segment(
                    analysis["text"],
                    analysis["job_dir"],
                    job_id=str(plan["job_id"]),
                    profile_id=str(plan["profile_id"]),
                    pricing=self.pricing,
                    selected_segment_id=plan.get("selected_segment_id"),
                )
            if int(result["network_requests"]) != network_requests or network_requests > MAX_NETWORK_REQUESTS:
                raise PaidRunError("Paid run exceeded its request cap.", category="request_cap_exceeded")
            return_value = {
                "plan_id": plan_id,
                "plan_digest": plan_digest,
                "state": "CONSUMED",
                "decision": plan["decision"],
                "manifest": str(manifest_path),
                **result,
                "remote_request_sent": network_requests == 1,
            }
        finally:
            with self.store.locked(plan_id):
                final_plan = self.store.load(plan_id)
                final_plan["state"] = "CONSUMED"
                final_plan["consumed_at"] = _iso(self._now())
                final_plan["network_requests"] = network_requests
                final_plan["remote_request_sent"] = network_requests == 1
                self.store.save(final_plan)
        return return_value
