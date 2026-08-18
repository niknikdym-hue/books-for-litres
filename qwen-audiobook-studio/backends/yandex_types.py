from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_ID = "yandex_speechkit_v3"
DEFAULT_ENDPOINT = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"


class YandexSpeechKitError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        retryable: bool = False,
        http_status: int | None = None,
        request_id: str | None = None,
        response_request_id: str | None = None,
        server_trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.http_status = http_status
        self.request_id = request_id
        self.response_request_id = response_request_id
        self.server_trace_id = server_trace_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "category": self.category,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "request_id": self.request_id,
            "response_request_id": self.response_request_id,
            "server_trace_id": self.server_trace_id,
        }


@dataclass(frozen=True)
class YandexVoiceProfile:
    voice: str = "lera"
    role: str = "neutral"
    speed: str = "1.04"
    output_container: str = "WAV"
    loudness_normalization: str = "LUFS"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "YandexVoiceProfile":
        data = data or {}
        return cls(
            voice=str(data.get("voice", "lera")),
            role=str(data.get("role", "neutral")),
            speed=str(data.get("speed", "1.04")),
            output_container=str(data.get("output_container", "WAV")),
            loudness_normalization=str(data.get("loudness_normalization", "LUFS")),
        )


@dataclass(frozen=True)
class TextSegment:
    segment_id: str
    text: str
    pause_after_ms: int
    paragraph_index: int


@dataclass(frozen=True)
class SynthesisResult:
    engine: str
    voice: str
    role: str
    speed: str
    output_path: str
    request_id: str
    response_request_id: str | None
    server_trace_id: str | None
    audio_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    fingerprint: str
    cached: bool


@dataclass(frozen=True)
class YandexBackendConfig:
    endpoint: str
    keychain_service: str
    keychain_account: str
    output_root: Path
    max_chars: int
    max_words: int
    sentence_pause_ms: int
    paragraph_pause_ms: int
    profile: YandexVoiceProfile

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "YandexBackendConfig":
        seg = dict(data.get("segmentation", {}))
        return cls(
            endpoint=str(data.get("endpoint") or DEFAULT_ENDPOINT),
            keychain_service=str(data.get("keychain_service") or "AudiobookStudio-YandexSpeechKit"),
            keychain_account=str(data.get("keychain_account") or ""),
            output_root=Path(str(data.get("output_root") or "~/Audiobook-Studio-Yandex")).expanduser(),
            max_chars=int(seg.get("max_chars", 220)),
            max_words=int(seg.get("max_words", 34)),
            sentence_pause_ms=int(seg.get("sentence_pause_ms", 380)),
            paragraph_pause_ms=int(seg.get("paragraph_pause_ms", 700)),
            profile=YandexVoiceProfile.from_mapping(data.get("default_profile")),
        )


def load_backend_config(path: Path) -> YandexBackendConfig:
    with path.open("r", encoding="utf-8") as f:
        return YandexBackendConfig.from_mapping(json.load(f))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def validate_api_key(api_key: str) -> None:
    if not api_key:
        raise YandexSpeechKitError("API key пустой. Проверьте запись в macOS Keychain.", category="credentials")
    if api_key != api_key.strip() or any(ch.isspace() for ch in api_key):
        raise YandexSpeechKitError("API key содержит пробелы или перевод строки.", category="credentials")
    if len(api_key) < 20:
        raise YandexSpeechKitError(
            f"API key выглядит слишком коротким ({len(api_key)} символов).",
            category="credentials",
        )
    if len(api_key) % 2 == 0:
        half = len(api_key) // 2
        if api_key[:half] == api_key[half:]:
            raise YandexSpeechKitError(
                "API key записан два раза подряд. Оставьте только одну половину ключа.",
                category="credentials_duplicate",
            )


def read_api_key_from_keychain(service: str, account: str = "") -> str:
    if not account:
        account = subprocess.check_output(["/usr/bin/id", "-un"], text=True).strip()
    try:
        key = subprocess.check_output(
            ["/usr/bin/security", "find-generic-password", "-a", account, "-s", service, "-w"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except FileNotFoundError as e:
        raise YandexSpeechKitError(
            "Утилита macOS Keychain /usr/bin/security не найдена.",
            category="platform",
        ) from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip()
        raise YandexSpeechKitError(
            f"Не удалось получить API key из Keychain ({service}/{account}). {detail}".strip(),
            category="credentials",
        ) from e
    validate_api_key(key)
    return key


def collapse_ws(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", text).strip()


def make_fingerprint(text: str, profile: YandexVoiceProfile) -> str:
    payload = {
        "engine": ENGINE_ID,
        "text": text,
        "voice": profile.voice,
        "role": profile.role,
        "speed": profile.speed,
        "output_container": profile.output_container,
        "loudness_normalization": profile.loudness_normalization,
        "unsafe_mode": False,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def response_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("result", data)
    if not isinstance(payload, dict):
        raise YandexSpeechKitError("Некорректная структура ответа SpeechKit.", category="response")
    return payload


def wav_info(path: Path) -> tuple[float, int, int, int]:
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frames = wf.getnframes()
    except (wave.Error, EOFError) as e:
        raise YandexSpeechKitError(f"Некорректный WAV: {path}", category="audio_integrity") from e
    if channels != 1:
        raise YandexSpeechKitError(f"Ожидался mono WAV, получено каналов: {channels}", category="audio_integrity")
    if sample_width != 2:
        raise YandexSpeechKitError(
            f"Ожидался 16-bit PCM WAV, sample width={sample_width}",
            category="audio_integrity",
        )
    if sample_rate <= 0 or frames <= 0:
        raise YandexSpeechKitError("WAV пустой или имеет некорректный sample rate.", category="audio_integrity")
    return frames / sample_rate, sample_rate, channels, sample_width


def materialize_cached(cache_path: Path, output_path: Path) -> None:
    if output_path.exists():
        try:
            wav_info(output_path)
            return
        except YandexSpeechKitError:
            output_path.unlink()
    try:
        os.link(cache_path, output_path)
    except OSError:
        shutil.copy2(cache_path, output_path)


def classify_http(status: int) -> tuple[str, bool]:
    if status == 400:
        return "bad_request", False
    if status == 401:
        return "authentication", False
    if status == 403:
        return "permission", False
    if status == 404:
        return "endpoint", False
    if status == 408:
        return "timeout", True
    if status == 429:
        return "rate_limit", True
    if 500 <= status <= 599:
        return "server", True
    return "http", False
