from __future__ import annotations

import json
import tempfile
import unittest
import wave
from datetime import date
from pathlib import Path

from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_speechkit import (
    DEFAULT_ENDPOINT,
    YandexBackendConfig,
    YandexSpeechKitBackend,
    YandexSpeechKitError,
    make_fingerprint,
)
from dilon_opening_credit_execute import (
    OpeningCreditExecutionError,
    OpeningCreditExternalExecutionService,
    normalize_review_wav,
)
from dilon_opening_credit_plan_store import OpeningCreditPlanStore
from dilon_opening_credit_prepare import EXPECTED_PROFILE
from dilon_opening_credit_review import review_root

TODAY = date(2026, 8, 29)


def pricing(unit_price: str = "0.21146666") -> YandexPricingConfig:
    return YandexPricingConfig.from_mapping({
        "engine": "yandex_speechkit_v3",
        "currency": "RUB",
        "unit": "billing_unit",
        "unit_price": unit_price,
        "pricing_model": "per_250_chars_or_request_unit",
        "source_region": "test",
        "verified_at": TODAY.isoformat(),
        "source_url": "https://example.invalid/pricing",
        "max_age_days": 30,
        "hard_limit_rub": "10.00",
        "demo_hard_limit_rub": "1.00",
    })


def write_wav(path: Path, *, sample_rate: int = 48_000, sample: int = 200, seconds: float = 2.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(sample_rate * seconds))
    payload = int(sample).to_bytes(2, "little", signed=True) * frames
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(payload)


