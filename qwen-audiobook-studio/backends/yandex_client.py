from __future__ import annotations

import base64
import json
import math
import os
import shutil
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .yandex_segmenter import segment_text
from .yandex_types import (
    ENGINE_ID,
    SynthesisResult,
    TextSegment,
    YandexBackendConfig,
    YandexSpeechKitError,
    atomic_write_json,
    classify_http,
    collapse_ws,
    make_fingerprint,
    materialize_cached,
    read_api_key_from_keychain,
    response_payload,
    utc_now_iso,
    validate_api_key,
    wav_info,
)


class YandexSpeechKitBackend:
    def __init__(self, config: YandexBackendConfig, *, api_key: str | None = None) -> None:
        self.config = config
        self.profile = config.profile
        self._api_key = api_key

    def list_voices(self) -> list[dict[str, str]]:
        return [{
            "id": self.profile.voice,
            "role": self.profile.role,
            "speed": self.profile.speed,
            "engine": ENGINE_ID,
        }]

    def validate_config(self, *, resolve_credentials: bool = True) -> dict[str, Any]:
        if not self.config.endpoint.startswith("https://"):
            raise YandexSpeechKitError("SpeechKit endpoint должен использовать HTTPS.", category="config")
        if not (1 <= self.config.max_chars <= 250):
            raise YandexSpeechKitError("max_chars должен быть в диапазоне 1..250.", category="config")
        if self.profile.output_container != "WAV":
            raise YandexSpeechKitError("MVP backend ожидает WAV output.", category="config")
        key = self._get_api_key() if resolve_credentials else None
        return {
            "ok": True,
            "engine": ENGINE_ID,
            "endpoint": self.config.endpoint,
            "voice": self.profile.voice,
            "role": self.profile.role,
            "speed": self.profile.speed,
            "keychain_service": self.config.keychain_service,
            "keychain_account": self.config.keychain_account,
            "credentials_present": key is not None if resolve_credentials else None,
            "unsafe_mode": False,
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

    def segment(self, text: str) -> list[TextSegment]:
        return segment_text(
            text,
            max_chars=self.config.max_chars,
            max_words=self.config.max_words,
            sentence_pause_ms=self.config.sentence_pause_ms,
            paragraph_pause_ms=self.config.paragraph_pause_ms,
        )

    def estimate(self, text: str) -> dict[str, Any]:
        segments = self.segment(text)
        units = sum(max(1, math.ceil(len(seg.text) / 250)) for seg in segments)
        return {
            "engine": ENGINE_ID,
            "characters": sum(len(seg.text) for seg in segments),
            "segments": len(segments),
            "estimated_billing_units": units,
            "unit_price": None,
        }

    def _get_api_key(self) -> str:
        if self._api_key is None:
            self._api_key = read_api_key_from_keychain(
                self.config.keychain_service,
                self.config.keychain_account,
            )
        validate_api_key(self._api_key)
        return self._api_key

    def _request(self, text: str, request_id: str) -> tuple[bytes, dict[str, str | None]]:
        if len(text) > 250:
            raise YandexSpeechKitError(
                f"Сегмент длиннее лимита normal mode: {len(text)} символов.",
                category="segment_limit",
                request_id=request_id,
            )
        payload = {
            "text": text,
            "hints": [
                {"voice": self.profile.voice},
                {"role": self.profile.role},
                {"speed": self.profile.speed},
            ],
            "outputAudioSpec": {
                "containerAudio": {"containerAudioType": self.profile.output_container}
            },
            "loudnessNormalizationType": self.profile.loudness_normalization,
            "unsafeMode": False,
        }
        req = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Api-Key {self._get_api_key()}",
                "Content-Type": "application/json",
                "x-client-request-id": request_id,
                "x-data-logging-enabled": "false",
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
            category, retryable = classify_http(e.code)
            detail = e.read().decode("utf-8", errors="replace")[:1200]
            raise YandexSpeechKitError(
                f"SpeechKit HTTP {e.code}: {detail}",
                category=category,
                retryable=retryable,
                http_status=e.code,
                request_id=request_id,
                response_request_id=e.headers.get("x-request-id") if e.headers else None,
                server_trace_id=e.headers.get("x-server-trace-id") if e.headers else None,
            ) from e
        except urllib.error.URLError as e:
            raise YandexSpeechKitError(
                f"Сетевая ошибка SpeechKit: {e.reason}",
                category="network_ambiguous",
                retryable=False,
                request_id=request_id,
            ) from e

        try:
            data = json.loads(raw.decode("utf-8"))
            encoded = response_payload(data)["audioChunk"]["data"]
            audio = base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
            raise YandexSpeechKitError(
                "Ответ SpeechKit не содержит корректный Base64 WAV audioChunk.data.",
                category="response",
                request_id=request_id,
                response_request_id=headers.get("x_request_id"),
                server_trace_id=headers.get("x_server_trace_id"),
            ) from e
        return audio, headers

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        request_id: str | None = None,
        cache_root: Path | None = None,
    ) -> SynthesisResult:
        text = collapse_ws(text)
        if not text:
            raise YandexSpeechKitError("Пустой текст для синтеза.", category="input")
        request_id = request_id or str(uuid.uuid4())
        fingerprint = make_fingerprint(text, self.profile)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cache_path: Path | None = None
        if cache_root is not None:
            cache_path = Path(cache_root) / ENGINE_ID / f"{fingerprint}.wav"
            if cache_path.exists():
                duration, sr, channels, width = wav_info(cache_path)
                materialize_cached(cache_path, output_path)
                return SynthesisResult(
                    ENGINE_ID, self.profile.voice, self.profile.role, self.profile.speed,
                    str(output_path), request_id, None, None,
                    duration, sr, channels, width, fingerprint, True,
                )

        audio, headers = self._request(text, request_id)
        tmp_path = output_path.with_suffix(output_path.suffix + ".part")
        try:
            tmp_path.write_bytes(audio)
            duration, sr, channels, width = wav_info(tmp_path)
            os.replace(tmp_path, output_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if not cache_path.exists():
                cache_tmp = cache_path.with_suffix(".wav.part")
                shutil.copy2(output_path, cache_tmp)
                os.replace(cache_tmp, cache_path)

        return SynthesisResult(
            ENGINE_ID, self.profile.voice, self.profile.role, self.profile.speed,
            str(output_path), request_id,
            headers.get("x_request_id"), headers.get("x_server_trace_id"),
            duration, sr, channels, width, fingerprint, False,
        )

    def run_text_job(self, text: str, job_dir: Path, *, job_id: str = "yandex-text-job") -> Path:
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
                "schema_version": 1,
                "engine": ENGINE_ID,
                "job_id": job_id,
                "created_at": utc_now_iso(),
                "profile": asdict(self.profile),
                "segmentation": {
                    "max_chars": self.config.max_chars,
                    "max_words": self.config.max_words,
                    "sentence_pause_ms": self.config.sentence_pause_ms,
                    "paragraph_pause_ms": self.config.paragraph_pause_ms,
                },
                "estimated_billing_units": self.estimate(text)["estimated_billing_units"],
                "segments": {},
            }

        entries: dict[str, Any] = manifest.setdefault("segments", {})
        ordered: list[tuple[Path, int]] = []

        for seg in segments:
            fingerprint = make_fingerprint(seg.text, self.profile)
            wav_path = segment_dir / f"{seg.segment_id}__{fingerprint[:12]}.wav"
            existing = entries.get(seg.segment_id, {})

            if existing.get("fingerprint") == fingerprint and existing.get("status") in {"DONE", "CACHED"}:
                if wav_path.exists():
                    wav_info(wav_path)
                    ordered.append((wav_path, seg.pause_after_ms))
                    continue

            if existing.get("fingerprint") == fingerprint and existing.get("status") == "IN_FLIGHT":
                cache_path = cache_root / ENGINE_ID / f"{fingerprint}.wav"
                recovered_from = None
                if wav_path.exists():
                    wav_info(wav_path)
                    recovered_from = "job_wav"
                elif cache_path.exists():
                    wav_info(cache_path)
                    materialize_cached(cache_path, wav_path)
                    recovered_from = "cache"
                if recovered_from:
                    existing.update({
                        "status": "CACHED" if recovered_from == "cache" else "DONE",
                        "recovered_after_interruption": recovered_from,
                        "updated_at": utc_now_iso(),
                    })
                    entries[seg.segment_id] = existing
                    atomic_write_json(manifest_path, manifest)
                    ordered.append((wav_path, seg.pause_after_ms))
                    continue

                existing["status"] = "AMBIGUOUS"
                existing["updated_at"] = utc_now_iso()
                entries[seg.segment_id] = existing
                atomic_write_json(manifest_path, manifest)
                raise YandexSpeechKitError(
                    f"Сегмент {seg.segment_id} был IN_FLIGHT при прерывании. "
                    "Автоповтор запрещён, чтобы не оплатить запрос дважды.",
                    category="resume_ambiguous",
                    request_id=existing.get("request_id"),
                )

            request_id = str(uuid.uuid4())
            entries[seg.segment_id] = {
                "status": "IN_FLIGHT",
                "text": seg.text,
                "pause_after_ms": seg.pause_after_ms,
                "paragraph_index": seg.paragraph_index,
                "fingerprint": fingerprint,
                "request_id": request_id,
                "wav": wav_path.name,
                "updated_at": utc_now_iso(),
            }
            atomic_write_json(manifest_path, manifest)

            try:
                result = self.synthesize(
                    seg.text,
                    wav_path,
                    request_id=request_id,
                    cache_root=cache_root,
                )
            except YandexSpeechKitError as e:
                entries[seg.segment_id].update({
                    "status": "AMBIGUOUS" if e.category == "network_ambiguous" else "FAILED",
                    "error": e.to_dict(),
                    "updated_at": utc_now_iso(),
                })
                atomic_write_json(manifest_path, manifest)
                raise

            entries[seg.segment_id].update({
                "status": "CACHED" if result.cached else "DONE",
                "result": asdict(result),
                "updated_at": utc_now_iso(),
            })
            atomic_write_json(manifest_path, manifest)
            ordered.append((wav_path, seg.pause_after_ms))

        joined = job_dir / f"{job_id}__{self.profile.voice}-{self.profile.role}-{self.profile.speed}.wav"
        join_wavs_with_pauses(ordered, joined)
        manifest["joined_wav"] = joined.name
        manifest["finished_at"] = utc_now_iso()
        manifest["status"] = "DONE"
        atomic_write_json(manifest_path, manifest)
        return joined


