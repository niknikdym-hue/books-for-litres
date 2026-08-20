"""TTS backends for the universal Audiobook Studio."""

from .yandex_speechkit import (
    ENGINE_ID as YANDEX_ENGINE_ID,
    YandexBackendConfig,
    YandexSpeechKitBackend,
    YandexSpeechKitError,
    YandexVoiceProfile,
    load_backend_config,
    segment_text,
)

__all__ = [
    "YANDEX_ENGINE_ID",
    "YandexBackendConfig",
    "YandexSpeechKitBackend",
    "YandexSpeechKitError",
    "YandexVoiceProfile",
    "load_backend_config",
    "segment_text",
]
