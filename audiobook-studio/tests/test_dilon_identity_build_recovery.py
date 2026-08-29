from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from audio_qa_review import path_identity, sha256_file
from backends.common import inspect_pcm_wav
from dilon_identity import DILON_BRAND, DILON_DESCRIPTION, OPENING_CREDIT_TEXT
import dilon_identity_build as build


class DilonIdentityBuildRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identities = self.root / "identities"
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.master_identity = "m" * 64
        master_dir = self.root / "masters" / self.book / self.job / self.master_identity
        master_dir.mkdir(parents=True)
        self.master = master_dir / "master.wav"
        self._wav(self.master, 4_800, 100)
        manifest = master_dir / "MANIFEST.json"
        manifest.write_text(json.dumps({"master_identity": self.master_identity}), encoding="utf-8")
        (master_dir.parent / "CURRENT.json").write_text(
            json.dumps({
                "schema_version": 1,
                "master_identity": self.master_identity,
                "manifest_path": str(manifest),
            }),
            encoding="utf-8",
        )
        self.credit = self.root / "credits" / "opening.wav"
        self.credit.parent.mkdir()
        self._wav(self.credit, 2_400, 50)
        credit_sha = sha256_file(self.credit)
        credit_identity = path_identity(self.credit)
        self.preflight = {
            "schema_version": 1,
            "identity_plan_id": "p" * 64,
            "state": "READY",
            "decision": "READY_TO_BUILD",
            "blockers": [],
            "brand": DILON_BRAND,
            "description": DILON_DESCRIPTION,
            "opening_credit_text": OPENING_CREDIT_TEXT,
            "book_slug": self.book,
            "book_title": "Demo Book",
            "job_id": self.job,
            "master": {
                "master_identity": self.master_identity,
                "audio_sha256": sha256_file(self.master),
                "path_identity": path_identity(self.master),
                "master_manifest_sha256": sha256_file(manifest),
            },
            "opening_credit": {
                "text": OPENING_CREDIT_TEXT,
                "audio_path": str(self.credit),
                "audio_sha256": credit_sha,
                "path_identity": credit_identity,
                "wav": inspect_pcm_wav(self.credit).to_dict(),
                "synthesis_fingerprint": "credit-v1",
                "automatic_status": "PASS",
                "manual_state": "APPROVED",
                "reviewed_identity": {
                    "audio_sha256": credit_sha,
                    "path_identity": credit_identity,
                    "synthesis_fingerprint": "credit-v1",
                },
            },
            "signature_asset": None,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _wav(path: Path, frames: int, sample: int) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(int(sample).to_bytes(2, "little", signed=True) * frames)

    def test_crash_after_package_publish_recovers_without_rebuilding_bytes(self) -> None:
        plan = build.prepare_identity_build(
            self.preflight, workspace_root=self.root, identities_root=self.identities
        )
        real_atomic = build.atomic_write_json
        failed = {"done": False}

        def fail_first_current(path: Path, payload: dict[str, object]) -> None:
            if Path(path).name == "CURRENT.json" and not failed["done"]:
                failed["done"] = True
                raise OSError("simulated pointer publication failure")
            real_atomic(path, payload)

        with mock.patch.object(build, "atomic_write_json", side_effect=fail_first_current):
            with self.assertRaises(OSError):
                build.build_identity_output(
                    self.preflight, workspace_root=self.root, identities_root=self.identities
                )

        output = Path(plan["output_dir"]) / "identity.wav"
        manifest = Path(plan["output_dir"]) / "MANIFEST.json"
        self.assertTrue(output.is_file())
        self.assertTrue(manifest.is_file())
        published_sha = sha256_file(output)

        recovered = build.build_identity_output(
            self.preflight, workspace_root=self.root, identities_root=self.identities
        )
        self.assertEqual(recovered["output"]["sha256"], published_sha)
        self.assertEqual(sha256_file(output), published_sha)
        current = self.identities / self.book / self.job / "CURRENT.json"
        self.assertTrue(current.is_file())
        resolved = build.resolve_current_identity(
            workspace_root=self.root,
            identities_root=self.identities,
            book_slug=self.book,
            job_id=self.job,
            expected_build_identity=plan["build_identity"],
        )
        self.assertEqual(resolved["output"]["sha256"], published_sha)

    def test_noncanonical_identity_root_is_rejected(self) -> None:
        with self.assertRaises(build.DilonIdentityBuildError) as caught:
            build.prepare_identity_build(
                self.preflight,
                workspace_root=self.root,
                identities_root=self.root / "other-identities",
            )
        self.assertEqual(caught.exception.code, "noncanonical_identity_root")


if __name__ == "__main__":
    unittest.main()
