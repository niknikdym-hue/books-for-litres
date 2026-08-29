"""Offline human-review authority for the Dilon Voices opening credit.

This module never synthesizes audio and never contacts a provider.  It takes an
already-produced, review-ready PCM WAV, copies it into an immutable candidate
package, and keeps it PENDING_HUMAN_REVIEW until an explicit approval call binds
the exact candidate id/digest.  Only that explicit approval may publish the
CURRENT.json envelope consumed by ``dilon_identity_status``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
import wave
from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from backends.common import WavValidationError, atomic_write_json, inspect_pcm_wav, utc_now_iso
from book_library import BookLibraryError, normalize_slug
from dilon_identity import OPENING_CREDIT_TEXT


REVIEW_SCHEMA_VERSION = 1
CURRENT_SCHEMA_VERSION = 1
EXPECTED_PROFILE = {
    "profile_id": "yandex_lera",
    "provider": "yandex",
    "engine": "yandex_speechkit_v3",
    "voice": "lera",
    "role": "neutral",
    "speed": "1.04",
    "frozen": True,
}


class OpeningCreditReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OpeningCreditReviewError("invalid_identity", f"Некорректный {label}.")
    return value


def _safe_slug(value: Any) -> str:
    try:
        return normalize_slug(str(value or ""))
    except BookLibraryError as error:
        raise OpeningCreditReviewError("invalid_book_slug", "Некорректный book_slug.") from error


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise OpeningCreditReviewError("invalid_identity", f"Некорректный {label}.")
    return value


def _workspace(path: Path) -> Path:
    requested = Path(path).expanduser().absolute()
    if requested.is_symlink():
        raise OpeningCreditReviewError("symlink_workspace_root", "Workspace root является symlink.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise OpeningCreditReviewError("missing_workspace", "Workspace root не найден.") from error


def _ensure_directory(path: Path, *, root: Path) -> Path:
    boundary = _workspace(root)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise OpeningCreditReviewError("path_escape", "Review directory находится вне workspace.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        if current.exists() or current.is_symlink():
            try:
                metadata = current.lstat()
            except OSError as error:
                raise OpeningCreditReviewError("invalid_review_path", "Review path не подтверждён.") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise OpeningCreditReviewError("invalid_review_path", "Review path содержит небезопасный компонент.")
        else:
            current.mkdir()
    return candidate


def _regular(path: Path, *, root: Path, label: str) -> Path:
    boundary = _workspace(root)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise OpeningCreditReviewError("path_escape", f"{label} находится вне workspace.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise OpeningCreditReviewError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise OpeningCreditReviewError("symlink_input", f"{label} содержит symlink.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise OpeningCreditReviewError("invalid_input", f"{label} должен быть обычным file.")
    return resolved


def _wav(path: Path) -> dict[str, Any]:
    try:
        facts = inspect_pcm_wav(path).to_dict()
    except (OSError, ValueError, WavValidationError) as error:
        raise OpeningCreditReviewError("invalid_wav", "Opening-credit review WAV повреждён.") from error
    if (
        facts.get("sample_rate_hz") != 48_000
        or facts.get("channels") != 1
        or facts.get("sample_width_bytes") != 2
        or facts.get("compression_type") != "NONE"
    ):
        raise OpeningCreditReviewError(
            "unsupported_review_wav",
            "Review-ready opening credit должен быть PCM16 mono 48 kHz.",
        )
    return facts


def _clipped_samples(path: Path) -> int:
    clipped = 0
    with wave.open(str(path), "rb") as source:
        while True:
            data = source.readframes(8192)
            if not data:
                return clipped
            for index in range(0, len(data), 2):
                sample = int.from_bytes(data[index:index + 2], "little", signed=True)
                if sample in {-32768, 32767}:
                    clipped += 1


def review_root(*, workspace_root: Path, book_slug: str, job_id: str) -> Path:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    return root / "runtime" / "dilon-opening-credit" / slug / job


def prepare_review_candidate(
    *,
    workspace_root: Path,
    book_slug: str,
    job_id: str,
    source_wav: Path,
    plan_id: str,
    plan_digest: str,
    synthesis_fingerprint: str,
    profile: Mapping[str, Any],
    provider_requests: int,
    remote_request_sent: bool,
    paid_execution: bool,
    billing_changed: bool,
) -> dict[str, Any]:
    """Create an immutable review candidate and never publish CURRENT.json."""
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    plan = _sha_id(plan_id, "plan_id")
    digest = _sha_id(plan_digest, "plan_digest")
    fingerprint = _sha_id(synthesis_fingerprint, "synthesis_fingerprint")
    if any(profile.get(key) != value for key, value in EXPECTED_PROFILE.items()):
        raise OpeningCreditReviewError(
            "production_profile_drift", "Opening credit не совпадает с frozen yandex_lera authority."
        )
    if (
        not isinstance(provider_requests, int)
        or provider_requests < 0
        or not isinstance(remote_request_sent, bool)
        or not isinstance(paid_execution, bool)
        or not isinstance(billing_changed, bool)
    ):
        raise OpeningCreditReviewError("invalid_provenance", "Historical provider provenance некорректна.")

    source = _regular(source_wav, root=root, label="Opening-credit source WAV")
    facts = _wav(source)
    if _clipped_samples(source):
        raise OpeningCreditReviewError("opening_credit_clipping", "Opening-credit candidate содержит clipping.")
    source_sha = sha256_file(source)
    semantic_identity = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "book_slug": slug,
        "job_id": job,
        "text": OPENING_CREDIT_TEXT,
        "plan_id": plan,
        "plan_digest": digest,
        "synthesis_fingerprint": fingerprint,
        "profile": dict(EXPECTED_PROFILE),
        "audio_sha256": source_sha,
        "wav": facts,
    }
    candidate_id = _canonical_hash(semantic_identity)
    package_root = _ensure_directory(
        review_root(workspace_root=root, book_slug=slug, job_id=job) / "candidates" / candidate_id,
        root=root,
    )
    audio_path = package_root / "opening-credit.wav"
    manifest_path = package_root / "REVIEW.json"
    if audio_path.is_symlink() or manifest_path.is_symlink():
        raise OpeningCreditReviewError("symlink_candidate", "Review candidate path является symlink.")

    if audio_path.exists():
        existing = _regular(audio_path, root=root, label="Existing opening-credit candidate")
        if sha256_file(existing) != source_sha:
            raise OpeningCreditReviewError("candidate_collision", "Existing review audio не совпадает с candidate identity.")
    else:
        temp = package_root / f".{uuid.uuid4().hex}.wav.part"
        try:
            shutil.copyfile(source, temp)
            if sha256_file(temp) != source_sha or _wav(temp) != facts:
                raise OpeningCreditReviewError("candidate_copy_mismatch", "Copied review candidate не совпадает с source.")
            os.replace(temp, audio_path)
        finally:
            temp.unlink(missing_ok=True)

    candidate = {
        **semantic_identity,
        "candidate_id": candidate_id,
        "audio_path": str(audio_path),
        "path_identity": path_identity(audio_path),
        "automatic_status": "PASS",
        "manual_state": "PENDING_HUMAN_REVIEW",
        "provider_requests": provider_requests,
        "remote_request_sent": remote_request_sent,
        "paid_execution": paid_execution,
        "billing_changed": billing_changed,
    }
    candidate_digest = _canonical_hash(candidate)
    envelope = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "created_at": utc_now_iso(),
        "candidate": candidate,
    }
    if manifest_path.exists():
        try:
            existing_envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise OpeningCreditReviewError("candidate_manifest_invalid", "Existing REVIEW.json повреждён.") from error
        if (
            not isinstance(existing_envelope, Mapping)
            or existing_envelope.get("candidate_id") != candidate_id
            or existing_envelope.get("candidate_digest") != candidate_digest
            or existing_envelope.get("candidate") != candidate
        ):
            raise OpeningCreditReviewError("candidate_collision", "Existing REVIEW.json не совпадает с candidate authority.")
    else:
        atomic_write_json(manifest_path, envelope)

    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "state": "PENDING_HUMAN_REVIEW",
        "decision": "HUMAN_LISTENING_REQUIRED",
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "candidate_path": str(manifest_path),
        "audio_path": str(audio_path),
        "audio_sha256": source_sha,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
        "historical_provenance": {
            "provider_requests": provider_requests,
            "remote_request_sent": remote_request_sent,
            "paid_execution": paid_execution,
            "billing_changed": billing_changed,
        },
    }


def _load_candidate(
    *, workspace_root: Path, book_slug: str, job_id: str, candidate_id: str, candidate_digest: str
) -> tuple[dict[str, Any], Path]:
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    identifier = _sha_id(candidate_id, "candidate_id")
    expected_digest = _sha_id(candidate_digest, "candidate_digest")
    package_root = review_root(workspace_root=root, book_slug=slug, job_id=job) / "candidates" / identifier
    manifest_path = _regular(package_root / "REVIEW.json", root=root, label="Opening-credit REVIEW.json")
    try:
        envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise OpeningCreditReviewError("candidate_manifest_invalid", "REVIEW.json повреждён.") from error
    candidate = envelope.get("candidate") if isinstance(envelope, Mapping) else None
    if (
        not isinstance(candidate, dict)
        or envelope.get("schema_version") != REVIEW_SCHEMA_VERSION
        or envelope.get("candidate_id") != identifier
        or envelope.get("candidate_digest") != expected_digest
        or _canonical_hash(candidate) != expected_digest
        or candidate.get("candidate_id") != identifier
        or candidate.get("book_slug") != slug
        or candidate.get("job_id") != job
        or candidate.get("text") != OPENING_CREDIT_TEXT
        or candidate.get("manual_state") != "PENDING_HUMAN_REVIEW"
        or candidate.get("automatic_status") != "PASS"
    ):
        raise OpeningCreditReviewError("candidate_integrity_mismatch", "Opening-credit review authority не подтверждена.")
    audio = _regular(Path(str(candidate.get("audio_path") or "")), root=root, label="Opening-credit candidate WAV")
    if (
        audio != package_root / "opening-credit.wav"
        or candidate.get("audio_sha256") != sha256_file(audio)
        or candidate.get("path_identity") != path_identity(audio)
        or candidate.get("wav") != _wav(audio)
        or _clipped_samples(audio)
    ):
        raise OpeningCreditReviewError("candidate_integrity_mismatch", "Opening-credit candidate WAV изменён.")
    return candidate, manifest_path


def approve_review_candidate(
    *,
    workspace_root: Path,
    book_slug: str,
    job_id: str,
    candidate_id: str,
    candidate_digest: str,
    decision: str,
) -> dict[str, Any]:
    """Publish CURRENT only after an explicit exact-candidate approval decision."""
    if decision != "APPROVE":
        raise OpeningCreditReviewError(
            "explicit_approval_required", "Для публикации opening-credit authority требуется decision=APPROVE."
        )
    root = _workspace(workspace_root)
    slug = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    candidate, manifest_path = _load_candidate(
        workspace_root=root,
        book_slug=slug,
        job_id=job,
        candidate_id=candidate_id,
        candidate_digest=candidate_digest,
    )
    audio = Path(candidate["audio_path"])
    fingerprint = candidate["synthesis_fingerprint"]
    opening_credit = {
        "text": OPENING_CREDIT_TEXT,
        "audio_path": str(audio),
        "audio_sha256": candidate["audio_sha256"],
        "path_identity": candidate["path_identity"],
        "wav": candidate["wav"],
        "synthesis_fingerprint": fingerprint,
        "automatic_status": "PASS",
        "manual_state": "APPROVED",
        "reviewed_identity": {
            "audio_sha256": candidate["audio_sha256"],
            "path_identity": candidate["path_identity"],
            "synthesis_fingerprint": fingerprint,
        },
        "plan_id": candidate["plan_id"],
        "plan_digest": candidate["plan_digest"],
        "profile": candidate["profile"],
        "provider_requests": candidate["provider_requests"],
        "remote_request_sent": candidate["remote_request_sent"],
        "paid_execution": candidate["paid_execution"],
        "billing_changed": candidate["billing_changed"],
    }
    approval = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "book_slug": slug,
        "job_id": job,
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate_digest,
        "candidate_manifest_path": str(manifest_path),
        "approved_at": utc_now_iso(),
        "opening_credit": opening_credit,
    }
    current = _ensure_directory(
        review_root(workspace_root=root, book_slug=slug, job_id=job), root=root
    ) / "CURRENT.json"
    if current.is_symlink():
        raise OpeningCreditReviewError("symlink_current", "Opening-credit CURRENT.json является symlink.")
    atomic_write_json(current, approval)
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "state": "APPROVED",
        "decision": "REVIEW_COMPLETE",
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate_digest,
        "authority_path": str(current),
        "opening_credit": opening_credit,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }
