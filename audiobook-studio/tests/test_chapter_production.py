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

    def test_prepare_rejects_any_frozen_yandex_profile_drift_without_request(self) -> None:
        for field, value in (("voice", "ermil"), ("role", "good"), ("speed", "1.05")):
            with self.subTest(field=field):
                service = self.service()
                service.backend.profile = replace(service.backend.profile, **{field: value})

                with self.assertRaisesRegex(ChapterProductionError, "frozen Lera/neutral/1.04"):
                    self.prepare(service)
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
            "request_routing": service.backend.request_routing_identity(),
            "segments": {first_segment.segment_id: {
                "status": "AMBIGUOUS",
                "fingerprint": make_fingerprint(first_segment.text, service.backend.profile),
            }},
        }), encoding="utf-8")
        blocked = self.prepare(service)
        self.assertEqual(blocked["decision"], "BLOCKED")
        self.assertIn("ambiguous_segment_requires_resolution", blocked["blockers"])
        self.assertEqual(self.requests, 0)

    def test_completed_inflight_segments_resume_without_provider_requests(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        job_dir = service._job_dir(book, "chapter-ch001")
        segment_dir = job_dir / "segments"
        segment_dir.mkdir(parents=True)
        entries = {}
        for segment in service.backend.segment(text):
            fingerprint = make_fingerprint(segment.text, service.backend.profile)
            wav_name = f"{segment.segment_id}__{fingerprint[:12]}.wav"
            (segment_dir / wav_name).write_bytes(wav_bytes())
            entries[segment.segment_id] = {
                "status": "IN_FLIGHT",
                "fingerprint": fingerprint,
                "request_id": f"interrupted-{segment.segment_id}",
                "wav": wav_name,
            }
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "request_routing": service.backend.request_routing_identity(),
            "segments": entries,
        }), encoding="utf-8")

        plan = self.prepare(service)
        self.assertEqual(plan["decision"], "CACHE_ONLY")
        self.assertEqual(plan["max_network_requests"], 0)
        self.assertNotIn("ambiguous_segment_requires_resolution", plan["blockers"])
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(self.requests, 0)
        recovered = json.loads((job_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertTrue(all(entry["status"] == "DONE" for entry in recovered["segments"].values()))

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
            "request_routing": service.backend.request_routing_identity(),
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
            "request_routing": service.backend.request_routing_identity(),
            "segments": {"s9999": {
                "status": "AMBIGUOUS",
                "fingerprint": make_fingerprint(current_segment.text, service.backend.profile),
            }},
        }), encoding="utf-8")

        blocked = self.prepare(service)
        self.assertEqual(blocked["decision"], "BLOCKED")
        self.assertIn("ambiguous_segment_requires_resolution", blocked["blockers"])
        self.assertEqual(self.requests, 0)

    def test_shifted_inflight_id_recovers_route_scoped_cache_without_request(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        segments = service.backend.segment(text)
        cache_dir = service.backend.cache_namespace(service.backend.config.output_root / "_cache")
        cache_dir.mkdir(parents=True)
        for segment in segments:
            fingerprint = make_fingerprint(segment.text, service.backend.profile)
            (cache_dir / f"{fingerprint}.wav").write_bytes(wav_bytes())
        shifted_fingerprint = make_fingerprint(segments[0].text, service.backend.profile)
        job_dir = service._job_dir(book, "chapter-ch001")
        job_dir.mkdir(parents=True)
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "request_routing": service.backend.request_routing_identity(),
            "segments": {"s9999": {
                "status": "IN_FLIGHT",
                "fingerprint": shifted_fingerprint,
                "request_id": "interrupted-before-id-shift",
            }},
        }), encoding="utf-8")

        plan = self.prepare(service)
        self.assertEqual(plan["decision"], "CACHE_ONLY")
        self.assertEqual(plan["max_network_requests"], 0)
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(self.requests, 0)

    def test_shifted_inflight_job_wav_without_cache_remains_blocked(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        first_segment = service.backend.segment(text)[0]
        fingerprint = make_fingerprint(first_segment.text, service.backend.profile)
        job_dir = service._job_dir(book, "chapter-ch001")
        segment_dir = job_dir / "segments"
        segment_dir.mkdir(parents=True)
        (segment_dir / f"s9999__{fingerprint[:12]}.wav").write_bytes(wav_bytes())
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "request_routing": service.backend.request_routing_identity(),
            "segments": {"s9999": {
                "status": "IN_FLIGHT",
                "fingerprint": fingerprint,
                "request_id": "interrupted-before-id-shift",
            }},
        }), encoding="utf-8")

        blocked = self.prepare(service)
        self.assertEqual(blocked["decision"], "BLOCKED")
        self.assertIn("ambiguous_segment_requires_resolution", blocked["blockers"])
        self.assertEqual(self.requests, 0)

    def test_shifted_inflight_prefers_cache_when_old_job_wav_also_exists(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        segments = service.backend.segment(text)
        for segment in segments:
            fingerprint = make_fingerprint(segment.text, service.backend.profile)
            cache_dir = service.backend.cache_namespace(service.backend.config.output_root / "_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{fingerprint}.wav").write_bytes(wav_bytes())
        shifted_fingerprint = make_fingerprint(segments[0].text, service.backend.profile)
        job_dir = service._job_dir(book, "chapter-ch001")
        segment_dir = job_dir / "segments"
        segment_dir.mkdir(parents=True)
        (segment_dir / f"s9999__{shifted_fingerprint[:12]}.wav").write_bytes(wav_bytes())
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "request_routing": service.backend.request_routing_identity(),
            "segments": {"s9999": {
                "status": "IN_FLIGHT",
                "fingerprint": shifted_fingerprint,
                "request_id": "interrupted-after-both-writes",
            }},
        }), encoding="utf-8")

        plan = self.prepare(service)
        self.assertEqual(plan["decision"], "CACHE_ONLY")
        self.assertEqual(plan["max_network_requests"], 0)
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(self.requests, 0)

        for cached_wav in cache_dir.glob("*.wav"):
            cached_wav.unlink()
        repeated = self.prepare(service)
        self.assertEqual(repeated["decision"], "CACHE_ONLY")
        self.assertEqual(repeated["max_network_requests"], 0)
        self.assertEqual(self.requests, 0)

    def test_shifted_inflight_duplicate_fingerprint_requires_every_current_artifact(self) -> None:
        service = self.service()
        book = service.library.load_book_for_execution("chapter-book")
        text = "\n\n".join(segment["text"] for segment in book["jobs"]["chapter-ch001"]["segments"])
        segments = service.backend.segment(text)
        fingerprints = [make_fingerprint(segment.text, service.backend.profile) for segment in segments]
        duplicate_fingerprint = next(value for value in fingerprints if fingerprints.count(value) > 1)
        current_segment = next(
            segment
            for segment in segments
            if make_fingerprint(segment.text, service.backend.profile) == duplicate_fingerprint
        )
        job_dir = service._job_dir(book, "chapter-ch001")
        segment_dir = job_dir / "segments"
        segment_dir.mkdir(parents=True)
        current_wav = f"{current_segment.segment_id}__{duplicate_fingerprint[:12]}.wav"
        (segment_dir / current_wav).write_bytes(wav_bytes())
        (segment_dir / f"s9999__{duplicate_fingerprint[:12]}.wav").write_bytes(wav_bytes())
        (job_dir / "MANIFEST.json").write_text(json.dumps({
            "schema_version": 1,
            "engine": "yandex_speechkit_v3",
            "job_id": "chapter-ch001",
            "profile": {"voice": "lera", "role": "neutral", "speed": "1.04"},
            "segmentation": service.backend.manifest_segmentation(),
            "request_routing": service.backend.request_routing_identity(),
            "segments": {
                current_segment.segment_id: {
                    "status": "DONE",
                    "fingerprint": duplicate_fingerprint,
                    "wav": current_wav,
                },
                "s9999": {
                    "status": "IN_FLIGHT",
                    "fingerprint": duplicate_fingerprint,
                    "request_id": "duplicate-before-id-shift",
                },
            },
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
            "request_routing": service.backend.request_routing_identity(),
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

    def test_cache_only_plan_repairs_corrupt_job_wav_from_valid_cache_without_request(self) -> None:
        paid_service = self.service()
        paid = self.prepare(paid_service)
        paid_service.execute(plan_id=paid["plan_id"], plan_digest=paid["plan_digest"])
        requests_after_paid_run = self.requests
        book = paid_service.library.load_book_for_execution("chapter-book")
        job_dir = paid_service._job_dir(book, "chapter-ch001")
        manifest = json.loads((job_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        first_entry = next(iter(manifest["segments"].values()))
        corrupt_job_wav = job_dir / "segments" / first_entry["wav"]
        corrupt_job_wav.write_bytes(b"corrupt-job-wav")

        cache_service = self.service()
        cached = self.prepare(cache_service)
        self.assertEqual(cached["decision"], "CACHE_ONLY")
        self.assertEqual(cached["max_network_requests"], 0)
        result = cache_service.execute(plan_id=cached["plan_id"], plan_digest=cached["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertEqual(self.requests, requests_after_paid_run)
        with wave.open(str(corrupt_job_wav), "rb") as repaired:
            self.assertGreater(repaired.getnframes(), 0)
        repaired_manifest = json.loads((job_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        repaired_entry = repaired_manifest["segments"][next(iter(repaired_manifest["segments"]))]
        self.assertTrue(repaired_entry["recovered_from_cache_after_invalid_job_wav"])

    def test_paid_plan_replaces_corrupt_job_and_cache_wavs_with_one_request(self) -> None:
        paid_service = self.service()
        initial = self.prepare(paid_service)
        paid_service.execute(plan_id=initial["plan_id"], plan_digest=initial["plan_digest"])
        requests_after_initial_run = self.requests
        book = paid_service.library.load_book_for_execution("chapter-book")
        job_dir = paid_service._job_dir(book, "chapter-ch001")
        manifest = json.loads((job_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        first_entry = next(iter(manifest["segments"].values()))
        fingerprint = first_entry["fingerprint"]
        job_wav = job_dir / "segments" / first_entry["wav"]
        cache_wav = (
            paid_service.backend.cache_namespace(paid_service.backend.config.output_root / "_cache")
            / f"{fingerprint}.wav"
        )
        job_wav.write_bytes(b"corrupt-job-wav")
        cache_wav.write_bytes(b"corrupt-cache-wav")

        retry_service = self.service()
        retry = self.prepare(retry_service)
        self.assertEqual(retry["decision"], "READY_FOR_CONFIRMATION")
        self.assertEqual(retry["max_network_requests"], 1)
        result = retry_service.execute(plan_id=retry["plan_id"], plan_digest=retry["plan_digest"])
        self.assertEqual(result["network_requests"], 1)
        self.assertEqual(self.requests, requests_after_initial_run + 1)
        with wave.open(str(job_wav), "rb") as repaired_job:
            self.assertGreater(repaired_job.getnframes(), 0)
        with wave.open(str(cache_wav), "rb") as repaired_cache:
            self.assertGreater(repaired_cache.getnframes(), 0)

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
