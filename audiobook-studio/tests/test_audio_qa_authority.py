from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_qa_authority import (
    AudioQAAuthorityError,
    resolve_qwen_authority,
    resolve_yandex_authority,
)
from backends.yandex_speechkit import TextSegment, YandexVoiceProfile, make_fingerprint
from book_library import BookLibrary


def write_wav(path: Path, *, rate: int = 22050, frames: int = 22050) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\x00\x10" * frames)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AudioQAAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        books = self.root / "books"
        books.mkdir()
        shutil.copy2(ROOT / "books/demo-book.json", books / "demo-book.json")
        self.library = BookLibrary(books)
        self.book = self.library.load_book_for_execution("demo-book")
        self.job = self.book["jobs"]["short-test"]
        self.text = self.job["segments"][0]["text"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_qwen_report_binds_current_book_text_voice_config_and_rate(self):
        config = json.loads((ROOT / "studio-config.json").read_text(encoding="utf-8"))
        config_path = self.root / "studio-config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        output = self.root / "qwen" / "demo.wav"
        report_path = output.with_name("RUN-REPORT.json")
        write_wav(output, rate=24000)
        report = {
            "book_profile_sha256": sha256(self.root / "books/demo-book.json"),
            "job": "short-test",
            "job_label": self.job["label"],
            "speaker": "Vivian",
            "model": config["model"],
            "generation": config["default_generation"],
            "audiobook_instruct": self.book["audiobook_instruct"],
            "segments": [{"id": "t01", "seed": 1}],
            "segment_count": 1,
            "sample_rate": 24000,
            "joined_wav": output.name,
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")

        authority = resolve_qwen_authority(
            library=self.library,
            book_name="demo-book",
            job_id="short-test",
            profile_id="qwen_vivian",
            report_candidates=[report_path],
            config_path=config_path,
        )
        self.assertEqual(authority.provider, "qwen")
        self.assertEqual(authority.expected_sample_rate_hz, 24000)
        self.assertEqual(authority.segment_text, self.text)
        self.assertTrue(authority.synthesis_fingerprint)

        changed = dict(config)
        changed["model"] = "changed-model"
        config_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(AudioQAAuthorityError, "report was not found"):
            resolve_qwen_authority(
                library=self.library,
                book_name="demo-book",
                job_id="short-test",
                profile_id="qwen_vivian",
                report_candidates=[report_path],
                config_path=config_path,
            )

    def test_yandex_manifest_accepts_authoritative_22050_output(self):
        profile = YandexVoiceProfile()
        segment = TextSegment("y0001", self.text, 0, 0)
        backend = SimpleNamespace(
            profile=profile,
            segment=lambda text: [segment],
            manifest_segmentation=lambda: {"max_chars": 220},
            request_routing_identity=lambda: {"endpoint": "https://example.invalid"},
        )
        output_root = self.root / "yandex"
        audio = output_root / "chapter.wav"
        manifest = output_root / "MANIFEST.json"
        write_wav(audio, rate=22050)
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "short-test",
            "status": "DONE",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": {"max_chars": 220},
            "request_routing": {"endpoint": "https://example.invalid"},
            "segments": {
                "y0001": {
                    "status": "DONE",
                    "fingerprint": make_fingerprint(self.text, profile),
                    "text": self.text,
                    "result": {"sample_rate_hz": 22050},
                }
            },
            "joined_wav": audio.name,
        }), encoding="utf-8")

        authority = resolve_yandex_authority(
            library=self.library,
            backend=backend,
            book_name="demo-book",
            job_id="short-test",
            profile_id="yandex_lera",
            manifest_candidates=[manifest],
        )
        self.assertEqual(authority.expected_sample_rate_hz, 22050)
        self.assertEqual(authority.audio_path, audio.resolve())
        self.assertEqual(authority.text_characters, len(self.text))


if __name__ == "__main__":
    unittest.main()
