from __future__ import annotations

import base64
import codecs
import hashlib
import http.client
import json
import math
import os
import shutil
import socket
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .yandex_segmenter import segment_text
from .yandex_pricing import YandexPricingConfig, price_estimate
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


_REST_STREAM_READ_SIZE = 64 * 1024


def _response_error(
    message: str,
    *,
    request_id: str,
    response_request_id: str | None,
    server_trace_id: str | None,
) -> YandexSpeechKitError:
    return YandexSpeechKitError(
        message,
        category="response",
        request_id=request_id,
        response_request_id=response_request_id,
        server_trace_id=server_trace_id,
    )


def _read_rest_v3_audio_stream(
    response: Any,
    *,
    request_id: str,
    response_request_id: str | None,
    server_trace_id: str | None,
) -> bytes:
    """Incrementally decode the REST v3 sequence of JSON response objects."""
    json_decoder = json.JSONDecoder()
    utf8_decoder = codecs.getincrementaldecoder("utf-8")()
    json_buffer = ""
    audio = bytearray()
    audio_chunks = 0

    def consume_complete_objects() -> None:
        nonlocal json_buffer, audio_chunks
        while True:
            json_buffer = json_buffer.lstrip()
            if not json_buffer:
                return
            try:
                data, end = json_decoder.raw_decode(json_buffer)
            except json.JSONDecodeError:
                # The current object may be split across network reads. Its
                # validity can be decided only after a normal HTTP EOF.
                return
            json_buffer = json_buffer[end:]
            if not isinstance(data, dict):
                raise _response_error(
                    "Ответ SpeechKit содержит JSON value вместо response object.",
                    request_id=request_id,
                    response_request_id=response_request_id,
                    server_trace_id=server_trace_id,
                )
            try:
                payload = response_payload(data)
            except YandexSpeechKitError as e:
                raise _response_error(
                    "Ответ SpeechKit содержит некорректную response structure.",
                    request_id=request_id,
                    response_request_id=response_request_id,
                    server_trace_id=server_trace_id,
                ) from e
            audio_chunk = payload.get("audioChunk")
            if audio_chunk is None:
                continue
            if not isinstance(audio_chunk, dict) or not isinstance(audio_chunk.get("data"), str):
                raise _response_error(
                    "Ответ SpeechKit содержит некорректный audioChunk.data.",
                    request_id=request_id,
                    response_request_id=response_request_id,
                    server_trace_id=server_trace_id,
                )
            try:
                decoded = base64.b64decode(audio_chunk["data"], validate=True)
            except (ValueError, TypeError) as e:
                raise _response_error(
                    "Ответ SpeechKit содержит некорректный Base64 audioChunk.data.",
                    request_id=request_id,
                    response_request_id=response_request_id,
                    server_trace_id=server_trace_id,
                ) from e
            audio.extend(decoded)
            audio_chunks += 1

    try:
        while True:
            raw = response.read(_REST_STREAM_READ_SIZE)
            if not raw:
                try:
                    json_buffer += utf8_decoder.decode(b"", final=True)
                except UnicodeDecodeError as e:
                    raise _response_error(
                        "Ответ SpeechKit содержит некорректный UTF-8 JSON stream.",
                        request_id=request_id,
                        response_request_id=response_request_id,
                        server_trace_id=server_trace_id,
                    ) from e
                consume_complete_objects()
                break
            try:
                json_buffer += utf8_decoder.decode(raw, final=False)
            except UnicodeDecodeError as e:
                raise _response_error(
                    "Ответ SpeechKit содержит некорректный UTF-8 JSON stream.",
                    request_id=request_id,
                    response_request_id=response_request_id,
                    server_trace_id=server_trace_id,
                ) from e
            consume_complete_objects()
    except (http.client.IncompleteRead, TimeoutError, socket.timeout, OSError) as e:
        raise YandexSpeechKitError(
            "Ответ SpeechKit оборвался после принятия запроса. "
            "Состояние оплаты неоднозначно; автоматический повтор запрещён.",
            category="network_ambiguous",
            retryable=False,
            request_id=request_id,
            response_request_id=response_request_id,
            server_trace_id=server_trace_id,
        ) from e

    if json_buffer.strip():
        raise _response_error(
            "Ответ SpeechKit содержит незавершённый или некорректный JSON stream.",
            request_id=request_id,
            response_request_id=response_request_id,
            server_trace_id=server_trace_id,
        )
    if audio_chunks == 0:
        raise _response_error(
            "Ответ SpeechKit не содержит audioChunk.data.",
            request_id=request_id,
            response_request_id=response_request_id,
            server_trace_id=server_trace_id,
        )
    return bytes(audio)


