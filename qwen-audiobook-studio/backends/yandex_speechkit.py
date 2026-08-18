#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ENGINE_ID = "yandex_speechkit_v3"
DEFAULT_ENDPOINT = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"


class YandexSpeechKitError(RuntimeError):
    def __init__(self, message: str, *, category: str = "unknown", retryable: bool = False,
                 http_status: int | None = None, request_id: str | None = None,
                 response_request_id: str | None = None, server_trace_id: str | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.http_status = http_status
        self.request_id = request_id
        self.response_request_id = response_request_id
        self.server_trace_id = server_trace_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self), "category": self.category, "retryable": self.retryable,
            "http_status": self.http_status, "request_id": self.request_id,
            "response_request_id": self.response_request_id, "server_trace_id": self.server_trace_id,
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
            voice=str(data.get("voice", "lera")), role=str(data.get("role", "neutral")),
            speed=str(data.get("speed", "1.04")), output_container=str(data.get("output_container", "WAV")),
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
            max_chars=int(seg.get("max_chars", 220)), max_words=int(seg.get("max_words", 34)),
            sentence_pause_ms=int(seg.get("sentence_pause_ms", 380)),
            paragraph_pause_ms=int(seg.get("paragraph_pause_ms", 700)),
            profile=YandexVoiceProfile.from_mapping(data.get("default_profile")),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
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


def load_backend_config(path: Path) -> YandexBackendConfig:
    with path.open("r", encoding="utf-8") as f:
        return YandexBackendConfig.from_mapping(json.load(f))


def validate_api_key(api_key: str) -> None:
    if not api_key:
        raise YandexSpeechKitError("API key пустой. Проверьте запись в macOS Keychain.", category="credentials")
    if api_key != api_key.strip() or any(ch.isspace() for ch in api_key):
        raise YandexSpeechKitError("API key содержит пробелы или перевод строки.", category="credentials")
    if len(api_key) < 20:
        raise YandexSpeechKitError(f"API key выглядит слишком коротким ({len(api_key)} символов).", category="credentials")
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
            text=True, stderr=subprocess.PIPE,
        ).strip()
    except FileNotFoundError as e:
        raise YandexSpeechKitError("Утилита macOS Keychain /usr/bin/security не найдена.", category="platform") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip()
        raise YandexSpeechKitError(
            f"Не удалось получить API key из Keychain ({service}/{account}). {detail}".strip(),
            category="credentials",
        ) from e
    validate_api_key(key)
    return key


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fits(text: str, max_chars: int, max_words: int) -> bool:
    return len(text) <= max_chars and len(text.split()) <= max_words


def _split_long_piece(text: str, max_chars: int, max_words: int) -> list[str]:
    text = _collapse_ws(text)
    if not text:
        return []
    if _fits(text, max_chars, max_words):
        return [text]
    clause_parts = [p.strip() for p in re.split(r"(?<=[,;:—])\s+", text) if p.strip()]
    if len(clause_parts) > 1:
        out: list[str] = []
        current = ""
        for part in clause_parts:
            candidate = f"{current} {part}".strip() if current else part
            if current and not _fits(candidate, max_chars, max_words):
                out.extend(_split_long_piece(current, max_chars, max_words))
                current = part
            else:
                current = candidate
        if current:
            out.extend(_split_long_piece(current, max_chars, max_words))
        return out
    words = text.split()
    out: list[str] = []
    current_words: list[str] = []
    for word in words:
        candidate_words = current_words + [word]
        candidate = " ".join(candidate_words)
        if current_words and not _fits(candidate, max_chars, max_words):
            out.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words = candidate_words
    if current_words:
        out.append(" ".join(current_words))
    return out


