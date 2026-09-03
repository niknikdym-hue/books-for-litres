from __future__ import annotations

import base64
import contextlib
import http.client
import io
import json
import socket
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backends import yandex_speechkit as module
from backends import yandex_client


def write_test_wav(path: Path, *, rate: int = 22050, frames: int = 2205) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)


def demo_pricing() -> module.YandexPricingConfig:
    return module.YandexPricingConfig.from_mapping({
        "engine": "yandex_speechkit_v3",
        "currency": "RUB",
        "unit_price": "0.21146666",
        "verified_at": "2026-08-20",
        "source_url": "https://yandex.cloud/ru-kz/docs/speechkit/pricing",
        "max_age_days": 30,
        "demo_hard_limit_rub": "1.00",
    })


def wav_bytes(*, rate: int = 22050, frames: int = 2205) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)
    return output.getvalue()


def response_object(audio: bytes, *, wrapped: bool = True) -> bytes:
    payload = {"audioChunk": {"data": base64.b64encode(audio).decode("ascii")}}
    data = {"result": payload} if wrapped else payload
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


class FakeStreamingResponse:
    def __init__(self, reads: list[bytes], *, terminal_error: BaseException | None = None) -> None:
        self.reads = list(reads)
        self.terminal_error = terminal_error
        self.read_calls = 0
        self.headers = {
            "x-request-id": "response-request-test",
            "x-server-trace-id": "trace-test",
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if self.reads:
            chunk = self.reads.pop(0)
            if size >= 0:
                self.assert_read_size(size)
            return chunk
        if self.terminal_error is not None:
            error = self.terminal_error
            self.terminal_error = None
            raise error
        return b""

    @staticmethod
    def assert_read_size(size: int) -> None:
        if size != yandex_client._REST_STREAM_READ_SIZE:
            raise AssertionError(f"unexpected streaming read size: {size}")


def read_stream(response: FakeStreamingResponse) -> bytes:
    return yandex_client._read_rest_v3_audio_stream(
        response,
        request_id="client-request-test",
        response_request_id=response.headers["x-request-id"],
        server_trace_id=response.headers["x-server-trace-id"],
    )


class YandexBackendTests(unittest.TestCase):
    def test_duplicate_key_is_rejected(self):
        key = "A" * 40
        with self.assertRaises(module.YandexSpeechKitError) as ctx:
            module.validate_api_key(key + key)
        self.assertEqual(ctx.exception.category, "credentials_duplicate")

    def test_segmenter_respects_limits_and_last_pause_zero(self):
        text = (
            "Первое предложение достаточно короткое. Второе предложение тоже короткое, но вместе они могут стать длиннее. "
            "Третье предложение добавляет ещё немного текста.\n\n"
            "Новый абзац начинается здесь и должен сохранить более длинную паузу между смысловыми блоками."
        )
        segments = module.segment_text(text, max_chars=90, max_words=12)
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(s.text) <= 90 for s in segments))
        self.assertTrue(all(len(s.text.split()) <= 12 for s in segments))
        self.assertEqual(segments[-1].pause_after_ms, 0)
        self.assertEqual([s.segment_id for s in segments], [f"s{i:04d}" for i in range(1, len(segments) + 1)])

    def test_fingerprint_changes_with_speed(self):
        p1 = module.YandexVoiceProfile(speed="1.00")
        p2 = module.YandexVoiceProfile(speed="1.04")
        self.assertNotEqual(module.make_fingerprint("Тест.", p1), module.make_fingerprint("Тест.", p2))

    def test_response_payload_accepts_wrapped_and_direct(self):
        direct = {"audioChunk": {"data": "abc"}}
        wrapped = {"result": direct}
        self.assertEqual(module._response_payload(direct), direct)
        self.assertEqual(module._response_payload(wrapped), direct)

    def test_rest_stream_accepts_one_json_response_chunk(self):
        audio = wav_bytes()
        self.assertEqual(read_stream(FakeStreamingResponse([response_object(audio)])), audio)

    def test_rest_stream_accepts_multiple_consecutive_response_objects(self):
        body = response_object(b"first") + b"\n" + response_object(b"second")
        self.assertEqual(read_stream(FakeStreamingResponse([body])), b"firstsecond")

    def test_rest_stream_handles_json_object_split_across_network_reads(self):
        body = response_object(b"split-boundary")
        split = len(body) // 2
        self.assertEqual(
            read_stream(FakeStreamingResponse([body[:split], body[split:]])),
            b"split-boundary",
        )

    def test_rest_stream_assembles_all_audio_chunks_into_valid_wav(self):
        expected = wav_bytes(frames=4410)
        boundaries = (37, 2048)
        pieces = [
            expected[:boundaries[0]],
            expected[boundaries[0]:boundaries[1]],
            expected[boundaries[1]:],
        ]
        body = b"\n".join(response_object(piece) for piece in pieces)
        actual = read_stream(FakeStreamingResponse([body]))
        self.assertEqual(actual, expected)
        with wave.open(io.BytesIO(actual), "rb") as wf:
            self.assertEqual(wf.getnframes(), 4410)
            self.assertEqual(wf.getframerate(), 22050)

    def test_rest_stream_normal_eof_after_all_chunks_is_success(self):
        response = FakeStreamingResponse([response_object(b"complete")])
        self.assertEqual(read_stream(response), b"complete")
        self.assertEqual(response.read_calls, 2)

    def test_rest_stream_incomplete_read_after_partial_is_ambiguous(self):
        response = FakeStreamingResponse(
            [response_object(b"partial")],
            terminal_error=http.client.IncompleteRead(b"truncated"),
        )
        with self.assertRaises(module.YandexSpeechKitError) as context:
            read_stream(response)
        self.assertEqual(context.exception.category, "network_ambiguous")
        self.assertFalse(context.exception.retryable)
        self.assertEqual(context.exception.response_request_id, "response-request-test")

    def test_rest_stream_socket_timeout_after_partial_is_ambiguous(self):
        response = FakeStreamingResponse(
            [response_object(b"partial")],
            terminal_error=socket.timeout("timed out"),
        )
        with self.assertRaises(module.YandexSpeechKitError) as context:
            read_stream(response)
        self.assertEqual(context.exception.category, "network_ambiguous")
        self.assertFalse(context.exception.retryable)

    def test_rest_stream_rejects_corrupt_base64_as_response_error(self):
        body = b'{"result":{"audioChunk":{"data":"not-base64!!!"}}}'
        with self.assertRaises(module.YandexSpeechKitError) as context:
            read_stream(FakeStreamingResponse([body]))
        self.assertEqual(context.exception.category, "response")

    def test_rest_stream_rejects_malformed_json_as_response_error(self):
        body = response_object(b"partial") + b'\n{"result": broken}'
        with self.assertRaises(module.YandexSpeechKitError) as context:
            read_stream(FakeStreamingResponse([body]))
        self.assertEqual(context.exception.category, "response")

    def test_rest_stream_rejects_response_without_audio_chunks(self):
        body = json.dumps({"result": {"textChunk": {"text": "Тест"}}}).encode("utf-8")
        with self.assertRaises(module.YandexSpeechKitError) as context:
            read_stream(FakeStreamingResponse([body]))
        self.assertEqual(context.exception.category, "response")

    def test_rest_stream_errors_and_output_do_not_expose_credentials(self):
        secret = "offline-secret-api-key-value-1234567890"
        backend = module.YandexSpeechKitBackend(
            module.YandexBackendConfig.from_mapping({"output_root": "/tmp/yandex-offline"}),
            api_key=secret,
        )
        response = FakeStreamingResponse([b'{"result": broken}'])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("backends.yandex_client.urllib.request.urlopen", return_value=response):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(module.YandexSpeechKitError) as context:
                    backend._request("Тест.", "client-request-test")
        serialized_error = json.dumps(context.exception.to_dict(), ensure_ascii=False)
        self.assertNotIn(secret, serialized_error)
        self.assertNotIn(secret, stdout.getvalue())
        self.assertNotIn(secret, stderr.getvalue())

    def test_rest_stream_keeps_legacy_direct_single_chunk_contract(self):
        audio = wav_bytes()
        self.assertEqual(
            read_stream(FakeStreamingResponse([response_object(audio, wrapped=False)])),
            audio,
        )

    def test_wav_info_accepts_mono_pcm16(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ok.wav"
            write_test_wav(path)
            duration, rate, channels, width = module._wav_info(path)
            self.assertAlmostEqual(duration, 0.1, places=2)
            self.assertEqual((rate, channels, width), (22050, 1, 2))

    def test_config_default_profile(self):
        cfg = module.YandexBackendConfig.from_mapping({"output_root": "~/tmp-audiobook"})
        self.assertEqual(cfg.profile.voice, "lera")
        self.assertEqual(cfg.profile.role, "neutral")
        self.assertEqual(cfg.profile.speed, "1.04")
        self.assertEqual(cfg.request_timeout_seconds, 180)

    def test_request_uses_configured_timeout_without_retry(self):
        backend = module.YandexSpeechKitBackend(
            module.YandexBackendConfig.from_mapping({
                "output_root": "/tmp/yandex-offline",
                "request_timeout_seconds": 240,
            }),
            api_key="1234567890abcdefghijklmnopqrstuvABCD",
        )
        response = FakeStreamingResponse([response_object(wav_bytes())])
        with mock.patch(
            "backends.yandex_client.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            audio, _headers = backend._request("Тест.", "client-request-test")
        self.assertTrue(audio)
        urlopen.assert_called_once()
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 240)

    def test_request_timeout_is_validated_offline(self):
        for value in (0, 601):
            with self.subTest(value=value):
                backend = module.YandexSpeechKitBackend(
                    module.YandexBackendConfig.from_mapping({
                        "output_root": "/tmp/yandex-offline",
                        "request_timeout_seconds": value,
                    }),
                    api_key="1234567890abcdefghijklmnopqrstuvABCD",
                )
                with self.assertRaises(module.YandexSpeechKitError) as context:
                    backend.validate_config(resolve_credentials=False)
                self.assertEqual(context.exception.category, "config")

    def test_pathological_long_token_is_split(self):
        segments = module.segment_text("A" * 501, max_chars=100, max_words=10)
        self.assertTrue(all(len(s.text) <= 100 for s in segments))

    def test_streaming_join_preserves_duration_and_pause(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.wav"
            b = root / "b.wav"
            joined = root / "joined.wav"
            write_test_wav(a, frames=2205)
            write_test_wav(b, frames=2205)
            module.join_wavs_with_pauses([(a, 100), (b, 0)], joined)
            duration, rate, channels, width = module._wav_info(joined)
            self.assertAlmostEqual(duration, 0.3, places=2)
            self.assertEqual((rate, channels, width), (22050, 1, 2))

    def test_streaming_join_rejects_mismatched_sample_rate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.wav"
            b = root / "b.wav"
            joined = root / "joined.wav"
            write_test_wav(a, rate=22050)
            write_test_wav(b, rate=44100)
            with self.assertRaises(module.YandexSpeechKitError) as ctx:
                module.join_wavs_with_pauses([(a, 0), (b, 0)], joined)
            self.assertEqual(ctx.exception.category, "audio_integrity")
            self.assertFalse(joined.exists())

    def test_inflight_without_local_artifact_becomes_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = module.YandexBackendConfig.from_mapping({
                "output_root": str(root / "out"),
                "segmentation": {"max_chars": 220, "max_words": 34},
            })
            backend = module.YandexSpeechKitBackend(cfg, api_key="1234567890abcdefghijklmnopqrstuvABCD")
            text = "Короткая тестовая фраза."
            seg = backend.segment(text)[0]
            fp = module.make_fingerprint(seg.text, backend.profile)
            job_dir = root / "job"
            (job_dir / "segments").mkdir(parents=True)
            manifest = {
                "schema_version": 1,
                "engine": module.ENGINE_ID,
                "job_id": "test",
                "created_at": module.utc_now_iso(),
                "profile": {},
                "segmentation": backend.manifest_segmentation(),
                "request_routing": backend.request_routing_identity(),
                "segments": {
                    seg.segment_id: {
                        "status": "IN_FLIGHT",
                        "fingerprint": fp,
                        "request_id": "req-old",
                        "wav": f"{seg.segment_id}__{fp[:12]}.wav",
                    }
                },
            }
            (job_dir / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(module.YandexSpeechKitError) as ctx:
                backend.run_text_job(text, job_dir, job_id="test", pricing=demo_pricing(), scope="demo")
            self.assertEqual(ctx.exception.category, "resume_ambiguous")

    def test_inflight_with_complete_job_wav_recovers_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = module.YandexBackendConfig.from_mapping({
                "output_root": str(root / "out"),
                "segmentation": {"max_chars": 220, "max_words": 34},
            })
            backend = module.YandexSpeechKitBackend(cfg, api_key="1234567890abcdefghijklmnopqrstuvABCD")
            text = "Короткая тестовая фраза."
            seg = backend.segment(text)[0]
            fp = module.make_fingerprint(seg.text, backend.profile)
            job_dir = root / "job"
            segment_dir = job_dir / "segments"
            segment_dir.mkdir(parents=True)
            wav_path = segment_dir / f"{seg.segment_id}__{fp[:12]}.wav"
            write_test_wav(wav_path)
            manifest = {
                "schema_version": 1,
                "engine": module.ENGINE_ID,
                "job_id": "test",
                "created_at": module.utc_now_iso(),
                "profile": {},
                "segmentation": backend.manifest_segmentation(),
                "request_routing": backend.request_routing_identity(),
                "segments": {
                    seg.segment_id: {
                        "status": "IN_FLIGHT",
                        "fingerprint": fp,
                        "request_id": "req-old",
                        "wav": wav_path.name,
                    }
                },
            }
            (job_dir / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            joined = backend.run_text_job(text, job_dir, job_id="test", pricing=demo_pricing(), scope="demo")
            self.assertTrue(joined.exists())
            updated = json.loads((job_dir / "MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["segments"][seg.segment_id]["status"], "DONE")
            self.assertEqual(updated["segments"][seg.segment_id]["recovered_after_interruption"], "job_wav")

    def test_existing_manifest_with_mismatched_segmentation_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = module.YandexBackendConfig.from_mapping({
                "output_root": str(root / "out"),
                "segmentation": {"max_chars": 220, "max_words": 34},
            })
            backend = module.YandexSpeechKitBackend(cfg, api_key="1234567890abcdefghijklmnopqrstuvABCD")
            job_dir = root / "job"
            job_dir.mkdir(parents=True)
            segmentation = backend.manifest_segmentation()
            segmentation["paragraph_pause_ms"] += 1
            (job_dir / "MANIFEST.json").write_text(json.dumps({
                "schema_version": 1,
                "engine": module.ENGINE_ID,
                "job_id": "test",
                "profile": {},
                "segmentation": segmentation,
                "request_routing": backend.request_routing_identity(),
                "segments": {},
            }), encoding="utf-8")
            backend._request = mock.Mock(side_effect=AssertionError("network request must not be sent"))

            with self.assertRaises(module.YandexSpeechKitError) as ctx:
                backend.run_text_job(
                    "Короткая тестовая фраза.",
                    job_dir,
                    job_id="test",
                    pricing=demo_pricing(),
                    scope="demo",
                )

            self.assertEqual(ctx.exception.category, "manifest")
            backend._request.assert_not_called()

    def test_cache_namespace_changes_with_request_routing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output_root = root / "out"
            base = {
                "output_root": str(output_root),
                "endpoint": "https://route-a.example.invalid/tts",
                "keychain_service": "Yandex-A",
                "keychain_account": "account-a",
            }
            first = module.YandexSpeechKitBackend(
                module.YandexBackendConfig.from_mapping(base),
                api_key="1234567890abcdefghijklmnopqrstuvABCD",
            )
            first._request = mock.Mock(return_value=(wav_bytes(), {}))
            text = "Маршрут кэша должен быть неизменяемым."
            cache_root = output_root / "_cache"
            first_result = first.synthesize(text, root / "first.wav", cache_root=cache_root)
            self.assertFalse(first_result.cached)
            first._request.assert_called_once()
            self.assertEqual(first.estimate(text)["cached_segments"], 1)

            second = module.YandexSpeechKitBackend(
                module.YandexBackendConfig.from_mapping({**base, "endpoint": "https://route-b.example.invalid/tts"}),
                api_key="1234567890abcdefghijklmnopqrstuvABCD",
            )
            second._request = mock.Mock(return_value=(wav_bytes(), {}))
            self.assertNotEqual(first.cache_namespace(cache_root), second.cache_namespace(cache_root))
            self.assertEqual(second.estimate(text)["cached_segments"], 0)
            second_result = second.synthesize(text, root / "second.wav", cache_root=cache_root)
            self.assertFalse(second_result.cached)
            second._request.assert_called_once()

    def test_existing_manifest_with_mismatched_routing_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = module.YandexSpeechKitBackend(
                module.YandexBackendConfig.from_mapping({
                    "output_root": str(root / "out"),
                    "endpoint": "https://route-b.example.invalid/tts",
                }),
                api_key="1234567890abcdefghijklmnopqrstuvABCD",
            )
            job_dir = root / "job"
            job_dir.mkdir(parents=True)
            old_routing = backend.request_routing_identity()
            old_routing["endpoint"] = "https://route-a.example.invalid/tts"
            (job_dir / "MANIFEST.json").write_text(json.dumps({
                "schema_version": 1,
                "engine": module.ENGINE_ID,
                "job_id": "test",
                "profile": {},
                "segmentation": backend.manifest_segmentation(),
                "request_routing": old_routing,
                "segments": {},
            }), encoding="utf-8")
            backend._request = mock.Mock(side_effect=AssertionError("network request must not be sent"))

            with self.assertRaises(module.YandexSpeechKitError) as ctx:
                backend.run_text_job(
                    "Короткая тестовая фраза.",
                    job_dir,
                    job_id="test",
                    pricing=demo_pricing(),
                    scope="demo",
                )

            self.assertEqual(ctx.exception.category, "manifest")
            backend._request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
