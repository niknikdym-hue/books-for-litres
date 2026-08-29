"""Offline deterministic no-music builder for Dilon Voices identity.

Consumes an already READY DILON_IDENTITY_V1 preflight and creates an immutable
provider-neutral WAV: reviewed opening credit + fixed silence + exact-current clean
master. No provider/network/paid execution is possible in this module. Signature
or music rendering is intentionally rejected until a later rights-cleared slice.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import struct
import uuid
import wave
from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from backends.common import atomic_write_json, inspect_pcm_wav
from dilon_identity import DILON_BRAND, DILON_DESCRIPTION, OPENING_CREDIT_TEXT
from production_authority_lock import production_authority_lock


IDENTITY_BUILD_SCHEMA_VERSION = 1
MASTER_SCHEMA_VERSION = 1
MASTER_PRESET_ID = "spoken_word_master_v1"
IDENTITY_BUILD_PRESET: dict[str, Any] = {
    "id": "dilon_identity_no_music_build_v1",
    "version": 1,
    "sample_rate_hz": 48_000,
    "channels": 1,
    "sample_width_bytes": 2,
    "compression_type": "NONE",
    "opening_credit_gap_seconds": 0.5,
    "component_order": ["opening_credit", "gap", "clean_master"],
    "signature_policy": "not_rendered_in_this_slice",
    "clean_master_policy": "read_only_byte_identical",
}


class DilonIdentityBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def identity_build_preset_hash() -> str:
    return _canonical_hash(IDENTITY_BUILD_PRESET)


def _safe_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise DilonIdentityBuildError("invalid_identity", f"Некорректный {label}.")
    return value


def _safe_slug(value: Any) -> str:
    slug = _safe_id(value, "book_slug")
    if slug.lower() != slug or any(not (c.isascii() and (c.isalnum() or c == "-")) for c in slug):
        raise DilonIdentityBuildError("invalid_book_slug", "Некорректный book_slug.")
    return slug


def _workspace(workspace_root: Path) -> Path:
    requested = Path(workspace_root).expanduser().absolute()
    if requested.is_symlink():
        raise DilonIdentityBuildError("symlink_workspace_root", "Workspace root является ссылкой.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise DilonIdentityBuildError("missing_workspace", "Workspace root не найден.") from error


def _regular(path: Path, *, root: Path, label: str) -> Path:
    boundary = _workspace(root)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise DilonIdentityBuildError("path_escape", f"{label} вне workspace.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise DilonIdentityBuildError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise DilonIdentityBuildError("symlink_input", f"{label} содержит symlink.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise DilonIdentityBuildError("invalid_input", f"{label} должен быть обычным файлом.")
    return resolved


def _output_root(workspace_root: Path, identities_root: Path) -> Path:
    boundary = _workspace(workspace_root)
    requested = Path(identities_root).expanduser().absolute()
    canonical = boundary / "identities"
    if requested != canonical:
        raise DilonIdentityBuildError(
            "noncanonical_identity_root", "Identity root должен быть canonical workspace/identities."
        )
    current = boundary
    for part in requested.relative_to(boundary).parts:
        current /= part
        if current.is_symlink():
            raise DilonIdentityBuildError("symlink_output_root", "Identity root содержит symlink.")
        current.mkdir(exist_ok=True)
    return requested


def _chapter_root(identities: Path, book_slug: str, job_id: str, *, create: bool) -> Path:
    current = identities
    for part in (book_slug, job_id):
        current = current / part
        if current.is_symlink():
            raise DilonIdentityBuildError("symlink_identity_path", "Identity package path содержит symlink.")
        if create:
            try:
                current.mkdir(exist_ok=True)
            except OSError as error:
                raise DilonIdentityBuildError("invalid_identity_path", "Identity package path недоступен.") from error
        elif not current.is_dir():
            raise DilonIdentityBuildError("missing_identity_path", "Identity package path не найден.")
    return current


def _pcm16_mono_48k(path: Path, label: str) -> dict[str, Any]:
    try:
        facts = inspect_pcm_wav(path).to_dict()
    except Exception as error:
        raise DilonIdentityBuildError("invalid_wav", f"{label} WAV повреждён.") from error
    if (
        facts.get("sample_rate_hz") != 48_000
        or facts.get("channels") != 1
        or facts.get("sample_width_bytes") != 2
        or facts.get("compression_type") != "NONE"
    ):
        raise DilonIdentityBuildError(
            "unsupported_wav_format", f"{label} должен быть PCM16 mono 48 kHz."
        )
    return facts


def _preflight(preflight: Mapping[str, Any]) -> dict[str, Any]:
    if (
        preflight.get("schema_version") != 1
        or preflight.get("state") != "READY"
        or preflight.get("decision") != "READY_TO_BUILD"
        or preflight.get("blockers") != []
        or preflight.get("provider_requests") != 0
        or preflight.get("remote_request_sent") is not False
        or preflight.get("paid_execution") is not False
        or preflight.get("billing_changed") is not False
        or preflight.get("brand") != DILON_BRAND
        or preflight.get("description") != DILON_DESCRIPTION
        or preflight.get("opening_credit_text") != OPENING_CREDIT_TEXT
    ):
        raise DilonIdentityBuildError("preflight_not_ready", "Dilon identity preflight не READY/canonical.")
    master = preflight.get("master")
    credit = preflight.get("opening_credit")
    if not isinstance(master, Mapping) or not isinstance(credit, Mapping):
        raise DilonIdentityBuildError("preflight_incomplete", "Master/opening credit authority отсутствует.")
    reviewed = credit.get("reviewed_identity")
    if (
        credit.get("text") != OPENING_CREDIT_TEXT
        or credit.get("automatic_status") not in {"PASS", "WARN"}
        or credit.get("manual_state") != "APPROVED"
        or not isinstance(reviewed, Mapping)
        or reviewed.get("audio_sha256") != credit.get("audio_sha256")
        or reviewed.get("path_identity") != credit.get("path_identity")
        or reviewed.get("synthesis_fingerprint") != credit.get("synthesis_fingerprint")
    ):
        raise DilonIdentityBuildError("opening_credit_not_approved", "Opening credit exact review authority не подтверждён.")
    if preflight.get("signature_asset") is not None:
        raise DilonIdentityBuildError(
            "signature_render_not_implemented",
            "Signature/music rendering не разрешён в no-music slice.",
        )
    return {
        "plan_id": _safe_id(preflight.get("identity_plan_id"), "identity_plan_id"),
        "book_slug": _safe_slug(preflight.get("book_slug")),
        "book_title": str(preflight.get("book_title") or ""),
        "job_id": _safe_id(preflight.get("job_id"), "job_id"),
        "master": dict(master),
        "credit": dict(credit),
    }


def _validated_inputs(preflight: Mapping[str, Any], workspace_root: Path) -> dict[str, Any]:
    authority = _preflight(preflight)
    root = _workspace(workspace_root)
    master_identity = _safe_id(authority["master"].get("master_identity"), "master_identity")
    master_dir = root / "masters" / authority["book_slug"] / authority["job_id"] / master_identity
    pointer_path = _regular(master_dir.parent / "CURRENT.json", root=root, label="Master CURRENT")
    manifest_path = _regular(master_dir / "MANIFEST.json", root=root, label="Master manifest")
    master_path = _regular(master_dir / "master.wav", root=root, label="Clean master")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DilonIdentityBuildError("invalid_master_pointer", "Master CURRENT повреждён.") from error
    if (
        pointer.get("schema_version") != MASTER_SCHEMA_VERSION
        or pointer.get("master_identity") != master_identity
        or pointer.get("manifest_path") != str(manifest_path)
        or authority["master"].get("master_manifest_sha256") != sha256_file(manifest_path)
    ):
        raise DilonIdentityBuildError("stale_master_authority", "Clean master больше не exact-current.")

    credit_path = _regular(
        Path(str(authority["credit"].get("audio_path") or "")), root=root, label="Opening credit"
    )
    master_sha = sha256_file(master_path)
    credit_sha = sha256_file(credit_path)
    if (
        authority["master"].get("audio_sha256") != master_sha
        or authority["master"].get("path_identity") != path_identity(master_path)
        or authority["credit"].get("audio_sha256") != credit_sha
        or authority["credit"].get("path_identity") != path_identity(credit_path)
    ):
        raise DilonIdentityBuildError("input_identity_mismatch", "Exact input identity изменилась после preflight.")
    return {
        **authority,
        "master_path": master_path,
        "credit_path": credit_path,
        "master_sha256": master_sha,
        "credit_sha256": credit_sha,
        "master_wav": _pcm16_mono_48k(master_path, "Clean master"),
        "credit_wav": _pcm16_mono_48k(credit_path, "Opening credit"),
    }


def _build_identity(inputs: Mapping[str, Any]) -> str:
    return _canonical_hash({
        "schema_version": IDENTITY_BUILD_SCHEMA_VERSION,
        "preflight_plan_id": inputs["plan_id"],
        "build_preset_hash": identity_build_preset_hash(),
        "master_sha256": inputs["master_sha256"],
        "opening_credit_sha256": inputs["credit_sha256"],
    })


def prepare_identity_build(
    preflight: Mapping[str, Any], *, workspace_root: Path, identities_root: Path
) -> dict[str, Any]:
    inputs = _validated_inputs(preflight, workspace_root)
    root = _output_root(workspace_root, identities_root)
    identity = _build_identity(inputs)
    return {
        "schema_version": 1,
        "state": "READY",
        "decision": "READY_TO_BUILD_OFFLINE",
        "build_identity": identity,
        "preflight_plan_id": inputs["plan_id"],
        "build_preset": IDENTITY_BUILD_PRESET,
        "build_preset_hash": identity_build_preset_hash(),
        "book_slug": inputs["book_slug"],
        "job_id": inputs["job_id"],
        "output_dir": str(root / inputs["book_slug"] / inputs["job_id"] / identity),
        "master_sha256": inputs["master_sha256"],
        "opening_credit_sha256": inputs["credit_sha256"],
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def _copy_frames(source_path: Path, target: wave.Wave_write) -> int:
    count = 0
    with wave.open(str(source_path), "rb") as source:
        while True:
            data = source.readframes(65_536)
            if not data:
                break
            target.writeframesraw(data)
            count += len(data) // 2
    return count


def _clipped_samples(path: Path) -> int:
    count = 0
    with wave.open(str(path), "rb") as source:
        while True:
            data = source.readframes(65_536)
            if not data:
                break
            count += sum(sample in {-32768, 32767} for (sample,) in struct.iter_unpack("<h", data))
    return count


def _read_ready(output_dir: Path, identity: str) -> dict[str, Any] | None:
    try:
        if output_dir.is_symlink():
            return None
        manifest_path = output_dir / "MANIFEST.json"
        audio_path = output_dir / "identity.wav"
        if manifest_path.is_symlink() or audio_path.is_symlink():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = manifest.get("output") if isinstance(manifest, dict) else None
        if (
            manifest.get("schema_version") != 1
            or manifest.get("status") != "READY"
            or manifest.get("build_identity") != identity
            or not isinstance(output, Mapping)
            or output.get("path") != str(audio_path.resolve(strict=True))
            or output.get("sha256") != sha256_file(audio_path)
            or output.get("path_identity") != path_identity(audio_path)
            or output.get("wav") != inspect_pcm_wav(audio_path).to_dict()
            or output.get("clipped_samples") != 0
            or _clipped_samples(audio_path) != 0
            or manifest.get("signature_asset") is not None
            or manifest.get("provider_requests") != 0
            or manifest.get("remote_request_sent") is not False
            or manifest.get("paid_execution") is not False
            or manifest.get("billing_changed") is not False
        ):
            return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        return None


def build_identity_output(
    preflight: Mapping[str, Any], *, workspace_root: Path, identities_root: Path
) -> dict[str, Any]:
    authority = _preflight(preflight)
    root = _workspace(workspace_root)
    with production_authority_lock(
        root,
        provider="master-book",
        book_slug=authority["book_slug"],
        job_id="book",
        profile_id=MASTER_PRESET_ID,
        exclusive=False,
    ):
        with production_authority_lock(
            root,
            provider="master",
            book_slug=authority["book_slug"],
            job_id=authority["job_id"],
            profile_id=MASTER_PRESET_ID,
            exclusive=False,
        ):
            return _build_identity_output_locked(
                preflight, workspace_root=root, identities_root=identities_root
            )


def _build_identity_output_locked(
    preflight: Mapping[str, Any], *, workspace_root: Path, identities_root: Path
) -> dict[str, Any]:
    inputs = _validated_inputs(preflight, workspace_root)
    identities = _output_root(workspace_root, identities_root)
    chapter_root = _chapter_root(identities, inputs["book_slug"], inputs["job_id"], create=True)
    identity = _build_identity(inputs)
    output_dir = chapter_root / identity
    existing = _read_ready(output_dir, identity) if output_dir.exists() else None
    if existing is not None:
        atomic_write_json(chapter_root / "CURRENT.json", {
            "schema_version": 1,
            "build_identity": identity,
            "manifest_path": str((output_dir / "MANIFEST.json").resolve(strict=True)),
        })
        return existing
    if output_dir.exists() or output_dir.is_symlink():
        raise DilonIdentityBuildError("invalid_existing_output", "Existing immutable identity package invalid.")

    master_before = sha256_file(inputs["master_path"])
    credit_before = sha256_file(inputs["credit_path"])
    gap_frames = 24_000
    temp_dir = chapter_root / f".tmp-{identity}-{uuid.uuid4().hex}"
    temp_dir.mkdir()
    temp_audio = temp_dir / "identity.wav"
    final_audio = output_dir / "identity.wav"
    final_manifest = output_dir / "MANIFEST.json"
    try:
        with wave.open(str(temp_audio), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(48_000)
            credit_frames = _copy_frames(inputs["credit_path"], target)
            target.writeframesraw(b"\x00\x00" * gap_frames)
            master_frames = _copy_frames(inputs["master_path"], target)
            target.writeframes(b"")
        if sha256_file(inputs["master_path"]) != master_before:
            raise DilonIdentityBuildError("master_changed_during_build", "Clean master изменился во время build.")
        if sha256_file(inputs["credit_path"]) != credit_before:
            raise DilonIdentityBuildError("credit_changed_during_build", "Opening credit изменился во время build.")
        wav_facts = _pcm16_mono_48k(temp_audio, "Identity output")
        if wav_facts.get("frame_count") != credit_frames + gap_frames + master_frames:
            raise DilonIdentityBuildError("identity_duration_mismatch", "Identity output frame count mismatch.")
        if _clipped_samples(temp_audio):
            raise DilonIdentityBuildError("identity_clipping", "Identity output содержит clipped PCM samples.")
        manifest = {
            "schema_version": 1,
            "status": "READY",
            "build_identity": identity,
            "preflight_plan_id": inputs["plan_id"],
            "build_preset": IDENTITY_BUILD_PRESET,
            "build_preset_hash": identity_build_preset_hash(),
            "book_slug": inputs["book_slug"],
            "book_title": inputs["book_title"],
            "job_id": inputs["job_id"],
            "components": [
                {"kind": "opening_credit", "sha256": credit_before, "frames": credit_frames},
                {"kind": "gap", "frames": gap_frames},
                {"kind": "clean_master", "sha256": master_before, "frames": master_frames},
            ],
            "output": {
                "path": str(final_audio.absolute()),
                "sha256": sha256_file(temp_audio),
                "path_identity": path_identity(final_audio),
                "wav": wav_facts,
                "clipped_samples": 0,
            },
            "source_integrity": {
                "clean_master_sha256_before": master_before,
                "clean_master_sha256_after": sha256_file(inputs["master_path"]),
                "opening_credit_sha256_before": credit_before,
                "opening_credit_sha256_after": sha256_file(inputs["credit_path"]),
            },
            "signature_asset": None,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        atomic_write_json(temp_dir / "MANIFEST.json", manifest)
        try:
            os.rename(temp_dir, output_dir)
        except OSError as error:
            if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                raise
            winner = _read_ready(output_dir, identity)
            if winner is None:
                raise DilonIdentityBuildError("identity_publish_conflict", "Конфликт immutable identity publication.")
            atomic_write_json(chapter_root / "CURRENT.json", {
                "schema_version": 1,
                "build_identity": identity,
                "manifest_path": str(final_manifest.resolve(strict=True)),
            })
            return winner
        if _read_ready(output_dir, identity) is None:
            raise DilonIdentityBuildError("identity_publication_invalid", "Published identity package invalid.")
        atomic_write_json(chapter_root / "CURRENT.json", {
            "schema_version": 1,
            "build_identity": identity,
            "manifest_path": str(final_manifest.resolve(strict=True)),
        })
        return manifest
    finally:
        if temp_dir.exists():
            for child in temp_dir.iterdir():
                child.unlink(missing_ok=True)
            temp_dir.rmdir()


def resolve_current_identity(
    *,
    workspace_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
    expected_build_identity: str | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace_root)
    identities = _output_root(root, identities_root)
    book = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    chapter_root = _chapter_root(identities, book, job, create=False)
    pointer_path = _regular(chapter_root / "CURRENT.json", root=root, label="Identity CURRENT")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DilonIdentityBuildError("invalid_identity_pointer", "Identity CURRENT повреждён.") from error
    identity = _safe_id(pointer.get("build_identity"), "build_identity")
    if expected_build_identity is not None and identity != expected_build_identity:
        raise DilonIdentityBuildError("stale_identity", "Dilon identity output устарел.")
    output_dir = chapter_root / identity
    expected_manifest = output_dir / "MANIFEST.json"
    if pointer.get("schema_version") != 1 or pointer.get("manifest_path") != str(expected_manifest.absolute()):
        raise DilonIdentityBuildError("identity_pointer_mismatch", "Identity CURRENT указывает не на canonical manifest.")
    manifest = _read_ready(output_dir, identity)
    if manifest is None:
        raise DilonIdentityBuildError("identity_output_invalid", "Current identity output не подтверждён.")
    return manifest
