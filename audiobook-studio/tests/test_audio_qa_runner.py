from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "audio_qa_runner.py"


class AudioQARunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.audio = self.root / "segment.wav"
        self.write_wav(self.audio)
        self.env = dict(os.environ, AUDIOBOOK_STUDIO_HOME=str(self.root), PYTHONDONTWRITEBYTECODE="1")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write_wav(path: Path) -> None:
        sample_rate = 24_000
        frames = 4_800
        samples = [
            int(3000 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate))
            for index in range(frames)
        ]
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    def run_json(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(RUNNER), *args],
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def base_args(self) -> tuple[str, ...]:
        return (
            "--book", "book-one",
            "--job", "chapter-ch001",
            "--segment-id", "s0001",
        )

    def test_scan_approve_status_and_downstream_are_offline_and_restart_safe(self):
        scanned = self.run_json(
            "--scan", *self.base_args(),
            "--audio-path", str(self.audio),
            "--fingerprint", "fp-1",
        )
        self.assertIn(scanned["automatic_status"], {"PASS", "WARN"})
        self.assertFalse(scanned["remote_request_sent"])

        approved = self.run_json(
            "--decide", *self.base_args(),
            "--audio-path", str(self.audio),
            "--fingerprint", "fp-1",
            "--decision", "APPROVED",
        )
        self.assertEqual(approved["manual_state"], "APPROVED")
        self.assertTrue(approved["downstream_eligible"])
        self.assertFalse(approved["remote_request_sent"])

        status = self.run_json("--status", *self.base_args())
        self.assertEqual(status["record"]["manual_state"], "APPROVED")
        self.assertFalse(status["remote_request_sent"])

        downstream = self.run_json(
            "--downstream", *self.base_args(),
            "--audio-path", str(self.audio),
            "--fingerprint", "fp-1",
        )
        self.assertTrue(downstream["eligible"])
        self.assertEqual(downstream["record"]["manual_state"], "APPROVED")
        self.assertFalse(downstream["remote_request_sent"])

    def test_request_regeneration_records_state_only(self):
        result = self.run_json(
            "--decide", *self.base_args(),
            "--audio-path", str(self.audio),
            "--fingerprint", "fp-1",
            "--decision", "REGENERATE_REQUESTED",
        )
        self.assertEqual(result["manual_state"], "REGENERATE_REQUESTED")
        self.assertFalse(result["downstream_eligible"])
        self.assertFalse(result["remote_request_sent"])


if __name__ == "__main__":
    unittest.main()
