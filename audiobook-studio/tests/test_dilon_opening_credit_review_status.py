from __future__ import annotations

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from dilon_opening_credit_review import EXPECTED_PROFILE, prepare_review_candidate
from dilon_opening_credit_review_status import OpeningCreditReviewError, opening_credit_review_status
import dilon_opening_credit_review_status_runner as runner


class DilonOpeningCreditReviewStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.source = self.root / "runtime" / "provider-output" / "opening-review.wav"
        self._wav(self.source, frames=96_000, sample=123)
        self.prepared = prepare_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            source_wav=self.source,
            plan_id="a" * 64,
            plan_digest="b" * 64,
            synthesis_fingerprint="c" * 64,
            profile=EXPECTED_PROFILE,
            provider_requests=1,
            remote_request_sent=True,
            paid_execution=True,
            billing_changed=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _wav(path: Path, *, frames: int, sample: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(int(sample).to_bytes(2, "little", signed=True) * frames)

    def _status(self) -> dict[str, object]:
        return opening_credit_review_status(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            candidate_id=str(self.prepared["candidate_id"]),
            candidate_digest=str(self.prepared["candidate_digest"]),
        )

    def test_pending_candidate_returns_exact_read_only_listening_identity(self) -> None:
        status = self._status()
        self.assertEqual(status["state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(status["decision"], "HUMAN_LISTENING_REQUIRED")
        self.assertEqual(status["candidate"]["manual_state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(status["preview"]["audio_sha256"], self.prepared["audio_sha256"])
        self.assertEqual(status["preview"]["path_identity"], self.prepared["path_identity"])
        self.assertEqual(
            status["preview"]["synthesis_fingerprint"], self.prepared["synthesis_fingerprint"]
        )
        self.assertTrue(status["preview"]["read_only"])
        self.assertEqual(status["listened_identity_required"]["audio_sha256"], self.prepared["audio_sha256"])
        self.assertEqual(status["provider_requests"], 0)
        self.assertFalse(status["remote_request_sent"])
        self.assertFalse(status["paid_execution"])
        self.assertFalse(status["billing_changed"])
        self.assertEqual(status["historical_provenance"]["provider_requests"], 1)
        self.assertTrue(status["historical_provenance"]["paid_execution"])

    def test_wrong_digest_or_tampered_candidate_is_blocked(self) -> None:
        with self.assertRaises(OpeningCreditReviewError):
            opening_credit_review_status(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
                candidate_id=str(self.prepared["candidate_id"]),
                candidate_digest="d" * 64,
            )
        Path(self.prepared["audio_path"]).write_bytes(b"tampered")
        with self.assertRaises(OpeningCreditReviewError):
            self._status()

    def test_runner_emits_same_identity_and_exposes_no_approval_action(self) -> None:
        with mock.patch.dict(os.environ, {"AUDIOBOOK_STUDIO_HOME": str(self.root)}), mock.patch(
            "builtins.print"
        ) as output:
            return_code = runner.main(
                [
                    "--status",
                    "--book", self.book,
                    "--job", self.job,
                    "--candidate-id", str(self.prepared["candidate_id"]),
                    "--candidate-digest", str(self.prepared["candidate_digest"]),
                ]
            )
        self.assertEqual(return_code, 0)
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["preview"]["audio_sha256"], self.prepared["audio_sha256"])
        self.assertEqual(payload["provider_requests"], 0)
        help_text = runner.build_parser().format_help().lower()
        self.assertNotIn("approve", help_text)
        self.assertNotIn("execute", help_text)
        self.assertNotIn("synthesize", help_text)
        self.assertNotIn("provider", help_text)

    def test_runner_failure_is_structured_and_offline(self) -> None:
        with mock.patch.dict(os.environ, {"AUDIOBOOK_STUDIO_HOME": str(self.root)}), mock.patch(
            "builtins.print"
        ) as output:
            return_code = runner.main(
                [
                    "--status",
                    "--book", self.book,
                    "--job", self.job,
                    "--candidate-id", str(self.prepared["candidate_id"]),
                    "--candidate-digest", "d" * 64,
                ]
            )
        self.assertEqual(return_code, 2)
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertIsNone(payload["preview"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])


if __name__ == "__main__":
    unittest.main()
