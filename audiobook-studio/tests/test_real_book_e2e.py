from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import real_book_e2e as e2e


class FakeAuthority:
    provider = "yandex"
    profile_id = "yandex_lera"
    book_slug = e2e.CANONICAL_BOOK
    job_id = e2e.CANONICAL_JOB
    segment_id = "seg-0001"
    synthesis_fingerprint = "fingerprint-v1"
    audio_path = "/tmp/accepted-yandex.wav"

    def to_dict(self):
        return {
            "provider": self.provider,
            "profile_id": self.profile_id,
            "book_slug": self.book_slug,
            "job_id": self.job_id,
            "segment_id": self.segment_id,
            "synthesis_fingerprint": self.synthesis_fingerprint,
            "audio_path": self.audio_path,
        }


class FakeBookLibrary:
    def resolve_book_profile(self, _name):
        return Path(f"/tmp/{e2e.CANONICAL_BOOK}.json")

    def load_book_for_execution(self, _name):
        return {
            "slug": e2e.CANONICAL_BOOK,
            "jobs": {
                e2e.CANONICAL_JOB: {
                    "kind": "chapter",
                    "label": "Введение",
                }
            },
        }


class FakePreparation:
    def status(self, _name):
        return {
            "preparation_status": "READY",
            "source_integrity": "OK",
        }


class StatusService:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def status(self, *args, **kwargs):
        self.calls += 1
        return self.value


