"""Owner-gated, one-request Yandex executor for the Dilon Voices opening credit.

The executor is deliberately downstream of the immutable PREPARE plan. It
revalidates the exact plan, price, frozen voice, route and request cap before a
future provider request. A provider result can only become an immutable
PENDING_HUMAN_REVIEW candidate; this module has no approval path.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

from audio_qa_review import sha256_file
from backends.common import atomic_write_json, inspect_pcm_wav, utc_now_iso
from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_speechkit import (
    DEFAULT_ENDPOINT,
    ENGINE_ID,
    YandexSpeechKitBackend,
    YandexSpeechKitError,
    make_fingerprint,
)
from book_library import BookLibraryError, normalize_slug
from dilon_identity import OPENING_CREDIT_TEXT
from dilon_opening_credit_plan_store import OpeningCreditPlanStore, OpeningCreditPlanStoreError
from dilon_opening_credit_prepare import EXPECTED_PROFILE, OpeningCreditPrepareError, prepare_opening_credit_plan
from dilon_opening_credit_review import OpeningCreditReviewError, prepare_review_candidate, review_root
from media_tools import resolve_ffmpeg
from production_authority_lock import production_authority_lock
from voice_library import DEFAULT_REGISTRY_PATH

SCHEMA_VERSION = 1
TARGET_RATE = 48_000
_NO_REQUEST_CATEGORIES = {
    "credentials",
    "credentials_duplicate",
    "platform",
    "config",
    "input",
    "segment_limit",
    "pricing_gate",
    "pricing",
    "manifest",
}


class OpeningCreditExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider_requests: int = 0,
        remote_request_sent: bool = False,
        paid_execution: bool = False,
        billing_changed: bool | None = False,
        retry_allowed: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider_requests = provider_requests
        self.remote_request_sent = remote_request_sent
        self.paid_execution = paid_execution
        self.billing_changed = billing_changed
        self.retry_allowed = retry_allowed


def _slug(value: str) -> str:
    try:
        return normalize_slug(value)
    except BookLibraryError as error:
        raise OpeningCreditExecutionError("invalid_book_slug", "Некорректный book_slug.") from error


def _id(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise OpeningCreditExecutionError("invalid_identity", f"Некорректный {label}.")
    return value


def _root(path: Path) -> Path:
    requested = Path(path).expanduser().absolute()
    if requested.is_symlink():
        raise OpeningCreditExecutionError("symlink_workspace_root", "Workspace root является symlink.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise OpeningCreditExecutionError("missing_workspace", "Workspace root не найден.") from error


def _safe_dir(path: Path, *, root: Path) -> Path:
    boundary = _root(root)
    candidate = Path(path).expanduser().absolute()
    try:
        parts = candidate.relative_to(boundary).parts
    except ValueError as error:
        raise OpeningCreditExecutionError("path_escape", "Execution path находится вне workspace.") from error
    current = boundary
    for part in parts:
        current /= part
        if current.exists() or current.is_symlink():
            meta = current.lstat()
            if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
                raise OpeningCreditExecutionError("invalid_execution_path", "Execution path небезопасен.")
        else:
            current.mkdir()
    return candidate


def _regular(path: Path, *, root: Path, label: str) -> Path:
    boundary = _root(root)
    candidate = Path(path).expanduser().absolute()
    try:
        parts = candidate.relative_to(boundary).parts
    except ValueError as error:
        raise OpeningCreditExecutionError("path_escape", f"{label} находится вне workspace.") from error
    current = boundary
    for part in parts:
        current /= part
        try:
            meta = current.lstat()
        except OSError as error:
            raise OpeningCreditExecutionError("missing_execution_artifact", f"{label} не найден.") from error
        if stat.S_ISLNK(meta.st_mode):
            raise OpeningCreditExecutionError("symlink_execution_artifact", f"{label} содержит symlink.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise OpeningCreditExecutionError("invalid_execution_artifact", f"{label} должен быть обычным file.")
    return resolved


def _json(path: Path, *, root: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(_regular(path, root=root, label=label).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise OpeningCreditExecutionError("invalid_execution_json", f"{label} повреждён.") from error
    if not isinstance(payload, dict):
        raise OpeningCreditExecutionError("invalid_execution_json", f"{label} имеет неверную структуру.")
    return payload


def normalize_review_wav(workspace_root: Path, source: Path, destination: Path) -> Path:
    """Preserve provider bytes and create deterministic PCM16 mono 48 kHz review audio."""
    root = _root(workspace_root)
    source = _regular(source, root=root, label="Provider opening-credit WAV")
    source_sha = sha256_file(source)
    facts = inspect_pcm_wav(source)
    if facts.channels != 1 or facts.sample_width_bytes != 2:
        raise OpeningCreditExecutionError("provider_wav_unsupported", "Provider WAV должен быть mono PCM16.")
    target = Path(destination).expanduser().absolute()
    _safe_dir(target.parent, root=root)
    if target.is_symlink():
        raise OpeningCreditExecutionError("symlink_review_output", "Review output является symlink.")
    fd, temp_name = tempfile.mkstemp(prefix=".review-", suffix=".wav", dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    try:
        if facts.sample_rate_hz == TARGET_RATE:
            shutil.copyfile(source, temp)
        else:
            ffmpeg = resolve_ffmpeg(root)
            if not ffmpeg.available or ffmpeg.path is None:
                raise OpeningCreditExecutionError("missing_ffmpeg", "Для нормализации opening credit требуется FFmpeg.")
            result = subprocess.run(
                [
                    str(ffmpeg.path),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-map_metadata",
                    "-1",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(TARGET_RATE),
                    "-c:a",
                    "pcm_s16le",
                    "-fflags",
                    "+bitexact",
                    "-flags:a",
                    "+bitexact",
                    str(temp),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                raise OpeningCreditExecutionError("ffmpeg_failed", "FFmpeg не смог подготовить review WAV.")
        output = inspect_pcm_wav(temp)
        if (
            output.sample_rate_hz != TARGET_RATE
            or output.channels != 1
            or output.sample_width_bytes != 2
        ):
            raise OpeningCreditExecutionError("review_output_invalid", "Review WAV имеет неверный PCM contract.")
        if sha256_file(source) != source_sha:
            raise OpeningCreditExecutionError("provider_wav_changed", "Provider WAV изменился во время нормализации.")
        if target.exists():
            existing = _regular(target, root=root, label="Existing review-ready WAV")
            if (
                sha256_file(existing) != sha256_file(temp)
                or inspect_pcm_wav(existing).to_dict() != output.to_dict()
            ):
                raise OpeningCreditExecutionError(
                    "review_output_collision",
                    "Existing review WAV не совпадает с deterministic normalization текущего provider WAV.",
                )
            return existing
        os.replace(temp, target)
        return target
    finally:
        temp.unlink(missing_ok=True)


@dataclass
class OpeningCreditExternalExecutionService:
    workspace_root: Path
    plans_root: Path
    pricing: YandexPricingConfig
    backend: YandexSpeechKitBackend
    registry_path: Path = DEFAULT_REGISTRY_PATH
    normalizer: Callable[[Path, Path, Path], Path] = normalize_review_wav
    billing_transactions: Callable[[], list[dict[str, Any]]] | None = None

    def __post_init__(self) -> None:
        self.workspace_root = _root(self.workspace_root)
        self.plans_root = Path(self.plans_root).expanduser().absolute()

    @staticmethod
    def _job_id(plan: Mapping[str, Any]) -> str:
        return f"dilon-opening-credit-{str(plan['plan_id'])[:16]}"

    def _expected_joined(self, execution_dir: Path, plan: Mapping[str, Any]) -> Path:
        name = (
            f"{self._job_id(plan)}__{self.backend.profile.voice}-"
            f"{self.backend.profile.role}-{self.backend.profile.speed}.wav"
        )
        return execution_dir / name

    def _plan(self, plan_id: str, plan_digest: str, today: date | None) -> dict[str, Any]:
        try:
            stored = OpeningCreditPlanStore(self.plans_root).load(
                plan_id=plan_id,
                expected_plan_digest=plan_digest,
            )
            current = prepare_opening_credit_plan(
                pricing=self.pricing,
                today=today,
                registry_path=self.registry_path,
            )
        except (OpeningCreditPlanStoreError, OpeningCreditPrepareError, YandexSpeechKitError) as error:
            code = getattr(error, "code", None) or getattr(error, "category", "plan_revalidation_failed")
            raise OpeningCreditExecutionError(
                str(code), "Opening-credit PREPARE authority не подтверждена."
            ) from error
        if (
            current.get("state") != "READY_FOR_OWNER_AUTHORIZATION"
            or current.get("plan_id") != stored.get("plan_id")
            or stored.get("plan_id") != plan_id
            or stored.get("plan_digest") != plan_digest
            or stored.get("maximum_provider_requests") != 1
            or stored.get("text") != OPENING_CREDIT_TEXT
            or stored.get("profile") != EXPECTED_PROFILE
        ):
            raise OpeningCreditExecutionError(
                "plan_stale_reprepare_required",
                "Opening-credit plan устарел; нужен новый PREPARE и новое owner authorization.",
            )
        return stored

    def _backend(self, plan: Mapping[str, Any]) -> None:
        try:
            status = self.backend.validate_config(resolve_credentials=False)
            segments = self.backend.segment(OPENING_CREDIT_TEXT)
        except YandexSpeechKitError as error:
            raise OpeningCreditExecutionError(
                "backend_revalidation_failed", "Yandex authority не подтверждена."
            ) from error
        if (
            status.get("ok") is not True
            or status.get("endpoint") != DEFAULT_ENDPOINT
            or self.backend.profile.voice != EXPECTED_PROFILE["voice"]
            or self.backend.profile.role != EXPECTED_PROFILE["role"]
            or self.backend.profile.speed != EXPECTED_PROFILE["speed"]
            or len(segments) != 1
        ):
            raise OpeningCreditExecutionError(
                "backend_authority_drift", "Yandex route/profile/request-cap drift."
            )
        segment = segments[0]
        actual = {
            "segment_id": segment.segment_id,
            "text": segment.text,
            "pause_after_ms": segment.pause_after_ms,
            "paragraph_index": segment.paragraph_index,
        }
        if (
            actual != plan.get("segment")
            or make_fingerprint(segment.text, self.backend.profile) != plan.get("synthesis_fingerprint")
        ):
            raise OpeningCreditExecutionError(
                "backend_fingerprint_drift", "Yandex segmentation/fingerprint drift."
            )

    def _execution_dir(self, slug: str, job: str, plan_id: str) -> Path:
        base = review_root(
            workspace_root=self.workspace_root,
            book_slug=slug,
            job_id=job,
        )
        return _safe_dir(base / "executions" / plan_id, root=self.workspace_root)

    def _authority(
        self,
        plan: Mapping[str, Any],
        plan_digest: str,
        slug: str,
        job: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "plan_digest": plan_digest,
            "book_slug": slug,
            "job_id": job,
            "text_sha256": plan["text_sha256"],
            "profile": dict(plan["profile"]),
            "synthesis_fingerprint": plan["synthesis_fingerprint"],
            "maximum_provider_requests": 1,
            "request_routing": self.backend.request_routing_identity(),
        }

    def _write_authority(self, path: Path, authority: Mapping[str, Any]) -> None:
        if path.is_symlink():
            raise OpeningCreditExecutionError(
                "symlink_execution_authority", "AUTHORITY.json является symlink."
            )
        if path.exists():
            if _json(path, root=self.workspace_root, label="Execution AUTHORITY.json") != authority:
                raise OpeningCreditExecutionError(
                    "execution_authority_collision", "Execution authority collision."
                )
        else:
            atomic_write_json(path, dict(authority))

    def _entry(
        self,
        execution_dir: Path,
        plan: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        path = execution_dir / "MANIFEST.json"
        if not path.exists() and not path.is_symlink():
            return None, None
        manifest = _json(path, root=self.workspace_root, label="Yandex MANIFEST.json")
        entries = manifest.get("segments")
        segment = plan["segment"]
        expected_segment_id = segment["segment_id"]
        if (
            manifest.get("schema_version") != 1
            or manifest.get("engine") != ENGINE_ID
            or manifest.get("job_id") != self._job_id(plan)
            or manifest.get("profile") != asdict(self.backend.profile)
            or manifest.get("segmentation") != self.backend.manifest_segmentation()
            or manifest.get("request_routing") != self.backend.request_routing_identity()
            or manifest.get("estimated_billing_units") != plan.get("pricing", {}).get("total_billing_units")
            or not isinstance(entries, dict)
            or set(entries) != {expected_segment_id}
        ):
            raise OpeningCreditExecutionError(
                "execution_manifest_mismatch", "Yandex manifest authority mismatch."
            )
        entry = entries.get(expected_segment_id)
        if not isinstance(entry, dict) or (
            entry.get("text") != segment["text"]
            or entry.get("pause_after_ms") != segment["pause_after_ms"]
            or entry.get("paragraph_index") != segment["paragraph_index"]
            or entry.get("fingerprint") != plan["synthesis_fingerprint"]
        ):
            raise OpeningCreditExecutionError(
                "execution_manifest_mismatch", "Yandex segment authority mismatch."
            )
        return manifest, entry

    def _billing_evidence_valid(
        self,
        *,
        entry: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> bool:
        transaction_id = entry.get("billing_transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id:
            return False
        if self.billing_transactions is None:
            return False
        try:
            transactions = self.billing_transactions()
        except Exception:
            return False
        matches = [
            item
            for item in transactions
            if isinstance(item, dict) and item.get("transaction_id") == transaction_id
        ]
        if len(matches) != 1:
            return False
        transaction = matches[0]
        segment = plan["segment"]
        return bool(
            transaction.get("provider") == "yandex"
            and transaction.get("job_id") == self._job_id(plan)
            and transaction.get("segment_id") == segment["segment_id"]
            and transaction.get("request_id") == entry.get("request_id")
            and transaction.get("profile_id") == EXPECTED_PROFILE["profile_id"]
            and transaction.get("fingerprint") == plan["synthesis_fingerprint"]
            and transaction.get("currency") == plan.get("pricing", {}).get("currency")
            and transaction.get("cost_source") in {"local_actual", "provider_reported"}
            and transaction.get("actual_cost") is not None
        )

    def _existing(
        self,
        execution_dir: Path,
        plan: Mapping[str, Any],
    ) -> tuple[Path, int, bool] | None:
        manifest, entry = self._entry(execution_dir, plan)
        if entry is None:
            return None
        status = entry.get("status")
        if status == "AMBIGUOUS":
            raise OpeningCreditExecutionError(
                "prior_provider_result_requires_resolution",
                "Prior request ambiguous; retry forbidden.",
            )
        if status == "FAILED":
            error = entry.get("error")
            category = error.get("category") if isinstance(error, Mapping) else None
            sent = bool(entry.get("request_id")) and category not in _NO_REQUEST_CATEGORIES
            if sent:
                raise OpeningCreditExecutionError(
                    "prior_provider_result_requires_resolution",
                    "Prior sent request FAILED; retry forbidden.",
                )
            return None
        if status == "IN_FLIGHT":
            recoverable = None
            if hasattr(self.backend, "recoverable_inflight_source"):
                recoverable = self.backend.recoverable_inflight_source(
                    execution_dir,
                    segment_id=plan["segment"]["segment_id"],
                    fingerprint=plan["synthesis_fingerprint"],
                )
            if recoverable is None:
                raise OpeningCreditExecutionError(
                    "prior_provider_result_requires_resolution",
                    "Prior request remained IN_FLIGHT without a recoverable local artifact; retry forbidden.",
                )
            return None
        if status not in {"DONE", "CACHED"} or not isinstance(manifest, dict):
            raise OpeningCreditExecutionError(
                "execution_manifest_mismatch", "Unknown provider execution state."
            )
        if manifest.get("status") != "DONE":
            raise OpeningCreditExecutionError(
                "execution_manifest_mismatch", "Completed Yandex manifest is not DONE."
            )
        expected_joined = self._expected_joined(execution_dir, plan)
        if manifest.get("joined_wav") != expected_joined.name:
            raise OpeningCreditExecutionError(
                "execution_manifest_mismatch", "Yandex joined_wav is not the canonical execution output."
            )
        joined = _regular(
            expected_joined,
            root=self.workspace_root,
            label="Provider opening-credit WAV",
        )
        remote = status == "DONE"
        if remote and not self._billing_evidence_valid(entry=entry, plan=plan):
            raise OpeningCreditExecutionError(
                "billing_evidence_missing", "Provider result lacks exact billing ledger evidence."
            )
        return joined, (1 if remote else 0), remote

    def _completed(
        self,
        execution_dir: Path,
        plan: Mapping[str, Any],
        joined: Path,
    ) -> tuple[Path, int, bool]:
        manifest, entry = self._entry(execution_dir, plan)
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in {"DONE", "CACHED"}
            or not isinstance(manifest, dict)
            or manifest.get("status") != "DONE"
        ):
            raise OpeningCreditExecutionError(
                "provider_result_unresolved",
                "Provider result is not DONE/CACHED.",
                provider_requests=1,
                remote_request_sent=True,
                paid_execution=True,
                billing_changed=None,
            )
        expected_joined = self._expected_joined(execution_dir, plan)
        if manifest.get("joined_wav") != expected_joined.name:
            raise OpeningCreditExecutionError(
                "provider_output_mismatch",
                "Provider manifest does not point to the canonical joined WAV.",
                provider_requests=1,
                remote_request_sent=True,
                paid_execution=True,
                billing_changed=None,
            )
        output = _regular(
            Path(joined),
            root=self.workspace_root,
            label="Provider opening-credit WAV",
        )
        if output != expected_joined.resolve(strict=True):
            raise OpeningCreditExecutionError(
                "provider_output_mismatch",
                "Provider output is not the canonical execution WAV.",
                provider_requests=1,
                remote_request_sent=True,
                paid_execution=True,
                billing_changed=None,
            )
        remote = entry.get("status") == "DONE"
        if remote and not self._billing_evidence_valid(entry=entry, plan=plan):
            raise OpeningCreditExecutionError(
                "billing_evidence_missing",
                "Yandex request lacks exact billing ledger evidence.",
                provider_requests=1,
                remote_request_sent=True,
                paid_execution=True,
                billing_changed=None,
            )
        return output, (1 if remote else 0), remote

    def execute_authorized(
        self,
        *,
        book_slug: str,
        job_id: str,
        plan_id: str,
        plan_digest: str,
        owner_authorized: bool,
        today: date | None = None,
    ) -> dict[str, Any]:
        if owner_authorized is not True:
            raise OpeningCreditExecutionError(
                "owner_authorization_required", "Explicit owner authorization required."
            )
        slug, job = _slug(book_slug), _id(job_id, "job_id")
        plan = self._plan(plan_id, plan_digest, today)
        self._backend(plan)
        execution_dir = self._execution_dir(slug, job, plan_id)
        authority_path = execution_dir / "AUTHORITY.json"
        self._write_authority(
            authority_path,
            self._authority(plan, plan_digest, slug, job),
        )
        with production_authority_lock(
            self.workspace_root,
            provider="yandex",
            book_slug=slug,
            job_id=job,
            profile_id=EXPECTED_PROFILE["profile_id"],
            exclusive=True,
        ):
            existing = self._existing(execution_dir, plan)
            current_requests = 0
            current_remote = False
            if existing is None:
                try:
                    joined = self.backend.run_text_job(
                        OPENING_CREDIT_TEXT,
                        execution_dir,
                        job_id=self._job_id(plan),
                        pricing=self.pricing,
                        scope="book",
                    )
                except YandexSpeechKitError as error:
                    remote = error.category not in _NO_REQUEST_CATEGORIES and error.category != "resume_ambiguous"
                    raise OpeningCreditExecutionError(
                        "provider_result_ambiguous"
                        if error.category in {"network_ambiguous", "resume_ambiguous"}
                        else "provider_execution_failed",
                        "Provider execution did not produce review-ready audio.",
                        provider_requests=1 if remote else 0,
                        remote_request_sent=remote,
                        paid_execution=remote,
                        billing_changed=None if remote else False,
                        retry_allowed=False,
                    ) from error
                provider_wav, historical_requests, historical_remote = self._completed(
                    execution_dir,
                    plan,
                    Path(joined),
                )
                current_requests, current_remote = historical_requests, historical_remote
            else:
                provider_wav, historical_requests, historical_remote = existing
            try:
                review_wav = self.normalizer(
                    self.workspace_root,
                    provider_wav,
                    execution_dir / "review-ready.wav",
                )
                candidate = prepare_review_candidate(
                    workspace_root=self.workspace_root,
                    book_slug=slug,
                    job_id=job,
                    source_wav=review_wav,
                    plan_id=plan_id,
                    plan_digest=plan_digest,
                    synthesis_fingerprint=plan["synthesis_fingerprint"],
                    profile=plan["profile"],
                    provider_requests=historical_requests,
                    remote_request_sent=historical_remote,
                    paid_execution=historical_remote,
                    billing_changed=historical_remote,
                )
            except (OpeningCreditExecutionError, OpeningCreditReviewError) as error:
                code = getattr(error, "code", "candidate_qa_failed")
                raise OpeningCreditExecutionError(
                    code,
                    "Opening-credit result did not reach immutable PENDING_HUMAN_REVIEW.",
                    provider_requests=current_requests,
                    remote_request_sent=current_remote,
                    paid_execution=current_remote,
                    billing_changed=current_remote,
                    retry_allowed=False,
                ) from error
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "PENDING_HUMAN_REVIEW",
            "decision": "HUMAN_LISTENING_REQUIRED",
            "book_slug": slug,
            "job_id": job,
            "plan_id": plan_id,
            "plan_digest": plan_digest,
            "execution_authority_path": str(authority_path),
            "provider_output_path": str(provider_wav),
            "review_ready_path": str(review_wav),
            "candidate_id": candidate["candidate_id"],
            "candidate_digest": candidate["candidate_digest"],
            "candidate_path": candidate["candidate_path"],
            "synthesis_fingerprint": plan["synthesis_fingerprint"],
            "manual_approval_published": False,
            "provider_requests": current_requests,
            "remote_request_sent": current_remote,
            "paid_execution": current_remote,
            "billing_changed": current_remote,
            "historical_provenance": {
                "provider_requests": historical_requests,
                "remote_request_sent": historical_remote,
                "paid_execution": historical_remote,
                "billing_changed": historical_remote,
            },
            "retry_allowed": False,
            "whole_book_release_ready": False,
            "finished_at": utc_now_iso(),
        }
