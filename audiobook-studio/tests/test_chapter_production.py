from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.yandex_speechkit import (
    YandexBackendConfig,
    YandexPricingConfig,
    YandexSpeechKitBackend,
    make_fingerprint,
)
from backends.yandex_speechkit import YandexSpeechKitError
from book_library import BookLibrary
from book_text_preparation import BookTextPreparationService
from chapter_production import ChapterProductionError, YandexChapterProductionService
from cloud_billing import CloudBillingService, CloudBillingSettings, save_settings


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(b"\x00\x00" * 220)
    return output.getvalue()


class ChapterProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.source = self.root / "source.txt"
        sentence = "Это достаточно длинное предложение для безопасной проверки производства главы. "
        self.source.write_text("Глава 1. Начало\n\n" + sentence * 12, encoding="utf-8")
        library = BookLibrary(self.books)
        library.import_text_book(
            source_file=self.source,
            title="Производство главы",
            author="Audiobook Studio Test",
            slug="chapter-book",
        )
        BookTextPreparationService(
            library,
            now=lambda: "2026-08-23T10:00:00+00:00",
        ).prepare("chapter-book")
        self.requests = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def service(self, *, current: datetime = NOW) -> YandexChapterProductionService:
        settings = self.root / "cloud-billing.json"
        save_settings(settings, CloudBillingSettings())
        billing = CloudBillingService(
            settings_path=settings,
            ledger_path=self.root / "ledger.json",
            cache_path=self.root / "provider-cache.json",
            now=lambda: current,
        )
        backend = YandexSpeechKitBackend(
            YandexBackendConfig.from_mapping({
                "output_root": str(self.root / "renders/yandex"),
                "keychain_account": "tester",
                "default_profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
                "segmentation": {"max_chars": 220, "max_words": 34},
            }),
            api_key="test-yandex-api-key-1234567890",
            billing_ledger=billing.ledger,
        )

        def request(_: str, request_id: str):
            self.requests += 1
            return wav_bytes(), {"x_request_id": request_id, "x_server_trace_id": "trace-test"}

        backend._request = request
        pricing = YandexPricingConfig.from_mapping({
            "engine": "yandex_speechkit_v3",
            "currency": "RUB",
            "unit_price": "0.20",
            "verified_at": date(2026, 8, 23).isoformat(),
            "source_url": "https://yandex.cloud/prices",
            "max_age_days": 30,
            "hard_limit_rub": "20.00",
        })
        return YandexChapterProductionService(
            backend=backend,
            pricing=pricing,
            billing=billing,
            books_dir=self.books,
            plans_dir=self.root / "runtime/paid-run-plans",
            now=lambda: current,
        )

    def prepare(self, service: YandexChapterProductionService | None = None) -> dict:
        return (service or self.service()).prepare(
            book_name="chapter-book",
            job_id="chapter-ch001",
            profile_id="yandex_lera",
        )

    def test_prepare_is_local_and_binds_one_chapter(self) -> None:
        plan = self.prepare()
        self.assertEqual(plan["decision"], "READY_FOR_CONFIRMATION")
        self.assertEqual(plan["state"], "PREPARED")
        self.assertGreater(plan["max_network_requests"], 0)
        self.assertEqual(plan["provider"], "yandex")
        self.assertEqual(plan["job_id"], "chapter-ch001")
        self.assertFalse(plan["remote_request_sent"])
        self.assertEqual(self.requests, 0)

    def test_preview_job_cannot_enter_chapter_production(self) -> None:
        with self.assertRaisesRegex(ChapterProductionError, "prepared chapter"):
            self.service().prepare(
                book_name="chapter-book",
                job_id="short-test",
                profile_id="yandex_lera",
            )
        self.assertEqual(self.requests, 0)

    def test_execute_consumes_plan_and_never_exceeds_bound(self) -> None:
        service = self.service()
        plan = self.prepare(service)
        profile_before = (self.books / "chapter-book.json").read_bytes()
        prepared_before = (self.books / "chapter-book/prepared/segments.json").read_bytes()
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["state"], "CONSUMED")
        self.assertTrue(Path(result["output_path"]).is_file())
        self.assertGreater(result["network_requests"], 0)
        self.assertLessEqual(result["network_requests"], plan["max_network_requests"])
        self.assertEqual(self.requests, result["network_requests"])
        self.assertEqual((self.books / "chapter-book.json").read_bytes(), profile_before)
        self.assertEqual((self.books / "chapter-book/prepared/segments.json").read_bytes(), prepared_before)
        with self.assertRaisesRegex(ChapterProductionError, "no longer executable"):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])

    def test_digest_mismatch_sends_no_request(self) -> None:
        service = self.service()
        plan = self.prepare(service)
        with self.assertRaisesRegex(ChapterProductionError, "digest"):
            service.execute(plan_id=plan["plan_id"], plan_digest="0" * 64)
        self.assertEqual(self.requests, 0)

    def test_plan_ttl_and_request_cap_tamper_send_no_request(self) -> None:
        for field, value in (("expires_at", "2099-08-23T12:10:00+00:00"), ("max_network_requests", 999)):
            with self.subTest(field=field):
                service = self.service()
                plan = self.prepare(service)
                stored = service.store.load(plan["plan_id"])
                stored[field] = value
                service.store.save(stored)
                with self.assertRaises(ChapterProductionError):
                    service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
                self.assertEqual(self.requests, 0)

    def test_ambiguous_manifest_blocks_prepare(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        first_segment = service.backend.segment(text)[0]
        job_dir = service._job_dir(service.library.load_book_for_execution("chapter-book"), "chapter-ch001")
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "segments": {first_segment.segment_id: {
                "status": "AMBIGUOUS",
                "fingerprint": make_fingerprint(first_segment.text, service.backend.profile),
            }},
        }), encoding="utf-8")
        blocked = self.prepare(service)
        self.assertEqual(blocked["decision"], "BLOCKED")
        self.assertIn("ambiguous_segment_requires_resolution", blocked["blockers"])
        self.assertEqual(self.requests, 0)

    def test_obsolete_manifest_states_do_not_block_reprepared_chapter(self) -> None:
        service = self.service()
        job_dir = service._job_dir(service.library.load_book_for_execution("chapter-book"), "chapter-ch001")
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "segments": {
                "s0001": {"status": "AMBIGUOUS", "fingerprint": "obsolete"},
                "s9999": {"status": "FAILED", "fingerprint": "surplus"},
            },
        }), encoding="utf-8")

        plan = self.prepare(service)
        self.assertEqual(plan["decision"], "READY_FOR_CONFIRMATION")
        self.assertNotIn("ambiguous_segment_requires_resolution", plan["blockers"])
        self.assertNotIn("failed_segment_requires_resolution", plan["blockers"])
        self.assertEqual(self.requests, 0)

    def test_shifted_segment_id_still_blocks_matching_ambiguous_fingerprint(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        current_segment = service.backend.segment(text)[0]
        job_dir = service._job_dir(book, "chapter-ch001")
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "segments": {"s9999": {
                "status": "AMBIGUOUS",
                "fingerprint": make_fingerprint(current_segment.text, service.backend.profile),
            }},
        }), encoding="utf-8")

        blocked = self.prepare(service)
        self.assertEqual(blocked["decision"], "BLOCKED")
        self.assertIn("ambiguous_segment_requires_resolution", blocked["blockers"])
        self.assertEqual(self.requests, 0)

    def test_mismatched_manifest_segmentation_blocks_prepare_without_request(self) -> None:
        service = self.service()
        job_dir = service._job_dir(service.library.load_book_for_execution("chapter-book"), "chapter-ch001")
        job_dir.mkdir(parents=True, exist_ok=True)
        segmentation = service.backend.manifest_segmentation()
        segmentation["sentence_pause_ms"] += 1
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": segmentation,
            "segments": {},
        }), encoding="utf-8")

        blocked = self.prepare(service)
        self.assertEqual(blocked["decision"], "BLOCKED")
        self.assertIn("manifest_mismatch", blocked["blockers"])
        self.assertEqual(self.requests, 0)

    def test_changed_working_copy_invalidates_plan_before_request(self) -> None:
        service = self.service()
        plan = self.prepare(service)
        working = self.books / "chapter-book/tts/working.txt"
        working.write_text(working.read_text(encoding="utf-8") + "\nИзменение.\n", encoding="utf-8")
        with self.assertRaisesRegex(ChapterProductionError, "facts changed"):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.requests, 0)

    def test_changed_segmentation_pause_invalidates_plan_before_request(self) -> None:
        service = self.service()
        plan = self.prepare(service)
        service.backend.config = replace(
            service.backend.config,
            sentence_pause_ms=service.backend.config.sentence_pause_ms + 1,
        )

        with self.assertRaisesRegex(ChapterProductionError, "facts changed"):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.requests, 0)

    def test_changed_request_routing_invalidates_plan_before_request(self) -> None:
        changes = {
            "endpoint": "https://alternate.example.invalid/tts",
            "keychain_service": "Alternate-Yandex-Service",
            "keychain_account": "alternate-account",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                service = self.service()
                plan = self.prepare(service)
                service.backend.config = replace(service.backend.config, **{field: value})

                with self.assertRaisesRegex(ChapterProductionError, "facts changed"):
                    service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
                self.assertEqual(self.requests, 0)

    def test_ambiguous_execution_is_consumed_and_never_retried(self) -> None:
        service = self.service()
        plan = self.prepare(service)

        def ambiguous(_: str, request_id: str):
            self.requests += 1
            raise YandexSpeechKitError(
                "ambiguous",
                category="network_ambiguous",
                request_id=request_id,
            )

        service.backend._request = ambiguous
        with self.assertRaises(YandexSpeechKitError):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.requests, 1)
        with self.assertRaisesRegex(ChapterProductionError, "no longer executable"):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.requests, 1)

    def test_cache_only_plan_materializes_with_zero_provider_requests(self) -> None:
        first_service = self.service()
        first = self.prepare(first_service)
        first_service.execute(plan_id=first["plan_id"], plan_digest=first["plan_digest"])
        requests_after_paid_run = self.requests

        cache_service = self.service()
        cached = self.prepare(cache_service)
        self.assertEqual(cached["decision"], "CACHE_ONLY")
        self.assertEqual(cached["max_network_requests"], 0)
        result = cache_service.execute(plan_id=cached["plan_id"], plan_digest=cached["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(self.requests, requests_after_paid_run)

    def test_cache_only_plan_ignores_stale_paid_pricing_gate(self) -> None:
        paid_service = self.service()
        paid = self.prepare(paid_service)
        paid_service.execute(plan_id=paid["plan_id"], plan_digest=paid["plan_digest"])
        requests_after_paid_run = self.requests

        cache_service = self.service()
        cache_service.pricing = YandexPricingConfig.from_mapping({
            "engine": "yandex_speechkit_v3",
            "currency": "RUB",
            "unit_price": "0.20",
            "verified_at": "2020-01-01",
            "source_url": "https://yandex.cloud/prices",
            "max_age_days": 30,
            "hard_limit_rub": None,
        })
        cached = self.prepare(cache_service)
        self.assertEqual(cached["decision"], "CACHE_ONLY")
        self.assertTrue(cached["pricing_stale"])
        result = cache_service.execute(
            plan_id=cached["plan_id"],
            plan_digest=cached["plan_digest"],
        )
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(self.requests, requests_after_paid_run)

    def test_two_plans_for_same_chapter_are_serialized_through_production(self) -> None:
        first_service = self.service()
        second_service = self.service()
        first_plan = self.prepare(first_service)
        second_plan = self.prepare(second_service)
        request_started = threading.Event()
        release_request = threading.Event()
        original_request = first_service.backend._request

        def slow_request(text: str, request_id: str):
            request_started.set()
            if not release_request.wait(timeout=3):
                raise AssertionError("test did not release the provider request")
            return original_request(text, request_id)

        first_service.backend._request = slow_request
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                first_service.execute,
                plan_id=first_plan["plan_id"],
                plan_digest=first_plan["plan_digest"],
            )
            self.assertTrue(request_started.wait(timeout=3))
            second_future = executor.submit(
                second_service.execute,
                plan_id=second_plan["plan_id"],
                plan_digest=second_plan["plan_digest"],
            )
            time.sleep(0.1)
            self.assertFalse(second_future.done())
            release_request.set()
            first_result = first_future.result(timeout=5)
            with self.assertRaises(ChapterProductionError):
                second_future.result(timeout=5)

        self.assertGreater(first_result["network_requests"], 0)
        self.assertEqual(self.requests, first_result["network_requests"])

    def test_two_chapters_with_shared_fingerprints_are_serialized(self) -> None:
        library = BookLibrary(self.books)
        library.import_text_book(
            source_file=self.source,
            title="Вторая книга с общим текстом",
            author="Audiobook Studio Test",
            slug="chapter-book-two",
        )
        BookTextPreparationService(
            library,
            now=lambda: "2026-08-23T10:00:00+00:00",
        ).prepare("chapter-book-two")
        first_service = self.service()
        second_service = self.service()
        first_plan = self.prepare(first_service)
        second_plan = second_service.prepare(
            book_name="chapter-book-two",
            job_id="chapter-ch001",
            profile_id="yandex_lera",
        )
        request_started = threading.Event()
        release_request = threading.Event()
        original_request = first_service.backend._request

        def slow_request(text: str, request_id: str):
            request_started.set()
            if not release_request.wait(timeout=3):
                raise AssertionError("test did not release the provider request")
            return original_request(text, request_id)

        first_service.backend._request = slow_request
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                first_service.execute,
                plan_id=first_plan["plan_id"],
                plan_digest=first_plan["plan_digest"],
            )
            self.assertTrue(request_started.wait(timeout=3))
            second_future = executor.submit(
                second_service.execute,
                plan_id=second_plan["plan_id"],
                plan_digest=second_plan["plan_digest"],
            )
            time.sleep(0.1)
            self.assertFalse(second_future.done())
            release_request.set()
            first_result = first_future.result(timeout=5)
            with self.assertRaises(ChapterProductionError):
                second_future.result(timeout=5)

        self.assertGreater(first_result["network_requests"], 0)
        self.assertEqual(self.requests, first_result["network_requests"])


if __name__ == "__main__":
    unittest.main()
