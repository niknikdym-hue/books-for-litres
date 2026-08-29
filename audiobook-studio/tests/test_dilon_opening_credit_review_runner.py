from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dilon_opening_credit_review import EXPECTED_PROFILE, prepare_review_candidate
import dilon_opening_credit_review_runner as runner


class DilonOpeningCreditReviewRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.book = "demo-book"
        self.job = "chapter-ch001"
        self.source = self.root / "runtime" / "provider-output" / "opening.wav"
        self._wav(self.source)
        self.prepared = prepare_review_candidate(
            workspace_root=self.root,
            book_slug=self.book,
            job_id=self.job,
            source_wav=self.source,
            plan_id="a" * 64,
            plan_digest="b" * 64,
            synthesis_fingerprint="c" * 64,
            profile=EXPECTED_PROFILE,
            provider_requests=1,
            remote_request_sent=True,
            paid_execution=True,
            billing_changed=True,
        )

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

    def _main(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with mock.patch.object(
            runner,
            "load_workspace_paths",
            return_value=SimpleNamespace(root=self.root),
        ), contextlib.redirect_stdout(output):
            code = runner.main(argv)
        return code, json.loads(output.getvalue())

    def _base_args(self) -> list[str]:
        return [
            "--book", self.book,
            "--job", self.job,
            "--candidate-id", str(self.prepared["candidate_id"]),
            "--candidate-digest", str(self.prepared["candidate_digest"]),
        ]

    def test_parser_exposes_only_status_and_approval_review_modes(self) -> None:
        parser = runner.build_parser()
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertIn("--candidate-status", option_strings)
        self.assertIn("--approve-candidate", option_strings)
        self.assertNotIn("--execute", option_strings)
        self.assertNotIn("--synthesize", option_strings)
        self.assertNotIn("--provider", option_strings)
        self.assertNotIn("--paid", option_strings)

    def test_candidate_status_is_exact_machine_readable_and_offline(self) -> None:
        code, payload = self._main(["--candidate-status", *self._base_args()])
        self.assertEqual(code, 0)
        self.assertEqual(payload["state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(payload["decision"], "HUMAN_LISTENING_REQUIRED")
        self.assertEqual(payload["candidate_id"], self.prepared["candidate_id"])
        self.assertEqual(payload["candidate_digest"], self.prepared["candidate_digest"])
        self.assertEqual(payload["audio_sha256"], self.prepared["audio_sha256"])
        self.assertEqual(payload["path_identity"], self.prepared["path_identity"])
        self.assertEqual(
            payload["synthesis_fingerprint"], self.prepared["synthesis_fingerprint"]
        )
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])
        self.assertEqual(payload["historical_provenance"]["provider_requests"], 1)
        self.assertTrue(payload["historical_provenance"]["paid_execution"])

    def test_approval_requires_exact_listened_identity_and_publishes_authority(self) -> None:
        args = [
            "--approve-candidate", *self._base_args(),
            "--decision", "APPROVE",
            "--listened-audio-sha256", str(self.prepared["audio_sha256"]),
            "--listened-path-identity", str(self.prepared["path_identity"]),
            "--listened-synthesis-fingerprint", str(self.prepared["synthesis_fingerprint"]),
        ]
        code, payload = self._main(args)
        self.assertEqual(code, 0)
        self.assertEqual(payload["state"], "APPROVED")
        self.assertEqual(payload["decision"], "REVIEW_COMPLETE")
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])
        self.assertTrue(Path(payload["authority_path"]).is_file())

    def test_wrong_listened_identity_fails_closed_without_current_publication(self) -> None:
        args = [
            "--approve-candidate", *self._base_args(),
            "--decision", "APPROVE",
            "--listened-audio-sha256", "d" * 64,
            "--listened-path-identity", str(self.prepared["path_identity"]),
            "--listened-synthesis-fingerprint", str(self.prepared["synthesis_fingerprint"]),
        ]
        code, payload = self._main(args)
        self.assertEqual(code, 2)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertEqual(payload["blockers"], ["listened_identity_mismatch"])
        self.assertEqual(payload["provider_requests"], 0)
        current = (
            self.root
            / "runtime"
            / "dilon-opening-credit"
            / self.book
            / self.job
            / "CURRENT.json"
        )
        self.assertFalse(current.exists())

    def test_missing_explicit_approval_inputs_are_structured_and_offline(self) -> None:
        code, payload = self._main(["--approve-candidate", *self._base_args()])
        self.assertEqual(code, 2)
        self.assertEqual(payload["blockers"], ["invalid_request"])
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])
        self.assertFalse(payload["paid_execution"])
        self.assertFalse(payload["billing_changed"])

    def test_tampered_candidate_status_fails_closed(self) -> None:
        Path(self.prepared["audio_path"]).write_bytes(b"tampered")
        code, payload = self._main(["--candidate-status", *self._base_args()])
        self.assertEqual(code, 2)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertIn(payload["blockers"][0], {"invalid_wav", "candidate_integrity_mismatch"})
        self.assertEqual(payload["provider_requests"], 0)

    def test_unicode_book_slug_remains_canonical_and_offline(self) -> None:
        unicode_book = "книга-тест"
        source = self.root / "runtime" / "provider-output" / "unicode-opening.wav"
        self._wav(source)
        prepared = prepare_review_candidate(
            workspace_root=self.root,
            book_slug=unicode_book,
            job_id=self.job,
            source_wav=source,
            plan_id="d" * 64,
            plan_digest="e" * 64,
            synthesis_fingerprint="f" * 64,
            profile=EXPECTED_PROFILE,
            provider_requests=0,
            remote_request_sent=False,
            paid_execution=False,
            billing_changed=False,
        )
        payload = runner.candidate_status(
            workspace_root=self.root,
            book_slug=unicode_book,
            job_id=self.job,
            candidate_id=str(prepared["candidate_id"]),
            candidate_digest=str(prepared["candidate_digest"]),
        )
        self.assertEqual(payload["book_slug"], unicode_book)
        self.assertEqual(payload["provider_requests"], 0)
        self.assertFalse(payload["remote_request_sent"])


if __name__ == "__main__":
    unittest.main()
