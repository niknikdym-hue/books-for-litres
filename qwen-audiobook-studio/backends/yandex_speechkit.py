"""Public compatibility facade for the Yandex SpeechKit v3 backend."""

from .yandex_client import YandexSpeechKitBackend, join_wavs_with_pauses
from .yandex_segmenter import segment_text
from .yandex_types import (
    ENGINE_ID,
    DEFAULT_ENDPOINT,
    SynthesisResult,
    TextSegment,
    YandexBackendConfig,
    YandexSpeechKitError,
    YandexVoiceProfile,
    classify_http as _classify_http,
    collapse_ws as _collapse_ws,
    load_backend_config,
    make_fingerprint,
    read_api_key_from_keychain,
    response_payload as _response_payload,
    utc_now_iso,
    validate_api_key,
    wav_info as _wav_info,
)

__all__ = [
    "ENGINE_ID",
    "DEFAULT_ENDPOINT",
    "SynthesisResult",
    "TextSegment",
    "YandexBackendConfig",
    "YandexSpeechKitBackend",
    "YandexSpeechKitError",
    "YandexVoiceProfile",
    "join_wavs_with_pauses",
    "load_backend_config",
    "make_fingerprint",
    "read_api_key_from_keychain",
    "segment_text",
    "utc_now_iso",
    "validate_api_key",
]
