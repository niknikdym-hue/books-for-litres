from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dilon_identity_status import _load_opening_credit_authority, opening_credit_authority_path


class DilonIdentityStatusProvenanceTests(unittest.TestCase):
    def test_historical_paid_credit_facts_do_not_look_like_new_status_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = opening_credit_authority_path(
                workspace_root=root,
                book_slug="demo-book",
                job_id="chapter-ch001",
            )
            path.parent.mkdir(parents=True)
            record = {
                "text": "reviewed credit",
                "audio_path": str(root / "credit.wav"),
                "audio_sha256": "a" * 64,
                "path_identity": "b" * 64,
                "synthesis_fingerprint": "credit-v1",
                "automatic_status": "PASS",
                "manual_state": "APPROVED",
                "reviewed_identity": {
                    "audio_sha256": "a" * 64,
                    "path_identity": "b" * 64,
                    "synthesis_fingerprint": "credit-v1",
                },
            }
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "book_slug": "demo-book",
                    "job_id": "chapter-ch001",
                    "opening_credit": record,
                    "provider_requests": 1,
                    "remote_request_sent": True,
                    "paid_execution": True,
                    "billing_changed": True,
                }),
                encoding="utf-8",
            )
            loaded, loaded_path = _load_opening_credit_authority(
                workspace_root=root,
                book_slug="demo-book",
                job_id="chapter-ch001",
            )
            self.assertEqual(loaded, record)
            self.assertEqual(loaded_path, path)


if __name__ == "__main__":
    unittest.main()
