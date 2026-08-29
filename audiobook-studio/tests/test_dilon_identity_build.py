from __future__ import annotations

import copy
import json
import tempfile
import unittest
import wave
from pathlib import Path

from audio_qa_review import path_identity, sha256_file
from backends.common import inspect_pcm_wav
from dilon_identity_build import (
    DilonIdentityBuildError,
    build_identity_output,
    prepare_identity_build,
    resolve_current_identity,
)


class DilonIdentityBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identities_root = self.root / "identities"
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.master_identity = "m" * 64
        self.master_dir = self.root / "masters" / self.book / self.job / self.master_identity
        self.master_dir.mkdir(parents=True)
        self.master = self.master_dir / "master.wav"
        self._write_wav(self.master, frames=4_800, sample=100)
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
        self.credit.parent.mkdir(parents=True)
        self._write_wav(self.credit, frames=2_400, sample=50)
        self.preflight = self._preflight()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_wav(path: Path, *, frames: int, sample: int = 0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = int(sample).to_bytes(2, "little", signed=True) * frames
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(payload)

    def _preflight(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "identity_plan_id": "p" * 64,
            "state": "READY",
            "decision": "READY_TO_BUILD",
            "blockers": [],
            "book_slug": self.book,
            "book_title": "Demo Book",
            "job_id": self.job,
            "master": {
                "master_identity": self.master_identity,
                "audio_sha256": sha256_file(self.master),
                "path_identity": path_identity(self.master),
                "master_manifest_sha256": sha256_file(self.master_manifest),
            },
            "opening_credit": {
                "text": "Demo credit",
                "audio_path": str(self.credit),
                "audio_sha256": sha256_file(self.credit),
                "path_identity": path_identity(self.credit),
                "wav": inspect_pcm_wav(self.credit).to_dict(),
                "synthesis_fingerprint": "credit-v1",
                "automatic_status": "PASS",
                "manual_state": "APPROVED",
                "reviewed_identity": {
                    "audio_sha256": sha256_file(self.credit),
                    "path_identity": path_identity(self.credit),
                    "synthesis_fingerprint": "credit-v1",
                },
            },
            "signature_asset": None,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }

    def test_blocked_preflight_cannot_build(self) -> None:
        blocked = copy.deepcopy(self.preflight)
        blocked["state"] = "BLOCKED"
        blocked["decision"] = "BLOCKED"
        blocked["blockers"] = ["opening_credit_missing"]
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(blocked, workspace_root=self.root, identities_root=self.identities_root)
        self.assertEqual(caught.exception.code, "preflight_not_ready")

    def test_signature_path_is_fail_closed_until_mixer_slice(self) -> None:
        with_signature = copy.deepcopy(self.preflight)
        with_signature["signature_asset"] = {"asset_id": "approved-signature"}
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(with_signature, workspace_root=self.root, identities_root=self.identities_root)
        self.assertEqual(caught.exception.code, "signature_render_not_implemented")

    def test_no_music_build_is_deterministic_and_preserves_sources(self) -> None:
        master_before = sha256_file(self.master)
        credit_before = sha256_file(self.credit)
        first = build_identity_output(
            self.preflight, workspace_root=self.root, identities_root=self.identities_root
        )
        second = build_identity_output(
            copy.deepcopy(self.preflight), workspace_root=self.root, identities_root=self.identities_root
        )
        self.assertEqual(first["build_identity"], second["build_identity"])
        self.assertEqual(first["output"]["sha256"], second["output"]["sha256"])
        self.assertEqual(sha256_file(self.master), master_before)
        self.assertEqual(sha256_file(self.credit), credit_before)
        self.assertEqual(first["provider_requests"], 0)
        self.assertFalse(first["remote_request_sent"])
        self.assertFalse(first["paid_execution"])
        self.assertFalse(first["billing_changed"])
        self.assertIsNone(first["signature_asset"])

        facts = inspect_pcm_wav(Path(first["output"]["path"])).to_dict()
        self.assertEqual(facts["sample_rate_hz"], 48_000)
        self.assertEqual(facts["channels"], 1)
        self.assertEqual(facts["sample_width_bytes"], 2)
        self.assertEqual(facts["frame_count"], 2_400 + 24_000 + 4_800)
        self.assertEqual(first["output"]["clipped_samples"], 0)
        self.assertEqual(
            [item["kind"] for item in first["components"]],
            ["opening_credit", "gap", "clean_master"],
        )

    def test_current_pointer_resolves_exact_immutable_output(self) -> None:
        built = build_identity_output(
            self.preflight, workspace_root=self.root, identities_root=self.identities_root
        )
        resolved = resolve_current_identity(
            workspace_root=self.root,
            identities_root=self.identities_root,
            book_slug=self.book,
            job_id=self.job,
            expected_build_identity=built["build_identity"],
        )
        self.assertEqual(resolved["build_identity"], built["build_identity"])
        self.assertEqual(resolved["output"]["sha256"], built["output"]["sha256"])

    def test_tampered_identity_output_fails_current_resolution(self) -> None:
        built = build_identity_output(
            self.preflight, workspace_root=self.root, identities_root=self.identities_root
        )
        Path(built["output"]["path"]).write_bytes(b"tampered")
        with self.assertRaises(DilonIdentityBuildError) as caught:
            resolve_current_identity(
                workspace_root=self.root,
                identities_root=self.identities_root,
                book_slug=self.book,
                job_id=self.job,
            )
        self.assertEqual(caught.exception.code, "identity_output_invalid")

    def test_changed_master_invalidates_preflight_before_build(self) -> None:
        self._write_wav(self.master, frames=4_800, sample=101)
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(self.preflight, workspace_root=self.root, identities_root=self.identities_root)
        self.assertEqual(caught.exception.code, "input_identity_mismatch")

    def test_master_current_change_invalidates_preflight_before_build(self) -> None:
        payload = json.loads(self.master_pointer.read_text(encoding="utf-8"))
        payload["master_identity"] = "n" * 64
        self.master_pointer.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(self.preflight, workspace_root=self.root, identities_root=self.identities_root)
        self.assertEqual(caught.exception.code, "stale_master_authority")

    def test_master_manifest_change_invalidates_preflight_before_build(self) -> None:
        self.master_manifest.write_text(json.dumps({"changed": True}), encoding="utf-8")
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(self.preflight, workspace_root=self.root, identities_root=self.identities_root)
        self.assertEqual(caught.exception.code, "stale_master_authority")

    def test_changed_preflight_plan_changes_build_identity(self) -> None:
        first = prepare_identity_build(self.preflight, workspace_root=self.root, identities_root=self.identities_root)
        changed = copy.deepcopy(self.preflight)
        changed["identity_plan_id"] = "q" * 64
        second = prepare_identity_build(changed, workspace_root=self.root, identities_root=self.identities_root)
        self.assertNotEqual(first["build_identity"], second["build_identity"])

    def test_symlinked_noncanonical_identity_root_is_rejected_without_following(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        alias = self.root / "identities-alias"
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(self.preflight, workspace_root=self.root, identities_root=alias)
        self.assertEqual(caught.exception.code, "noncanonical_identity_root")
        self.assertEqual(list(outside.iterdir()), [])

    def test_non_48k_opening_credit_fails_closed(self) -> None:
        with wave.open(str(self.credit), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(44_100)
            output.writeframes(b"\x00\x00" * 2_400)
        changed = copy.deepcopy(self.preflight)
        changed["opening_credit"]["audio_sha256"] = sha256_file(self.credit)
        changed["opening_credit"]["path_identity"] = path_identity(self.credit)
        with self.assertRaises(DilonIdentityBuildError) as caught:
            prepare_identity_build(changed, workspace_root=self.root, identities_root=self.identities_root)
        self.assertEqual(caught.exception.code, "unsupported_wav_format")

    def test_current_pointer_manifest_relocation_is_rejected(self) -> None:
        build_identity_output(
            self.preflight, workspace_root=self.root, identities_root=self.identities_root
        )
        pointer = self.identities_root / self.book / self.job / "CURRENT.json"
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(self.root / "elsewhere" / "MANIFEST.json")
        pointer.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(DilonIdentityBuildError) as caught:
            resolve_current_identity(
                workspace_root=self.root,
                identities_root=self.identities_root,
                book_slug=self.book,
                job_id=self.job,
            )
        self.assertEqual(caught.exception.code, "identity_pointer_mismatch")


if __name__ == "__main__":
    unittest.main()
