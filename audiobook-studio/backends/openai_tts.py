"""Public production facade for Audiobook Studio's OpenAI TTS backend."""

from .openai_client import (
    OpenAITTSBackend as _BaseOpenAITTSBackend,
    load_approved_profile,
    make_fingerprint,
    normalize_input_text,
    read_credential_from_keychain,
    segment_text,
    text_sha256,
)
from .openai_pricing import OpenAIPricingConfig, build_preflight, load_pricing_config
from .openai_types import (
    DEFAULT_ENDPOINT,
    ENGINE_ID,
    OpenAIBackendConfig,
    OpenAICredential,
    OpenAISynthesisResult,
    OpenAITTSError,
    OpenAITextSegment,
    PaidExecutionBlocked,
    load_backend_config,
)
from .pronunciation_markup import openai_instruction_suffix


class OpenAITTSBackend(_BaseOpenAITTSBackend):
    """OpenAI backend that turns canonical stress marks into exact instructions.

    The canonical input itself keeps the Unicode stress mark, so cache and plan
    fingerprints change when the owner changes an accent. The instruction suffix
    is a deterministic function of that same segment text; provider syntax never
    leaks into the editable literary/TTS working copy.
    """

    def build_synthesis_payload(self, text: str, profile_id: str) -> dict[str, str]:
        payload = super().build_synthesis_payload(text, profile_id)
        suffix = openai_instruction_suffix(text)
        if suffix:
            base = payload["instructions"].rstrip()
            payload["instructions"] = f"{base}\n\n{suffix}"
        return payload


__all__ = [
    "DEFAULT_ENDPOINT",
    "ENGINE_ID",
    "OpenAIBackendConfig",
    "OpenAICredential",
    "OpenAIPricingConfig",
    "OpenAISynthesisResult",
    "OpenAITTSError",
    "OpenAITTSBackend",
    "OpenAITextSegment",
    "PaidExecutionBlocked",
    "build_preflight",
    "load_approved_profile",
    "load_backend_config",
    "load_pricing_config",
    "make_fingerprint",
    "normalize_input_text",
    "read_credential_from_keychain",
    "segment_text",
    "text_sha256",
]
