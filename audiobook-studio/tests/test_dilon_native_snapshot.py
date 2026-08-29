from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from audio_qa_review import sha256_file
from dilon_opening_credit_review import (
    EXPECTED_PROFILE,
    approve_review_candidate,
    prepare_review_candidate,
)
import dilon_native_snapshot as native


class DilonNativeSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.masters = self.root / "masters"
        self.identities = self.root / "identities"
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.source = self.root / "runtime" / "provider-output" / "opening.wav"
        self._wav(self.source)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _wav(path: Path, *, frames: int = 96_000, sample: int = 123) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(int(sample).to_bytes(2, "little", signed=True) * frames)

    def _candidate(
        self,
        *,
        book: str | None = None,
        source: Path | None = None,
        plan_character: str = "a",
        digest_character: str = "b",
        fingerprint_character: str = "c",
    ) -> dict[str, object]:
        return prepare_review_candidate(
            workspace_root=self.root,
            book_slug=book or self.book,
            job_id=self.job,
            source_wav=source or self.source,
            plan_id=plan_character * 64,
            plan_digest=digest_character * 64,
            synthesis_fingerprint=fingerprint_character * 64,
            profile=EXPECTED_PROFILE,
            provider_requests=1,
            remote_request_sent=True,
            paid_execution=True,
            billing_changed=True,
        )

    @staticmethod
    def _offline_status(book: str, job: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "state": "BLOCKED",
            "decision": "BLOCKED",
            "book_slug": book,
            "job_id": job,
            "whole_book_release_ready": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
            "blockers": ["opening_credit_missing"],
        }

    def test_valid_candidate_catalog_is_exact_deterministic_and_read_only(self) -> None:
        prepared = self._candidate()
        source_before = sha256_file(self.source)
        first = native.list_review_candidates(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
        )
        second = native.list_review_candidates(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        item = first[0]
        self.assertEqual(item["candidate_id"], prepared["candidate_id"])
        self.assertEqual(item["candidate_digest"], prepared["candidate_digest"])
        self.assertEqual(item["audio_sha256"], prepared["audio_sha256"])
        self.assertEqual(item["path_identity"], prepared["path_identity"])
        self.assertEqual(item["synthesis_fingerprint"], prepared["synthesis_fingerprint"])
        self.assertFalse(item["is_current_approved"])
        self.assertEqual(item["historical_provenance"]["provider_requests"], 1)
        self.assertTrue(item["historical_provenance"]["paid_execution"])
        self.assertEqual(sha256_file(self.source), source_before)

    def test_approved_current_candidate_is_marked_only_after_exact_authority_validation(self) -> None:
        prepared = self._candidate()
        approve_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            candidate_id=str(prepared["candidate_id"]),
            candidate_digest=str(prepared["candidate_digest"]),
            decision="APPROVE",
            listened_audio_sha256=str(prepared["audio_sha256"]),
            listened_path_identity=str(prepared["path_identity"]),
            listened_synthesis_fingerprint=str(prepared["synthesis_fingerprint"]),
        )
        catalog = native.list_review_candidates(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
        )
        self.assertEqual(len(catalog), 1)
        self.assertTrue(catalog[0]["is_current_approved"])

    def test_tampered_current_candidate_reference_fails_closed(self) -> None:
        prepared = self._candidate()
        approved = approve_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            candidate_id=str(prepared["candidate_id"]),
            candidate_digest=str(prepared["candidate_digest"]),
            decision="APPROVE",
            listened_audio_sha256=str(prepared["audio_sha256"]),
            listened_path_identity=str(prepared["path_identity"]),
            listened_synthesis_fingerprint=str(prepared["synthesis_fingerprint"]),
        )
        current = Path(str(approved["authority_path"]))
        payload = json.loads(current.read_text(encoding="utf-8"))
        payload["candidate_digest"] = "d" * 64
        current.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(native.DilonNativeSnapshotError) as caught:
            native.list_review_candidates(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
            )
        self.assertEqual(caught.exception.code, "opening_credit_current_invalid")

    def test_symlinked_candidate_catalog_fails_closed_without_traversal(self) -> None:
        review = self.root / "runtime" / "dilon-opening-credit" / self.book / self.job
        review.mkdir(parents=True)
        outside = self.root / "outside-candidates"
        outside.mkdir()
        marker = outside / "marker.txt"
        marker.write_text("unchanged", encoding="utf-8")
        (review / "candidates").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(native.DilonNativeSnapshotError) as caught:
            native.list_review_candidates(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
            )
        self.assertEqual(caught.exception.code, "review_candidate_catalog_unsafe")
        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

    def test_invalid_candidate_package_blocks_catalog_instead_of_being_silently_skipped(self) -> None:
        prepared = self._candidate()
        Path(str(prepared["audio_path"])).write_bytes(b"tampered")
        with self.assertRaises(native.DilonNativeSnapshotError) as caught:
            native.list_review_candidates(
                workspace_root=self.root,
                book_slug=self.book,
                job_id=self.job,
            )
        self.assertEqual(caught.exception.code, "review_candidate_catalog_invalid")

    def test_unicode_book_slug_catalog_is_supported(self) -> None:
        book = "книга-тест"
        source = self.root / "runtime" / "provider-output" / "unicode.wav"
        self._wav(source)
        prepared = self._candidate(
            book=book,
            source=source,
            plan_character="d",
            digest_character="e",
            fingerprint_character="f",
        )
        catalog = native.list_review_candidates(
            workspace_root=self.root,
            book_slug=book,
            job_id=self.job,
        )
        self.assertEqual(catalog[0]["candidate_id"], prepared["candidate_id"])

    def test_native_snapshot_combines_current_status_and_review_candidates_offline(self) -> None:
        prepared = self._candidate()
        fake_status = self._offline_status(self.book, self.job)
        with mock.patch.object(
            native,
            "current_dilon_identity_status",
            return_value=fake_status,
        ) as status_call:
            snapshot = native.current_native_snapshot(
                workspace_root=self.root,
                masters_root=self.masters,
                identities_root=self.identities,
                book_slug=self.book,
                job_id=self.job,
            )
        status_call.assert_called_once()
        self.assertEqual(snapshot["state"], "READY")
        self.assertEqual(snapshot["decision"], "DISPLAY_CURRENT_DILON_STATE")
        self.assertEqual(snapshot["dilon_status"], fake_status)
        self.assertEqual(snapshot["review_candidates"][0]["candidate_id"], prepared["candidate_id"])
        self.assertTrue(snapshot["capabilities"]["prepare_opening_credit_offline"])
        self.assertTrue(snapshot["capabilities"]["review_candidate_offline"])
        self.assertTrue(snapshot["capabilities"]["identity_preview_offline"])
        self.assertFalse(snapshot["capabilities"]["provider_execution_available"])
        self.assertFalse(snapshot["capabilities"]["paid_execution_available"])
        self.assertFalse(snapshot["capabilities"]["automatic_review_approval"])
        self.assertFalse(snapshot["whole_book_release_ready"])
        self.assertEqual(snapshot["provider_requests"], 0)
        self.assertFalse(snapshot["remote_request_sent"])
        self.assertFalse(snapshot["paid_execution"])
        self.assertFalse(snapshot["billing_changed"])

    def test_nonoffline_status_is_rejected_before_native_presentation(self) -> None:
        unsafe = self._offline_status(self.book, self.job)
        unsafe["provider_requests"] = 1
        with mock.patch.object(
            native,
            "current_dilon_identity_status",
            return_value=unsafe,
        ):
            with self.assertRaises(native.DilonNativeSnapshotError) as caught:
                native.current_native_snapshot(
                    workspace_root=self.root,
                    masters_root=self.masters,
                    identities_root=self.identities,
                    book_slug=self.book,
                    job_id=self.job,
                )
        self.assertEqual(caught.exception.code, "offline_contract_violation")


if __name__ == "__main__":
    unittest.main()
