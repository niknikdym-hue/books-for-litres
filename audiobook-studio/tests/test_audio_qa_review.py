from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_qa_review import AudioQAError, AudioQAReviewService


class AudioQAReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_root = self.root / "qa-state"
        self.audio = self.root / "segment.wav"
        self.service = AudioQAReviewService(self.state_root)
        self.write_wav(self.audio, frequency=440.0)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write_wav(path: Path, *, frequency: float, amplitude: int = 4000, duration: float = 0.20) -> None:
        sample_rate = 24_000
        frame_count = int(sample_rate * duration)
        samples = [
            int(amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate))
            for index in range(frame_count)
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    def scan(self, *, fingerprint: str = "fp-1"):
        return self.service.scan(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint=fingerprint,
        )

    def decide(self, decision: str, *, fingerprint: str = "fp-1"):
        return self.service.decide(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint=fingerprint,
            decision=decision,
        )

    def test_valid_wav_passes_or_warns_only_for_environmental_ffmpeg(self):
        result = self.scan()
        self.assertIn(result["automatic_status"], {"PASS", "WARN"})
        self.assertEqual(result["automatic_reasons"], [])
        self.assertEqual(result["wav"]["sample_rate_hz"], 24_000)
        self.assertEqual(result["wav"]["channels"], 1)
        self.assertEqual(result["wav"]["sample_width_bytes"], 2)
        self.assertEqual(len(result["identity"]["audio_sha256"]), 64)
        self.assertTrue(result["signal_metrics"]["available"])
        self.assertFalse(result["remote_request_sent"])

    def test_corrupt_or_truncated_wav_is_fail_and_cannot_be_approved(self):
        self.audio.write_bytes(b"RIFF\x00\x00")
        result = self.scan()
        self.assertEqual(result["automatic_status"], "FAIL")
        self.assertIn("invalid_or_truncated_wav", result["automatic_reasons"])
        with self.assertRaises(AudioQAError):
            self.decide("APPROVED")

    def test_approval_persists_across_restart_for_unchanged_audio(self):
        approved = self.decide("APPROVED")
        self.assertTrue(approved["downstream_eligible"])
        restarted = AudioQAReviewService(self.state_root)
        result = restarted.scan(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
        )
        self.assertEqual(result["manual_state"], "APPROVED")
        self.assertTrue(result["downstream_eligible"])

    def test_changed_audio_invalidates_old_approval(self):
        approved = self.decide("APPROVED")
        old_sha = approved["identity"]["audio_sha256"]
        self.write_wav(self.audio, frequency=660.0)
        result = self.scan()
        self.assertNotEqual(result["identity"]["audio_sha256"], old_sha)
        self.assertEqual(result["manual_state"], "STALE")
        self.assertFalse(result["downstream_eligible"])

    def test_changed_fingerprint_invalidates_old_approval_even_when_bytes_match(self):
        self.decide("APPROVED", fingerprint="fp-1")
        result = self.scan(fingerprint="fp-2")
        self.assertEqual(result["manual_state"], "STALE")
        self.assertFalse(result["downstream_eligible"])

    def test_rejected_and_regenerate_requested_states_persist_without_provider_request(self):
        rejected = self.decide("REJECTED")
        self.assertEqual(rejected["manual_state"], "REJECTED")
        self.assertFalse(rejected["remote_request_sent"])
        regenerated = self.decide("REGENERATE_REQUESTED")
        self.assertEqual(regenerated["manual_state"], "REGENERATE_REQUESTED")
        self.assertFalse(regenerated["remote_request_sent"])
        restarted = AudioQAReviewService(self.state_root)
        stored = restarted.status(book_slug="book-one", job_id="chapter-ch001", segment_id="s0001")
        self.assertEqual(stored["manual_state"], "REGENERATE_REQUESTED")

    def test_downstream_selector_admits_only_exact_current_approved_audio(self):
        self.assertIsNone(self.service.downstream_audio(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
        ))
        self.decide("APPROVED")
        eligible = self.service.downstream_audio(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
        )
        self.assertIsNotNone(eligible)
        self.assertTrue(eligible["downstream_eligible"])
        self.decide("REJECTED")
        self.assertIsNone(self.service.downstream_audio(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
        ))

    def test_state_contains_no_credentials_or_secret_fields(self):
        self.decide("APPROVED")
        state_file = self.state_root / "book-one" / "chapter-ch001" / "s0001.json"
        payload = state_file.read_text(encoding="utf-8").lower()
        for forbidden in ("api_key", "apikey", "credential", "password", "bearer"):
            self.assertNotIn(forbidden, payload)
        decoded = json.loads(payload)
        self.assertEqual(decoded["remote_request_sent"], False)


if __name__ == "__main__":
    unittest.main()
