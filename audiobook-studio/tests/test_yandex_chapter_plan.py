from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from backends.yandex_speechkit import YandexSpeechKitError
from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from yandex_chapter_plan import YandexChapterPlanError, YandexChapterPlanService


@dataclass(frozen=True)
class FakePricing:
    currency: str = "RUB"
    unit: str = "billing_unit"
    unit_price: Decimal | None = Decimal("1.00")
    pricing_model: str = "per_segment"
    source_region: str = "ru-central1"
    verified_at: date | None = date(2026, 8, 23)
    source_url: str = "https://example.invalid/pricing"
    max_age_days: int = 30
    hard_limit_rub: Decimal | None = Decimal("100.00")
    demo_hard_limit_rub: Decimal | None = Decimal("5.00")


class FakeYandexBackend:
    def __init__(self, root: Path) -> None:
        self.config = SimpleNamespace(
            output_root=root / "renders",
            endpoint="https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis",
            keychain_service="AudiobookStudio-YandexSpeechKit",
            keychain_account="tester",
            max_chars=220,
            max_words=34,
            sentence_pause_ms=380,
            paragraph_pause_ms=700,
        )
        self.profile = SimpleNamespace(
            voice="lera", role="neutral", speed="1.04",
            output_container="WAV", loudness_normalization="LUFS",
        )
        self.cached_segments = 0
        self.allowed_to_start = True
        self.blocked_reason = None
        self.estimate_calls = 0
        self.provider_requests = 0
        self.extra_request = False
        self.request_error_category: str | None = None
        self.run_delay_seconds = 0.0
        self.assemble_values: list[bool] = []
        self._activity_lock = threading.Lock()
        self.active_runs = 0
        self.max_active_runs = 0

    def estimate(self, text: str, *, pricing, job_dir: Path, scope: str):
        self.estimate_calls += 1
        segments = 3
        remaining = segments - self.cached_segments
        return {
            "engine": "yandex",
            "characters": len(text),
            "segments": segments,
            "cached_segments": self.cached_segments,
            "billable_remaining_units": remaining,
            "estimated_remaining_cost": str(Decimal(remaining) * Decimal("1.00")),
            "hard_limit_rub": str(pricing.hard_limit_rub) if pricing.hard_limit_rub is not None else None,
            "allowed_to_start": self.allowed_to_start,
            "blocked_reason": self.blocked_reason,
        }

    def _request(self, text: str, request_id: str):
        if self.request_error_category:
            raise YandexSpeechKitError(
                "pre-network request failure",
                category=self.request_error_category,
                retryable=False,
                request_id=request_id,
            )
        self.provider_requests += 1
        return b"wav", {}

    def run_text_job(
        self,
        text: str,
        job_dir: Path,
        *,
        job_id: str,
        pricing,
        scope: str,
        assemble: bool = True,
    ) -> Path:
        self.assemble_values.append(assemble)
        with self._activity_lock:
            self.active_runs += 1
            self.max_active_runs = max(self.max_active_runs, self.active_runs)
        try:
            if self.run_delay_seconds:
                time.sleep(self.run_delay_seconds)
            remaining = 3 - self.cached_segments
            for index in range(remaining + (1 if self.extra_request else 0)):
                self._request(f"segment-{index}", f"request-{index}")
            job_dir.mkdir(parents=True, exist_ok=True)
            if not assemble:
                manifest = job_dir / "MANIFEST.json"
                manifest.write_text(json.dumps({"status": "SEGMENTS_DONE"}), encoding="utf-8")
                return manifest
            output = job_dir / "chapter.wav"
            output.write_bytes(b"fake")
            return output
        finally:
            with self._activity_lock:
                self.active_runs -= 1


class YandexChapterPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.books.mkdir()
        source = self.root / "source.txt"
        source.write_text(
            "Глава 1. Начало\n\nПервое предложение. Второе предложение.\n\n"
            "Глава 2. Продолжение\n\nТретье предложение. Четвёртое предложение.\n",
            encoding="utf-8",
        )
        self.library = BookLibrary(self.books)
        self.library.import_text_book(source_file=source, title="Книга", author="Автор", slug="book")
        self.preparation = BookTextPreparationService(
            self.library,
            now=lambda: "2026-08-23T12:00:00+00:00",
        )
        self.preparation.prepare("book")
        self.backend = FakeYandexBackend(self.root)
        self.now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
        self.service = YandexChapterPlanService(
            library=self.library,
            backend=self.backend,
            pricing=FakePricing(),
            plans_dir=self.root / "plans",
            now=lambda: self.now,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_is_network_free_and_cache_aware(self) -> None:
        self.backend.cached_segments = 1
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.assertEqual(plan["decision"], "READY_FOR_CONFIRMATION")
        self.assertEqual(plan["provider_segments"], 3)
        self.assertEqual(plan["cached_segments"], 1)
        self.assertEqual(plan["max_network_requests"], 2)
        self.assertEqual(plan["confirmation_scope"], "chapter")
        self.assertFalse(plan["remote_request_sent"])
        self.assertEqual(self.backend.provider_requests, 0)

    def test_cache_only_plan_requires_zero_new_requests(self) -> None:
        self.backend.cached_segments = 3
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.assertEqual(plan["decision"], "CACHE_ONLY")
        self.assertEqual(plan["max_network_requests"], 0)
        self.assertEqual(plan["blockers"], [])

    def test_pricing_gate_still_blocks_cache_only_until_backend_has_local_materializer(self) -> None:
        self.backend.cached_segments = 3
        self.backend.allowed_to_start = False
        self.backend.blocked_reason = "stale_tariff"
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.assertEqual(plan["decision"], "BLOCKED")
        self.assertIn("stale_tariff", plan["blockers"])

    def test_pricing_gate_blocks_plan_with_remaining_requests(self) -> None:
        self.backend.allowed_to_start = False
        self.backend.blocked_reason = "hard_limit_exceeded"
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.assertEqual(plan["state"], "BLOCKED")
        self.assertEqual(plan["decision"], "BLOCKED")
        self.assertIn("hard_limit_exceeded", plan["blockers"])
        self.assertEqual(self.backend.provider_requests, 0)

    def test_profile_mismatch_fails_closed(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_anton")
        self.assertEqual(plan["state"], "BLOCKED")
        self.assertIn("profile_mismatch", plan["blockers"])

    def test_revalidate_preserves_exact_plan_identity_without_network(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        result = self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["chapter_production_identity"], plan["chapter_production_identity"])
        self.assertEqual(result["max_network_requests"], plan["max_network_requests"])
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(self.backend.provider_requests, 0)

    def test_reprepare_invalidates_existing_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        working = self.books / "book/tts/working.txt"
        working.write_text(
            working.read_text(encoding="utf-8").replace("Первое предложение.", "Новое первое предложение."),
            encoding="utf-8",
        )
        self.preparation.prepare("book")
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.backend.provider_requests, 0)

    def test_cache_change_invalidates_existing_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.backend.cached_segments = 1
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_digest_mismatch_is_rejected_before_reanalysis(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        calls_before = self.backend.estimate_calls
        with self.assertRaisesRegex(YandexChapterPlanError, "digest"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest="0" * 64)
        self.assertEqual(self.backend.estimate_calls, calls_before)

    def test_execute_consumes_plan_and_obeys_frozen_request_cap_without_assembly(self) -> None:
        self.backend.cached_segments = 1
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        result = self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 2)
        self.assertEqual(result["max_network_requests"], 2)
        self.assertTrue(result["remote_request_sent"])
        self.assertFalse(result["chapter_assembly_performed"])
        self.assertEqual(result["next_gate"], "AUTOMATIC_QA")
        self.assertEqual(Path(result["segment_manifest"]).name, "MANIFEST.json")
        self.assertEqual(self.backend.assemble_values, [False])
        self.assertFalse((Path(plan["job_dir"]) / "chapter.wav").exists())
        stored = self.service.store.load(plan["plan_id"])
        self.assertEqual(stored["state"], "CONSUMED")
        self.assertEqual(stored["network_requests"], 2)
        with self.assertRaisesRegex(YandexChapterPlanError, "consumed"):
            self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.backend.provider_requests, 2)

    def test_cache_only_execute_uses_zero_provider_requests_and_no_assembly(self) -> None:
        self.backend.cached_segments = 3
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        result = self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["request_slots"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["chapter_assembly_performed"])
        self.assertEqual(self.backend.assemble_values, [False])
        self.assertEqual(self.backend.provider_requests, 0)

    def test_pre_network_credential_failures_do_not_report_remote_requests(self) -> None:
        self.backend.cached_segments = 2
        for category in ("credentials", "credentials_duplicate", "platform"):
            with self.subTest(category=category):
                self.backend.request_error_category = category
                plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
                with self.assertRaises(YandexSpeechKitError):
                    self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
                stored = self.service.store.load(plan["plan_id"])
                self.assertEqual(stored["state"], "CONSUMED")
                self.assertEqual(stored["request_slots"], 1)
                self.assertEqual(stored["network_requests"], 0)
                self.assertFalse(stored["remote_request_sent"])
                self.assertEqual(self.backend.provider_requests, 0)
        self.backend.request_error_category = None

    def test_request_cap_blocks_extra_request_before_provider(self) -> None:
        self.backend.cached_segments = 1
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.backend.extra_request = True
        with self.assertRaisesRegex(YandexChapterPlanError, "cap"):
            self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.backend.provider_requests, 2)
        stored = self.service.store.load(plan["plan_id"])
        self.assertEqual(stored["state"], "CONSUMED")
        self.assertEqual(stored["network_requests"], 2)

    def test_concurrent_plans_serialize_backend_hook_execution(self) -> None:
        self.backend.cached_segments = 2
        self.backend.run_delay_seconds = 0.05
        first = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        second = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def execute(plan: dict[str, object]) -> None:
            try:
                results.append(self.service.execute(
                    plan_id=str(plan["plan_id"]),
                    plan_digest=str(plan["plan_digest"]),
                ))
            except BaseException as error:  # capture thread failures for the main assertion
                errors.append(error)

        threads = [
            threading.Thread(target=execute, args=(first,)),
            threading.Thread(target=execute, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(self.backend.max_active_runs, 1)
        self.assertEqual(self.backend.provider_requests, 2)
        self.assertEqual(self.backend.assemble_values, [False, False])
        self.assertTrue(all(result["network_requests"] == 1 for result in results))
        self.assertTrue(all(result["chapter_assembly_performed"] is False for result in results))

    def test_expiry_tamper_breaks_plan_integrity(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        stored = self.service.store.load(plan["plan_id"])
        stored["expires_at"] = "2026-08-24T12:00:00+00:00"
        self.service.store.save(stored)
        with self.assertRaisesRegex(YandexChapterPlanError, "immutable fields"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_output_container_change_invalidates_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.backend.profile.output_container = "OGG_OPUS"
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_loudness_change_invalidates_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.backend.profile.loudness_normalization = "PEAK"
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_segmentation_policy_change_invalidates_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.backend.config.max_chars = 221
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_pricing_age_policy_change_invalidates_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.service.pricing = replace(self.service.pricing, max_age_days=31)
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_pricing_provenance_change_invalidates_plan(self) -> None:
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        self.service.pricing = replace(self.service.pricing, source_region="other-region")
        with self.assertRaisesRegex(YandexChapterPlanError, "changed"):
            self.service.revalidate(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])


if __name__ == "__main__":
    unittest.main()
