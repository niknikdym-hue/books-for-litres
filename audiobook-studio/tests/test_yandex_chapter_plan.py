from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from yandex_chapter_plan import YandexChapterPlanError, YandexChapterPlanService


@dataclass(frozen=True)
class FakePricing:
    currency: str = "RUB"
    unit: str = "billing_unit"
    unit_price: Decimal | None = Decimal("1.00")
    pricing_model: str = "per_segment"
    verified_at: date | None = date(2026, 8, 23)
    source_url: str = "https://example.invalid/pricing"
    hard_limit_rub: Decimal | None = Decimal("100.00")


class FakeYandexBackend:
    def __init__(self, root: Path) -> None:
        self.config = SimpleNamespace(output_root=root / "renders")
        self.profile = SimpleNamespace(voice="lera", role="neutral", speed="1.04")
        self.cached_segments = 0
        self.allowed_to_start = True
        self.blocked_reason = None
        self.estimate_calls = 0
        self.provider_requests = 0
        self.extra_request = False

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
        self.provider_requests += 1
        return b"wav", {}

    def run_text_job(self, text: str, job_dir: Path, *, job_id: str, pricing, scope: str) -> Path:
        remaining = 3 - self.cached_segments
        for index in range(remaining + (1 if self.extra_request else 0)):
            self._request(f"segment-{index}", f"request-{index}")
        job_dir.mkdir(parents=True, exist_ok=True)
        output = job_dir / "chapter.wav"
        output.write_bytes(b"fake")
        return output


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

    def test_execute_consumes_plan_and_obeys_frozen_request_cap(self) -> None:
        self.backend.cached_segments = 1
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        result = self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 2)
        self.assertEqual(result["max_network_requests"], 2)
        self.assertTrue(result["remote_request_sent"])
        stored = self.service.store.load(plan["plan_id"])
        self.assertEqual(stored["state"], "CONSUMED")
        self.assertEqual(stored["network_requests"], 2)
        with self.assertRaisesRegex(YandexChapterPlanError, "consumed"):
            self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.backend.provider_requests, 2)

    def test_cache_only_execute_uses_zero_provider_requests(self) -> None:
        self.backend.cached_segments = 3
        plan = self.service.prepare(book_id="book", job_id="chapter-ch001", profile_id="yandex_lera")
        result = self.service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["request_slots"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(self.backend.provider_requests, 0)

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


if __name__ == "__main__":
    unittest.main()
