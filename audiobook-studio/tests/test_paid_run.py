from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import wave
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.common import atomic_write_json
from backends.openai_client import OpenAITTSBackend, make_fingerprint, normalize_input_text
from backends.openai_pricing import OpenAIPricingConfig
from backends.openai_types import OpenAIBackendConfig, OpenAICredential, OpenAITTSError
from cloud_billing import CloudBillingService, CloudBillingSettings, save_settings
from paid_run import PaidRunError, PaidRunService, _canonical_hash
from audio_qa_authority import AudioQAAuthorityError, resolve_openai_authority


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 240)
    return output.getvalue()


class FakeResponse:
    def __init__(self, body: bytes, *, terminal_error: BaseException | None = None):
        self.body = io.BytesIO(body)
        self.headers = {"Content-Type": "audio/wav", "x-request-id": "req-paid-run-test"}
        self.status = 200
        self.terminal_error = terminal_error

    def read(self, size: int = -1) -> bytes:
        value = self.body.read(size)
        if value:
            return value
        if self.terminal_error:
            error, self.terminal_error = self.terminal_error, None
            raise error
        return b""

    def close(self) -> None:
        pass


def backend_config(root: Path, *, target_chars: int = 45) -> OpenAIBackendConfig:
    return OpenAIBackendConfig.from_mapping({
        "schema_version": 1,
        "engine": "openai_tts",
        "endpoint": "https://api.openai.com/v1/audio/speech",
        "keychain_service": "AudiobookStudio-OpenAI",
        "keychain_account": "tester",
        "cache_root": str(root / "cache"),
        "jobs_root": str(root / "jobs"),
        "request_timeout_seconds": 5,
        "paid_execution_enabled": False,
        "segmentation": {
            "target_chars": target_chars,
            "hard_chars": 120,
            "hard_utf8_bytes": 500,
            "api_max_input_tokens": 2000,
            "sentence_pause_ms": 350,
            "paragraph_pause_ms": 700,
        },
    })


def pricing(*, verified_at: date | None = None, max_age_days: int = 30) -> OpenAIPricingConfig:
    return OpenAIPricingConfig.from_mapping({
        "schema_version": 1,
        "engine": "openai_tts",
        "model": "gpt-4o-mini-tts",
        "currency": "USD",
        "text_input_per_million_tokens": "0.60",
        "audio_output_per_million_tokens": "12.00",
        "verified_at": (verified_at or NOW.date()).isoformat(),
        "source_url": "https://developers.openai.com/api/docs/models/gpt-4o-mini-tts",
        "max_age_days": max_age_days,
        "output_cost_estimate": "unavailable_without_calibration",
        "actual_cost_source": "provider_billing",
    })


class PaidRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.books = self.root / "books"
        self.books.mkdir()
        self.book_path = self.books / "demo-book.json"
        self.write_book([
            "Первый достаточно длинный сегмент для отдельного запроса.",
            "Второй достаточно длинный сегмент для следующего запроса.",
        ])
        self.calls = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_book(self, texts: list[str]) -> None:
        atomic_write_json(self.book_path, {
            "enabled": True,
            "slug": "demo-book",
            "title": "Демо",
            "author": "Studio",
            "language": "Russian",
            "default_speaker": "Vivian",
            "audiobook_instruct": "Read naturally.",
            "pronunciation_overrides": {},
            "jobs": {"job-1": {
                "label": "Подготовленная задача",
                "segments": [
                    {"id": f"source-{index}", "text": text, "pause_after_ms": 0}
                    for index, text in enumerate(texts, 1)
                ],
            }},
        })

    def opener(self, *_: object, **__: object) -> FakeResponse:
        self.calls += 1
        return FakeResponse(wav_bytes())

    def service(
        self,
        *,
        current: datetime = NOW,
        price: OpenAIPricingConfig | None = None,
        credential: bool = True,
        opener=None,
        hard_limit: Decimal | None = Decimal("1.00"),
    ) -> PaidRunService:
        settings_path = self.root / "settings.json"
        save_settings(settings_path, CloudBillingSettings(openai_hard_limit_usd=Decimal("1.00")))
        billing = CloudBillingService(
            settings_path=settings_path,
            ledger_path=self.root / "ledger.json",
            cache_path=self.root / "provider-cache.json",
            now=lambda: current,
        )
        if hard_limit is None:
            billing.settings = replace(billing.settings, openai_hard_limit_usd=None)  # type: ignore[arg-type]
        else:
            billing.settings = replace(billing.settings, openai_hard_limit_usd=hard_limit)

        def credential_loader(*_: object) -> OpenAICredential:
            if not credential:
                raise OpenAITTSError("missing", category="credentials")
            return OpenAICredential("sk-test-key-12345678901234567890")

        backend = OpenAITTSBackend(
            backend_config(self.root),
            credential_loader=credential_loader,
            opener=opener or self.opener,
            billing_ledger=billing.ledger,
        )
        return PaidRunService(
            backend=backend,
            pricing=price or pricing(),
            billing=billing,
            books_dir=self.books,
            plans_dir=self.root / "runtime" / "paid-run-plans",
            now=lambda: current,
        )

    def prepare(self, service: PaidRunService | None = None, profile: str = "openai_onyx") -> dict:
        return (service or self.service()).prepare(
            book_name=self.book_path.name, job_id="job-1", profile_id=profile
        )

    def test_prepare_is_offline_deterministic_and_selects_only_one_miss(self):
        service = self.service()
        first = self.prepare(service)
        second = self.prepare(service)
        self.assertEqual(self.calls, 0)
        self.assertEqual(first["decision"], "READY_FOR_CONFIRMATION")
        self.assertEqual(first["max_network_requests"], 1)
        self.assertEqual(first["network_miss_count_for_this_plan"], 1)
        self.assertEqual(first["selected_segment_id"], "s0001")
        self.assertEqual(first["plan_digest"], second["plan_digest"])
        self.assertNotEqual(first["plan_id"], second["plan_id"])

    def test_digest_changes_for_text_profile_and_selected_segment(self):
        service = self.service()
        original = self.prepare(service)
        cedar = self.prepare(service, "openai_cedar")
        self.write_book(["Изменённый первый сегмент.", "Второй сегмент."])
        changed = self.prepare(service)
        critical = {"selected_segment_id": "s9999"}
        self.assertNotEqual(original["plan_digest"], cedar["plan_digest"])
        self.assertNotEqual(original["plan_digest"], changed["plan_digest"])
        self.assertNotEqual(original["plan_digest"], _canonical_hash(critical))

    def test_missing_credential_stale_pricing_and_hard_limit_block(self):
        missing = self.prepare(self.service(credential=False))
        stale = self.prepare(self.service(price=pricing(verified_at=NOW.date() - timedelta(days=31))))
        no_limit = self.prepare(self.service(hard_limit=None))
        zero_limit = self.prepare(self.service(hard_limit=Decimal("0")))
        self.assertIn("missing_credential", missing["blockers"])
        self.assertIn("stale_pricing", stale["blockers"])
        self.assertIn("missing_hard_limit", no_limit["blockers"])
        self.assertIn("hard_limit_not_positive", zero_limit["blockers"])
        self.assertTrue(all(plan["decision"] == "BLOCKED" for plan in (missing, stale, no_limit, zero_limit)))
        self.assertEqual(self.calls, 0)

    def test_expired_digest_mismatch_and_changed_source_send_zero_requests(self):
        service = self.service()
        plan = self.prepare(service)
        with self.assertRaises(PaidRunError) as digest_error:
            service.execute(plan_id=plan["plan_id"], plan_digest="0" * 64)
        self.assertEqual(digest_error.exception.category, "plan_digest_mismatch")
        self.write_book(["Источник изменился после подтверждения.", "Второй сегмент."])
        with self.assertRaises(PaidRunError) as source_error:
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(source_error.exception.category, "execution_facts_changed")
        self.assertEqual(self.calls, 0)

        expired_service = self.service(current=NOW + timedelta(minutes=11))
        self.write_book([
            "Первый достаточно длинный сегмент для отдельного запроса.",
            "Второй достаточно длинный сегмент для следующего запроса.",
        ])
        with self.assertRaises(PaidRunError) as expired_error:
            expired_service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(expired_error.exception.category, "plan_expired")
        self.assertEqual(self.calls, 0)

    def test_single_success_consumes_plan_updates_partial_manifest_cache_and_ledger(self):
        service = self.service()
        plan = self.prepare(service)
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["network_requests"], 1)
        self.assertIs(result["remote_request_sent"], True)
        self.assertEqual(result["manifest_state"], "PARTIAL")
        self.assertEqual(result["remaining_segments"], 1)
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["segments"]["s0001"]["state"], "SUCCEEDED")
        self.assertEqual(manifest["segments"]["s0002"]["state"], "PENDING")
        self.assertEqual(len(service.billing.ledger.transactions()), 1)
        transaction = service.billing.ledger.transactions()[0]
        self.assertIsNone(transaction["actual_cost"])
        self.assertEqual(transaction["cost_source"], "unavailable")
        stored = service.store.load(plan["plan_id"])
        self.assertEqual(stored["state"], "CONSUMED")
        self.assertEqual(stored["network_requests"], 1)
        self.assertIs(stored["remote_request_sent"], True)

        with self.assertRaises(PaidRunError):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(service.billing.ledger.transactions()), 1)

        next_plan = self.prepare(service)
        self.assertEqual(next_plan["selected_segment_id"], "s0002")

    def test_plan_is_atomically_consuming_before_the_only_network_request(self):
        service = self.service()
        plan = self.prepare(service)

        def inspect_state(*_: object, **__: object) -> FakeResponse:
            self.calls += 1
            self.assertEqual(service.store.load(plan["plan_id"])["state"], "CONSUMING")
            return FakeResponse(wav_bytes())

        service.backend._opener = inspect_state
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 1)
        self.assertEqual(self.calls, 1)
        self.assertEqual(service.store.load(plan["plan_id"])["state"], "CONSUMED")

    def test_plan_schema_has_execution_facts_and_never_serializes_credential(self):
        plan = self.prepare(self.service())
        for field in (
            "schema_version", "plan_id", "plan_digest", "state", "created_at", "expires_at",
            "provider", "book_id", "job_id", "job_label", "profile_id", "model", "voice",
            "response_format", "instructions_sha256", "job_text_sha256", "selected_segment_id",
            "selected_segment_text_sha256", "selected_segment_fingerprint",
            "selected_segment_characters", "selected_segment_utf8_bytes", "total_segments",
            "succeeded_segments", "cached_segments", "pending_segments", "ambiguous_segments",
            "failed_segments", "network_miss_count_for_this_plan", "max_network_requests",
            "hard_limit", "currency", "pricing_verified_at", "pricing_stale",
            "credential_available", "cost_estimate", "cost_estimate_source", "warnings",
            "blockers", "decision",
        ):
            self.assertIn(field, plan)
        serialized = json.dumps(plan).lower()
        self.assertNotIn("sk-test", serialized)
        self.assertNotIn("api_key", serialized)
        self.assertEqual(plan["cost_estimate_source"], "unavailable")
        self.assertIsNone(plan["cost_estimate"])

    def test_cache_only_materializes_without_network_or_new_ledger_event(self):
        service = self.service()
        profile = __import__("backends.openai_client", fromlist=["load_approved_profile"]).load_approved_profile("openai_onyx")
        _, _, _, text = service._load_source(self.book_path.name, "job-1")
        for segment in service.backend.segment(text):
            fingerprint = make_fingerprint(normalize_input_text(segment.text), profile)
            path = service.backend.config.cache_root / f"{fingerprint}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wav_bytes())
        plan = self.prepare(service)
        self.assertEqual(plan["decision"], "CACHE_ONLY")
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(result["network_requests"], 0)
        self.assertIs(result["remote_request_sent"], False)
        self.assertEqual(result["manifest_state"], "SUCCEEDED")
        self.assertEqual(self.calls, 0)
        self.assertEqual(service.billing.ledger.transactions(), [])
        self.assertEqual([item["segment_id"] for item in result["qa_targets"]], ["s0001", "s0002"])
        self.assertIsNone(result["output_path"])
        for target in result["qa_targets"]:
            authority = resolve_openai_authority(
                library=service.book_library,
                backend=service.backend,
                book_name=self.book_path.name,
                job_id="job-1",
                profile_id="openai_onyx",
                manifest_path=Path(result["manifest"]),
                audio_path=Path(target["output_path"]),
            )
            self.assertEqual(authority.segment_id, target["segment_id"])
            self.assertEqual(authority.synthesis_fingerprint, target["synthesis_fingerprint"])
        with self.assertRaisesRegex(AudioQAAuthorityError, "not unambiguous"):
            resolve_openai_authority(
                library=service.book_library,
                backend=service.backend,
                book_name=self.book_path.name,
                job_id="job-1",
                profile_id="openai_onyx",
                manifest_path=Path(result["manifest"]),
            )
        stored = service.store.load(plan["plan_id"])
        self.assertEqual(stored["state"], "CONSUMED")
        self.assertEqual(stored["network_requests"], 0)
        self.assertIs(stored["remote_request_sent"], False)

    def test_single_segment_cache_only_preserves_direct_exact_qa_target(self):
        self.write_book(["Один полностью кэшированный сегмент."])
        service = self.service()
        profile = __import__("backends.openai_client", fromlist=["load_approved_profile"]).load_approved_profile("openai_onyx")
        _, _, _, text = service._load_source(self.book_path.name, "job-1")
        segment = service.backend.segment(text)[0]
        fingerprint = make_fingerprint(normalize_input_text(segment.text), profile)
        cache = service.backend.config.cache_root / f"{fingerprint}.wav"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(wav_bytes())
        plan = self.prepare(service)
        result = service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(plan["decision"], "CACHE_ONLY")
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["selected_segment_id"], "s0001")
        self.assertEqual(result["output_path"], result["qa_targets"][0]["output_path"])
        self.assertEqual(self.calls, 0)

    def test_ambiguous_and_failed_manifest_block_without_retry(self):
        service = self.service()
        base = self.prepare(service)
        _, book, _, text = service._load_source(self.book_path.name, "job-1")
        job_dir = service._job_dir(book, "job-1", "openai_onyx")
        service.backend.prepare_job(text, job_dir, job_id="job-1", profile_id="openai_onyx", pricing=pricing())
        manifest_path = job_dir / "MANIFEST.json"
        for state, blocker in (
            ("AMBIGUOUS", "ambiguous_segment_requires_resolution"),
            ("FAILED", "failed_segment_requires_resolution"),
        ):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["segments"]["s0001"]["state"] = state
            atomic_write_json(manifest_path, manifest)
            plan = self.prepare(service)
            self.assertEqual(plan["decision"], "BLOCKED")
            self.assertIn(blocker, plan["blockers"])
            self.assertEqual(plan["state"], "BLOCKED")
        self.assertEqual(base["automatic_retry_count"] if "automatic_retry_count" in base else 0, 0)
        self.assertEqual(self.calls, 0)

    def test_ambiguous_fake_response_is_consumed_and_never_retried(self):
        def interrupted(*_: object, **__: object) -> FakeResponse:
            self.calls += 1
            return FakeResponse(b"RIFFpartial", terminal_error=TimeoutError("stop"))

        service = self.service(opener=interrupted)
        plan = self.prepare(service)
        with self.assertRaises(OpenAITTSError) as raised:
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(raised.exception.state, "AMBIGUOUS")
        self.assertEqual(self.calls, 1)
        stored = service.store.load(plan["plan_id"])
        self.assertEqual(stored["state"], "CONSUMED")
        self.assertEqual(stored["network_requests"], 1)
        self.assertIs(stored["remote_request_sent"], True)
        with self.assertRaises(PaidRunError):
            service.execute(plan_id=plan["plan_id"], plan_digest=plan["plan_digest"])
        self.assertEqual(self.calls, 1)
        manifest = json.loads(
            (
                service.backend.config.jobs_root
                / "demo-book/job-1/openai/openai_onyx/MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["automatic_retry_count"], 0)
        forensic = list((service.backend.config.jobs_root / "demo-book/job-1/openai/openai_onyx/diagnostics").glob("*.ambiguous"))
        self.assertEqual(len(forensic), 1)

    def test_job_catalog_contains_real_prepared_jobs(self):
        catalog = self.service().job_catalog()
        self.assertEqual(catalog[0]["id"], "demo-book.json")
        self.assertEqual(catalog[0]["jobs"], [{
            "id": "job-1", "label": "Подготовленная задача", "segment_count": 2,
        }])


if __name__ == "__main__":
    unittest.main()
