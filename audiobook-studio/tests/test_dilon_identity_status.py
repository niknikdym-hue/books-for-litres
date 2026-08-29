from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

from audio_qa_review import path_identity, sha256_file
from backends.common import inspect_pcm_wav
from dilon_identity import OPENING_CREDIT_TEXT, build_identity_preflight
from dilon_identity_build import build_identity_output
from dilon_identity_status import current_dilon_identity_status, opening_credit_authority_path


class DilonIdentityStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identities = self.root / "identities"
        self.masters = self.root / "masters"
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.master_identity = "m" * 64
        self.master_authority = self._make_master_authority(self.book)
        self.credit = self.root / "credits" / "opening.wav"
        self.credit.parent.mkdir()
        self._wav(self.credit, 2_400, 50)
        self.credit_record = self._credit_record()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _wav(path: Path, frames: int, sample: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(int(sample).to_bytes(2, "little", signed=True) * frames)

    def _make_master_authority(self, book_slug: str) -> dict[str, object]:
        master_dir = self.masters / book_slug / self.job / self.master_identity
        master_dir.mkdir(parents=True)
        master = master_dir / "master.wav"
        self._wav(master, 4_800, 100)
        manifest = master_dir / "MANIFEST.json"
        manifest.write_text(
            json.dumps({"schema_version": 1, "master_identity": self.master_identity}),
            encoding="utf-8",
        )
        (master_dir.parent / "CURRENT.json").write_text(
            json.dumps({
                "schema_version": 1,
                "master_identity": self.master_identity,
                "manifest_path": str(manifest),
            }),
            encoding="utf-8",
        )
        return {
            "master_identity": self.master_identity,
            "master_manifest_path": str(manifest),
            "master_manifest_sha256": sha256_file(manifest),
            "audio_path": str(master),
            "audio_sha256": sha256_file(master),
            "path_identity": path_identity(master),
            "wav": inspect_pcm_wav(master).to_dict(),
            "book_slug": book_slug,
            "book_title": "Demo Book",
            "job_id": self.job,
            "job_label": "Chapter 1",
            "provider": "yandex",
            "profile_id": "yandex_lera",
            "assembly_identity": "a" * 64,
        }

    def _credit_record(self) -> dict[str, object]:
        digest = sha256_file(self.credit)
        identity = path_identity(self.credit)
        return {
            "text": OPENING_CREDIT_TEXT,
            "audio_path": str(self.credit),
            "audio_sha256": digest,
            "path_identity": identity,
            "wav": inspect_pcm_wav(self.credit).to_dict(),
            "synthesis_fingerprint": "credit-v1",
            "automatic_status": "PASS",
            "manual_state": "APPROVED",
            "reviewed_identity": {
                "audio_sha256": digest,
                "path_identity": identity,
                "synthesis_fingerprint": "credit-v1",
            },
        }

    def _resolver(self, **_: object) -> dict[str, object]:
        return dict(self.master_authority)

    def _publish_credit_authority(self, *, book: str | None = None) -> Path:
        slug = book or self.book
        path = opening_credit_authority_path(
            workspace_root=self.root, book_slug=slug, job_id=self.job
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({
                "schema_version": 1,
                "book_slug": slug,
                "job_id": self.job,
                "opening_credit": self.credit_record,
                "provider_requests": 0,
                "remote_request_sent": False,
                "paid_execution": False,
                "billing_changed": False,
            }),
            encoding="utf-8",
        )
        return path

    def test_missing_opening_credit_is_explicit_offline_blocker(self) -> None:
        status = current_dilon_identity_status(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            opening_credit_prepare={"decision": "OWNER_AUTHORIZATION_REQUIRED"},
            master_resolver=self._resolver,
        )
        self.assertEqual(status["state"], "BLOCKED")
        self.assertIn("opening_credit_missing", status["blockers"])
        self.assertEqual(status["opening_credit_prepare"]["decision"], "OWNER_AUTHORIZATION_REQUIRED")
        self.assertFalse(status["technical_ready"])
        self.assertFalse(status["whole_book_release_ready"])
        self.assertEqual(status["provider_requests"], 0)
        self.assertFalse(status["remote_request_sent"])
        self.assertFalse(status["paid_execution"])
        self.assertFalse(status["billing_changed"])

    def test_approved_credit_without_identity_is_ready_to_build_offline(self) -> None:
        self._publish_credit_authority()
        status = current_dilon_identity_status(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            master_resolver=self._resolver,
        )
        self.assertEqual(status["state"], "READY_TO_BUILD")
        self.assertEqual(status["decision"], "READY_TO_BUILD_OFFLINE")
        self.assertEqual(status["blockers"], ["identity_output_missing"])
        self.assertFalse(status["identity"]["current"])
        self.assertEqual(status["provider_requests"], 0)

    def test_current_identity_runs_independent_technical_qa_and_requires_human_listening(self) -> None:
        self._publish_credit_authority()
        preflight = build_identity_preflight(
            self.master_authority,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT_TEXT,
            opening_credit=self.credit_record,
            signature_asset=None,
        )
        built = build_identity_output(
            preflight,
            workspace_root=self.root,
            identities_root=self.identities,
        )
        status = current_dilon_identity_status(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            master_resolver=self._resolver,
        )
        self.assertEqual(status["state"], "CURRENT_TECHNICAL_QA_PASS")
        self.assertEqual(status["decision"], "HUMAN_LISTENING_REQUIRED")
        self.assertTrue(status["identity"]["current"])
        self.assertEqual(status["identity"]["build_identity"], built["build_identity"])
        self.assertEqual(status["technical_qa"]["status"], "PASS")
        self.assertTrue(status["technical_ready"])
        self.assertTrue(status["human_listening_required"])
        self.assertFalse(status["whole_book_release_ready"])

    def test_symlinked_opening_credit_authority_fails_closed_without_following(self) -> None:
        expected = opening_credit_authority_path(
            workspace_root=self.root, book_slug=self.book, job_id=self.job
        )
        expected.parent.mkdir(parents=True)
        outside = self.root / "outside-credit-authority.json"
        outside.write_text("{}", encoding="utf-8")
        expected.symlink_to(outside)
        status = current_dilon_identity_status(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            master_resolver=self._resolver,
        )
        self.assertEqual(status["state"], "BLOCKED")
        self.assertEqual(status["blockers"], ["symlink_input"])
        self.assertEqual(outside.read_text(encoding="utf-8"), "{}")

    def test_unicode_canonical_book_slug_is_accepted_by_status_bridge(self) -> None:
        unicode_book = "книга-тест"
        unicode_master = self._make_master_authority(unicode_book)

        def resolver(**_: object) -> dict[str, object]:
            return dict(unicode_master)

        status = current_dilon_identity_status(
            workspace_root=self.root,
            masters_root=self.masters,
            identities_root=self.identities,
            book_slug=unicode_book,
            job_id=self.job,
            master_resolver=resolver,
        )
        self.assertEqual(status["book_slug"], unicode_book)
        self.assertEqual(status["state"], "BLOCKED")
        self.assertIn("opening_credit_missing", status["blockers"])
        self.assertIn(unicode_book, status["opening_credit_authority_path"])


if __name__ == "__main__":
    unittest.main()