class RealBookE2EPreflightTests(unittest.TestCase):
    def setUp(self):
        self.qa = {
            "identity": {
                "audio_sha256": e2e.ACCEPTED_PROVIDER_WAV_SHA256,
                "path_identity": "path-id",
                "synthesis_fingerprint": "fingerprint-v1",
            },
            "automatic_status": "PASS",
            "manual_state": "APPROVED",
            "downstream_eligible": True,
            "remote_request_sent": False,
        }
        self.assembly = {
            "decision": "ALREADY_ASSEMBLED",
            "assembly_identity": "assembly-1",
            "assembly": {"output": {"sha256": "assembly-sha"}},
            "provider_requests": 0,
            "remote_request_sent": False,
        }
        self.mastering = {
            "decision": "ALREADY_MASTERED",
            "master_identity": "master-1",
            "master": {"output": {"sha256": "master-sha"}},
            "provider_requests": 0,
            "remote_request_sent": False,
            "billing_changed": False,
        }
        self.export = {
            "decision": "ALREADY_EXPORTED",
            "chapter_export": {
                "candidate_identity": "export-1",
                "sha256": "mp3-sha",
            },
            "book_export": {
                "ready": False,
                "blockers": ["missing_chapters"],
            },
            "provider_requests": 0,
            "remote_request_sent": False,
            "billing_changed": False,
        }
        self.dilon = {
            "dilon_status": {
                "state": "CURRENT_TECHNICAL_QA_PASS",
                "decision": "HUMAN_LISTENING_REQUIRED",
                "technical_ready": True,
                "blockers": [],
                "provider_requests": 0,
                "remote_request_sent": False,
                "paid_execution": False,
                "billing_changed": False,
            },
            "identity_preview": {
                "build_identity": "dilon-build-1",
                "audio_sha256": "dilon-sha",
                "read_only": True,
            },
            "whole_book_release_ready": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        self.identity_review = {
            "state": "APPROVED",
            "decision": "IDENTITY_REVIEW_COMPLETE",
            "identity_accepted": True,
            "human_listening_required": False,
            "review_manifest_path": "/tmp/review.json",
            "whole_book_release_ready": False,
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }

    def run_preflight(self, *, export=None, dilon=None, review=None, accepted_sha=None):
        qa_service = StatusService(self.qa)
        assembly_service = StatusService(self.assembly)
        mastering_service = StatusService(self.mastering)
        export_service = StatusService(export or self.export)
        patches = [
            mock.patch.object(e2e, "BOOK_LIBRARY", FakeBookLibrary()),
            mock.patch.object(e2e, "BOOK_TEXT_PREPARATION", FakePreparation()),
            mock.patch.object(e2e, "_audio_qa_authority", return_value=FakeAuthority()),
            mock.patch.object(e2e, "_audio_qa_service", return_value=qa_service),
            mock.patch.object(e2e, "sha256_file", return_value=accepted_sha or e2e.ACCEPTED_PROVIDER_WAV_SHA256),
            mock.patch.object(e2e, "path_identity", return_value="path-id"),
            mock.patch.object(e2e, "assembly_input_from_qa", return_value={"input": "qa"}),
            mock.patch.object(e2e, "_chapter_assembly_service", return_value=assembly_service),
            mock.patch.object(e2e, "resolve_current_assembly", return_value={"assembly_identity": "assembly-1"}),
            mock.patch.object(e2e, "_mastering_service", return_value=mastering_service),
            mock.patch.object(e2e, "resolve_current_master", return_value={"master_identity": "master-1", "audio_sha256": "master-sha"}),
            mock.patch.object(e2e, "_litres_export_service", return_value=export_service),
            mock.patch.object(e2e, "current_native_snapshot", return_value=dilon or self.dilon),
            mock.patch.object(e2e, "identity_review_status", return_value=review or self.identity_review),
        ]
        for patcher in patches:
            patcher.start()
        try:
            result = e2e.real_book_e2e_preflight()
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return result, qa_service, assembly_service, mastering_service, export_service

    def test_all_exact_current_gates_are_ready_but_whole_book_remains_false(self):
        result, qa, assembly, mastering, export = self.run_preflight()
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["decision"], "READY_FOR_PRODUCTION_APP_ACCEPTANCE")
        self.assertTrue(all(item["status"] == "PASS" for item in result["gates"]))
        self.assertEqual(result["real_book_progress"], {"production_ready_sections": 1, "expected_sections": 16})
        self.assertFalse(result["whole_book_release_ready"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])
        self.assertEqual(qa.calls, 1)
        self.assertEqual(assembly.calls, 1)
        self.assertEqual(mastering.calls, 1)
        self.assertEqual(export.calls, 1)

    def test_changed_accepted_provider_wav_sha_blocks_before_downstream(self):
        result, _qa, assembly, mastering, export = self.run_preflight(accepted_sha="0" * 64)
        gate = next(item for item in result["gates"] if item["name"] == "accepted_yandex_qa_authority")
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertIn("accepted_yandex_or_manual_qa_not_current", result["blockers"])
        self.assertEqual(assembly.calls, 0)
        self.assertEqual(mastering.calls, 0)
        self.assertEqual(export.calls, 0)

    def test_whole_book_must_not_become_ready_at_one_of_sixteen(self):
        invalid = dict(self.export)
        invalid["book_export"] = {"ready": True, "blockers": []}
        result, *_ = self.run_preflight(export=invalid)
        gate = next(item for item in result["gates"] if item["name"] == "litres_chapter_export")
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertFalse(result["whole_book_release_ready"])

    def test_dilon_missing_is_the_remaining_external_gate_not_a_false_pass(self):
        pending = dict(self.dilon)
        pending["dilon_status"] = {
            "state": "BLOCKED",
            "decision": "BLOCKED",
            "technical_ready": False,
            "blockers": ["opening_credit_missing"],
            "provider_requests": 0,
            "remote_request_sent": False,
            "paid_execution": False,
            "billing_changed": False,
        }
        pending["identity_preview"] = None
        result, *_ = self.run_preflight(dilon=pending)
        technical = next(item for item in result["gates"] if item["name"] == "dilon_identity_technical")
        human = next(item for item in result["gates"] if item["name"] == "dilon_identity_human_acceptance")
        self.assertEqual(technical["status"], "BLOCKED")
        self.assertEqual(human["blocker"], "upstream_dilon_identity_blocked")
        self.assertEqual(result["state"], "BLOCKED")

    def test_final_identity_human_review_is_mandatory(self):
        pending = dict(self.identity_review)
        pending.update({
            "state": "PENDING_HUMAN_REVIEW",
            "decision": "HUMAN_LISTENING_REQUIRED",
            "identity_accepted": False,
            "human_listening_required": True,
        })
        result, *_ = self.run_preflight(review=pending)
        gate = next(item for item in result["gates"] if item["name"] == "dilon_identity_human_acceptance")
        self.assertEqual(gate["status"], "BLOCKED")
        self.assertEqual(gate["blocker"], "dilon_identity_human_listening_required")

    def test_preflight_source_contains_no_mutating_or_provider_actions(self):
        source = (Path(__file__).resolve().parents[1] / "real_book_e2e.py").read_text(encoding="utf-8")
        forbidden = (
            ".scan(",
            ".decide(",
            ".assemble(",
            ".master(",
            ".export(",
            "reconcile_release_authority",
            "execute_authorized",
            "run_text_job",
            "approve_current_identity",
            "approve_review_candidate",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
