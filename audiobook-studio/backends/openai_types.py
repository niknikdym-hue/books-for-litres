"""Production contracts for the OpenAI TTS backend."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from workspace_paths import load_workspace_paths


ENGINE_ID = "openai_tts"
PROVIDER = "openai"
DEFAULT_ENDPOINT = "https://api.openai.com/v1/audio/speech"
FINGERPRINT_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
SEGMENT_STATES = {"PENDING", "IN_FLIGHT", "SUCCEEDED", "FAILED", "AMBIGUOUS"}


class OpenAITTSError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        state: str = "FAILED",
        request_id: str | None = None,
        http_status: int | None = None,
        diagnostics: Mapping[str, Any] | None = None,
        forensic_artifact_path: str | None = None,
    ) -> None:
        super().__init__(message)
        if state not in SEGMENT_STATES:
            raise ValueError(f"Invalid OpenAI segment state: {state}")
        self.category = category
        self.state = state
        self.request_id = request_id
        self.http_status = http_status
        self.diagnostics = dict(diagnostics or {})
        self.forensic_artifact_path = forensic_artifact_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "category": self.category,
            "state": self.state,
            "request_id": self.request_id,
            "http_status": self.http_status,
            "response_diagnostics": dict(self.diagnostics),
            "forensic_artifact_path": self.forensic_artifact_path,
            "retryable": False,
        }


class PaidExecutionBlocked(OpenAITTSError):
    def __init__(self) -> None:
        super().__init__(
            "OpenAI paid execution is disabled until the Cloud Billing gate is implemented.",
            category="paid_execution_gate",
            state="FAILED",
        )


@dataclass(frozen=True)
class OpenAICredential:
    value: str
    source_type: str = "macos_keychain"


@dataclass(frozen=True)
class OpenAITextSegment:
    segment_id: str
    text: str
    pause_after_ms: int
    paragraph_index: int


@dataclass(frozen=True)
class OpenAISynthesisResult:
    engine: str
    provider: str
    profile_id: str
    model: str
    voice: str
    output_path: str
    request_id: str | None
    fingerprint: str
    cached: bool
    wav_metadata: dict[str, Any]
    response_diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True)
class OpenAIBackendConfig:
    endpoint: str
    keychain_service: str
    keychain_account: str
    cache_root: Path
    jobs_root: Path
    request_timeout_seconds: int
    paid_execution_enabled: bool
    target_chars: int
    hard_chars: int
    hard_utf8_bytes: int
    api_max_input_tokens: int
    sentence_pause_ms: int
    paragraph_pause_ms: int

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "OpenAIBackendConfig":
        if data.get("engine", ENGINE_ID) != ENGINE_ID:
            raise OpenAITTSError("OpenAI config has the wrong engine.", category="config")
        if int(data.get("schema_version", 0)) != 1:
            raise OpenAITTSError("Unsupported OpenAI config schema.", category="config")
        segmentation = dict(data.get("segmentation") or {})
        config = cls(
            endpoint=str(data.get("endpoint") or DEFAULT_ENDPOINT),
            keychain_service=str(data.get("keychain_service") or "AudiobookStudio-OpenAI"),
            keychain_account=str(data.get("keychain_account") or ""),
            cache_root=Path(str(data.get("cache_root") or "cache/openai")).expanduser(),
            jobs_root=Path(str(data.get("jobs_root") or "jobs")).expanduser(),
            request_timeout_seconds=int(data.get("request_timeout_seconds", 180)),
            paid_execution_enabled=data.get("paid_execution_enabled") is True,
            target_chars=int(segmentation.get("target_chars", 900)),
            hard_chars=int(segmentation.get("hard_chars", 1200)),
            hard_utf8_bytes=int(segmentation.get("hard_utf8_bytes", 2000)),
            api_max_input_tokens=int(segmentation.get("api_max_input_tokens", 2000)),
            sentence_pause_ms=int(segmentation.get("sentence_pause_ms", 350)),
            paragraph_pause_ms=int(segmentation.get("paragraph_pause_ms", 700)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.endpoint != DEFAULT_ENDPOINT or not self.endpoint.startswith("https://"):
            raise OpenAITTSError("Unexpected OpenAI Speech endpoint.", category="config")
        if not (1 <= self.target_chars <= self.hard_chars):
            raise OpenAITTSError("Invalid OpenAI character segmentation limits.", category="config")
        if self.hard_chars >= 2000:
            raise OpenAITTSError("OpenAI hard character limit is not conservative.", category="config")
        if not (1 <= self.hard_utf8_bytes <= self.api_max_input_tokens):
            raise OpenAITTSError("Invalid conservative OpenAI token safety bound.", category="config")
        if self.request_timeout_seconds <= 0:
            raise OpenAITTSError("OpenAI request timeout must be positive.", category="config")


def load_backend_config(path: Path) -> OpenAIBackendConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    paths = load_workspace_paths()
    data["cache_root"] = str(paths.resolve(data.get("cache_root"), "cache/openai"))
    data["jobs_root"] = str(paths.resolve(data.get("jobs_root"), "jobs"))
    return OpenAIBackendConfig.from_mapping(data)