def _write_silence_stream(out: wave.Wave_write, *, frames: int, channels: int, width: int) -> None:
    remaining = frames
    frames_per_chunk = 65536
    zero_frame = b"\x00" * channels * width
    while remaining > 0:
        count = min(remaining, frames_per_chunk)
        out.writeframesraw(zero_frame * count)
        remaining -= count


def _copy_wav_frames(source: Path, out: wave.Wave_write, expected: tuple[int, int, int]) -> None:
    with wave.open(str(source), "rb") as wf:
        current = (wf.getnchannels(), wf.getsampwidth(), wf.getframerate())
        if current != expected:
            raise YandexSpeechKitError(
                f"Нельзя собрать WAV с разными параметрами: {source.name}",
                category="audio_integrity",
            )
        while True:
            chunk = wf.readframes(65536)
            if not chunk:
                break
            out.writeframesraw(chunk)


def join_wavs_with_pauses(items: Iterable[tuple[Path, int]], output_path: Path) -> None:
    """Stream segments into a joined WAV without holding audiobook audio in RAM."""
    iterator = iter(items)
    try:
        first_path, first_pause_ms = next(iterator)
    except StopIteration as e:
        raise YandexSpeechKitError("Нет WAV для сборки.", category="audio_integrity") from e

    first_path = Path(first_path)
    with wave.open(str(first_path), "rb") as first:
        params = (first.getnchannels(), first.getsampwidth(), first.getframerate())
    channels, width, rate = params
    if channels != 1 or width != 2 or rate <= 0:
        raise YandexSpeechKitError(
            f"Некорректные параметры WAV для сборки: channels={channels}, width={width}, rate={rate}",
            category="audio_integrity",
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".part")

    def write_one(out: wave.Wave_write, path: Path, pause_ms: int) -> None:
        _copy_wav_frames(Path(path), out, params)
        if pause_ms > 0:
            silence_frames = int(round(rate * pause_ms / 1000.0))
            _write_silence_stream(
                out,
                frames=silence_frames,
                channels=channels,
                width=width,
            )

    try:
        with wave.open(str(tmp), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(width)
            out.setframerate(rate)
            write_one(out, first_path, first_pause_ms)
            for path, pause_ms in iterator:
                write_one(out, Path(path), pause_ms)
        wav_info(tmp)
        os.replace(tmp, output_path)
    finally:
        if tmp.exists():
            tmp.unlink()
