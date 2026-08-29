from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

from audio_qa_review import sha256_file
from dilon_identity_status import _load_opening_credit_authority
from dilon_opening_credit_review import (
    EXPECTED_PROFILE,
    OpeningCreditReviewError,
    approve_review_candidate,
    prepare_review_candidate,
)


class DilonOpeningCreditReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.source = self.root / "runtime" / "provider-output" / "opening-review.wav"
        self._wav(self.source, frames=4_800, sample=123)
        self.source_before = sha256_file(self.source)
        self.plan_id = "a" * 64
        self.plan_digest = "b" * 64
        self.fingerprint = "c" * 64

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

    def _prepare(self) -> dict[str, object]:
        return prepare_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            source_wav=self.source,
            plan_id=self.plan_id,
            plan_digest=self.plan_digest,
            synthesis_fingerprint=self.fingerprint,
            profile=EXPECTED_PROFILE,
            provider_requests=1,
            remote_request_sent=True,
            paid_execution=True,
            billing_changed=True,
        )

    def test_prepare_creates_immutable_candidate_but_not_current(self) -> None:
        prepared = self._prepare()
        self.assertEqual(prepared["state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(prepared["decision"], "HUMAN_LISTENING_REQUIRED")
        self.assertTrue(Path(prepared["candidate_path"]).is_file())
        self.assertTrue(Path(prepared["audio_path"]).is_file())
        self.assertEqual(sha256_file(self.source), self.source_before)
        current = (
            self.root / "runtime" / "dilon-opening-credit" / self.book / self.job / "CURRENT.json"
        )
        self.assertFalse(current.exists())
        self.assertEqual(prepared["provider_requests"], 0)
        self.assertFalse(prepared["remote_request_sent"])
        self.assertFalse(prepared["paid_execution"])
        self.assertFalse(prepared["billing_changed"])
        self.assertEqual(prepared["historical_provenance"]["provider_requests"], 1)
        self.assertTrue(prepared["historical_provenance"]["paid_execution"])

    def test_prepare_is_idempotent_for_exact_same_candidate(self) -> None:
        first = self._prepare()
        manifest_bytes = Path(first["candidate_path"]).read_bytes()
        audio_bytes = Path(first["audio_path"]).read_bytes()
        second = self._prepare()
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(second["candidate_digest"], first["candidate_digest"])
        self.assertEqual(Path(second["candidate_path"]).read_bytes(), manifest_bytes)
        self.assertEqual(Path(second["audio_path"]).read_bytes(), audio_bytes)

    def test_approval_requires_explicit_exact_candidate_decision(self) -> None:
        prepared = self._prepare()
        with self.assertRaises(OpeningCreditReviewError) as caught:
            approve_review_candidate(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
                candidate_id=prepared["candidate_id"],
                candidate_digest=prepared["candidate_digest"],
                decision="",
            )
        self.assertEqual(caught.exception.code, "explicit_approval_required")
        current = self.root / "runtime" / "dilon-opening-credit" / self.book / self.job / "CURRENT.json"
        self.assertFalse(current.exists())

    def test_explicit_approval_publishes_status_compatible_current_authority(self) -> None:
        prepared = self._prepare()
        approved = approve_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            candidate_id=prepared["candidate_id"],
            candidate_digest=prepared["candidate_digest"],
            decision="APPROVE",
        )
        self.assertEqual(approved["state"], "APPROVED")
        self.assertEqual(approved["decision"], "REVIEW_COMPLETE")
        self.assertEqual(approved["provider_requests"], 0)
        self.assertFalse(approved["remote_request_sent"])
        self.assertFalse(approved["paid_execution"])
        self.assertFalse(approved["billing_changed"])
        authority, path = _load_opening_credit_authority(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
        )
        self.assertTrue(path.is_file())
        self.assertIsNotNone(authority)
        self.assertEqual(authority["manual_state"], "APPROVED")
        self.assertEqual(authority["reviewed_identity"]["synthesis_fingerprint"], self.fingerprint)
        self.assertEqual(authority["provider_requests"], 1)
        self.assertTrue(authority["remote_request_sent"])
        self.assertTrue(authority["paid_execution"])
        self.assertTrue(authority["billing_changed"])

    def test_candidate_audio_tamper_blocks_approval(self) -> None:
        prepared = self._prepare()
        Path(prepared["audio_path"]).write_bytes(b"tampered")
        with self.assertRaises(OpeningCreditReviewError) as caught:
            approve_review_candidate(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
                candidate_id=prepared["candidate_id"],
                candidate_digest=prepared["candidate_digest"],
                decision="APPROVE",
            )
        self.assertEqual(caught.exception.code, "candidate_integrity_mismatch")

    def test_coordinated_manifest_tamper_blocks_approval(self) -> None:
        prepared = self._prepare()
        path = Path(prepared["candidate_path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["candidate"]["manual_state"] = "APPROVED"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(OpeningCreditReviewError) as caught:
            approve_review_candidate(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
                candidate_id=prepared["candidate_id"],
                candidate_digest=prepared["candidate_digest"],
                decision="APPROVE",
            )
        self.assertEqual(caught.exception.code, "candidate_integrity_mismatch")

    def test_non_48k_candidate_is_rejected_before_review(self) -> None:
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(22_050)
            output.writeframes(b"\x00\x00" * 100)
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._prepare()
        self.assertEqual(caught.exception.code, "unsupported_review_wav")

    def test_clipped_candidate_is_rejected_before_review(self) -> None:
        self._wav(self.source, frames=100, sample=32767)
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._prepare()
        self.assertEqual(caught.exception.code, "opening_credit_clipping")


if __name__ == "__main__":
    unittest.main()
