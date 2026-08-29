from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dilon_native_snapshot as native


class DilonNativePreviewConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.identities = self.root / "identities"
        self.identities.mkdir()
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.identity = "a" * 64
        self.status = {
            "identity": {
                "build_identity": self.identity,
                "output_path": "/canonical/identity.wav",
                "output_sha256": "b" * 64,
                "current": True,
            }
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _bridge(self, *, audio_path: str = "/canonical/identity.wav", audio_sha256: str = "b" * 64):
        service = mock.Mock()
        service.identity_status.return_value = {
            "state": "READY",
            "decision": "READY_TO_PREVIEW",
            "identity": {
                "build_identity": self.identity,
                "book_slug": self.book,
                "job_id": self.job,
            },
            "preview": {
                "audio_path": audio_path,
                "audio_sha256": audio_sha256,
                "path_identity": "c" * 64,
                "read_only": True,
            },
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        return service

    def test_status_and_bridge_path_disagreement_fails_closed(self) -> None:
        service = self._bridge(audio_path="/other/identity.wav")
        with mock.patch.object(native, "DilonIdentityBridgeService", return_value=service):
            with self.assertRaises(native.DilonNativeSnapshotError) as caught:
                native._identity_preview(
                    workspace_root=self.root,
                    identities_root=self.identities,
                    status=self.status,
                    book_slug=self.book,
                    job_id=self.job,
                )
        self.assertEqual(caught.exception.code, "identity_preview_not_current")

    def test_status_and_bridge_sha_disagreement_fails_closed(self) -> None:
        service = self._bridge(audio_sha256="d" * 64)
        with mock.patch.object(native, "DilonIdentityBridgeService", return_value=service):
            with self.assertRaises(native.DilonNativeSnapshotError) as caught:
                native._identity_preview(
                    workspace_root=self.root,
                    identities_root=self.identities,
                    status=self.status,
                    book_slug=self.book,
                    job_id=self.job,
                )
        self.assertEqual(caught.exception.code, "identity_preview_not_current")


if __name__ == "__main__":
    unittest.main()
