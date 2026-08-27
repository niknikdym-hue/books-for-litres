from __future__ import annotations

import json
import math
import multiprocessing
import struct
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_qa_review import AudioQAError, AudioQAReviewService


def _delayed_status_scan(
    state_root: str,
    audio_path: str,
    entered: multiprocessing.synchronize.Event,
) -> None:
    import audio_qa_review as module

    original = module.atomic_write_json

    def delayed_write(path, payload):
        if payload.get("manual_state") == "APPROVED":
            entered.set()
            time.sleep(0.35)
        original(path, payload)

    module.atomic_write_json = delayed_write
    AudioQAReviewService(Path(state_root)).scan(
        book_slug="book-one",
        job_id="chapter-ch001",
        segment_id="s0001",
        audio_path=Path(audio_path),
        synthesis_fingerprint="fp-1",
        expected_sample_rate_hz=24_000,
        text_characters=8,
    )


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
    def write_wav(
        path: Path,
        *,
        frequency: float,
        amplitude: int = 4000,
        duration: float = 0.20,
        sample_rate: int = 24_000,
    ) -> None:
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

    def scan(
        self,
        *,
        fingerprint: str = "fp-1",
        expected_sample_rate_hz: int = 24_000,
        text_characters: int = 8,
    ):
        return self.service.scan(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint=fingerprint,
            expected_sample_rate_hz=expected_sample_rate_hz,
            text_characters=text_characters,
        )

    def decide(self, decision: str, *, fingerprint: str = "fp-1", reviewed_identity=None):
        reviewed_identity = reviewed_identity or self.scan(fingerprint=fingerprint)["identity"]
        return self.service.decide(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint=fingerprint,
            expected_sample_rate_hz=24_000,
            text_characters=8,
            decision=decision,
            reviewed_identity=reviewed_identity,
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
            expected_sample_rate_hz=24_000,
            text_characters=8,
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
            expected_sample_rate_hz=24_000,
            text_characters=8,
        ))
        self.decide("APPROVED")
        eligible = self.service.downstream_audio(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
            expected_sample_rate_hz=24_000,
            text_characters=8,
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
            expected_sample_rate_hz=24_000,
            text_characters=8,
        ))

    def test_decision_rejects_replacement_bytes_not_the_audio_reviewed(self):
        reviewed = self.scan()["identity"]
        self.write_wav(self.audio, frequency=880.0)
        with self.assertRaisesRegex(AudioQAError, "identity is stale"):
            self.decide("APPROVED", reviewed_identity=reviewed)
        stored = self.service.status(book_slug="book-one", job_id="chapter-ch001", segment_id="s0001")
        self.assertEqual(stored["manual_state"], "STALE")
        self.assertFalse(stored["downstream_eligible"])

    def test_decision_rejects_changed_current_fingerprint_with_same_bytes(self):
        reviewed = self.scan(fingerprint="fp-1")["identity"]
        with self.assertRaisesRegex(AudioQAError, "identity is stale"):
            self.decide("APPROVED", fingerprint="fp-2", reviewed_identity=reviewed)
        stored = self.service.status(book_slug="book-one", job_id="chapter-ch001", segment_id="s0001")
        self.assertEqual(stored["manual_state"], "STALE")

    def test_provider_specific_sample_rate_contracts(self):
        self.write_wav(self.audio, frequency=440.0, sample_rate=22_050)
        yandex = self.scan(expected_sample_rate_hz=22_050)
        self.assertNotIn("unexpected_sample_rate", yandex["automatic_reasons"])
        mismatch = self.scan(expected_sample_rate_hz=24_000)
        self.assertIn("unexpected_sample_rate", mismatch["automatic_reasons"])
        self.write_wav(self.audio, frequency=440.0, sample_rate=24_000)
        openai = self.scan(expected_sample_rate_hz=24_000)
        self.assertNotIn("unexpected_sample_rate", openai["automatic_reasons"])

    def test_dot_only_and_traversal_state_identifiers_are_rejected(self):
        for value in (".", "..", "...", "../escape", "a/b"):
            with self.subTest(value=value), self.assertRaises(AudioQAError):
                self.service.scan(
                    book_slug=value,
                    job_id="chapter-ch001",
                    segment_id="s0001",
                    audio_path=self.audio,
                    synthesis_fingerprint="fp-1",
                    expected_sample_rate_hz=24_000,
                    text_characters=8,
                )

    def test_unicode_book_slug_persists_and_preserves_exact_identity(self):
        scanned = self.service.scan(
            book_slug="война-и-мир",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
            expected_sample_rate_hz=24_000,
            text_characters=8,
        )
        approved = self.service.decide(
            book_slug="война-и-мир",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
            expected_sample_rate_hz=24_000,
            text_characters=8,
            decision="APPROVED",
            reviewed_identity=scanned["identity"],
        )
        self.assertEqual(approved["book_slug"], "война-и-мир")
        restarted = AudioQAReviewService(self.state_root)
        stored = restarted.status(
            book_slug="война-и-мир", job_id="chapter-ch001", segment_id="s0001"
        )
        self.assertEqual(stored["manual_state"], "APPROVED")
        self.write_wav(self.audio, frequency=660.0)
        stale = restarted.scan(
            book_slug="война-и-мир",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
            expected_sample_rate_hz=24_000,
            text_characters=8,
        )
        self.assertEqual(stale["manual_state"], "STALE")
        self.assertTrue(
            (self.state_root / "война-и-мир/chapter-ch001/s0001.json")
            .resolve()
            .is_relative_to(self.state_root.resolve())
        )

    def test_unicode_book_slug_still_rejects_every_path_escape(self):
        for value in (".", "..", "...", "../foo", "foo/bar", "foo\\bar", "война/мир"):
            with self.subTest(value=value), self.assertRaises(AudioQAError):
                self.service.scan(
                    book_slug=value,
                    job_id="chapter-ch001",
                    segment_id="s0001",
                    audio_path=self.audio,
                    synthesis_fingerprint="fp-1",
                    expected_sample_rate_hz=24_000,
                    text_characters=8,
                )

    def test_text_derived_threshold_rejects_obvious_truncation_but_accepts_short_text(self):
        self.write_wav(self.audio, frequency=440.0, duration=0.08)
        truncated = self.scan(text_characters=200)
        self.assertIn("implausibly_short_for_text", truncated["automatic_reasons"])
        short = self.scan(text_characters=2)
        self.assertNotIn("implausibly_short_for_text", short["automatic_reasons"])

    def test_signal_metrics_stream_long_wav_without_read_bytes_or_full_sample_list(self):
        self.write_wav(self.audio, frequency=440.0, duration=12.0)
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("full WAV read")):
            result = self.scan(text_characters=100)
        metrics = result["signal_metrics"]
        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["stream_chunk_bytes"], 65_536)
        self.assertLess(metrics["stream_chunk_bytes"], result["wav"]["data_bytes"])

    def test_concurrent_status_cannot_resurrect_approval_over_newer_rejection(self):
        approved = self.decide("APPROVED")
        context = multiprocessing.get_context("fork")
        entered = context.Event()
        process = context.Process(
            target=_delayed_status_scan,
            args=(str(self.state_root), str(self.audio), entered),
        )
        process.start()
        self.assertTrue(entered.wait(5), "delayed status did not reach the write")
        rejected = self.service.decide(
            book_slug="book-one",
            job_id="chapter-ch001",
            segment_id="s0001",
            audio_path=self.audio,
            synthesis_fingerprint="fp-1",
            expected_sample_rate_hz=24_000,
            text_characters=8,
            decision="REJECTED",
            reviewed_identity=approved["identity"],
        )
        process.join(5)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(rejected["manual_state"], "REJECTED")
        stored = self.service.status(book_slug="book-one", job_id="chapter-ch001", segment_id="s0001")
        self.assertEqual(stored["manual_state"], "REJECTED")

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
