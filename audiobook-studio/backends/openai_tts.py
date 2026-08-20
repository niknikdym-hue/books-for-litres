"""Public production facade for Audiobook Studio's OpenAI TTS backend."""

from .openai_client import (
    OpenAITTSBackend,
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
