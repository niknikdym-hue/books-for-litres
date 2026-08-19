from __future__ import annotations

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backends import yandex_speechkit as module


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


if __name__ == "__main__":
    unittest.main()
