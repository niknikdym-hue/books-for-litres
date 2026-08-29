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
        self._wav(self.source, frames=96_000, sample=123)
        self.source_before = sha256_file(self.source)
        self.plan_id = "a" * 64
        self.plan_digest = "b" * 64
        self.fingerprint = "c" * 64

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _wav(path: Path, *, frames: int, sample: int, sample_rate: int = 48_000) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
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

    def _approve(self, prepared: dict[str, object], **overrides: str) -> dict[str, object]:
        return approve_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            candidate_id=str(prepared["candidate_id"]),
            candidate_digest=str(prepared["candidate_digest"]),
            decision=overrides.get("decision", "APPROVE"),
            listened_audio_sha256=overrides.get(
                "listened_audio_sha256", str(prepared["audio_sha256"])
            ),
            listened_path_identity=overrides.get(
                "listened_path_identity", str(prepared["path_identity"])
            ),
            listened_synthesis_fingerprint=overrides.get(
                "listened_synthesis_fingerprint", str(prepared["synthesis_fingerprint"])
            ),
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

    def test_approval_requires_explicit_decision(self) -> None:
        prepared = self._prepare()
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._approve(prepared, decision="")
        self.assertEqual(caught.exception.code, "explicit_approval_required")
        current = self.root / "runtime" / "dilon-opening-credit" / self.book / self.job / "CURRENT.json"
        self.assertFalse(current.exists())

    def test_approval_is_bound_to_exact_listened_audio_identity(self) -> None:
        prepared = self._prepare()
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._approve(prepared, listened_audio_sha256="d" * 64)
        self.assertEqual(caught.exception.code, "listened_identity_mismatch")
        current = self.root / "runtime" / "dilon-opening-credit" / self.book / self.job / "CURRENT.json"
        self.assertFalse(current.exists())

        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._approve(prepared, listened_synthesis_fingerprint="e" * 64)
        self.assertEqual(caught.exception.code, "listened_identity_mismatch")
        self.assertFalse(current.exists())

    def test_explicit_listened_approval_publishes_status_compatible_authority(self) -> None:
        prepared = self._prepare()
        approved = self._approve(prepared)
        self.assertEqual(approved["state"], "APPROVED")
        self.assertEqual(approved["decision"], "REVIEW_COMPLETE")
        self.assertEqual(approved["listened_identity"]["audio_sha256"], prepared["audio_sha256"])
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
            self._approve(prepared)
        self.assertEqual(caught.exception.code, "candidate_integrity_mismatch")

    def test_coordinated_manifest_tamper_blocks_approval(self) -> None:
        prepared = self._prepare()
        path = Path(prepared["candidate_path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["candidate"]["manual_state"] = "APPROVED"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._approve(prepared)
        self.assertEqual(caught.exception.code, "candidate_integrity_mismatch")

    def test_non_48k_candidate_is_rejected_before_review(self) -> None:
        self._wav(self.source, frames=44_100 * 2, sample=123, sample_rate=44_100)
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._prepare()
        self.assertEqual(caught.exception.code, "unsupported_review_wav")

    def test_short_candidate_is_rejected_before_human_review(self) -> None:
        self._wav(self.source, frames=24_000, sample=123)
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._prepare()
        self.assertEqual(caught.exception.code, "opening_credit_duration_invalid")

    def test_silent_candidate_is_rejected_before_human_review(self) -> None:
        self._wav(self.source, frames=96_000, sample=0)
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._prepare()
        self.assertEqual(caught.exception.code, "opening_credit_silent")

    def test_clipped_candidate_is_rejected_before_review(self) -> None:
        self._wav(self.source, frames=96_000, sample=32767)
        with self.assertRaises(OpeningCreditReviewError) as caught:
            self._prepare()
        self.assertEqual(caught.exception.code, "opening_credit_clipping")

    def test_impossible_zero_request_paid_provenance_is_rejected(self) -> None:
        with self.assertRaises(OpeningCreditReviewError) as caught:
            prepare_review_candidate(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
                source_wav=self.source,
                plan_id=self.plan_id,
                plan_digest=self.plan_digest,
                synthesis_fingerprint=self.fingerprint,
                profile=EXPECTED_PROFILE,
                provider_requests=0,
                remote_request_sent=True,
                paid_execution=True,
                billing_changed=True,
            )
        self.assertEqual(caught.exception.code, "invalid_provenance")


if __name__ == "__main__":
    unittest.main()
