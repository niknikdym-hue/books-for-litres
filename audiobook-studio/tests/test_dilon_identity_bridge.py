from __future__ import annotations

from datetime import date
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audio_qa_review import sha256_file
from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_speechkit import YandexSpeechKitBackend
import dilon_identity_bridge as bridge_module
from dilon_identity_bridge import DilonIdentityBridgeError, DilonIdentityBridgeService
from dilon_identity_build import DilonIdentityBuildError


def pricing() -> YandexPricingConfig:
    return YandexPricingConfig.from_mapping(
        {
            "engine": "yandex_speechkit_v3",
            "currency": "RUB",
            "unit": "billing_unit",
            "unit_price": "0.21146666",
            "pricing_model": "per_250_chars_or_request_unit",
            "source_region": "published_ruble_rate",
            "verified_at": "2026-08-20",
            "source_url": "https://yandex.cloud/ru-kz/docs/speechkit/pricing",
            "max_age_days": 30,
            "hard_limit_rub": "10.00",
            "demo_hard_limit_rub": "1.00",
        }
    )


class DilonIdentityBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identities = self.root / "identities"
        self.plans = self.root / "runtime" / "paid-run-plans"
        self.service = DilonIdentityBridgeService(
            workspace_root=self.root,
            identities_root=self.identities,
            paid_plans_root=self.plans,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _output(self, name: str = "identity.wav") -> Path:
        output = self.identities / "demo-book" / "chapter-ch001" / ("a" * 64) / name
        output.parent.mkdir(parents=True, exist_ok=True)
        return output

    def test_bridge_requires_canonical_identity_and_plan_roots(self) -> None:
        with self.assertRaises(DilonIdentityBridgeError) as identity_error:
            DilonIdentityBridgeService(
                workspace_root=self.root,
                identities_root=self.root / "other-identities",
                paid_plans_root=self.plans,
            )
        self.assertEqual(identity_error.exception.code, "noncanonical_identity_root")

        with self.assertRaises(DilonIdentityBridgeError) as plans_error:
            DilonIdentityBridgeService(
                workspace_root=self.root,
                identities_root=self.identities,
                paid_plans_root=self.root / "other-plans",
            )
        self.assertEqual(plans_error.exception.code, "noncanonical_plan_root")

    def test_prepare_persists_owner_ready_plan_without_network(self) -> None:
        with mock.patch.object(
            YandexSpeechKitBackend,
            "_request",
            side_effect=AssertionError("network attempted"),
        ) as request:
            result = self.service.prepare_opening_credit(
                pricing=pricing(), today=date(2026, 8, 29)
            )
        request.assert_not_called()
        plan = result["opening_credit_plan"]
        self.assertTrue(plan["stored"])
        self.assertTrue(Path(plan["plan_path"]).is_file())
        self.assertEqual(plan["maximum_provider_requests"], 1)
        self.assertEqual(plan["pricing"]["estimated_remaining_cost"], "0.21146666")
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])

    def test_plan_status_requires_exact_digest(self) -> None:
        prepared = self.service.prepare_opening_credit(
            pricing=pricing(), today=date(2026, 8, 29)
        )["opening_credit_plan"]
        status = self.service.opening_credit_plan_status(
            plan_id=prepared["plan_id"], plan_digest=prepared["plan_digest"]
        )
        self.assertEqual(status["opening_credit_plan"]["plan_id"], prepared["plan_id"])
        self.assertFalse(status["opening_credit_plan"]["execution_available"])

    def test_missing_or_stale_identity_returns_safe_blocker(self) -> None:
        with mock.patch.object(
            bridge_module,
            "resolve_current_identity",
            side_effect=DilonIdentityBuildError("identity_pointer_mismatch", "stale"),
        ):
            result = self.service.identity_status(
                book_slug="demo-book", job_id="chapter-ch001"
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["decision"], "IDENTITY_NOT_CURRENT")
        self.assertEqual(result["blockers"], ["identity_pointer_mismatch"])
        self.assertIsNone(result["preview"])
        self.assertEqual(result["provider_requests"], 0)

    def test_exact_current_identity_returns_read_only_preview(self) -> None:
        output = self._output()
        output.write_bytes(b"offline-audio-fixture")
        digest = sha256_file(output)
        manifest = {
            "build_identity": "a" * 64,
            "preflight_plan_id": "b" * 64,
            "book_slug": "demo-book",
            "job_id": "chapter-ch001",
            "output": {"path": str(output), "sha256": digest},
        }
        with mock.patch.object(
            bridge_module, "resolve_current_identity", return_value=manifest
        ):
            result = self.service.identity_status(
                book_slug="demo-book",
                job_id="chapter-ch001",
                expected_build_identity="a" * 64,
            )
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["decision"], "READY_TO_PREVIEW")
        self.assertEqual(result["identity"]["build_identity"], "a" * 64)
        self.assertEqual(result["preview"]["audio_sha256"], digest)
        self.assertTrue(result["preview"]["read_only"])
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])

    def test_preview_rechecks_output_sha_after_resolver(self) -> None:
        output = self._output()
        output.write_bytes(b"current")
        old_digest = sha256_file(output)
        manifest = {
            "build_identity": "a" * 64,
            "preflight_plan_id": "b" * 64,
            "book_slug": "demo-book",
            "job_id": "chapter-ch001",
            "output": {"path": str(output), "sha256": old_digest},
        }
        output.write_bytes(b"changed")
        with mock.patch.object(
            bridge_module, "resolve_current_identity", return_value=manifest
        ):
            result = self.service.identity_status(
                book_slug="demo-book", job_id="chapter-ch001"
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["blockers"], ["identity_output_sha_mismatch"])
        self.assertIsNone(result["preview"])

    def test_preview_symlink_swap_fails_closed_without_following(self) -> None:
        output = self._output()
        outside = self.root / "outside-audio.wav"
        outside.write_bytes(b"outside")
        output.symlink_to(outside)
        digest = sha256_file(outside)
        manifest = {
            "build_identity": "a" * 64,
            "preflight_plan_id": "b" * 64,
            "book_slug": "demo-book",
            "job_id": "chapter-ch001",
            "output": {"path": str(output), "sha256": digest},
        }
        with mock.patch.object(
            bridge_module, "resolve_current_identity", return_value=manifest
        ):
            result = self.service.identity_status(
                book_slug="demo-book", job_id="chapter-ch001"
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["blockers"], ["identity_preview_path_invalid"])
        self.assertIsNone(result["preview"])
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_service_exposes_no_execute_or_synthesize_action(self) -> None:
        self.assertFalse(hasattr(self.service, "execute"))
        self.assertFalse(hasattr(self.service, "synthesize"))
        self.assertFalse(hasattr(self.service, "execute_opening_credit"))


if __name__ == "__main__":
    unittest.main()
