"""Resolve current produced-audio identity from canonical production authorities."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backends.common import inspect_pcm_wav
from book_library import BookLibrary


class AudioQAAuthorityError(RuntimeError):
    """Raised when current synthesis identity cannot be proven offline."""


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AudioQAAuthorityError(f"Invalid production authority: {path}") from error
    if not isinstance(payload, dict):
        raise AudioQAAuthorityError(f"Invalid production authority: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _qwen_profile_id(voice: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", voice.lower()).strip("_")
    return f"qwen_{normalized}" if normalized else ""


def _job(library: BookLibrary, book_name: str, job_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    book = library.load_book_for_execution(book_name)
    job = (book.get("jobs") or {}).get(job_id)
    segments = job.get("segments") if isinstance(job, dict) else None
    if not isinstance(job, dict) or not isinstance(segments, list) or not segments:
        raise AudioQAAuthorityError("Current prepared job is unavailable.")
    texts: list[str] = []
    for segment in segments:
        text = segment.get("text") if isinstance(segment, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise AudioQAAuthorityError("Current prepared job contains invalid text.")
        texts.append(text.strip())
    return book, job, "\n\n".join(texts)


def _canonical_book_slug(library: BookLibrary, book_name: str) -> str:
    """Return the canonical registry identity, never a raw optional profile field."""
    return library.resolve_book_profile(book_name).stem


def _same_path(left: Path, right: Path) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(strict=False)


def _require_below(path: Path, root: Path, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    try:
        resolved.relative_to(Path(root).expanduser().resolve(strict=False))
    except ValueError as error:
        raise AudioQAAuthorityError(f"{label} escapes its production root.") from error
    return resolved


def _require_no_symlink_components(path: Path, root: Path, label: str) -> Path:
    """Require every lexical component below root to be a real path entry."""
    candidate = Path(path).expanduser().absolute()
    boundary = Path(root).expanduser().absolute()
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as error:
        raise AudioQAAuthorityError(f"{label} escapes its production root.") from error
    current = boundary
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise AudioQAAuthorityError(f"{label} cannot contain symlink components.")
    return candidate


def _require_under_allowed_roots(
    path: Path,
    roots: list[Path],
    label: str,
) -> tuple[Path, Path]:
    """Return a canonical path and its lexical provider root, failing closed."""
    candidate = Path(path).expanduser().absolute()
    for root in roots:
        boundary = Path(root).expanduser().absolute()
        try:
            candidate.relative_to(boundary)
        except ValueError:
            continue
        lexical = _require_no_symlink_components(candidate, boundary, label)
        return _require_below(lexical, boundary, label), boundary
    raise AudioQAAuthorityError(f"{label} escapes its production root.")


@dataclass(frozen=True)
class AudioQAAuthority:
    provider: str
    book_slug: str
    book_title: str
    job_id: str
    job_label: str
    profile_id: str
    segment_id: str
    segment_text: str
    audio_path: Path
    manifest_path: Path
    synthesis_fingerprint: str
    expected_sample_rate_hz: int
    text_characters: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "book_slug": self.book_slug,
            "book_title": self.book_title,
            "job_id": self.job_id,
            "job_label": self.job_label,
            "profile_id": self.profile_id,
            "segment_id": self.segment_id,
            "segment_text": self.segment_text,
            "audio_path": str(self.audio_path),
            "manifest_path": str(self.manifest_path),
            "synthesis_fingerprint": self.synthesis_fingerprint,
            "expected_sample_rate_hz": self.expected_sample_rate_hz,
            "text_characters": self.text_characters,
        }


def resolve_qwen_authority(
    *,
    library: BookLibrary,
    book_name: str,
    job_id: str,
    profile_id: str,
    report_candidates: list[Path],
    allowed_output_roots: list[Path],
    config_path: Path,
    audio_path: Path | None = None,
) -> AudioQAAuthority:
    book, job, text = _job(library, book_name, job_id)
    profile_path = library.resolve_book_profile(book_name)
    config = _load_json(config_path)
    expected_generation = dict(config.get("default_generation") or {})
    expected_generation.update(book.get("generation") or {})
    expected_generation.update(job.get("generation") or {})
    expected_instruct = job.get("audiobook_instruct", book.get("audiobook_instruct"))
    expected_segment_ids = [str(item.get("id")) for item in job["segments"]]
    valid: list[tuple[Path, dict[str, Any], Path]] = []
    for candidate in report_candidates:
        lexical_path = Path(candidate).expanduser().absolute()
        path, _ = _require_under_allowed_roots(
            lexical_path, allowed_output_roots, "Qwen production report"
        )
        if not path.is_file():
            continue
        report = _load_json(path)
        speaker = report.get("speaker")
        entries = report.get("segments")
        joined_name = report.get("joined_wav")
        if (
            report.get("book_profile_sha256") != _sha256_file(profile_path)
            or report.get("job") != job_id
            or not isinstance(speaker, str)
            or _qwen_profile_id(speaker) != profile_id
            or report.get("model") != config.get("model")
            or report.get("generation") != expected_generation
            or report.get("audiobook_instruct") != expected_instruct
            or report.get("segment_count") != len(expected_segment_ids)
            or not isinstance(entries, list)
            or [str(entry.get("id")) for entry in entries if isinstance(entry, dict)] != expected_segment_ids
            or not isinstance(joined_name, str)
            or Path(joined_name).name != joined_name
            or not isinstance(report.get("sample_rate"), int)
        ):
            continue
        output, _ = _require_under_allowed_roots(
            lexical_path.parent / joined_name, allowed_output_roots, "Qwen audio"
        )
        if output.is_file() and (audio_path is None or _same_path(audio_path, output)):
            valid.append((path.resolve(), report, output))
    if not valid:
        raise AudioQAAuthorityError("Current Qwen production report was not found.")
    valid.sort(key=lambda item: item[0].stat().st_mtime_ns, reverse=True)
    manifest_path, report, authoritative_audio = valid[0]
    actual_rate = inspect_pcm_wav(authoritative_audio).sample_rate_hz
    if actual_rate != int(report["sample_rate"]):
        raise AudioQAAuthorityError("Qwen output rate disagrees with its production report.")
    synthesis_fingerprint = _canonical_hash({
        "provider": "qwen",
        "book_profile_sha256": report["book_profile_sha256"],
        "job": job_id,
        "profile_id": profile_id,
        "speaker": report["speaker"],
        "model": report["model"],
        "generation": report["generation"],
        "audiobook_instruct": report["audiobook_instruct"],
        "segments": [{"id": item["id"], "seed": item.get("seed")} for item in report["segments"]],
    })
    return AudioQAAuthority(
        provider="qwen",
        book_slug=profile_path.stem,
        book_title=str(book.get("title") or book_name),
        job_id=job_id,
        job_label=str(job.get("label") or job_id),
        profile_id=profile_id,
        segment_id=job_id,
        segment_text=text,
        audio_path=authoritative_audio,
        manifest_path=manifest_path,
        synthesis_fingerprint=synthesis_fingerprint,
        expected_sample_rate_hz=actual_rate,
        text_characters=len(text),
    )


def resolve_yandex_authority(
    *,
    library: BookLibrary,
    backend: Any,
    book_name: str,
    job_id: str,
    profile_id: str,
    manifest_candidates: list[Path],
    allowed_output_roots: list[Path],
    audio_path: Path | None = None,
) -> AudioQAAuthority:
    from backends.yandex_speechkit import make_fingerprint

    if profile_id != "yandex_lera":
        raise AudioQAAuthorityError("Current Yandex QA supports only yandex_lera production output.")
    book, job, text = _job(library, book_name, job_id)
    current_segments = backend.segment(text)
    manifest_path = None
    lexical_manifest_path = None
    for candidate in manifest_candidates:
        lexical_candidate = Path(candidate).expanduser().absolute()
        canonical_candidate, _ = _require_under_allowed_roots(
            lexical_candidate, allowed_output_roots, "Yandex production manifest"
        )
        if canonical_candidate.is_file():
            manifest_path = canonical_candidate
            lexical_manifest_path = lexical_candidate
            break
    if manifest_path is None:
        raise AudioQAAuthorityError("Current Yandex production manifest was not found.")
    manifest = _load_json(manifest_path)
    profile = manifest.get("profile")
    entries = manifest.get("segments")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("engine") != "yandex_speechkit_v3"
        or manifest.get("job_id") != job_id
        or manifest.get("status") != "DONE"
        or not isinstance(profile, dict)
        or profile.get("voice") != backend.profile.voice
        or profile.get("role") != backend.profile.role
        or str(profile.get("speed")) != str(backend.profile.speed)
        or manifest.get("segmentation") != backend.manifest_segmentation()
        or manifest.get("request_routing") != backend.request_routing_identity()
        or not isinstance(entries, dict)
    ):
        raise AudioQAAuthorityError("Current Yandex manifest identity does not match the active pipeline.")

    segment_facts: list[dict[str, Any]] = []
    sample_rates: set[int] = set()
    for segment in current_segments:
        fingerprint = make_fingerprint(segment.text, backend.profile)
        entry = entries.get(segment.segment_id)
        result = entry.get("result") if isinstance(entry, dict) else None
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in {"DONE", "CACHED"}
            or entry.get("fingerprint") != fingerprint
            or entry.get("text") != segment.text
        ):
            raise AudioQAAuthorityError("Yandex manifest is stale against the current prepared text.")
        if isinstance(result, dict) and isinstance(result.get("sample_rate_hz"), int):
            sample_rates.add(int(result["sample_rate_hz"]))
        segment_facts.append({
            "segment_id": segment.segment_id,
            "fingerprint": fingerprint,
            "pause_after_ms": segment.pause_after_ms,
            "paragraph_index": segment.paragraph_index,
        })
    if set(entries) != {segment.segment_id for segment in current_segments}:
        raise AudioQAAuthorityError("Yandex manifest segment set is not current.")
    joined_name = manifest.get("joined_wav")
    if not isinstance(joined_name, str) or not joined_name or Path(joined_name).name != joined_name:
        raise AudioQAAuthorityError("Yandex joined WAV identity is unavailable.")
    assert lexical_manifest_path is not None
    authoritative_audio, _ = _require_under_allowed_roots(
        lexical_manifest_path.parent / joined_name, allowed_output_roots, "Yandex audio"
    )
    if audio_path is not None and not _same_path(audio_path, authoritative_audio):
        raise AudioQAAuthorityError("Selected Yandex audio is not the authoritative joined WAV.")
    if not authoritative_audio.is_file():
        raise AudioQAAuthorityError("Authoritative Yandex joined WAV is unavailable.")
    actual_rate = inspect_pcm_wav(authoritative_audio).sample_rate_hz
    if sample_rates and sample_rates != {actual_rate}:
        raise AudioQAAuthorityError("Yandex output rate disagrees with its segment authority.")
    preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else {}
    synthesis_fingerprint = _canonical_hash({
        "provider": "yandex",
        "book_slug": book.get("slug"),
        "job_id": job_id,
        "preparation_identity": preparation.get("identity_sha256"),
        "profile": {
            "voice": backend.profile.voice,
            "role": backend.profile.role,
            "speed": str(backend.profile.speed),
        },
        "request_routing": backend.request_routing_identity(),
        "segmentation": backend.manifest_segmentation(),
        "segments": segment_facts,
    })
    return AudioQAAuthority(
        provider="yandex",
        book_slug=_canonical_book_slug(library, book_name),
        book_title=str(book.get("title") or book_name),
        job_id=job_id,
        job_label=str(job.get("label") or job_id),
        profile_id=profile_id,
        segment_id=job_id,
        segment_text=text,
        audio_path=authoritative_audio,
        manifest_path=manifest_path.resolve(),
        synthesis_fingerprint=synthesis_fingerprint,
        expected_sample_rate_hz=actual_rate,
        text_characters=len(text),
    )


def _openai_candidates(
    *,
    library: BookLibrary,
    backend: Any,
    book_name: str,
    job_id: str,
    profile_id: str,
    manifest_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    str,
    str,
    Path,
    list[tuple[Any, dict[str, Any], Path, str]],
]:
    from backends.openai_tts import load_approved_profile, make_fingerprint, normalize_input_text

    book, job, text = _job(library, book_name, job_id)
    profile = load_approved_profile(profile_id)
    canonical_book_slug = _canonical_book_slug(library, book_name)
    supplied_manifest = Path(manifest_path).expanduser().absolute()
    expected_manifest = (
        Path(backend.config.jobs_root)
        / canonical_book_slug
        / job_id
        / "openai"
        / profile_id
        / "MANIFEST.json"
    ).expanduser().absolute()
    if supplied_manifest != expected_manifest:
        raise AudioQAAuthorityError("Selected OpenAI manifest is not the canonical job authority.")
    lexical_manifest_parent = supplied_manifest.parent
    _require_no_symlink_components(
        supplied_manifest, Path(backend.config.jobs_root), "Canonical OpenAI manifest"
    )
    manifest_path = _require_below(
        supplied_manifest, Path(backend.config.jobs_root), "OpenAI manifest"
    )
    manifest = _load_json(manifest_path)
    entries = manifest.get("segments")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("provider") != "openai"
        or manifest.get("job_id") != job_id
        or manifest.get("profile_id") != profile_id
        or manifest.get("model") != profile.get("model")
        or manifest.get("voice") != profile.get("voice")
        or not isinstance(entries, dict)
    ):
        raise AudioQAAuthorityError("Current OpenAI manifest identity does not match the active pipeline.")
    current_segments = backend.segment(text)
    candidates: list[tuple[Any, dict[str, Any], Path, str]] = []
    for segment in current_segments:
        fingerprint = make_fingerprint(normalize_input_text(segment.text), profile)
        entry = entries.get(segment.segment_id)
        output_value = entry.get("output_path") if isinstance(entry, dict) else None
        output = None
        if isinstance(output_value, str):
            lexical_output = _require_no_symlink_components(
                Path(output_value), lexical_manifest_parent, "Canonical OpenAI audio"
            )
            output = _require_below(lexical_output, manifest_path.parent, "OpenAI audio")
        if (
            isinstance(entry, dict)
            and entry.get("state") == "SUCCEEDED"
            and entry.get("fingerprint") == fingerprint
            and output is not None
            and output.is_file()
            and not output.is_symlink()
        ):
            candidates.append((segment, entry, output, fingerprint))
    return book, job, canonical_book_slug, text, manifest_path, candidates


def _openai_authority_from_candidate(
    *,
    book: Mapping[str, Any],
    job: Mapping[str, Any],
    job_id: str,
    profile_id: str,
    book_name: str,
    canonical_book_slug: str,
    manifest_path: Path,
    candidate: tuple[Any, dict[str, Any], Path, str],
) -> AudioQAAuthority:
    segment, entry, authoritative_audio, fingerprint = candidate
    metadata = entry.get("wav_metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("sample_rate_hz"), int):
        raise AudioQAAuthorityError("OpenAI sample-rate authority is unavailable.")
    actual_rate = inspect_pcm_wav(authoritative_audio).sample_rate_hz
    if actual_rate != int(metadata["sample_rate_hz"]):
        raise AudioQAAuthorityError("OpenAI output rate disagrees with its manifest authority.")
    return AudioQAAuthority(
        provider="openai",
        book_slug=canonical_book_slug,
        book_title=str(book.get("title") or book_name),
        job_id=job_id,
        job_label=str(job.get("label") or job_id),
        profile_id=profile_id,
        segment_id=str(segment.segment_id),
        segment_text=str(segment.text),
        audio_path=authoritative_audio,
        manifest_path=manifest_path,
        synthesis_fingerprint=fingerprint,
        expected_sample_rate_hz=actual_rate,
        text_characters=len(str(segment.text)),
    )


def list_openai_qa_targets(
    *,
    library: BookLibrary,
    backend: Any,
    book_name: str,
    job_id: str,
    profile_id: str,
    manifest_path: Path,
) -> list[dict[str, str]]:
    """List exact current successful OpenAI outputs without provider access."""
    book, job, canonical_slug, _, authority_path, candidates = _openai_candidates(
        library=library,
        backend=backend,
        book_name=book_name,
        job_id=job_id,
        profile_id=profile_id,
        manifest_path=manifest_path,
    )
    targets: list[dict[str, str]] = []
    for candidate in candidates:
        authority = _openai_authority_from_candidate(
            book=book,
            job=job,
            job_id=job_id,
            profile_id=profile_id,
            book_name=book_name,
            canonical_book_slug=canonical_slug,
            manifest_path=authority_path,
            candidate=candidate,
        )
        targets.append({
            "segment_id": authority.segment_id,
            "output_path": str(authority.audio_path),
            "manifest_path": str(authority.manifest_path),
            "synthesis_fingerprint": authority.synthesis_fingerprint,
        })
    return targets


def resolve_openai_authority(
    *,
    library: BookLibrary,
    backend: Any,
    book_name: str,
    job_id: str,
    profile_id: str,
    manifest_path: Path,
    audio_path: Path | None = None,
) -> AudioQAAuthority:
    book, job, canonical_slug, _, authority_path, candidates = _openai_candidates(
        library=library,
        backend=backend,
        book_name=book_name,
        job_id=job_id,
        profile_id=profile_id,
        manifest_path=manifest_path,
    )
    if audio_path is not None:
        candidates = [item for item in candidates if _same_path(item[2], audio_path)]
    if len(candidates) != 1:
        raise AudioQAAuthorityError("OpenAI produced segment selection is not unambiguous.")
    return _openai_authority_from_candidate(
        book=book,
        job=job,
        job_id=job_id,
        profile_id=profile_id,
        book_name=book_name,
        canonical_book_slug=canonical_slug,
        manifest_path=authority_path,
        candidate=candidates[0],
    )
