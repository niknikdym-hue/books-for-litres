"""Provider-neutral offline preflight for the downstream Dilon Voices identity layer.

This module intentionally does not synthesize, mix, encode, or publish audio.  It
binds DILON_IDENTITY_V1 to an exact current clean master and validates optional
reviewed/rights-cleared component evidence before any later identity build may
run.  Every returned plan is network-free and billing-neutral by contract.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from backends.common import WavValidationError, inspect_pcm_wav
from book_library import BookLibraryError, normalize_slug
from mastering_export import resolve_current_master


IDENTITY_SCHEMA_VERSION = 1
IDENTITY_PRESET_ID = "dilon_voices_identity_v1"
DILON_BRAND = "Dilon Voices"
DILON_DESCRIPTION = (
    "Dilon Voices — проект аудиокниг с профессионально подготовленной "
    "синтезированной озвучкой и авторской аудиообработкой."
)

IDENTITY_PRESET: dict[str, Any] = {
    "id": IDENTITY_PRESET_ID,
    "version": 1,
    "brand": DILON_BRAND,
    "processing": "downstream_derived_identity_v1",
    "clean_master_policy": "preserve_byte_identical",
    "opening_credit_policy": "exact_reviewed_audio_required",
    "signature_policy": "optional_rights_proven_only",
    "no_music_path": True,
}


class DilonIdentityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def identity_preset_hash() -> str:
    return _canonical_hash(IDENTITY_PRESET)


def _safe_slug(value: Any) -> str:
    try:
        return normalize_slug(str(value or ""))
    except BookLibraryError as error:
        raise DilonIdentityError("invalid_book_slug", "Некорректный идентификатор книги.") from error


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise DilonIdentityError("invalid_identity", f"Некорректный {label}.")
    return value


def _require_regular_path(path: Path, *, root: Path, label: str) -> Path:
    requested_root = Path(root).expanduser().absolute()
    if requested_root.is_symlink():
        raise DilonIdentityError("symlink_workspace_root", "Workspace root является ссылкой.")
    boundary = requested_root.resolve(strict=True)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise DilonIdentityError("path_escape", f"{label} находится вне рабочего пространства.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise DilonIdentityError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise DilonIdentityError("symlink_input", f"{label} содержит символическую ссылку.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise DilonIdentityError("invalid_input", f"{label} должен быть обычным файлом.")
    return resolved


def _inspect_wav(path: Path, *, code: str, message: str) -> dict[str, Any]:
    try:
        return inspect_pcm_wav(path).to_dict()
    except (OSError, ValueError, WavValidationError) as error:
        raise DilonIdentityError(code, message) from error


def _validate_master_authority(
    value: Mapping[str, Any], *, workspace_root: Path
) -> dict[str, Any]:
    master_identity = _safe_id(value.get("master_identity"), "master_identity")
    book_slug = _safe_slug(value.get("book_slug"))
    job_id = _safe_id(value.get("job_id"), "job_id")
    audio = _require_regular_path(
        Path(str(value.get("audio_path") or "")),
        root=workspace_root,
        label="Clean master WAV",
    )
    manifest = _require_regular_path(
        Path(str(value.get("master_manifest_path") or "")),
        root=workspace_root,
        label="Clean master manifest",
    )
    canonical = workspace_root / "masters" / book_slug / job_id / master_identity
    if audio != canonical / "master.wav" or manifest != canonical / "MANIFEST.json":
        raise DilonIdentityError(
            "master_path_identity_mismatch",
            "Clean master находится вне канонического immutable master package.",
        )
    wav = _inspect_wav(
        audio,
        code="master_invalid_wav",
        message="Clean master WAV повреждён.",
    )
    if (
        value.get("audio_sha256") != sha256_file(audio)
        or value.get("path_identity") != path_identity(audio)
        or value.get("master_manifest_sha256") != sha256_file(manifest)
        or value.get("wav") != wav
        or wav.get("sample_rate_hz") != 48_000
        or wav.get("channels") != 1
        or wav.get("sample_width_bytes") != 2
        or wav.get("compression_type") != "NONE"
    ):
        raise DilonIdentityError(
            "master_authority_mismatch", "Exact-current clean master не подтверждён."
        )
    return {
        "master_identity": master_identity,
        "master_manifest_path": str(manifest),
        "master_manifest_sha256": sha256_file(manifest),
        "audio_path": str(audio),
        "audio_sha256": sha256_file(audio),
        "path_identity": path_identity(audio),
        "wav": wav,
        "book_slug": book_slug,
        "book_title": str(value.get("book_title") or ""),
        "job_id": job_id,
        "job_label": str(value.get("job_label") or job_id),
        "provider": _safe_id(value.get("provider"), "provider"),
        "profile_id": _safe_id(value.get("profile_id"), "profile_id"),
        "assembly_identity": value.get("assembly_identity"),
    }


def _validate_opening_credit(
    value: Mapping[str, Any],
    *,
    expected_text: str,
    workspace_root: Path,
) -> dict[str, Any]:
    text = value.get("text")
    if not isinstance(text, str) or text != expected_text:
        raise DilonIdentityError(
            "opening_credit_text_mismatch", "Текст opening credit не совпадает с authority."
        )
    if value.get("automatic_status") not in {"PASS", "WARN"}:
        raise DilonIdentityError(
            "opening_credit_automatic_qa_required", "Opening credit не прошёл automatic QA."
        )
    if value.get("manual_state") != "APPROVED":
        raise DilonIdentityError(
            "opening_credit_manual_approval_required", "Opening credit не одобрен вручную."
        )
    reviewed = value.get("reviewed_identity")
    if not isinstance(reviewed, Mapping):
        raise DilonIdentityError(
            "opening_credit_review_identity_missing", "Exact reviewed identity opening credit отсутствует."
        )
    fingerprint = value.get("synthesis_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise DilonIdentityError(
            "opening_credit_fingerprint_missing", "Synthesis fingerprint opening credit отсутствует."
        )
    audio = _require_regular_path(
        Path(str(value.get("audio_path") or "")),
        root=workspace_root,
        label="Opening credit WAV",
    )
    audio_sha = sha256_file(audio)
    audio_path_identity = path_identity(audio)
    wav = _inspect_wav(
        audio,
        code="opening_credit_invalid_wav",
        message="Opening credit WAV повреждён.",
    )
    if (
        value.get("audio_sha256") != audio_sha
        or value.get("path_identity") != audio_path_identity
        or value.get("wav") != wav
        or reviewed.get("audio_sha256") != audio_sha
        or reviewed.get("path_identity") != audio_path_identity
        or reviewed.get("synthesis_fingerprint") != fingerprint
        or wav.get("compression_type") != "NONE"
        or int(wav.get("channels") or 0) < 1
    ):
        raise DilonIdentityError(
            "opening_credit_identity_mismatch", "Reviewed opening credit больше не совпадает с WAV."
        )
    return {
        "text": expected_text,
        "audio_path": str(audio),
        "audio_sha256": audio_sha,
        "path_identity": audio_path_identity,
        "wav": wav,
        "synthesis_fingerprint": fingerprint,
        "automatic_status": value.get("automatic_status"),
        "manual_state": "APPROVED",
        "reviewed_identity": {
            "audio_sha256": audio_sha,
            "path_identity": audio_path_identity,
            "synthesis_fingerprint": fingerprint,
        },
    }


def _validate_signature_asset(
    value: Mapping[str, Any], *, workspace_root: Path
) -> dict[str, Any]:
    asset_id = _safe_id(value.get("asset_id"), "signature asset_id")
    path = _require_regular_path(
        Path(str(value.get("path") or "")),
        root=workspace_root,
        label="Signature asset",
    )
    digest = sha256_file(path)
    if value.get("sha256") != digest or value.get("path_identity") != path_identity(path):
        raise DilonIdentityError(
            "signature_asset_identity_mismatch", "Signature asset identity изменилась."
        )
    rights = value.get("rights_provenance")
    if not isinstance(rights, Mapping):
        raise DilonIdentityError(
            "signature_rights_unproven", "Rights/provenance signature asset не подтверждены."
        )
    provenance = rights.get("source_provenance")
    right_to_use = rights.get("right_to_use")
    if (
        rights.get("verified") is not True
        or rights.get("commercial_audiobook_distribution") is not True
        or not isinstance(provenance, str)
        or not provenance.strip()
        or not isinstance(right_to_use, str)
        or not right_to_use.strip()
    ):
        raise DilonIdentityError(
            "signature_rights_unproven", "Коммерческие права на signature asset не доказаны."
        )
    return {
        "asset_id": asset_id,
        "path": str(path),
        "path_identity": path_identity(path),
        "sha256": digest,
        "rights_provenance": {
            "verified": True,
            "commercial_audiobook_distribution": True,
            "source_provenance": provenance.strip(),
            "right_to_use": right_to_use.strip(),
            "territory": rights.get("territory"),
            "term": rights.get("term"),
        },
    }


def build_identity_preflight(
    master_authority: Mapping[str, Any],
    *,
    workspace_root: Path,
    opening_credit_text: str,
    opening_credit: Mapping[str, Any] | None = None,
    signature_asset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic, network-free Dilon identity build plan.

    ``master_authority`` must already represent the exact-current clean master;
    ``prepare_current_identity`` is the canonical entry point that resolves it
    through the MASTERING_EXPORT_V1 CURRENT authority first.
    """
    if not isinstance(opening_credit_text, str) or not opening_credit_text.strip():
        raise DilonIdentityError("invalid_opening_credit_text", "Opening credit text обязателен.")
    root = Path(workspace_root).expanduser().resolve(strict=True)
    master = _validate_master_authority(master_authority, workspace_root=root)
    blockers: list[str] = []

    credit_record: dict[str, Any] | None = None
    if opening_credit is None:
        blockers.append("opening_credit_missing")
    else:
        try:
            credit_record = _validate_opening_credit(
                opening_credit,
                expected_text=opening_credit_text,
                workspace_root=root,
            )
        except DilonIdentityError as error:
            blockers.append(error.code)

    signature_record: dict[str, Any] | None = None
    if signature_asset is not None:
        try:
            signature_record = _validate_signature_asset(signature_asset, workspace_root=root)
        except DilonIdentityError as error:
            blockers.append(error.code)

    blockers = list(dict.fromkeys(blockers))
    identity_inputs = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "preset": IDENTITY_PRESET,
        "preset_hash": identity_preset_hash(),
        "brand": DILON_BRAND,
        "description": DILON_DESCRIPTION,
        "book_slug": master["book_slug"],
        "book_title": master["book_title"],
        "job_id": master["job_id"],
        "master": {
            "master_identity": master["master_identity"],
            "master_manifest_sha256": master["master_manifest_sha256"],
            "audio_sha256": master["audio_sha256"],
            "path_identity": master["path_identity"],
        },
        "opening_credit_text": opening_credit_text,
        "opening_credit": credit_record,
        "signature_asset": signature_record,
    }
    plan_identity = _canonical_hash(identity_inputs)
    ready = not blockers
    return {
        **identity_inputs,
        "identity_plan_id": plan_identity,
        "state": "READY" if ready else "BLOCKED",
        "decision": "READY_TO_BUILD" if ready else "BLOCKED",
        "blockers": blockers,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def prepare_current_identity(
    *,
    workspace_root: Path,
    masters_root: Path,
    book_slug: str,
    job_id: str,
    opening_credit_text: str,
    opening_credit: Mapping[str, Any] | None = None,
    signature_asset: Mapping[str, Any] | None = None,
    expected_master_identity: str | None = None,
) -> dict[str, Any]:
    """Resolve exact-current clean master and build an offline identity preflight."""
    master = resolve_current_master(
        workspace_root=workspace_root,
        masters_root=masters_root,
        book_slug=book_slug,
        job_id=job_id,
        expected_master_identity=expected_master_identity,
    )
    return build_identity_preflight(
        master,
        workspace_root=workspace_root,
        opening_credit_text=opening_credit_text,
        opening_credit=opening_credit,
        signature_asset=signature_asset,
    )