class FakeBackend:
    def __init__(self, root: Path, *, mode: str = "done", endpoint: str = DEFAULT_ENDPOINT, sample: int = 200) -> None:
        self.mode = mode
        self.calls = 0
        self.endpoint = endpoint
        self.sample = sample
        config = YandexBackendConfig.from_mapping({
            "endpoint": endpoint,
            "keychain_service": "AudiobookStudio-YandexSpeechKit",
            "keychain_account": "test",
            "output_root": str(root / "renders-yandex"),
            "default_profile": {
                "voice": "lera",
                "role": "neutral",
                "speed": "1.04",
                "output_container": "WAV",
                "loudness_normalization": "LUFS",
            },
            "segmentation": {
                "max_chars": 220,
                "max_words": 34,
                "sentence_pause_ms": 380,
                "paragraph_pause_ms": 700,
            },
        })
        self.delegate = YandexSpeechKitBackend(config, api_key="x" * 24)
        self.profile = self.delegate.profile

    def validate_config(self, *, resolve_credentials: bool = False) -> dict[str, object]:
        return {
            "ok": True,
            "endpoint": self.endpoint,
            "voice": self.profile.voice,
            "role": self.profile.role,
            "speed": self.profile.speed,
        }

    def segment(self, text: str):
        return self.delegate.segment(text)

    def request_routing_identity(self) -> dict[str, str]:
        return {
            "endpoint": self.endpoint,
            "keychain_service": "AudiobookStudio-YandexSpeechKit",
            "keychain_account": "test",
        }

    def _manifest(self, text: str, job_dir: Path, status: str, *, category: str | None = None) -> Path:
        segment = self.segment(text)[0]
        fingerprint = make_fingerprint(segment.text, self.profile)
        joined = job_dir / "joined.wav"
        entry: dict[str, object] = {
            "status": status,
            "text": segment.text,
            "pause_after_ms": segment.pause_after_ms,
            "paragraph_index": segment.paragraph_index,
            "fingerprint": fingerprint,
            "request_id": "request-1",
            "wav": "joined.wav",
        }
        if status == "DONE":
            entry["billing_transaction_id"] = "billing-1"
        if category:
            entry["error"] = {"category": category}
        manifest: dict[str, object] = {
            "schema_version": 1,
            "job_id": "fake",
            "segments": {segment.segment_id: entry},
        }
        job_dir.mkdir(parents=True, exist_ok=True)
        if status in {"DONE", "CACHED"}:
            write_wav(joined, sample=self.sample)
            manifest["joined_wav"] = joined.name
        (job_dir / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        return joined

    def run_text_job(
        self,
        text: str,
        job_dir: Path,
        *,
        job_id: str,
        pricing: YandexPricingConfig,
        scope: str,
    ) -> Path:
        self.calls += 1
        job_dir.mkdir(parents=True, exist_ok=True)
        if self.mode == "ambiguous":
            self._manifest(text, job_dir, "AMBIGUOUS", category="network_ambiguous")
            raise YandexSpeechKitError("ambiguous", category="network_ambiguous")
        if self.mode == "credentials":
            self._manifest(text, job_dir, "FAILED", category="credentials")
            raise YandexSpeechKitError("missing credential", category="credentials")
        if self.mode == "http-failed":
            self._manifest(text, job_dir, "FAILED", category="permission")
            raise YandexSpeechKitError("permission", category="permission", http_status=403)
        return self._manifest(text, job_dir, "CACHED" if self.mode == "cached" else "DONE")


class OpeningCreditExternalExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plans = self.root / "paid-plans"
        self.pricing = pricing()
        self.plan = OpeningCreditPlanStore(self.plans).prepare(pricing=self.pricing, today=TODAY)
        self.assertTrue(self.plan["stored"])
        self.book = "hvatit-sebya-obestsenivat"
        self.job = "chapter-ch001"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def service(self, backend: FakeBackend, *, current_pricing: YandexPricingConfig | None = None):
        return OpeningCreditExternalExecutionService(
            workspace_root=self.root,
            plans_root=self.plans,
            pricing=current_pricing or self.pricing,
            backend=backend,
        )

    def execute(self, service: OpeningCreditExternalExecutionService, *, authorized: bool = True):
        return service.execute_authorized(
            book_slug=self.book,
            job_id=self.job,
            plan_id=self.plan["plan_id"],
            plan_digest=self.plan["plan_digest"],
            owner_authorized=authorized,
            today=TODAY,
        )

    def test_owner_authorization_blocks_before_provider(self) -> None:
        backend = FakeBackend(self.root)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(self.service(backend), authorized=False)
        self.assertEqual(caught.exception.code, "owner_authorization_required")
        self.assertEqual(backend.calls, 0)
        self.assertFalse(caught.exception.remote_request_sent)

    def test_changed_price_requires_fresh_prepare_and_authorization(self) -> None:
        backend = FakeBackend(self.root)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(self.service(backend, current_pricing=pricing("0.31146666")))
        self.assertEqual(caught.exception.code, "plan_stale_reprepare_required")
        self.assertEqual(backend.calls, 0)

    def test_endpoint_drift_blocks_before_provider(self) -> None:
        backend = FakeBackend(self.root, endpoint="https://example.invalid/tts")
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(self.service(backend))
        self.assertEqual(caught.exception.code, "backend_authority_drift")
        self.assertEqual(backend.calls, 0)

    def test_success_publishes_only_pending_review_and_is_idempotent(self) -> None:
        backend = FakeBackend(self.root, mode="done")
        service = self.service(backend)
        first = self.execute(service)
        self.assertEqual(first["state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(first["decision"], "HUMAN_LISTENING_REQUIRED")
        self.assertEqual(first["provider_requests"], 1)
        self.assertTrue(first["remote_request_sent"])
        self.assertTrue(first["paid_execution"])
        self.assertTrue(first["billing_changed"])
        self.assertFalse(first["manual_approval_published"])
        self.assertFalse(first["whole_book_release_ready"])
        self.assertEqual(backend.calls, 1)
        current = review_root(workspace_root=self.root, book_slug=self.book, job_id=self.job) / "CURRENT.json"
        self.assertFalse(current.exists())
        candidate = json.loads(Path(first["candidate_path"]).read_text(encoding="utf-8"))
        self.assertEqual(candidate["candidate"]["manual_state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(candidate["candidate"]["provider_requests"], 1)
        self.assertTrue(candidate["candidate"]["remote_request_sent"])
        self.assertEqual(candidate["candidate"]["profile"], EXPECTED_PROFILE)

        second = self.execute(service)
        self.assertEqual(backend.calls, 1, "completed provider result must never be requested again")
        self.assertEqual(second["provider_requests"], 0)
        self.assertFalse(second["remote_request_sent"])
        self.assertEqual(second["historical_provenance"]["provider_requests"], 1)
        self.assertEqual(second["candidate_id"], first["candidate_id"])

    def test_cache_only_materialization_is_zero_request(self) -> None:
        backend = FakeBackend(self.root, mode="cached")
        result = self.execute(self.service(backend))
        self.assertEqual(result["provider_requests"], 0)
        self.assertFalse(result["remote_request_sent"])
        self.assertFalse(result["paid_execution"])
        self.assertFalse(result["billing_changed"])
        self.assertEqual(result["historical_provenance"]["provider_requests"], 0)

    def test_ambiguous_result_is_never_retried(self) -> None:
        backend = FakeBackend(self.root, mode="ambiguous")
        service = self.service(backend)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(service)
        self.assertEqual(caught.exception.code, "provider_result_ambiguous")
        self.assertEqual(caught.exception.provider_requests, 1)
        self.assertTrue(caught.exception.remote_request_sent)
        self.assertIsNone(caught.exception.billing_changed)
        self.assertFalse(caught.exception.retry_allowed)
        self.assertEqual(backend.calls, 1)
        backend.mode = "done"
        with self.assertRaises(OpeningCreditExecutionError) as second:
            self.execute(service)
        self.assertEqual(second.exception.code, "prior_provider_result_requires_resolution")
        self.assertEqual(backend.calls, 1)
        self.assertFalse(second.exception.remote_request_sent)

    def test_pre_request_credential_failure_can_retry_without_double_charge(self) -> None:
        backend = FakeBackend(self.root, mode="credentials")
        service = self.service(backend)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(service)
        self.assertEqual(caught.exception.code, "provider_execution_failed")
        self.assertFalse(caught.exception.remote_request_sent)
        self.assertEqual(caught.exception.provider_requests, 0)
        backend.mode = "done"
        result = self.execute(service)
        self.assertEqual(result["state"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(backend.calls, 2)

    def test_http_failure_after_request_blocks_retry(self) -> None:
        backend = FakeBackend(self.root, mode="http-failed")
        service = self.service(backend)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(service)
        self.assertTrue(caught.exception.remote_request_sent)
        self.assertEqual(caught.exception.provider_requests, 1)
        backend.mode = "done"
        with self.assertRaises(OpeningCreditExecutionError) as second:
            self.execute(service)
        self.assertEqual(second.exception.code, "prior_provider_result_requires_resolution")
        self.assertEqual(backend.calls, 1)

    def test_candidate_qa_failure_never_publishes_current(self) -> None:
        backend = FakeBackend(self.root, mode="done", sample=0)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            self.execute(self.service(backend))
        self.assertEqual(caught.exception.code, "opening_credit_silent")
        current = review_root(workspace_root=self.root, book_slug=self.book, job_id=self.job) / "CURRENT.json"
        self.assertFalse(current.exists())

    def test_unicode_slug_uses_canonical_book_identity(self) -> None:
        backend = FakeBackend(self.root, mode="cached")
        result = self.service(backend).execute_authorized(
            book_slug="книга-тест",
            job_id=self.job,
            plan_id=self.plan["plan_id"],
            plan_digest=self.plan["plan_digest"],
            owner_authorized=True,
            today=TODAY,
        )
        self.assertEqual(result["book_slug"], "книга-тест")
        self.assertIn("книга-тест", result["candidate_path"])

    def test_default_normalizer_preserves_existing_48k_source(self) -> None:
        source = self.root / "provider.wav"
        target = self.root / "review.wav"
        write_wav(source, sample_rate=48_000, sample=111)
        before = source.read_bytes()
        result = normalize_review_wav(self.root, source, target)
        self.assertEqual(result, target)
        self.assertEqual(source.read_bytes(), before)
        with wave.open(str(target), "rb") as audio:
            self.assertEqual(audio.getframerate(), 48_000)
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getsampwidth(), 2)

    def test_default_normalizer_rejects_tampered_existing_review_output(self) -> None:
        source = self.root / "provider-tamper.wav"
        target = self.root / "review-tamper.wav"
        write_wav(source, sample_rate=48_000, sample=111)
        write_wav(target, sample_rate=48_000, sample=222)
        with self.assertRaises(OpeningCreditExecutionError) as caught:
            normalize_review_wav(self.root, source, target)
        self.assertEqual(caught.exception.code, "review_output_collision")


if __name__ == "__main__":
    unittest.main()
