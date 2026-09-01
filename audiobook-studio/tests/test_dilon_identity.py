from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from audio_qa_review import path_identity, sha256_file
from backends.common import inspect_pcm_wav
from dilon_identity import (
    DILON_BRAND,
    DilonIdentityError,
    build_identity_preflight,
    prepare_current_identity,
)


OPENING_CREDIT = "Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices."


class DilonIdentityPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.master_dir = self.root / "masters" / "demo-book" / "chapter-ch001" / ("m" * 64)
        self.master_dir.mkdir(parents=True)
        self.master_audio = self.master_dir / "master.wav"
        self._write_wav(self.master_audio, frames=4_800)
        self.master_manifest = self.master_dir / "MANIFEST.json"
        self.master_manifest.write_text('{"status":"READY"}\n', encoding="utf-8")
        self.master = self._master_authority(
            identity="m" * 64,
            directory=self.master_dir,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_wav(path: Path, *, frames: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(b"\x00\x00" * frames)

    def _master_authority(self, *, identity: str, directory: Path) -> dict[str, object]:
        audio = directory / "master.wav"
        manifest = directory / "MANIFEST.json"
        return {
            "schema_version": 1,
            "master_identity": identity,
            "master_manifest_path": str(manifest),
            "master_manifest_sha256": sha256_file(manifest),
            "audio_path": str(audio),
            "audio_sha256": sha256_file(audio),
            "path_identity": path_identity(audio),
            "wav": inspect_pcm_wav(audio).to_dict(),
            "book_slug": "demo-book",
            "book_title": "Demo Book",
            "job_id": "chapter-ch001",
            "job_label": "Введение",
            "provider": "yandex",
            "profile_id": "yandex_lera",
            "assembly_identity": "a" * 64,
        }

    def _credit(self, *, approved: bool = True) -> dict[str, object]:
        audio = self.root / "credits" / "opening-credit.wav"
        self._write_wav(audio, frames=2_400)
        digest = sha256_file(audio)
        identity = path_identity(audio)
        fingerprint = "credit-fingerprint-v1"
        return {
            "text": OPENING_CREDIT,
            "audio_path": str(audio),
            "audio_sha256": digest,
            "path_identity": identity,
            "wav": inspect_pcm_wav(audio).to_dict(),
            "synthesis_fingerprint": fingerprint,
            "automatic_status": "PASS",
            "manual_state": "APPROVED" if approved else "UNREVIEWED",
            "reviewed_identity": {
                "audio_sha256": digest,
                "path_identity": identity,
                "synthesis_fingerprint": fingerprint,
            },
        }

    def _signature(self, *, rights_verified: bool) -> dict[str, object]:
        asset = self.root / "assets" / "signature.bin"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"signature-audio-asset")
        return {
            "asset_id": "lounge-vibes-05-7",
            "path": str(asset),
            "path_identity": path_identity(asset),
            "sha256": sha256_file(asset),
            "rights_provenance": {
                "verified": rights_verified,
                "commercial_audiobook_distribution": rights_verified,
                "source_provenance": "owner rights file",
                "right_to_use": "commercial audiobook distribution",
                "territory": "worldwide",
                "term": "perpetual",
            },
        }

    def test_missing_credit_is_blocked_without_provider_or_billing(self) -> None:
        result = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertEqual(result["blockers"], ["opening_credit_missing"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])

    def test_reviewed_credit_no_music_path_is_ready_and_deterministic(self) -> None:
        credit = self._credit()
        first = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
        )
        second = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=copy.deepcopy(credit),
        )
        self.assertEqual(first["state"], "READY")
        self.assertEqual(first["decision"], "READY_TO_BUILD")
        self.assertEqual(first["blockers"], [])
        self.assertIsNone(first["signature_asset"])
        self.assertEqual(first["brand"], DILON_BRAND)
        self.assertEqual(first["identity_plan_id"], second["identity_plan_id"])
        self.assertEqual(first["master"]["audio_sha256"], self.master["audio_sha256"])
        self.assertEqual(first["provider_requests"], 0)

    def test_unreviewed_credit_is_blocked(self) -> None:
        result = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=self._credit(approved=False),
        )
        self.assertIn("opening_credit_manual_approval_required", result["blockers"])
        self.assertEqual(result["provider_requests"], 0)

    def test_credit_tamper_is_blocked(self) -> None:
        credit = self._credit()
        Path(str(credit["audio_path"])).write_bytes(b"tampered")
        result = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("opening_credit_invalid_wav", result["blockers"])
        self.assertEqual(result["provider_requests"], 0)

    def test_unproven_signature_rights_are_blocked_but_optional_signature_is_not(self) -> None:
        credit = self._credit()
        blocked = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
            signature_asset=self._signature(rights_verified=False),
        )
        self.assertIn("signature_rights_unproven", blocked["blockers"])

        no_music = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
        )
        self.assertEqual(no_music["state"], "READY")
        self.assertIsNone(no_music["signature_asset"])

    def test_rights_proven_signature_is_bound_into_plan_identity(self) -> None:
        credit = self._credit()
        no_music = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
        )
        with_music = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
            signature_asset=self._signature(rights_verified=True),
        )
        self.assertEqual(with_music["state"], "READY")
        self.assertIsNotNone(with_music["signature_asset"])
        self.assertNotEqual(no_music["identity_plan_id"], with_music["identity_plan_id"])

    def test_signature_symlink_is_blocked_without_following_it(self) -> None:
        credit = self._credit()
        outside = self.root / "outside.bin"
        outside.write_bytes(b"outside")
        alias = self.root / "assets" / "alias.bin"
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.symlink_to(outside)
        signature = self._signature(rights_verified=True)
        signature.update({
            "path": str(alias),
            "path_identity": path_identity(alias),
            "sha256": sha256_file(outside),
        })
        result = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
            signature_asset=signature,
        )
        self.assertIn("symlink_input", result["blockers"])
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_master_change_changes_plan_identity(self) -> None:
        credit = self._credit()
        first = build_identity_preflight(
            self.master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
        )
        next_identity = "n" * 64
        next_dir = self.root / "masters" / "demo-book" / "chapter-ch001" / next_identity
        next_dir.mkdir(parents=True)
        shutil.copyfile(self.master_audio, next_dir / "master.wav")
        shutil.copyfile(self.master_manifest, next_dir / "MANIFEST.json")
        changed_master = self._master_authority(identity=next_identity, directory=next_dir)
        second = build_identity_preflight(
            changed_master,
            workspace_root=self.root,
            opening_credit_text=OPENING_CREDIT,
            opening_credit=credit,
        )
        self.assertNotEqual(first["identity_plan_id"], second["identity_plan_id"])

    def test_relocated_master_package_is_rejected(self) -> None:
        relocated = self.root / "relocated-master" / ("m" * 64)
        relocated.mkdir(parents=True)
        shutil.copyfile(self.master_audio, relocated / "master.wav")
        shutil.copyfile(self.master_manifest, relocated / "MANIFEST.json")
        forged = self._master_authority(identity="m" * 64, directory=relocated)
        with self.assertRaises(DilonIdentityError) as caught:
            build_identity_preflight(
                forged,
                workspace_root=self.root,
                opening_credit_text=OPENING_CREDIT,
                opening_credit=self._credit(),
            )
        self.assertEqual(caught.exception.code, "master_path_identity_mismatch")

    def test_invalid_master_bytes_fail_closed(self) -> None:
        Path(str(self.master["audio_path"])).write_bytes(b"not-a-wave")
        with self.assertRaises(DilonIdentityError) as caught:
            build_identity_preflight(
                self.master,
                workspace_root=self.root,
                opening_credit_text=OPENING_CREDIT,
                opening_credit=self._credit(),
            )
        self.assertEqual(caught.exception.code, "master_invalid_wav")

    def test_prepare_current_identity_only_resolves_master_and_stays_offline(self) -> None:
        credit = self._credit()
        with mock.patch("dilon_identity.resolve_current_master", return_value=self.master) as resolver:
            result = prepare_current_identity(
                workspace_root=self.root,
                masters_root=self.root / "masters",
                book_slug="demo-book",
                job_id="chapter-ch001",
                opening_credit_text=OPENING_CREDIT,
                opening_credit=credit,
                expected_master_identity="m" * 64,
            )
        resolver.assert_called_once_with(
            workspace_root=self.root,
            masters_root=self.root / "masters",
            book_slug="demo-book",
            job_id="chapter-ch001",
            expected_master_identity="m" * 64,
        )
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])


if __name__ == "__main__":
    unittest.main()
