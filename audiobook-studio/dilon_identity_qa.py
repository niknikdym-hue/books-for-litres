"""Provider-neutral offline technical QA for immutable Dilon Voices identity audio."""

from __future__ import annotations

import json
import stat
import wave
from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from backends.common import WavValidationError, inspect_pcm_wav
from dilon_identity import OPENING_CREDIT_TEXT
from dilon_identity_build import DilonIdentityBuildError, resolve_current_identity


QA_SCHEMA_VERSION = 1
EXPECTED_GAP_FRAMES = 24_000  # 0.5 s at 48 kHz.


class DilonIdentityQAError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _regular(path: Path, *, root: Path, label: str) -> Path:
    boundary = Path(root).expanduser().absolute()
    if boundary.is_symlink():
        raise DilonIdentityQAError("symlink_workspace_root", "Workspace root является ссылкой.")
    try:
        boundary = boundary.resolve(strict=True)
    except OSError as error:
        raise DilonIdentityQAError("missing_workspace", "Workspace root не найден.") from error
    candidate = Path(path).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise DilonIdentityQAError("path_escape", f"{label} находится вне workspace.") from error
    current = boundary
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise DilonIdentityQAError("missing_input", f"{label} не найден.") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise DilonIdentityQAError("symlink_input", f"{label} содержит symbolic link.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise DilonIdentityQAError("invalid_input", f"{label} должен быть обычным файлом.")
    return resolved


def _wav(path: Path, label: str) -> dict[str, Any]:
    try:
        facts = inspect_pcm_wav(path).to_dict()
    except (OSError, ValueError, WavValidationError) as error:
        raise DilonIdentityQAError("invalid_wav", f"{label} WAV повреждён.") from error
    if (
        facts.get("sample_rate_hz") != 48_000
        or facts.get("channels") != 1
        or facts.get("sample_width_bytes") != 2
        or facts.get("compression_type") != "NONE"
    ):
        raise DilonIdentityQAError("unsupported_wav_format", f"{label} должен быть PCM16 mono 48 kHz.")
    return facts


def _source(
    value: Mapping[str, Any], *, root: Path, label: str, require_review: bool = False
) -> tuple[Path, dict[str, Any]]:
    path = _regular(Path(str(value.get("audio_path") or "")), root=root, label=label)
    facts = _wav(path, label)
    digest = sha256_file(path)
    identity = path_identity(path)
    if value.get("audio_sha256") != digest or value.get("path_identity") != identity:
        raise DilonIdentityQAError("source_identity_mismatch", f"{label} identity изменилась.")
    if require_review:
        reviewed = value.get("reviewed_identity")
        fingerprint = value.get("synthesis_fingerprint")
        if (
            value.get("text") != OPENING_CREDIT_TEXT
            or value.get("automatic_status") not in {"PASS", "WARN"}
            or value.get("manual_state") != "APPROVED"
            or not isinstance(fingerprint, str)
            or not fingerprint
            or not isinstance(reviewed, Mapping)
        ):
            raise DilonIdentityQAError("opening_credit_not_approved", "Opening credit authority не подтверждена.")
        if (
            reviewed.get("audio_sha256") != digest
            or reviewed.get("path_identity") != identity
            or reviewed.get("synthesis_fingerprint") != fingerprint
        ):
            raise DilonIdentityQAError("opening_credit_review_stale", "Reviewed opening credit устарел.")
    return path, facts


def _current_master_source(
    value: Mapping[str, Any], *, root: Path, book_slug: str, job_id: str
) -> tuple[Path, dict[str, Any]]:
    master_identity = value.get("master_identity")
    if (
        not isinstance(master_identity, str)
        or not master_identity
        or master_identity in {".", ".."}
        or "/" in master_identity
        or "\\" in master_identity
    ):
        raise DilonIdentityQAError("invalid_master_identity", "Некорректный master_identity.")
    path, facts = _source(value, root=root, label="Clean master")
    canonical_dir = root / "masters" / book_slug / job_id / master_identity
    manifest = _regular(
        Path(str(value.get("master_manifest_path") or "")), root=root, label="Clean master manifest"
    )
    if path != canonical_dir / "master.wav" or manifest != canonical_dir / "MANIFEST.json":
        raise DilonIdentityQAError("clean_master_not_current", "Clean master находится вне canonical immutable package.")
    if value.get("master_manifest_sha256") != sha256_file(manifest):
        raise DilonIdentityQAError("clean_master_not_current", "Clean master manifest identity изменилась.")
    pointer_path = _regular(canonical_dir.parent / "CURRENT.json", root=root, label="Clean master CURRENT")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise DilonIdentityQAError("clean_master_not_current", "Clean master CURRENT повреждён.") from error
    if (
        not isinstance(pointer, Mapping)
        or pointer.get("schema_version") != 1
        or pointer.get("master_identity") != master_identity
        or pointer.get("manifest_path") != str(manifest)
    ):
        raise DilonIdentityQAError("clean_master_not_current", "Clean master больше не является exact-current.")
    return path, facts


def _same_frames(source: wave.Wave_read, output: wave.Wave_read, frames: int) -> bool:
    remaining = frames
    while remaining:
        count = min(8192, remaining)
        expected = source.readframes(count)
        actual = output.readframes(count)
        if expected != actual or len(expected) != count * 2:
            return False
        remaining -= count
    return True


def _silent_frames(output: wave.Wave_read, frames: int) -> bool:
    remaining = frames
    while remaining:
        count = min(8192, remaining)
        data = output.readframes(count)
        if len(data) != count * 2 or any(data):
            return False
        remaining -= count
    return True


def _has_clipping(path: Path) -> bool:
    with wave.open(str(path), "rb") as source:
        while True:
            data = source.readframes(8192)
            if not data:
                return False
            for index in range(0, len(data), 2):
                sample = int.from_bytes(data[index:index + 2], "little", signed=True)
                if sample in {-32768, 32767}:
                    return True


def run_identity_technical_qa(
    *,
    workspace_root: Path,
    identities_root: Path,
    book_slug: str,
    job_id: str,
    opening_credit_authority: Mapping[str, Any],
    clean_master_authority: Mapping[str, Any],
    expected_build_identity: str | None = None,
) -> dict[str, Any]:
    """Independently verify an exact-current Dilon identity WAV without network access."""
    root = Path(workspace_root).expanduser().resolve(strict=True)
    try:
        manifest = resolve_current_identity(
            workspace_root=root,
            identities_root=identities_root,
            book_slug=book_slug,
            job_id=job_id,
            expected_build_identity=expected_build_identity,
        )
    except DilonIdentityBuildError as error:
        raise DilonIdentityQAError("identity_not_current", "Exact-current Dilon identity output не подтверждён.") from error

    if (
        manifest.get("provider_requests") != 0
        or manifest.get("remote_request_sent") is not False
        or manifest.get("paid_execution") is not False
        or manifest.get("billing_changed") is not False
    ):
        raise DilonIdentityQAError("identity_execution_contract_invalid", "Identity manifest нарушает offline contract.")

    components = manifest.get("components")
    if (
        not isinstance(components, list)
        or len(components) != 3
        or [item.get("kind") for item in components if isinstance(item, Mapping)]
        != ["opening_credit", "gap", "clean_master"]
    ):
        raise DilonIdentityQAError("identity_component_order_invalid", "Identity component order повреждён.")

    credit_path, credit_facts = _source(
        opening_credit_authority, root=root, label="Opening credit", require_review=True
    )
    master_path, master_facts = _current_master_source(
        clean_master_authority, root=root, book_slug=book_slug, job_id=job_id
    )
    credit_sha = sha256_file(credit_path)
    master_sha = sha256_file(master_path)
    if (
        components[0].get("sha256") != credit_sha
        or components[0].get("frames") != credit_facts.get("frame_count")
        or components[1].get("frames") != EXPECTED_GAP_FRAMES
        or components[2].get("sha256") != master_sha
        or components[2].get("frames") != master_facts.get("frame_count")
    ):
        raise DilonIdentityQAError("identity_component_identity_mismatch", "Identity components не совпадают с approved sources.")

    output = manifest.get("output")
    if not isinstance(output, Mapping):
        raise DilonIdentityQAError("identity_output_missing", "Identity output metadata отсутствует.")
    output_path = _regular(Path(str(output.get("path") or "")), root=root, label="Dilon identity output")
    output_facts = _wav(output_path, "Dilon identity output")
    expected_frames = int(credit_facts["frame_count"]) + EXPECTED_GAP_FRAMES + int(master_facts["frame_count"])
    if output_facts.get("frame_count") != expected_frames or output.get("sha256") != sha256_file(output_path):
        raise DilonIdentityQAError("identity_output_identity_mismatch", "Identity output hash/duration не совпадают.")

    with wave.open(str(output_path), "rb") as joined, wave.open(str(credit_path), "rb") as credit, wave.open(str(master_path), "rb") as master:
        if not _same_frames(credit, joined, int(credit_facts["frame_count"])):
            raise DilonIdentityQAError("opening_credit_pcm_mismatch", "Opening credit PCM в identity output изменён.")
        if not _silent_frames(joined, EXPECTED_GAP_FRAMES):
            raise DilonIdentityQAError("identity_gap_not_silent", "Identity gap не является точной цифровой тишиной 0.5 с.")
        if not _same_frames(master, joined, int(master_facts["frame_count"])):
            raise DilonIdentityQAError("clean_master_pcm_mismatch", "Clean master PCM в identity output изменён.")
        if joined.readframes(1):
            raise DilonIdentityQAError("identity_trailing_audio", "Identity output содержит лишние PCM frames.")

    if _has_clipping(output_path):
        raise DilonIdentityQAError("identity_clipping", "Identity output содержит clipped PCM samples.")

    return {
        "schema_version": QA_SCHEMA_VERSION,
        "status": "PASS",
        "build_identity": manifest.get("build_identity"),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "opening_credit_sha256": credit_sha,
        "clean_master_sha256": master_sha,
        "gap_frames": EXPECTED_GAP_FRAMES,
        "gap_seconds": "0.5",
        "frame_count": expected_frames,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }
