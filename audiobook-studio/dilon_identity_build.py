"""Offline deterministic builder for the first Dilon Voices identity output slice.

This module consumes an already READY ``DILON_IDENTITY_V1`` preflight and builds
only the canonical no-music identity path: reviewed opening credit + fixed silence
+ exact clean master. It never calls a TTS provider, never performs paid execution,
and never mutates the clean master or opening-credit source audio.

Optional signature/music rendering is deliberately NOT implemented here. A
preflight containing a signature asset fails closed until a later rights-cleared
mixer slice is accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from backends.common import atomic_write_json, inspect_pcm_wav


IDENTITY_BUILD_SCHEMA_VERSION = 1
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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


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
    value = _safe_id(value, "book_slug")
    if value.lower() != value or any(not (c.isalnum() or c == "-") for c in value):
        raise DilonIdentityBuildError("invalid_book_slug", "Некорректный book_slug.")
    return value


def _workspace_boundary(workspace_root: Path) -> Path:
    requested = Path(workspace_root).expanduser().absolute()
    if requested.is_symlink():
        raise DilonIdentityBuildError("symlink_workspace_root", "Workspace root является ссылкой.")
    try:
        return requested.resolve(strict=True)
    except OSError as error:
        raise DilonIdentityBuildError("missing_workspace", "Workspace root не найден.") from error


def _require_regular_path(path: Path, *, root: Path, label: str) -> Path:
    boundary = _workspace_boundary(root)
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise DilonIdentityBuildError("path_escape", f"{label} находится вне workspace.") from error
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


def _validate_output_root(workspace_root: Path, identities_root: Path) -> Path:
    boundary = _workspace_boundary(workspace_root)
    requested = Path(identities_root).expanduser().absolute()
    try:
        relative = requested.relative_to(boundary)
    except ValueError as error:
        raise DilonIdentityBuildError("output_root_escape", "Identity root вне workspace.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise DilonIdentityBuildError("symlink_output_root", "Identity root содержит symlink.")
        current.mkdir(exist_ok=True)
    return requested


def _validate_preflight(preflight: Mapping[str, Any]) -> dict[str, Any]:
    blockers = preflight.get("blockers")
    if (
        preflight.get("schema_version") != 1
        or preflight.get("state") != "READY"
        or preflight.get("decision") != "READY_TO_BUILD"
        or blockers != []
        or preflight.get("provider_requests") != 0
        or preflight.get("remote_request_sent") is not False
        or preflight.get("paid_execution") is not False
        or preflight.get("billing_changed") is not False
    ):
        raise DilonIdentityBuildError("preflight_not_ready", "Dilon identity preflight не READY.")
    plan_id = _safe_id(preflight.get("identity_plan_id"), "identity_plan_id")
    book_slug = _safe_slug(preflight.get("book_slug"))
    job_id = _safe_id(preflight.get("job_id"), "job_id")
    master = preflight.get("master")
    credit = preflight.get("opening_credit")
    if not isinstance(master, Mapping) or not isinstance(credit, Mapping):
        raise DilonIdentityBuildError("preflight_incomplete", "Master/opening credit authority отсутствует.")
    if preflight.get("signature_asset") is not None:
        raise DilonIdentityBuildError(
            "signature_render_not_implemented",
            "Signature/music rendering не разрешён в no-music build slice.",
        )
    return {
        "plan_id": plan_id,
        "book_slug": book_slug,
        "job_id": job_id,
        "book_title": str(preflight.get("book_title") or ""),
        "master": dict(master),
        "credit": dict(credit),
    }


def _require_pcm16_mono_48k(path: Path, label: str) -> dict[str, Any]:
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


def _validated_inputs(preflight: Mapping[str, Any], workspace_root: Path) -> dict[str, Any]:
    authority = _validate_preflight(preflight)
    root = _workspace_boundary(workspace_root)
    master_identity = _safe_id(authority["master"].get("master_identity"), "master_identity")
    master_path = root / "masters" / authority["book_slug"] / authority["job_id"] / master_identity / "master.wav"
    master = _require_regular_path(master_path, root=root, label="Clean master")
    credit = _require_regular_path(
        Path(str(authority["credit"].get("audio_path") or "")), root=root, label="Opening credit"
    )
    master_sha = sha256_file(master)
    credit_sha = sha256_file(credit)
    if (
        authority["master"].get("audio_sha256") != master_sha
        or authority["master"].get("path_identity") != path_identity(master)
        or authority["credit"].get("audio_sha256") != credit_sha
        or authority["credit"].get("path_identity") != path_identity(credit)
    ):
        raise DilonIdentityBuildError("input_identity_mismatch", "Входная exact identity изменилась после preflight.")
    master_wav = _require_pcm16_mono_48k(master, "Clean master")
    credit_wav = _require_pcm16_mono_48k(credit, "Opening credit")
    return {
        **authority,
        "master_path": master,
        "credit_path": credit,
        "master_sha256": master_sha,
        "credit_sha256": credit_sha,
        "master_wav": master_wav,
        "credit_wav": credit_wav,
    }


def _build_identity(inputs: Mapping[str, Any]) -> str:
    return _canonical_hash({
        "schema_version": IDENTITY_BUILD_SCHEMA_VERSION,
        "preflight_plan_id": inputs["plan_id"],
        "build_preset": IDENTITY_BUILD_PRESET,
        "build_preset_hash": identity_build_preset_hash(),
        "master_sha256": inputs["master_sha256"],
        "opening_credit_sha256": inputs["credit_sha256"],
    })


def prepare_identity_build(
    preflight: Mapping[str, Any], *, workspace_root: Path, identities_root: Path
) -> dict[str, Any]:
    inputs = _validated_inputs(preflight, workspace_root)
    root = _validate_output_root(workspace_root, identities_root)
    build_identity = _build_identity(inputs)
    output_dir = root / inputs["book_slug"] / inputs["job_id"] / build_identity
    return {
        "schema_version": IDENTITY_BUILD_SCHEMA_VERSION,
        "state": "READY",
        "decision": "READY_TO_BUILD_OFFLINE",
        "build_identity": build_identity,
        "preflight_plan_id": inputs["plan_id"],
        "build_preset": IDENTITY_BUILD_PRESET,
        "build_preset_hash": identity_build_preset_hash(),
        "book_slug": inputs["book_slug"],
        "job_id": inputs["job_id"],
        "output_dir": str(output_dir),
        "master_sha256": inputs["master_sha256"],
        "opening_credit_sha256": inputs["credit_sha256"],
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def _copy_wave_frames(source_path: Path, output: wave.Wave_write) -> int:
    total = 0
    with wave.open(str(source_path), "rb") as source:
        while True:
            data = source.readframes(65_536)
            if not data:
                break
            output.writeframesraw(data)
            total += len(data) // 2
    return total


def _count_clipped_samples(path: Path) -> int:
    clipped = 0
    with wave.open(str(path), "rb") as source:
        while True:
            data = source.readframes(65_536)
            if not data:
                break
            for (sample,) in struct.iter_unpack("<h", data):
                if sample in {-32768, 32767}:
                    clipped += 1
    return clipped


def _read_ready_package(output_dir: Path, build_identity: str) -> dict[str, Any] | None:
    try:
        manifest_path = output_dir / "MANIFEST.json"
        audio_path = output_dir / "identity.wav"
        if manifest_path.is_symlink() or audio_path.is_symlink():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = manifest.get("output") if isinstance(manifest, dict) else None
        if (
            manifest.get("schema_version") != IDENTITY_BUILD_SCHEMA_VERSION
            or manifest.get("status") != "READY"
            or manifest.get("build_identity") != build_identity
            or not isinstance(output, Mapping)
            or output.get("path") != str(audio_path.resolve(strict=True))
            or output.get("sha256") != sha256_file(audio_path)
            or output.get("path_identity") != path_identity(audio_path)
            or output.get("wav") != inspect_pcm_wav(audio_path).to_dict()
            or output.get("clipped_samples") != 0
            or _count_clipped_samples(audio_path) != 0
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
    inputs = _validated_inputs(preflight, workspace_root)
    identities = _validate_output_root(workspace_root, identities_root)
    chapter_root = identities / inputs["book_slug"] / inputs["job_id"]
    chapter_root.mkdir(parents=True, exist_ok=True)
    build_identity = _build_identity(inputs)
    output_dir = chapter_root / build_identity
    existing = _read_ready_package(output_dir, build_identity) if output_dir.exists() else None
    if existing is not None:
        atomic_write_json(chapter_root / "CURRENT.json", {
            "schema_version": IDENTITY_BUILD_SCHEMA_VERSION,
            "build_identity": build_identity,
            "manifest_path": str((output_dir / "MANIFEST.json").resolve(strict=True)),
        })
        return existing
    if output_dir.exists():
        raise DilonIdentityBuildError("invalid_existing_output", "Existing immutable identity package invalid.")

    master_before = sha256_file(inputs["master_path"])
    credit_before = sha256_file(inputs["credit_path"])
    gap_frames = int(round(48_000 * float(IDENTITY_BUILD_PRESET["opening_credit_gap_seconds"])))
    temp_dir = chapter_root / f".tmp-{build_identity}-{uuid.uuid4().hex}"
    temp_dir.mkdir()
    temp_audio = temp_dir / "identity.wav"
    try:
        with wave.open(str(temp_audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            credit_frames = _copy_wave_frames(inputs["credit_path"], output)
            output.writeframesraw(b"\x00\x00" * gap_frames)
            master_frames = _copy_wave_frames(inputs["master_path"], output)
            output.writeframes(b"")
        if sha256_file(inputs["master_path"]) != master_before:
            raise DilonIdentityBuildError("master_changed_during_build", "Clean master изменился во время build.")
        if sha256_file(inputs["credit_path"]) != credit_before:
            raise DilonIdentityBuildError("credit_changed_during_build", "Opening credit изменился во время build.")
        wav_facts = _require_pcm16_mono_48k(temp_audio, "Identity output")
        clipped = _count_clipped_samples(temp_audio)
        if clipped:
            raise DilonIdentityBuildError("identity_clipping", "Identity output содержит clipped PCM samples.")
        expected_frames = credit_frames + gap_frames + master_frames
        if wav_facts.get("frame_count") != expected_frames:
            raise DilonIdentityBuildError("identity_duration_mismatch", "Identity output frame count mismatch.")
        manifest = {
            "schema_version": IDENTITY_BUILD_SCHEMA_VERSION,
            "status": "READY",
            "build_identity": build_identity,
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
                "path": str((output_dir / "identity.wav").absolute()),
                "sha256": sha256_file(temp_audio),
                "path_identity": None,
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
        os.rename(temp_dir, output_dir)
        final_audio = output_dir / "identity.wav"
        final_manifest_path = output_dir / "MANIFEST.json"
        manifest["output"]["path"] = str(final_audio.resolve(strict=True))
        manifest["output"]["path_identity"] = path_identity(final_audio)
        atomic_write_json(final_manifest_path, manifest)
        if _read_ready_package(output_dir, build_identity) is None:
            raise DilonIdentityBuildError("identity_publication_invalid", "Published identity package failed validation.")
        atomic_write_json(chapter_root / "CURRENT.json", {
            "schema_version": IDENTITY_BUILD_SCHEMA_VERSION,
            "build_identity": build_identity,
            "manifest_path": str(final_manifest_path.resolve(strict=True)),
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
    root = _workspace_boundary(workspace_root)
    identities = _validate_output_root(root, identities_root)
    book = _safe_slug(book_slug)
    job = _safe_id(job_id, "job_id")
    chapter_root = identities / book / job
    pointer_path = _require_regular_path(chapter_root / "CURRENT.json", root=root, label="Identity CURRENT")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DilonIdentityBuildError("invalid_identity_pointer", "Identity CURRENT повреждён.") from error
    identity = _safe_id(pointer.get("build_identity"), "build_identity")
    if expected_build_identity is not None and identity != expected_build_identity:
        raise DilonIdentityBuildError("stale_identity", "Dilon identity output устарел.")
    output_dir = chapter_root / identity
    expected_manifest = output_dir / "MANIFEST.json"
    if pointer.get("schema_version") != IDENTITY_BUILD_SCHEMA_VERSION or pointer.get("manifest_path") != str(expected_manifest.absolute()):
        raise DilonIdentityBuildError("identity_pointer_mismatch", "Identity CURRENT указывает не на canonical manifest.")
    manifest = _read_ready_package(output_dir, identity)
    if manifest is None:
        raise DilonIdentityBuildError("identity_output_invalid", "Current identity output не подтверждён.")
    return manifest