class YandexSpeechKitBackend:
    def __init__(
        self,
        config: YandexBackendConfig,
        *,
        api_key: str | None = None,
        billing_ledger: Any | None = None,
    ) -> None:
        self.config = config
        self.profile = config.profile
        self._api_key = api_key
        self._billing_ledger = billing_ledger

    def _record_billing_event(
        self,
        *,
        job_id: str,
        segment: TextSegment,
        request_id: str | None,
        fingerprint: str,
        timestamp: str,
        pricing: YandexPricingConfig,
        cost_known: bool,
    ) -> str | None:
        if self._billing_ledger is None:
            return None
        actual_cost = None
        cost_source = "unavailable"
        if cost_known and pricing.unit_price is not None:
            units = max(1, math.ceil(len(segment.text) / 250))
            actual_cost = Decimal(units) * pricing.unit_price
            cost_source = "local_actual"
        transaction_id, _ = self._billing_ledger.record(
            provider="yandex",
            job_id=job_id,
            segment_id=segment.segment_id,
            request_id=request_id,
            profile_id=f"yandex_{self.profile.voice}",
            timestamp=timestamp,
            currency=pricing.currency,
            actual_cost=actual_cost,
            cost_source=cost_source,
            fingerprint=fingerprint,
        )
        return transaction_id

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

    def manifest_segmentation(self) -> dict[str, int]:
        """Return the execution facts that must match an existing manifest."""
        return {
            "max_chars": self.config.max_chars,
            "max_words": self.config.max_words,
            "sentence_pause_ms": self.config.sentence_pause_ms,
            "paragraph_pause_ms": self.config.paragraph_pause_ms,
        }

    def request_routing_identity(self) -> dict[str, str]:
        """Return non-secret routing facts that define one cache authority."""
        return {
            "endpoint": self.config.endpoint,
            "keychain_service": self.config.keychain_service,
            "keychain_account": self.config.keychain_account,
        }

    def cache_namespace(self, cache_root: Path) -> Path:
        encoded = json.dumps(
            self.request_routing_identity(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        routing_sha256 = hashlib.sha256(encoded).hexdigest()
        return Path(cache_root) / ENGINE_ID / routing_sha256

    def _cached_segment_ids(self, segments: list[TextSegment], job_dir: Path | None) -> set[str]:
        """Find only integrity-checked cache/Resume hits; never create audio."""
        cached: set[str] = set()
        entries: dict[str, Any] = {}
        if job_dir is not None:
            manifest_path = Path(job_dir) / "MANIFEST.json"
            if manifest_path.exists():
                try:
                    with manifest_path.open("r", encoding="utf-8") as source:
                        manifest = json.load(source)
                    if (
                        isinstance(manifest, dict)
                        and manifest.get("segmentation") == self.manifest_segmentation()
                        and manifest.get("request_routing") == self.request_routing_identity()
                    ):
                        entries = dict(manifest.get("segments", {}))
                except (OSError, ValueError, TypeError):
                    entries = {}

        cache_root = self.cache_namespace(self.config.output_root / "_cache")
        for segment in segments:
            fingerprint = make_fingerprint(segment.text, self.profile)
            entry = entries.get(segment.segment_id, {})
            if (
                job_dir is not None
                and entry.get("fingerprint") == fingerprint
                and entry.get("status") == "IN_FLIGHT"
                and self.recoverable_inflight_source(
                    job_dir,
                    segment_id=segment.segment_id,
                    fingerprint=fingerprint,
                )
            ):
                cached.add(segment.segment_id)
                continue
            candidates: list[Path] = [cache_root / f"{fingerprint}.wav"]
            if (
                job_dir is not None
                and entry.get("fingerprint") == fingerprint
                and entry.get("status") in {"DONE", "CACHED"}
                and isinstance(entry.get("wav"), str)
            ):
                candidates.insert(0, Path(job_dir) / "segments" / entry["wav"])
            for candidate in candidates:
                if not candidate.exists():
                    continue
                try:
                    wav_info(candidate)
                except YandexSpeechKitError:
                    continue
                cached.add(segment.segment_id)
                break
        return cached

    def estimate(
        self,
        text: str,
        *,
        pricing: YandexPricingConfig | None = None,
        job_dir: Path | None = None,
        scope: str = "book",
    ) -> dict[str, Any]:
        segments = self.segment(text)
        units = sum(max(1, math.ceil(len(seg.text) / 250)) for seg in segments)
        cached_ids = self._cached_segment_ids(segments, job_dir)
        remaining_units = sum(
            max(1, math.ceil(len(segment.text) / 250))
            for segment in segments
            if segment.segment_id not in cached_ids
        )
        result = {
            "engine": ENGINE_ID,
            "characters": sum(len(seg.text) for seg in segments),
            "segments": len(segments),
            "estimated_billing_units": units,
            "cached_segments": len(cached_ids),
        }
        if pricing is None:
            result["unit_price"] = None
            return result
        result.update(price_estimate(
            total_units=units,
            billable_remaining_units=remaining_units,
            pricing=pricing,
            scope=scope,
        ))
        return result

    def recoverable_inflight_source(
        self,
        job_dir: Path,
        *,
        segment_id: str,
        fingerprint: str,
        prefer_cache: bool = False,
    ) -> str | None:
        """Return the integrity-checked local source for an interrupted segment."""
        job_wav = Path(job_dir) / "segments" / f"{segment_id}__{fingerprint[:12]}.wav"
        cache_wav = self.cache_namespace(self.config.output_root / "_cache") / f"{fingerprint}.wav"
        candidates = (("cache", cache_wav), ("job_wav", job_wav)) if prefer_cache else (
            ("job_wav", job_wav),
            ("cache", cache_wav),
        )
        for source, candidate in candidates:
            if not candidate.exists():
                continue
            try:
                wav_info(candidate)
            except YandexSpeechKitError:
                continue
            return source
        return None

    @staticmethod
    def require_allowed_to_start(estimate: dict[str, Any]) -> None:
        if estimate.get("allowed_to_start"):
            return
        reason = estimate.get("blocked_reason", "pricing")
        messages = {
            "missing_tariff": "Тариф не настроен. Обновите тариф перед запуском.",
            "stale_tariff": "Тариф требует проверки. Обновите тариф перед запуском.",
            "missing_hard_limit": "Задайте максимальную стоимость одной задачи в Настройках.",
            "hard_limit_exceeded": "Оценка превышает лимит задачи. Измените лимит в Настройках.",
        }
        raise YandexSpeechKitError(messages.get(reason, "Запуск заблокирован pricing policy."), category="pricing_gate")

    def _get_api_key(self) -> str:
        if self._api_key is None:
            self._api_key = read_api_key_from_keychain(
                self.config.keychain_service,
                self.config.keychain_account,
            )
        validate_api_key(self._api_key)
        return self._api_key

    def build_synthesis_payload(self, text: str) -> dict[str, Any]:
        hints: list[dict[str, str]] = [{"voice": self.profile.voice}]
        if self.profile.role:
            hints.append({"role": self.profile.role})
        hints.append({"speed": self.profile.speed})
        return {
            "text": text,
            "hints": hints,
            "outputAudioSpec": {
                "containerAudio": {"containerAudioType": self.profile.output_container}
            },
            "loudnessNormalizationType": self.profile.loudness_normalization,
            "unsafeMode": False,
        }

    def _request(self, text: str, request_id: str) -> tuple[bytes, dict[str, str | None]]:
        if len(text) > 250:
            raise YandexSpeechKitError(
                f"Сегмент длиннее лимита normal mode: {len(text)} символов.",
                category="segment_limit",
                request_id=request_id,
            )
        payload = self.build_synthesis_payload(text)
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
                headers = {
                    "x_request_id": response.headers.get("x-request-id"),
                    "x_server_trace_id": response.headers.get("x-server-trace-id"),
                }
                audio = _read_rest_v3_audio_stream(
                    response,
                    request_id=request_id,
                    response_request_id=headers["x_request_id"],
                    server_trace_id=headers["x_server_trace_id"],
                )
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
            cache_path = self.cache_namespace(Path(cache_root)) / f"{fingerprint}.wav"
            if cache_path.exists():
                try:
                    duration, sr, channels, width = wav_info(cache_path)
                except YandexSpeechKitError:
                    cache_path.unlink(missing_ok=True)
                else:
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

    def run_text_job(
        self,
        text: str,
        job_dir: Path,
        *,
        job_id: str = "yandex-text-job",
        pricing: YandexPricingConfig,
        scope: str = "book",
        cache_only: bool = False,
    ) -> Path:
        estimate = self.estimate(text, pricing=pricing, job_dir=job_dir, scope=scope)
        fully_cached = int(estimate.get("segments") or 0) > 0 and (
            int(estimate.get("cached_segments") or 0) == int(estimate.get("segments") or 0)
        )
        if not (cache_only and fully_cached):
            self.require_allowed_to_start(estimate)
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
            if (
                not isinstance(manifest, dict)
                or manifest.get("segmentation") != self.manifest_segmentation()
                or manifest.get("request_routing") != self.request_routing_identity()
            ):
                raise YandexSpeechKitError(
                    "Existing manifest execution facts do not match the current Yandex job.",
                    category="manifest",
                )
        else:
            manifest = {
                "schema_version": 1,
                "engine": ENGINE_ID,
                "job_id": job_id,
                "created_at": utc_now_iso(),
                "profile": asdict(self.profile),
                "segmentation": self.manifest_segmentation(),
                "request_routing": self.request_routing_identity(),
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
                    try:
                        wav_info(wav_path)
                    except YandexSpeechKitError:
                        pass
                    else:
                        ordered.append((wav_path, seg.pause_after_ms))
                        continue
                cache_path = self.cache_namespace(cache_root) / f"{fingerprint}.wav"
                if cache_path.exists():
                    try:
                        wav_info(cache_path)
                    except YandexSpeechKitError:
                        pass
                    else:
                        materialize_cached(cache_path, wav_path)
                        existing.update({
                            "status": "CACHED",
                            "recovered_from_cache_after_invalid_job_wav": True,
                            "updated_at": utc_now_iso(),
                        })
                        entries[seg.segment_id] = existing
                        atomic_write_json(manifest_path, manifest)
                        ordered.append((wav_path, seg.pause_after_ms))
                        continue

            if existing.get("fingerprint") == fingerprint and existing.get("status") == "IN_FLIGHT":
                cache_path = self.cache_namespace(cache_root) / f"{fingerprint}.wav"
                recovered_from = self.recoverable_inflight_source(
                    job_dir,
                    segment_id=seg.segment_id,
                    fingerprint=fingerprint,
                )
                if recovered_from == "cache":
                    materialize_cached(cache_path, wav_path)
                if recovered_from:
                    recovered_at = utc_now_iso()
                    existing.update({
                        "status": "CACHED" if recovered_from == "cache" else "DONE",
                        "recovered_after_interruption": recovered_from,
                        "updated_at": recovered_at,
                    })
                    existing["billing_transaction_id"] = self._record_billing_event(
                        job_id=job_id,
                        segment=seg,
                        request_id=existing.get("request_id"),
                        fingerprint=fingerprint,
                        timestamp=recovered_at,
                        pricing=pricing,
                        cost_known=False,
                    )
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

            finished_at = utc_now_iso()
            entries[seg.segment_id].update({
                "status": "CACHED" if result.cached else "DONE",
                "result": asdict(result),
                "updated_at": finished_at,
            })
            if not result.cached:
                entries[seg.segment_id]["billing_transaction_id"] = self._record_billing_event(
                    job_id=job_id,
                    segment=seg,
                    request_id=result.request_id,
                    fingerprint=fingerprint,
                    timestamp=finished_at,
                    pricing=pricing,
                    cost_known=True,
                )
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
