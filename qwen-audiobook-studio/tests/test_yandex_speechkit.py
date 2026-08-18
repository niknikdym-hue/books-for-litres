from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import wave
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "backends" / "yandex_speechkit.py"
spec = importlib.util.spec_from_file_location("yandex_speechkit", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


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
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                wf.writeframes(b"\x00\x00" * 2205)
            duration, rate, channels, width = module._wav_info(path)
            self.assertAlmostEqual(duration, 0.1, places=2)
            self.assertEqual((rate, channels, width), (22050, 1, 2))

    def test_config_default_profile(self):
        cfg = module.YandexBackendConfig.from_mapping({"output_root": "~/tmp-audiobook"})
        self.assertEqual(cfg.profile.voice, "lera")
        self.assertEqual(cfg.profile.role, "neutral")
        self.assertEqual(cfg.profile.speed, "1.04")


if __name__ == "__main__":
    unittest.main()