def segment_text(text: str, *, max_chars: int = 220, max_words: int = 34,
                 sentence_pause_ms: int = 380, paragraph_pause_ms: int = 700) -> list[TextSegment]:
    """Literary-first splitter for SpeechKit v3 normal mode (unsafeMode=False)."""
    if max_chars <= 0 or max_chars > 250:
        raise ValueError("max_chars must be in 1..250 for SpeechKit v3 normal mode")
    if max_words <= 0:
        raise ValueError("max_words must be positive")
    raw_paragraphs = [p for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    segments: list[TextSegment] = []
    for p_idx, paragraph in enumerate(raw_paragraphs, start=1):
        paragraph = _collapse_ws(paragraph)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", paragraph) if s.strip()] or [paragraph]
        pieces: list[str] = []
        for sentence in sentences:
            pieces.extend(_split_long_piece(sentence, max_chars, max_words))
        packed: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip() if current else piece
            if current and not _fits(candidate, max_chars, max_words):
                packed.append(current)
                current = piece
            else:
                current = candidate
        if current:
            packed.append(current)
        for local_idx, piece in enumerate(packed):
            segments.append(TextSegment(
                segment_id="", text=piece,
                pause_after_ms=paragraph_pause_ms if local_idx == len(packed) - 1 else sentence_pause_ms,
                paragraph_index=p_idx,
            ))
    if segments:
        last = segments[-1]
        segments[-1] = TextSegment("", last.text, 0, last.paragraph_index)
    return [TextSegment(f"s{i:04d}", s.text, s.pause_after_ms, s.paragraph_index)
            for i, s in enumerate(segments, start=1)]


def make_fingerprint(text: str, profile: YandexVoiceProfile) -> str:
    payload = {
        "engine": ENGINE_ID, "text": text, "voice": profile.voice, "role": profile.role,
        "speed": profile.speed, "output_container": profile.output_container,
        "loudness_normalization": profile.loudness_normalization, "unsafe_mode": False,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _response_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("result", data)
    if not isinstance(payload, dict):
        raise YandexSpeechKitError("Некорректная структура ответа SpeechKit.", category="response")
    return payload


def _wav_info(path: Path) -> tuple[float, int, int, int]:
    try:
        with wave.open(str(path), "rb") as wf:
            channels, sample_width, sample_rate, frames = (
                wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
            )
    except (wave.Error, EOFError) as e:
        raise YandexSpeechKitError(f"Некорректный WAV: {path}", category="audio_integrity") from e
    if channels != 1:
        raise YandexSpeechKitError(f"Ожидался mono WAV, получено каналов: {channels}", category="audio_integrity")
    if sample_width != 2:
        raise YandexSpeechKitError(f"Ожидался 16-bit PCM WAV, sample width={sample_width}", category="audio_integrity")
    if sample_rate <= 0 or frames <= 0:
        raise YandexSpeechKitError("WAV пустой или имеет некорректный sample rate.", category="audio_integrity")
    return frames / sample_rate, sample_rate, channels, sample_width


def _classify_http(status: int) -> tuple[str, bool]:
    if status == 400: return "bad_request", False
    if status == 401: return "authentication", False
    if status == 403: return "permission", False
    if status == 404: return "endpoint", False
    if status == 408: return "timeout", True
    if status == 429: return "rate_limit", True
    if 500 <= status <= 599: return "server", True
    return "http", False


class YandexSpeechKitBackend:
    def __init__(self, config: YandexBackendConfig, *, api_key: str | None = None) -> None:
        self.config = config
        self.profile = config.profile
        self._api_key = api_key

    def list_voices(self) -> list[dict[str, str]]:
        return [{"id": self.profile.voice, "role": self.profile.role, "speed": self.profile.speed, "engine": ENGINE_ID}]

    def validate_config(self, *, resolve_credentials: bool = True) -> dict[str, Any]:
        if not self.config.endpoint.startswith("https://"):
            raise YandexSpeechKitError("SpeechKit endpoint должен использовать HTTPS.", category="config")
        if self.config.max_chars > 250:
            raise YandexSpeechKitError("max_chars > 250 несовместим с normal mode API v3.", category="config")
        if self.profile.output_container != "WAV":
            raise YandexSpeechKitError("MVP backend ожидает WAV output.", category="config")
        key = self._get_api_key() if resolve_credentials else None
        return {
            "ok": True, "engine": ENGINE_ID, "endpoint": self.config.endpoint,
            "voice": self.profile.voice, "role": self.profile.role, "speed": self.profile.speed,
            "keychain_service": self.config.keychain_service, "keychain_account": self.config.keychain_account,
            "credentials_present": key is not None if resolve_credentials else None, "unsafe_mode": False,
        }

    def healthcheck(self, *, remote: bool = False, output_path: Path | None = None) -> dict[str, Any]:
        local = self.validate_config(resolve_credentials=True)
        if not remote:
            local["remote_request_sent"] = False
            return local
        if output_path is None:
            raise ValueError("output_path is required for remote healthcheck")
        result = self.synthesize("Проверка Audiobook Studio.", output_path)
        return {**local, "remote_request_sent": True, "result": asdict(result)}

    def estimate(self, text: str) -> dict[str, Any]:
        segments = self.segment(text)
        units = sum(max(1, math.ceil(len(seg.text) / 250)) for seg in segments)
        return {
            "engine": ENGINE_ID, "characters": sum(len(seg.text) for seg in segments),
            "segments": len(segments), "estimated_billing_units": units, "unit_price": None,
        }

    def segment(self, text: str) -> list[TextSegment]:
        return segment_text(
            text, max_chars=self.config.max_chars, max_words=self.config.max_words,
            sentence_pause_ms=self.config.sentence_pause_ms, paragraph_pause_ms=self.config.paragraph_pause_ms,
        )

    def _get_api_key(self) -> str:
        if self._api_key is None:
            self._api_key = read_api_key_from_keychain(self.config.keychain_service, self.config.keychain_account)
        validate_api_key(self._api_key)
        return self._api_key

    def _request(self, text: str, request_id: str) -> tuple[bytes, dict[str, str | None]]:
        if len(text) > 250:
            raise YandexSpeechKitError(
                f"Сегмент длиннее лимита normal mode: {len(text)} символов.",
                category="segment_limit", request_id=request_id,
            )
        payload = {
            "text": text,
            "hints": [{"voice": self.profile.voice}, {"role": self.profile.role}, {"speed": self.profile.speed}],
            "outputAudioSpec": {"containerAudio": {"containerAudioType": self.profile.output_container}},
            "loudnessNormalizationType": self.profile.loudness_normalization,
            "unsafeMode": False,
        }
        req = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Api-Key {self._get_api_key()}", "Content-Type": "application/json",
                "x-client-request-id": request_id, "x-data-logging-enabled": "false",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read()
                headers = {
                    "x_request_id": response.headers.get("x-request-id"),
                    "x_server_trace_id": response.headers.get("x-server-trace-id"),
                }
        except urllib.error.HTTPError as e:
            category, retryable = _classify_http(e.code)
            detail = e.read().decode("utf-8", errors="replace")[:1200]
            raise YandexSpeechKitError(
                f"SpeechKit HTTP {e.code}: {detail}", category=category, retryable=retryable,
                http_status=e.code, request_id=request_id,
                response_request_id=e.headers.get("x-request-id") if e.headers else None,
                server_trace_id=e.headers.get("x-server-trace-id") if e.headers else None,
            ) from e
        except urllib.error.URLError as e:
            raise YandexSpeechKitError(
                f"Сетевая ошибка SpeechKit: {e.reason}", category="network_ambiguous",
                retryable=False, request_id=request_id,
            ) from e
        try:
            data = json.loads(raw.decode("utf-8"))
            encoded = _response_payload(data)["audioChunk"]["data"]
            audio = base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
            raise YandexSpeechKitError(
                "Ответ SpeechKit не содержит корректный Base64 WAV audioChunk.data.", category="response",
                request_id=request_id, response_request_id=headers.get("x_request_id"),
                server_trace_id=headers.get("x_server_trace_id"),
            ) from e
        return audio, headers

    def synthesize(self, text: str, output_path: Path, *, request_id: str | None = None,
                   cache_root: Path | None = None) -> SynthesisResult:
        text = _collapse_ws(text)
        if not text:
            raise YandexSpeechKitError("Пустой текст для синтеза.", category="input")
        request_id = request_id or str(uuid.uuid4())
        fingerprint = make_fingerprint(text, self.profile)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path = None
        if cache_root is not None:
            cache_path = Path(cache_root) / ENGINE_ID / f"{fingerprint}.wav"
            if cache_path.exists():
                duration, sr, channels, width = _wav_info(cache_path)
                self._materialize_cached(cache_path, output_path)
                return SynthesisResult(
                    ENGINE_ID, self.profile.voice, self.profile.role, self.profile.speed, str(output_path),
                    request_id, None, None, duration, sr, channels, width, fingerprint, True,
                )
        audio, headers = self._request(text, request_id)
        tmp_path = output_path.with_suffix(output_path.suffix + ".part")
        try:
            tmp_path.write_bytes(audio)
            duration, sr, channels, width = _wav_info(tmp_path)
            os.replace(tmp_path, output_path)
        finally:
            if tmp_path.exists(): tmp_path.unlink()
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if not cache_path.exists():
                cache_tmp = cache_path.with_suffix(".wav.part")
                shutil.copy2(output_path, cache_tmp)
                os.replace(cache_tmp, cache_path)
        return SynthesisResult(
            ENGINE_ID, self.profile.voice, self.profile.role, self.profile.speed, str(output_path), request_id,
            headers.get("x_request_id"), headers.get("x_server_trace_id"), duration, sr, channels, width,
            fingerprint, False,
        )

    @staticmethod
    def _materialize_cached(cache_path: Path, output_path: Path) -> None:
        if output_path.exists():
            _wav_info(output_path)
            return
        try:
            os.link(cache_path, output_path)
        except OSError:
            shutil.copy2(cache_path, output_path)

    def run_text_job(self, text: str, job_dir: Path, *, job_id: str = "yandex-text-job") -> Path:
        """Run/resume a segmented job; never auto-resend an ambiguous IN_FLIGHT request."""
        segments = self.segment(text)
        if not segments:
            raise YandexSpeechKitError("После сегментации нет текста.", category="input")
        job_dir = Path(job_dir)
        segment_dir = job_dir / "segments"
        segment_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = job_dir / "MANIFEST.json"
        cache_root = self.config.output_root / "_cache"
        if manifest_path.exists():
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = {
                "schema_version": 1, "engine": ENGINE_ID, "job_id": job_id, "created_at": utc_now_iso(),
                "profile": asdict(self.profile),
                "segmentation": {
                    "max_chars": self.config.max_chars, "max_words": self.config.max_words,
                    "sentence_pause_ms": self.config.sentence_pause_ms,
                    "paragraph_pause_ms": self.config.paragraph_pause_ms,
                },
                "estimated_billing_units": self.estimate(text)["estimated_billing_units"], "segments": {},
            }
        entries: dict[str, Any] = manifest.setdefault("segments", {})
        ordered_paths: list[tuple[Path, int]] = []
        for seg in segments:
            fingerprint = make_fingerprint(seg.text, self.profile)
            wav_path = segment_dir / f"{seg.segment_id}__{fingerprint[:12]}.wav"
            existing = entries.get(seg.segment_id, {})
            if existing.get("fingerprint") == fingerprint and existing.get("status") in {"DONE", "CACHED"}:
                if wav_path.exists():
                    _wav_info(wav_path)
                    ordered_paths.append((wav_path, seg.pause_after_ms))
                    continue
            if existing.get("fingerprint") == fingerprint and existing.get("status") == "IN_FLIGHT":
                existing["status"] = "AMBIGUOUS"
                existing["updated_at"] = utc_now_iso()
                entries[seg.segment_id] = existing
                _atomic_write_json(manifest_path, manifest)
                raise YandexSpeechKitError(
                    f"Сегмент {seg.segment_id} был IN_FLIGHT при прерывании. Автоповтор запрещён, чтобы не оплатить запрос дважды.",
                    category="resume_ambiguous", request_id=existing.get("request_id"),
                )
            request_id = str(uuid.uuid4())
            entries[seg.segment_id] = {
                "status": "IN_FLIGHT", "text": seg.text, "pause_after_ms": seg.pause_after_ms,
                "paragraph_index": seg.paragraph_index, "fingerprint": fingerprint,
                "request_id": request_id, "wav": wav_path.name, "updated_at": utc_now_iso(),
            }
            _atomic_write_json(manifest_path, manifest)
            try:
                result = self.synthesize(seg.text, wav_path, request_id=request_id, cache_root=cache_root)
            except YandexSpeechKitError as e:
                entries[seg.segment_id].update({
                    "status": "FAILED" if e.category != "network_ambiguous" else "AMBIGUOUS",
                    "error": e.to_dict(), "updated_at": utc_now_iso(),
                })
                _atomic_write_json(manifest_path, manifest)
                raise
            entries[seg.segment_id].update({
                "status": "CACHED" if result.cached else "DONE", "result": asdict(result),
                "updated_at": utc_now_iso(),
            })
            _atomic_write_json(manifest_path, manifest)
            ordered_paths.append((wav_path, seg.pause_after_ms))
        joined = job_dir / f"{job_id}__{self.profile.voice}-{self.profile.role}-{self.profile.speed}.wav"
        join_wavs_with_pauses(ordered_paths, joined)
        manifest["joined_wav"] = joined.name
        manifest["finished_at"] = utc_now_iso()
        manifest["status"] = "DONE"
        _atomic_write_json(manifest_path, manifest)
        return joined


def join_wavs_with_pauses(items: Iterable[tuple[Path, int]], output_path: Path) -> None:
    params: tuple[int, int, int] | None = None
    chunks: list[bytes] = []
    for path, pause_ms in items:
        with wave.open(str(path), "rb") as wf:
            current = (wf.getnchannels(), wf.getsampwidth(), wf.getframerate())
            if params is None: params = current
            elif current != params:
                raise YandexSpeechKitError(
                    f"Нельзя собрать WAV с разными параметрами: {path.name}", category="audio_integrity"
                )
            chunks.append(wf.readframes(wf.getnframes()))
            if pause_ms > 0:
                channels, width, rate = current
                silence_frames = int(round(rate * pause_ms / 1000.0))
                chunks.append(b"\x00" * silence_frames * channels * width)
    if params is None:
        raise YandexSpeechKitError("Нет WAV для сборки.", category="audio_integrity")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    channels, width, rate = params
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    try:
        with wave.open(str(tmp), "wb") as out:
            out.setnchannels(channels); out.setsampwidth(width); out.setframerate(rate)
            for chunk in chunks: out.writeframes(chunk)
        _wav_info(tmp)
        os.replace(tmp, output_path)
    finally:
        if tmp.exists(): tmp.unlink()
