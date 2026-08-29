from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dilon_identity_review as review


class DilonIdentityReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.masters = self.root / "masters"
        self.identities = self.root / "identities"
        self.masters.mkdir()
        self.identities.mkdir()
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.subject = {
            "book_slug": self.book,
            "job_id": self.job,
            "build_identity": "a" * 64,
            "audio_path": str(self.root / "identities" / "identity.wav"),
            "audio_sha256": "b" * 64,
            "path_identity": "c" * 64,
            "technical_qa": {
                "status": "PASS",
                "output_sha256": "b" * 64,
                "opening_credit_sha256": "d" * 64,
                "clean_master_sha256": "e" * 64,
                "frame_count": 123456,
                "gap_frames": 24000,
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def patch_subject(self, value: dict[str, object] | None = None):
        return mock.patch.object(
            review,
            "current_identity_subject",
            return_value=dict(value or self.subject),
        )

    def status(self):
        return review.identity_review_status(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
        )

    def approve(self, **overrides: str):
        return review.approve_current_identity(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            listened_build_identity=overrides.get("build", self.subject["build_identity"]),
            listened_audio_sha256=overrides.get("sha", self.subject["audio_sha256"]),
            listened_path_identity=overrides.get("path", self.subject["path_identity"]),
        )

    def test_unreviewed_current_identity_is_pending_and_offline(self) -> None:
        with self.patch_subject():
            result = self.status()
        self.assertEqual(result["state"], "PENDING_HUMAN_REVIEW")
        self.assertTrue(result["human_listening_required"])
        self.assertFalse(result["identity_accepted"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])
        self.assertFalse(result["whole_book_release_ready"])

    def test_exact_listened_identity_approves_and_is_idempotent(self) -> None:
        with self.patch_subject():
            first = self.approve()
            manifest_path = Path(first["review_manifest_path"])
            before = manifest_path.read_bytes()
            second = self.approve()
        self.assertEqual(first["state"], "APPROVED")
        self.assertEqual(first["decision"], "IDENTITY_REVIEW_COMPLETE")
        self.assertTrue(first["identity_accepted"])
        self.assertFalse(first["human_listening_required"])
        self.assertEqual(second["subject"], first["subject"])
        self.assertEqual(manifest_path.read_bytes(), before)
        current = Path(first["review_authority_path"])
        payload = json.loads(current.read_text(encoding="utf-8"))
        self.assertEqual(payload["build_identity"], self.subject["build_identity"])
        self.assertEqual(payload["audio_sha256"], self.subject["audio_sha256"])
        self.assertEqual(payload["path_identity"], self.subject["path_identity"])

    def test_wrong_listened_identity_is_rejected_without_current(self) -> None:
        with self.patch_subject():
            with self.assertRaises(review.DilonIdentityReviewError) as caught:
                self.approve(sha="f" * 64)
        self.assertEqual(caught.exception.code, "listened_identity_mismatch")
        current = review.identity_review_root(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
        ) / "CURRENT.json"
        self.assertFalse(current.exists())

    def test_changed_current_build_invalidates_old_review(self) -> None:
        with self.patch_subject():
            self.approve()
        changed = dict(self.subject)
        changed["build_identity"] = "9" * 64
        changed["audio_sha256"] = "8" * 64
        changed["path_identity"] = "7" * 64
        changed["audio_path"] = str(self.root / "identities" / "new-identity.wav")
        with self.patch_subject(changed):
            result = self.status()
        self.assertEqual(result["state"], "PENDING_HUMAN_REVIEW")
        self.assertTrue(result["stale_previous_review"])
        self.assertFalse(result["identity_accepted"])

    def test_tampered_review_manifest_fails_closed(self) -> None:
        with self.patch_subject():
            approved = self.approve()
            manifest = Path(approved["review_manifest_path"])
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["listened_identity"]["audio_sha256"] = "0" * 64
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(review.DilonIdentityReviewError) as caught:
                self.status()
        self.assertEqual(caught.exception.code, "identity_review_stale")

    def test_symlinked_current_is_rejected_without_following_target(self) -> None:
        review_root = review.identity_review_root(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
        )
        review_root.mkdir(parents=True)
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        (review_root / "CURRENT.json").symlink_to(outside)
        with self.patch_subject():
            with self.assertRaises(review.DilonIdentityReviewError) as caught:
                self.status()
        self.assertEqual(caught.exception.code, "review_symlink")
        self.assertEqual(outside.read_text(encoding="utf-8"), "{}")

    def test_unicode_slug_remains_canonical(self) -> None:
        subject = dict(self.subject)
        subject["book_slug"] = "книга-тест"
        with self.patch_subject(subject):
            result = review.approve_current_identity(
                workspace_root=self.root,
                masters_root=self.masters,
                identities_root=self.identities,
                book_slug="книга-тест",
                job_id=self.job,
                listened_build_identity=subject["build_identity"],
                listened_audio_sha256=subject["audio_sha256"],
                listened_path_identity=subject["path_identity"],
            )
        self.assertEqual(result["subject"]["book_slug"], "книга-тест")
        self.assertIn("книга-тест", result["review_authority_path"])


if __name__ == "__main__":
    unittest.main()
