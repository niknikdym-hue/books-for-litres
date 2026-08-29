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
from dilon_identity_qa import DilonIdentityQAError, EXPECTED_GAP_FRAMES, run_identity_technical_qa


class DilonIdentityQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identities = self.root / "identities"
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.master_identity = "m" * 64
        self.master_dir = self.root / "masters" / self.book / self.job / self.master_identity
        self.master_dir.mkdir(parents=True)
        self.master = self.master_dir / "master.wav"
        self._wav(self.master, 4_800, 100)
        self.master_manifest = self.master_dir / "MANIFEST.json"
        self.master_manifest.write_text(
            json.dumps({"schema_version": 1, "master_identity": self.master_identity}),
            encoding="utf-8",
        )
        self.master_pointer = self.master_dir.parent / "CURRENT.json"
        self.master_pointer.write_text(
            json.dumps({
                "schema_version": 1,
                "master_identity": self.master_identity,
                "manifest_path": str(self.master_manifest),
            }),
            encoding="utf-8",
        )
        self.credit = self.root / "credits" / "opening.wav"
        self.credit.parent.mkdir()
        self._wav(self.credit, 2_400, 50)
        self.credit_authority = self._credit_authority()
        self.master_authority = self._master_authority()
        self.preflight = build_identity_preflight(
            self.master_authority,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT_TEXT,
            opening_credit=self.credit_authority,
            signature_asset=None,
        )
        self.built = build_identity_output(
            self.preflight, workspace_root=self.root, identities_root=self.identities
        )

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

    def _credit_authority(self) -> dict[str, object]:
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

    def _master_authority(self) -> dict[str, object]:
        return {
            "master_identity": self.master_identity,
            "master_manifest_path": str(self.master_manifest),
            "master_manifest_sha256": sha256_file(self.master_manifest),
            "audio_path": str(self.master),
            "audio_sha256": sha256_file(self.master),
            "path_identity": path_identity(self.master),
            "wav": inspect_pcm_wav(self.master).to_dict(),
            "book_slug": self.book,
            "book_title": "Demo Book",
            "job_id": self.job,
            "job_label": "Demo chapter",
            "provider": "test-provider",
            "profile_id": "test-profile",
            "assembly_identity": "assembly-v1",
        }

    def _qa(self) -> dict[str, object]:
        return run_identity_technical_qa(
            workspace_root=self.root,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            opening_credit_authority=self.credit_authority,
            clean_master_authority=self.master_authority,
            expected_build_identity=self.built["build_identity"],
        )

    def test_exact_identity_passes_and_stays_offline(self) -> None:
        result = self._qa()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["gap_frames"], EXPECTED_GAP_FRAMES)
        self.assertEqual(result["gap_seconds"], "0.5")
        self.assertEqual(result["opening_credit_sha256"], sha256_file(self.credit))
        self.assertEqual(result["clean_master_sha256"], sha256_file(self.master))
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])

    def test_unapproved_credit_is_rejected(self) -> None:
        self.credit_authority["manual_state"] = "UNREVIEWED"
        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "opening_credit_not_approved")

    def test_stale_reviewed_fingerprint_is_rejected(self) -> None:
        self.credit_authority["reviewed_identity"]["synthesis_fingerprint"] = "stale-credit"
        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "opening_credit_review_stale")

    def test_wrong_credit_text_is_rejected(self) -> None:
        self.credit_authority["text"] = "Wrong opening credit"
        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "opening_credit_not_approved")

    def test_master_current_pointer_change_is_rejected(self) -> None:
        payload = json.loads(self.master_pointer.read_text(encoding="utf-8"))
        payload["master_identity"] = "n" * 64
        self.master_pointer.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "clean_master_not_current")

    def test_changed_clean_master_authority_is_rejected(self) -> None:
        self._wav(self.master, 4_800, 101)
        self.master_authority = self._master_authority()
        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "identity_component_identity_mismatch")

    def test_coordinated_gap_tamper_is_detected_independently(self) -> None:
        output_path = Path(self.built["output"]["path"])
        with wave.open(str(output_path), "rb") as source:
            params = source.getparams()
            frames = bytearray(source.readframes(source.getnframes()))
        credit_frames = int(inspect_pcm_wav(self.credit).frame_count)
        offset = (credit_frames + 10) * 2
        frames[offset:offset + 2] = (123).to_bytes(2, "little", signed=True)
        with wave.open(str(output_path), "wb") as target:
            target.setparams(params)
            target.writeframes(bytes(frames))

        manifest_path = output_path.parent / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["output"]["sha256"] = sha256_file(output_path)
        manifest["output"]["wav"] = inspect_pcm_wav(output_path).to_dict()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "identity_gap_not_silent")

    def test_output_tamper_without_manifest_coordination_fails_current_identity(self) -> None:
        Path(self.built["output"]["path"]).write_bytes(b"tampered")
        with self.assertRaises(DilonIdentityQAError) as caught:
            self._qa()
        self.assertEqual(caught.exception.code, "identity_not_current")


if __name__ == "__main__":
    unittest.main()
