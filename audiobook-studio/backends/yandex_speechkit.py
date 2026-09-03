"""Public compatibility facade for the Yandex SpeechKit v3 backend."""

from .pronunciation_markup import yandex_text_markup
from .yandex_cache_lock import shared_cache_execution_lock
from .yandex_client import YandexSpeechKitBackend as _BaseYandexSpeechKitBackend, join_wavs_with_pauses
from .yandex_pricing import YandexPricingConfig, load_pricing_config, price_estimate
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


class YandexSpeechKitBackend(_BaseYandexSpeechKitBackend):
    """SpeechKit backend with deterministic rendering of owner stress marks.

    Cache/manifest fingerprints intentionally remain bound to the canonical
    human-readable TTS text (``замо́к``). The network payload is a deterministic
    rendering of that exact identity (``зам+ок``), so changing an accent changes
    the text fingerprint before any paid request while keeping provider syntax
    out of the editable working copy.
    """

    def build_synthesis_payload(self, text: str):
        try:
            provider_text = yandex_text_markup(text)
        except ValueError as error:
            raise YandexSpeechKitError(
                "Некорректная ручная разметка ударения в TTS-тексте.",
                category="pronunciation_markup",
            ) from error
        return super().build_synthesis_payload(provider_text)


__all__ = [
    "ENGINE_ID",
    "DEFAULT_ENDPOINT",
    "SynthesisResult",
    "TextSegment",
    "YandexBackendConfig",
    "YandexSpeechKitBackend",
    "YandexPricingConfig",
    "YandexSpeechKitError",
    "YandexVoiceProfile",
    "join_wavs_with_pauses",
    "load_pricing_config",
    "load_backend_config",
    "make_fingerprint",
    "price_estimate",
    "read_api_key_from_keychain",
    "shared_cache_execution_lock",
    "segment_text",
    "utc_now_iso",
    "validate_api_key",
]
