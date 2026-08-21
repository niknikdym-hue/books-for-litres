"""Fail-closed production OpenAI Speech backend for Audiobook Studio."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from voice_library import load_voice_library

from .common import (
    WavTruncatedError,
    WavValidationError,
    atomic_write_json,
    inspect_pcm_wav,
    materialize_validated_file,
    utc_now_iso,
    wav_size_markers,
)
from .openai_pricing import OpenAIPricingConfig, build_preflight
from .openai_types import (
    ENGINE_ID,
    FINGERPRINT_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PROVIDER,
    OpenAIBackendConfig,
    OpenAICredential,
    OpenAISynthesisResult,
    OpenAITTSError,
    OpenAITextSegment,
    PaidExecutionBlocked,
)


_READ_SIZE = 64 * 1024


def normalize_input_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.strip())


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_approved_profile(profile_id: str) -> dict[str, Any]:
    profiles = [
        profile for profile in load_voice_library(provider="openai")
        if profile["profile_id"] == profile_id
    ]
    if len(profiles) != 1:
        raise OpenAITTSError(
            f"OpenAI profile is not approved: {profile_id}.",
            category="profile",
        )
    profile = profiles[0]
    if not profile.get("instructions"):
        raise OpenAITTSError(
            f"Approved OpenAI profile has no stable instructions: {profile_id}.",
            category="profile",
        )
    if profile.get("voice_source") != "builtin" or profile.get("response_format") != "wav":
        raise OpenAITTSError("Unsupported OpenAI production profile contract.", category="profile")
    return profile


def make_fingerprint(text: str, profile: Mapping[str, Any]) -> str:
    normalized = normalize_input_text(text)
    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "provider": PROVIDER,
        "profile_id": profile["profile_id"],
        "model": profile["model"],
        "voice_source": profile["voice_source"],
        "voice": profile["voice"],
        "instructions": profile["instructions"],
        "response_format": profile["response_format"],
        "normalized_input_text_sha256": text_sha256(normalized),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fits(text: str, config: OpenAIBackendConfig, *, target: bool = False) -> bool:
    char_limit = config.target_chars if target else config.hard_chars
    return len(text) <= char_limit and len(text.encode("utf-8")) <= config.hard_utf8_bytes


def _split_oversized_piece(text: str, config: OpenAIBackendConfig) -> list[str]:
    text = normalize_input_text(text)
    if _fits(text, config):
        return [text]

    clauses = [part.strip() for part in re.split(r"(?<=[,;:—])\s+", text) if part.strip()]
    if len(clauses) > 1:
        output: list[str] = []
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip()
            if current and not _fits(candidate, config):
                output.extend(_split_oversized_piece(current, config))
                current = clause
            else:
                current = candidate
        if current:
            output.extend(_split_oversized_piece(current, config))
        return output

    output = []
    words: list[str] = []
    for word in text.split():
        if not _fits(word, config):
            raise OpenAITTSError(
                "A single token exceeds the conservative OpenAI backend limit; words are never cut.",
                category="segment_limit",
            )
        candidate = " ".join(words + [word])
        if words and not _fits(candidate, config):
            output.append(" ".join(words))
            words = [word]
        else:
            words.append(word)
    if words:
        output.append(" ".join(words))
    return output


def segment_text(text: str, config: OpenAIBackendConfig) -> list[OpenAITextSegment]:
    paragraphs = [part for part in re.split(r"\n\s*\n+", text.strip()) if part.strip()]
    raw: list[OpenAITextSegment] = []
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        paragraph = normalize_input_text(paragraph)
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?…])\s+", paragraph)
            if sentence.strip()
        ] or [paragraph]
        pieces: list[str] = []
        for sentence in sentences:
            pieces.extend(_split_oversized_piece(sentence, config))

        packed: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and not _fits(candidate, config, target=True):
                packed.append(current)
                current = piece
            else:
                current = candidate
        if current:
            packed.append(current)

        for index, piece in enumerate(packed):
            if not _fits(piece, config):
                raise OpenAITTSError("OpenAI segment exceeds the backend safety limit.", category="segment_limit")
            raw.append(OpenAITextSegment(
                segment_id="",
                text=piece,
                pause_after_ms=(
                    config.paragraph_pause_ms if index == len(packed) - 1
                    else config.sentence_pause_ms
                ),
                paragraph_index=paragraph_index,
            ))
    if raw:
        last = raw[-1]
        raw[-1] = OpenAITextSegment("", last.text, 0, last.paragraph_index)
    return [
        OpenAITextSegment(f"s{index:04d}", segment.text, segment.pause_after_ms, segment.paragraph_index)
        for index, segment in enumerate(raw, start=1)
    ]


def validate_api_key(value: str) -> None:
    if not value or len(value) < 20:
        raise OpenAITTSError("OpenAI credential is unavailable or invalid.", category="credentials")
    if value != value.strip() or any(character.isspace() for character in value):
        raise OpenAITTSError("OpenAI credential contains whitespace.", category="credentials")


def read_credential_from_keychain(
    service: str,
    account: str = "",
    *,
    runner: Callable[..., Any] = subprocess.run,
    username_loader: Callable[..., str] = subprocess.check_output,
) -> OpenAICredential:
    if not account:
        try:
            account = username_loader(["/usr/bin/id", "-un"], text=True).strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise OpenAITTSError("Unable to determine the Keychain account.", category="credentials") from error
    try:
        result = runner(
            ["/usr/bin/security", "find-generic-password", "-a", account, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise OpenAITTSError("macOS Keychain utility is unavailable.", category="credentials") from error
    value = result.stdout.strip() if result.returncode == 0 else ""
    if not value:
        raise OpenAITTSError("OpenAI credential is not available in macOS Keychain.", category="credentials")
    validate_api_key(value)
    return OpenAICredential(value=value)


def request_id_from_headers(headers: Any) -> str | None:
    for name in ("x-request-id", "request-id", "openai-request-id"):
        value = headers.get(name) if headers is not None else None
        if value:
            return str(value)
    return None


def _response_diagnostics(
    *,
    headers: Any,
    request_id: str | None,
    http_status: int | None,
    content_length: int | None,
    bytes_written: int,
    part_path: Path | None = None,
) -> dict[str, Any]:
    diagnostics = {
        "request_id": request_id,
        "http_status": http_status,
        "content_type": headers.get("Content-Type") if headers is not None else None,
        "content_length": content_length,
        "bytes_written": bytes_written,
        "riff_declared_size": None,
        "data_declared_size": None,
        "riff_size_sentinel": False,
        "data_size_sentinel": False,
    }
    if part_path is not None and part_path.exists():
        diagnostics.update(wav_size_markers(part_path))
    return diagnostics


def _forensic_artifact_path(output_path: Path) -> Path:
    output_path = Path(output_path)
    job_root = output_path.parent.parent if output_path.parent.name == "segments" else output_path.parent
    return job_root / "diagnostics" / f"{output_path.name}.ambiguous"


class OpenAITTSBackend:
    def __init__(
        self,
        config: OpenAIBackendConfig,
        *,
        credential_loader: Callable[[str, str], OpenAICredential] = read_credential_from_keychain,
        opener: Callable[..., Any] = urllib.request.urlopen,
        billing_ledger: Any | None = None,
    ) -> None:
        self.config = config
        self._credential_loader = credential_loader
        self._opener = opener
        self._billing_ledger = billing_ledger

    def _record_billing_event(
        self,
        *,
        job_id: str,
        segment_id: str,
        request_id: str | None,
        profile_id: str,
        fingerprint: str,
        timestamp: str,
    ) -> str | None:
        if self._billing_ledger is None:
            return None
        transaction_id, _ = self._billing_ledger.record(
            provider="openai",
            job_id=job_id,
            segment_id=segment_id,
            request_id=request_id,
            profile_id=profile_id,
            timestamp=timestamp,
            currency="USD",
            actual_cost=None,
            cost_source="unavailable",
            fingerprint=fingerprint,
        )
        return transaction_id

    def list_voices(self) -> list[dict[str, Any]]:
        return load_voice_library(provider="openai")

    def credential_available(self) -> bool:
        try:
            self._credential_loader(self.config.keychain_service, self.config.keychain_account)
        except OpenAITTSError:
            return False
        return True

    def status(self, *, check_credentials: bool = False) -> dict[str, Any]:
        return {
            "engine": ENGINE_ID,
            "endpoint": self.config.endpoint,
            "approved_profiles": [profile["profile_id"] for profile in self.list_voices()],
            "cache_root": str(self.config.cache_root),
            "paid_execution_enabled": self.config.paid_execution_enabled,
            "credential_available": self.credential_available() if check_credentials else None,
            "credential_check": "performed" if check_credentials else "not_attempted",
            "remote_request_sent": False,
        }

    def segment(self, text: str) -> list[OpenAITextSegment]:
        return segment_text(text, self.config)

    def build_synthesis_payload(self, text: str, profile_id: str) -> dict[str, str]:
        profile = load_approved_profile(profile_id)
        normalized = normalize_input_text(text)
        self._validate_segment_input(normalized)
        return {
            "model": str(profile["model"]),
            "input": normalized,
            "voice": str(profile["voice"]),
            "instructions": str(profile["instructions"]),
            "response_format": str(profile["response_format"]),
        }

    def _validate_segment_input(self, text: str) -> None:
        if not text:
            raise OpenAITTSError("OpenAI synthesis input is empty.", category="input")
        if not _fits(text, self.config):
            raise OpenAITTSError(
                "OpenAI segment exceeds conservative character/token safety limits.",
                category="segment_limit",
            )

    def _cache_path(self, fingerprint: str) -> Path:
        return self.config.cache_root / f"{fingerprint}.wav"

    @staticmethod
    def _valid_wav(path: Path) -> dict[str, Any] | None:
        try:
            return inspect_pcm_wav(path).to_dict()
        except WavValidationError:
            return None

    def _request_to_part(
        self,
        payload: Mapping[str, str],
        part_path: Path,
    ) -> tuple[str | None, dict[str, Any]]:
        credential = self._credential_loader(
            self.config.keychain_service,
            self.config.keychain_account,
        )
        validate_api_key(credential.value)
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {credential.value}",
                "Content-Type": "application/json",
                "Accept": "audio/wav",
            },
        )
        try:
            response = self._opener(request, timeout=self.config.request_timeout_seconds)
        except urllib.error.HTTPError as error:
            request_id = request_id_from_headers(error.headers)
            state = "AMBIGUOUS" if 500 <= error.code <= 599 else "FAILED"
            category = "server_ambiguous" if state == "AMBIGUOUS" else (
                "rate_limit" if error.code == 429 else "http_client"
            )
            diagnostic = OpenAITTSError(
                f"OpenAI Speech HTTP {error.code}.",
                category=category,
                state=state,
                request_id=request_id,
                http_status=error.code,
                diagnostics=_response_diagnostics(
                    headers=error.headers,
                    request_id=request_id,
                    http_status=error.code,
                    content_length=None,
                    bytes_written=0,
                ),
            )
            error.close()
            raise diagnostic from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise OpenAITTSError(
                "OpenAI request outcome is ambiguous; automatic retry is forbidden.",
                category="network_ambiguous",
                state="AMBIGUOUS",
            ) from error

        request_id = request_id_from_headers(getattr(response, "headers", None))
        headers = getattr(response, "headers", {})
        status = int(getattr(response, "status", 200))
        expected_length: int | None = None
        written = 0
        try:
            if status < 200 or status >= 300:
                raise OpenAITTSError(
                    f"Unexpected OpenAI Speech status {status}.",
                    category="http",
                    state="AMBIGUOUS" if status >= 500 else "FAILED",
                    request_id=request_id,
                    http_status=status,
                    diagnostics=_response_diagnostics(
                        headers=headers,
                        request_id=request_id,
                        http_status=status,
                        content_length=None,
                        bytes_written=0,
                    ),
                )
            content_length_value = headers.get("Content-Length")
            try:
                expected_length = int(content_length_value) if content_length_value else None
                if expected_length is not None and expected_length < 0:
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise OpenAITTSError(
                    "OpenAI audio response has an invalid Content-Length.",
                    category="response_protocol",
                    state="AMBIGUOUS",
                    request_id=request_id,
                    http_status=status,
                    diagnostics=_response_diagnostics(
                        headers=headers,
                        request_id=request_id,
                        http_status=status,
                        content_length=None,
                        bytes_written=0,
                    ),
                ) from error
            with part_path.open("wb") as output:
                while True:
                    try:
                        chunk = response.read(_READ_SIZE)
                    except http.client.IncompleteRead as error:
                        if error.partial:
                            output.write(error.partial)
                            written += len(error.partial)
                        raise
                    if not chunk:
                        break
                    output.write(chunk)
                    written += len(chunk)
            if expected_length is not None and written != expected_length:
                raise OpenAITTSError(
                    "OpenAI audio response ended before Content-Length was satisfied.",
                    category="truncated_response",
                    state="AMBIGUOUS",
                    request_id=request_id,
                    http_status=status,
                    diagnostics=_response_diagnostics(
                        headers=headers,
                        request_id=request_id,
                        http_status=status,
                        content_length=expected_length,
                        bytes_written=written,
                        part_path=part_path,
                    ),
                )
        except OpenAITTSError:
            raise
        except (http.client.IncompleteRead, TimeoutError, socket.timeout, OSError) as error:
            raise OpenAITTSError(
                "OpenAI audio stream was interrupted; automatic retry is forbidden.",
                category="network_ambiguous",
                state="AMBIGUOUS",
                request_id=request_id,
                http_status=status,
                diagnostics=_response_diagnostics(
                    headers=headers,
                    request_id=request_id,
                    http_status=status,
                    content_length=expected_length,
                    bytes_written=written,
                    part_path=part_path,
                ),
            ) from error
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return request_id, _response_diagnostics(
            headers=headers,
            request_id=request_id,
            http_status=status,
            content_length=expected_length,
            bytes_written=written,
            part_path=part_path,
        )

    def synthesize_segment(
        self,
        text: str,
        output_path: Path,
        *,
        profile_id: str,
    ) -> OpenAISynthesisResult:
        profile = load_approved_profile(profile_id)
        normalized = normalize_input_text(text)
        self._validate_segment_input(normalized)
        fingerprint = make_fingerprint(normalized, profile)
        output_path = Path(output_path)
        cache_path = self._cache_path(fingerprint)

        cached_metadata = self._valid_wav(cache_path) if cache_path.exists() else None
        if cached_metadata is not None:
            materialize_validated_file(cache_path, output_path, validator=inspect_pcm_wav)
            return OpenAISynthesisResult(
                ENGINE_ID, PROVIDER, profile_id, profile["model"], profile["voice"],
                str(output_path), None, fingerprint, True, cached_metadata,
            )

        if not self.config.paid_execution_enabled:
            raise PaidExecutionBlocked()

        payload = self.build_synthesis_payload(normalized, profile_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = output_path.with_suffix(output_path.suffix + ".part")
        request_id: str | None = None
        response_diagnostics: dict[str, Any] | None = None
        try:
            request_id, response_diagnostics = self._request_to_part(payload, part_path)
            try:
                metadata = inspect_pcm_wav(part_path).to_dict()
            except WavTruncatedError as error:
                raise OpenAITTSError(
                    "OpenAI WAV response ended before all declared audio data arrived.",
                    category="truncated_response",
                    state="AMBIGUOUS",
                    request_id=request_id,
                    http_status=response_diagnostics.get("http_status"),
                    diagnostics={**response_diagnostics, **wav_size_markers(part_path)},
                ) from error
            except WavValidationError as error:
                raise OpenAITTSError(
                    "OpenAI response is not a valid supported PCM WAV.",
                    category="audio_integrity",
                    state="FAILED",
                    request_id=request_id,
                    http_status=response_diagnostics.get("http_status"),
                    diagnostics={**response_diagnostics, **wav_size_markers(part_path)},
                ) from error
            os.replace(part_path, output_path)
        except OpenAITTSError as error:
            if error.state == "AMBIGUOUS" and part_path.exists() and part_path.stat().st_size > 0:
                forensic_path = _forensic_artifact_path(output_path)
                forensic_path.parent.mkdir(parents=True, exist_ok=True)
                suffix = 2
                while forensic_path.exists():
                    forensic_path = forensic_path.with_name(
                        f"{output_path.name}.{suffix}.ambiguous"
                    )
                    suffix += 1
                os.replace(part_path, forensic_path)
                error.forensic_artifact_path = str(forensic_path)
                error.diagnostics = {
                    **error.diagnostics,
                    **wav_size_markers(forensic_path),
                    "bytes_written": forensic_path.stat().st_size,
                }
            raise
        finally:
            if part_path.exists():
                part_path.unlink()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists() and self._valid_wav(cache_path) is None:
            cache_path.unlink()
        if not cache_path.exists():
            cache_part = cache_path.with_suffix(".wav.part")
            try:
                shutil.copy2(output_path, cache_part)
                inspect_pcm_wav(cache_part)
                os.replace(cache_part, cache_path)
            finally:
                if cache_part.exists():
                    cache_part.unlink()
        return OpenAISynthesisResult(
            ENGINE_ID, PROVIDER, profile_id, profile["model"], profile["voice"],
            str(output_path), request_id, fingerprint, False, metadata, response_diagnostics,
        )

    def _recover_existing(
        self,
        entry: dict[str, Any],
        *,
        output_path: Path,
        fingerprint: str,
    ) -> bool:
        if entry.get("fingerprint") != fingerprint:
            return False
        if output_path.exists() and self._valid_wav(output_path) is not None:
            return True
        cache_path = self._cache_path(fingerprint)
        if cache_path.exists() and self._valid_wav(cache_path) is not None:
            materialize_validated_file(cache_path, output_path, validator=inspect_pcm_wav)
            entry["cache_status"] = "HIT"
            return True
        return False

    def preflight(
        self,
        text: str,
        *,
        profile_id: str,
        pricing: OpenAIPricingConfig,
        job_dir: Path | None = None,
    ) -> dict[str, Any]:
        profile = load_approved_profile(profile_id)
        segments = self.segment(text)
        entries: dict[str, Any] = {}
        if job_dir is not None:
            manifest_path = Path(job_dir) / "MANIFEST.json"
            if manifest_path.exists():
                try:
                    entries = dict(json.loads(manifest_path.read_text(encoding="utf-8")).get("segments", {}))
                except (OSError, ValueError, TypeError):
                    entries = {}

        cached_indexes: set[int] = set()
        plan: list[dict[str, Any]] = []
        for index, segment in enumerate(segments):
            fingerprint = make_fingerprint(segment.text, profile)
            cache_path = self._cache_path(fingerprint)
            entry = entries.get(segment.segment_id, {})
            cache_hit = cache_path.exists() and self._valid_wav(cache_path) is not None
            if not cache_hit and isinstance(entry, dict) and entry.get("fingerprint") == fingerprint:
                output_value = entry.get("output_path")
                output_path = Path(output_value) if isinstance(output_value, str) else None
                cache_hit = bool(
                    entry.get("state") == "SUCCEEDED"
                    and output_path is not None
                    and output_path.exists()
                    and self._valid_wav(output_path) is not None
                )
            if cache_hit:
                cached_indexes.add(index)
            plan.append({
                "segment_id": segment.segment_id,
                "fingerprint": fingerprint,
                "characters": len(segment.text),
                "utf8_bytes": len(segment.text.encode("utf-8")),
                "cache_status": "HIT" if cache_hit else "MISS",
                "state": entry.get("state", "PENDING") if isinstance(entry, dict) else "PENDING",
            })

        result = build_preflight(
            [segment.text for segment in segments],
            cached_segment_indexes=cached_indexes,
            instructions=str(profile["instructions"]),
            pricing=pricing,
            paid_execution_enabled=self.config.paid_execution_enabled,
        )
        result["profile_id"] = profile_id
        result["segment_plan"] = plan
        return result

    def prepare_job(
        self,
        text: str,
        job_dir: Path,
        *,
        job_id: str,
        profile_id: str,
        pricing: OpenAIPricingConfig,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = load_approved_profile(profile_id)
        segments = self.segment(text)
        if not segments:
            raise OpenAITTSError("OpenAI job contains no segments.", category="input")
        job_dir = Path(job_dir)
        segment_dir = job_dir / "segments"
        segment_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = job_dir / "MANIFEST.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
                or manifest.get("provider") != PROVIDER
                or manifest.get("job_id") != job_id
                or manifest.get("profile_id") != profile_id
            ):
                raise OpenAITTSError("Existing manifest does not match the OpenAI job.", category="manifest")
        else:
            manifest = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "provider": PROVIDER,
                "engine": ENGINE_ID,
                "job_id": job_id,
                "profile_id": profile_id,
                "model": profile["model"],
                "voice": profile["voice"],
                "created_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
                "state": "PENDING",
                "automatic_retry_count": 0,
                "segments": {},
            }

        entries: dict[str, Any] = manifest.setdefault("segments", {})
        cached_indexes: set[int] = set()
        for index, segment in enumerate(segments):
            normalized = normalize_input_text(segment.text)
            fingerprint = make_fingerprint(normalized, profile)
            output_path = segment_dir / f"{segment.segment_id}__{fingerprint[:12]}.wav"
            existing = entries.get(segment.segment_id)
            if not isinstance(existing, dict) or existing.get("fingerprint") != fingerprint:
                existing = {
                    "segment_id": segment.segment_id,
                    "text_sha256": text_sha256(normalized),
                    "fingerprint": fingerprint,
                    "provider": PROVIDER,
                    "profile_id": profile_id,
                    "model": profile["model"],
                    "voice": profile["voice"],
                    "state": "PENDING",
                    "cache_status": "MISS",
                    "output_path": str(output_path),
                    "request_id": None,
                    "attempt_count": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error_category": None,
                    "response_diagnostics": None,
                    "forensic_artifact_path": None,
                    "pause_after_ms": segment.pause_after_ms,
                    "paragraph_index": segment.paragraph_index,
                }
            cache_path = self._cache_path(fingerprint)
            if cache_path.exists() and self._valid_wav(cache_path) is not None:
                existing["cache_status"] = "HIT"
                cached_indexes.add(index)
            elif existing.get("state") == "SUCCEEDED" and self._recover_existing(
                existing, output_path=output_path, fingerprint=fingerprint
            ):
                cached_indexes.add(index)
            else:
                existing["cache_status"] = "MISS"
            entries[segment.segment_id] = existing

        preflight = build_preflight(
            [segment.text for segment in segments],
            cached_segment_indexes=cached_indexes,
            instructions=str(profile["instructions"]),
            pricing=pricing,
            paid_execution_enabled=self.config.paid_execution_enabled,
        )
        manifest["preflight"] = preflight
        manifest["updated_at"] = utc_now_iso()
        atomic_write_json(manifest_path, manifest)
        return manifest, preflight

    def run_text_job(
        self,
        text: str,
        job_dir: Path,
        *,
        job_id: str,
        profile_id: str,
        pricing: OpenAIPricingConfig,
    ) -> Path:
        job_dir = Path(job_dir)
        manifest_path = job_dir / "MANIFEST.json"
        manifest, preflight = self.prepare_job(
            text,
            job_dir,
            job_id=job_id,
            profile_id=profile_id,
            pricing=pricing,
        )
        profile = load_approved_profile(profile_id)
        segments = self.segment(text)
        entries: dict[str, Any] = manifest["segments"]

        for segment in segments:
            entry = entries[segment.segment_id]
            fingerprint = make_fingerprint(segment.text, profile)
            output_path = Path(entry["output_path"])

            if entry["state"] == "SUCCEEDED" and self._recover_existing(
                entry, output_path=output_path, fingerprint=fingerprint
            ):
                continue
            if entry["state"] == "IN_FLIGHT":
                if self._recover_existing(entry, output_path=output_path, fingerprint=fingerprint):
                    finished_at = utc_now_iso()
                    entry.update({"state": "SUCCEEDED", "finished_at": finished_at, "error_category": None})
                    entry["billing_transaction_id"] = self._record_billing_event(
                        job_id=job_id,
                        segment_id=segment.segment_id,
                        request_id=entry.get("request_id"),
                        profile_id=profile_id,
                        fingerprint=fingerprint,
                        timestamp=finished_at,
                    )
                    atomic_write_json(manifest_path, manifest)
                    continue
                entry.update({"state": "AMBIGUOUS", "error_category": "resume_ambiguous"})
                manifest["state"] = "AMBIGUOUS"
                atomic_write_json(manifest_path, manifest)
                raise OpenAITTSError(
                    f"Segment {segment.segment_id} was IN_FLIGHT without a valid artifact.",
                    category="resume_ambiguous",
                    state="AMBIGUOUS",
                    request_id=entry.get("request_id"),
                )
            if entry["state"] == "AMBIGUOUS":
                raise OpenAITTSError(
                    f"Segment {segment.segment_id} is AMBIGUOUS and requires human resolution.",
                    category="resume_ambiguous",
                    state="AMBIGUOUS",
                    request_id=entry.get("request_id"),
                )
            if entry["state"] == "FAILED":
                raise OpenAITTSError(
                    f"Segment {segment.segment_id} is FAILED and requires an explicit future action.",
                    category="resume_failed",
                )

            cache_path = self._cache_path(fingerprint)
            if cache_path.exists() and self._valid_wav(cache_path) is not None:
                materialize_validated_file(cache_path, output_path, validator=inspect_pcm_wav)
                entry.update({
                    "state": "SUCCEEDED",
                    "cache_status": "HIT",
                    "finished_at": utc_now_iso(),
                    "error_category": None,
                })
                atomic_write_json(manifest_path, manifest)
                continue

            if not preflight["allowed_to_start"]:
                manifest["state"] = "PENDING"
                atomic_write_json(manifest_path, manifest)
                raise PaidExecutionBlocked()

            entry.update({
                "state": "IN_FLIGHT",
                "attempt_count": int(entry.get("attempt_count", 0)) + 1,
                "started_at": utc_now_iso(),
                "finished_at": None,
                "error_category": None,
            })
            manifest["state"] = "IN_FLIGHT"
            atomic_write_json(manifest_path, manifest)
            try:
                result = self.synthesize_segment(
                    segment.text,
                    output_path,
                    profile_id=profile_id,
                )
            except OpenAITTSError as error:
                entry.update({
                    "state": error.state,
                    "request_id": error.request_id,
                    "finished_at": utc_now_iso(),
                    "error_category": error.category,
                    "response_diagnostics": dict(error.diagnostics),
                    "forensic_artifact_path": error.forensic_artifact_path,
                })
                manifest["state"] = error.state
                atomic_write_json(manifest_path, manifest)
                raise
            finished_at = utc_now_iso()
            entry.update({
                "state": "SUCCEEDED",
                "cache_status": "HIT" if result.cached else "STORED",
                "request_id": result.request_id,
                "finished_at": finished_at,
                "error_category": None,
                "wav_metadata": result.wav_metadata,
                "response_diagnostics": result.response_diagnostics,
                "forensic_artifact_path": None,
            })
            if not result.cached:
                entry["billing_transaction_id"] = self._record_billing_event(
                    job_id=job_id,
                    segment_id=segment.segment_id,
                    request_id=result.request_id,
                    profile_id=profile_id,
                    fingerprint=fingerprint,
                    timestamp=finished_at,
                )
            atomic_write_json(manifest_path, manifest)

        manifest["state"] = "SUCCEEDED"
        manifest["finished_at"] = utc_now_iso()
        manifest["updated_at"] = utc_now_iso()
        atomic_write_json(manifest_path, manifest)
        return manifest_path

    def run_approved_segment(
        self,
        text: str,
        job_dir: Path,
        *,
        job_id: str,
        profile_id: str,
        pricing: OpenAIPricingConfig,
        selected_segment_id: str | None,
    ) -> tuple[Path, dict[str, Any]]:
        """Materialize free hits and synthesize at most one pre-approved MISS.

        This is the only production primitive used by a one-time paid plan. It
        deliberately cannot accept a list of segment IDs and contains no retry.
        """
        if not self.config.paid_execution_enabled:
            raise PaidExecutionBlocked()
        job_dir = Path(job_dir)
        manifest_path = job_dir / "MANIFEST.json"
        manifest, preflight = self.prepare_job(
            text,
            job_dir,
            job_id=job_id,
            profile_id=profile_id,
            pricing=pricing,
        )
        if not preflight["allowed_to_start"]:
            raise PaidExecutionBlocked()
        profile = load_approved_profile(profile_id)
        segments = self.segment(text)
        entries: dict[str, Any] = manifest["segments"]
        network_requests = 0
        selected_seen = selected_segment_id is None
        selected_output: str | None = None

        for segment in segments:
            entry = entries[segment.segment_id]
            fingerprint = make_fingerprint(segment.text, profile)
            output_path = Path(entry["output_path"])
            if segment.segment_id == selected_segment_id:
                selected_seen = True

            if entry["state"] == "SUCCEEDED" and self._recover_existing(
                entry, output_path=output_path, fingerprint=fingerprint
            ):
                if segment.segment_id == selected_segment_id:
                    selected_output = str(output_path)
                continue
            if entry["state"] == "IN_FLIGHT":
                if self._recover_existing(entry, output_path=output_path, fingerprint=fingerprint):
                    finished_at = utc_now_iso()
                    entry.update({"state": "SUCCEEDED", "finished_at": finished_at, "error_category": None})
                    entry["billing_transaction_id"] = self._record_billing_event(
                        job_id=job_id,
                        segment_id=segment.segment_id,
                        request_id=entry.get("request_id"),
                        profile_id=profile_id,
                        fingerprint=fingerprint,
                        timestamp=finished_at,
                    )
                    atomic_write_json(manifest_path, manifest)
                    continue
                entry.update({"state": "AMBIGUOUS", "error_category": "resume_ambiguous"})
                manifest["state"] = "AMBIGUOUS"
                atomic_write_json(manifest_path, manifest)
                raise OpenAITTSError(
                    f"Segment {segment.segment_id} was IN_FLIGHT without a valid artifact.",
                    category="resume_ambiguous",
                    state="AMBIGUOUS",
                    request_id=entry.get("request_id"),
                )
            if entry["state"] == "AMBIGUOUS":
                raise OpenAITTSError(
                    f"Segment {segment.segment_id} is AMBIGUOUS and requires human resolution.",
                    category="resume_ambiguous",
                    state="AMBIGUOUS",
                    request_id=entry.get("request_id"),
                )
            if entry["state"] == "FAILED":
                raise OpenAITTSError(
                    f"Segment {segment.segment_id} is FAILED and requires an explicit future action.",
                    category="resume_failed",
                )

            cache_path = self._cache_path(fingerprint)
            if cache_path.exists() and self._valid_wav(cache_path) is not None:
                materialize_validated_file(cache_path, output_path, validator=inspect_pcm_wav)
                entry.update({
                    "state": "SUCCEEDED",
                    "cache_status": "HIT",
                    "finished_at": utc_now_iso(),
                    "error_category": None,
                })
                if segment.segment_id == selected_segment_id:
                    selected_output = str(output_path)
                atomic_write_json(manifest_path, manifest)
                continue

            if segment.segment_id != selected_segment_id:
                continue
            if network_requests >= 1:
                raise OpenAITTSError(
                    "One-time paid run request cap was exhausted.",
                    category="request_cap",
                )
            entry.update({
                "state": "IN_FLIGHT",
                "attempt_count": int(entry.get("attempt_count", 0)) + 1,
                "started_at": utc_now_iso(),
                "finished_at": None,
                "error_category": None,
            })
            manifest["state"] = "IN_FLIGHT"
            atomic_write_json(manifest_path, manifest)
            network_requests += 1
            try:
                result = self.synthesize_segment(segment.text, output_path, profile_id=profile_id)
            except OpenAITTSError as error:
                entry.update({
                    "state": error.state,
                    "request_id": error.request_id,
                    "finished_at": utc_now_iso(),
                    "error_category": error.category,
                    "response_diagnostics": dict(error.diagnostics),
                    "forensic_artifact_path": error.forensic_artifact_path,
                })
                manifest["state"] = error.state
                atomic_write_json(manifest_path, manifest)
                raise
            finished_at = utc_now_iso()
            entry.update({
                "state": "SUCCEEDED",
                "cache_status": "HIT" if result.cached else "STORED",
                "request_id": result.request_id,
                "finished_at": finished_at,
                "error_category": None,
                "wav_metadata": result.wav_metadata,
                "response_diagnostics": result.response_diagnostics,
                "forensic_artifact_path": None,
            })
            if not result.cached:
                entry["billing_transaction_id"] = self._record_billing_event(
                    job_id=job_id,
                    segment_id=segment.segment_id,
                    request_id=result.request_id,
                    profile_id=profile_id,
                    fingerprint=fingerprint,
                    timestamp=finished_at,
                )
            selected_output = str(output_path)
            atomic_write_json(manifest_path, manifest)

        if not selected_seen:
            raise OpenAITTSError("Approved OpenAI segment no longer exists.", category="approved_segment_mismatch")
        state_counts: dict[str, int] = {}
        for entry in entries.values():
            state = str(entry.get("state") or "PENDING")
            state_counts[state] = state_counts.get(state, 0) + 1
        if state_counts.get("AMBIGUOUS"):
            manifest["state"] = "AMBIGUOUS"
        elif state_counts.get("FAILED"):
            manifest["state"] = "FAILED"
        elif state_counts.get("PENDING") or state_counts.get("IN_FLIGHT"):
            manifest["state"] = "PARTIAL" if state_counts.get("SUCCEEDED") else "PENDING"
        else:
            manifest["state"] = "SUCCEEDED"
            manifest["finished_at"] = utc_now_iso()
        manifest["updated_at"] = utc_now_iso()
        atomic_write_json(manifest_path, manifest)
        return manifest_path, {
            "network_requests": network_requests,
            "selected_segment_id": selected_segment_id,
            "output_path": selected_output,
            "manifest_state": manifest["state"],
            "remaining_segments": state_counts.get("PENDING", 0),
            "automatic_retry_count": 0,
        }
