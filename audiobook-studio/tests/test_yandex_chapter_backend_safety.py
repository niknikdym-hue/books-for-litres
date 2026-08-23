from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from backends.yandex_client import YandexSpeechKitBackend
from backends.yandex_pricing import YandexPricingConfig
from backends.yandex_types import (
    YandexBackendConfig,
    YandexSpeechKitError,
    YandexVoiceProfile,
    make_fingerprint,
)


class YandexChapterBackendSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = YandexBackendConfig(
            endpoint="https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis",
            keychain_service="AudiobookStudio-YandexSpeechKit",
            keychain_account="tester",
            output_root=self.root / "renders",
            max_chars=220,
            max_words=34,
            sentence_pause_ms=380,
            paragraph_pause_ms=700,
            profile=YandexVoiceProfile(),
        )
        self.pricing = YandexPricingConfig(
            currency="RUB",
            unit="billing_unit",
            unit_price=Decimal("1.00"),
            pricing_model="per_segment",
            source_region="ru-central1",
            verified_at=date(2026, 8, 23),
            source_url="https://example.invalid/pricing",
            max_age_days=30,
            hard_limit_rub=Decimal("100.00"),
            demo_hard_limit_rub=Decimal("5.00"),
        )
        self.backend = YandexSpeechKitBackend(self.config, api_key="A" * 21)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_existing_ambiguous_segment_is_never_automatically_retried(self) -> None:
        text = "Первое предложение."
        segment = self.backend.segment(text)[0]
        fingerprint = make_fingerprint(segment.text, self.backend.profile)
        job_dir = self.root / "job"
        job_dir.mkdir(parents=True)
        (job_dir / "MANIFEST.json").write_text(
            json.dumps({
                "schema_version": 1,
                "engine": "yandex_speechkit_v3",
                "job_id": "chapter-ch001",
                "segments": {
                    segment.segment_id: {
                        "status": "AMBIGUOUS",
                        "fingerprint": fingerprint,
                        "request_id": "previous-ambiguous-request",
                        "wav": f"{segment.segment_id}.wav",
                    }
                },
            }),
            encoding="utf-8",
        )

        with patch.object(self.backend, "synthesize", side_effect=AssertionError("must not retry")) as synthesize:
            with self.assertRaises(YandexSpeechKitError) as caught:
                self.backend.run_text_job(
                    text,
                    job_dir,
                    job_id="chapter-ch001",
                    pricing=self.pricing,
                    scope="chapter",
                    assemble=False,
                )
        self.assertEqual(caught.exception.category, "resume_ambiguous")
        synthesize.assert_not_called()

    def test_dispatch_gate_is_not_called_before_request_construction_succeeds(self) -> None:
        dispatched: list[str] = []
        self.backend._network_dispatch_gate = dispatched.append
        with patch("backends.yandex_client.urllib.request.Request", side_effect=ValueError("bad request")):
            with self.assertRaisesRegex(ValueError, "bad request"):
                self.backend._request("Проверка.", "request-before-dispatch")
        self.assertEqual(dispatched, [])

    def test_dispatch_gate_runs_immediately_before_network_attempt(self) -> None:
        dispatched: list[str] = []
        self.backend._network_dispatch_gate = dispatched.append
        with patch(
            "backends.yandex_client.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline test"),
        ):
            with self.assertRaises(YandexSpeechKitError) as caught:
                self.backend._request("Проверка.", "request-at-dispatch")
        self.assertEqual(caught.exception.category, "network_ambiguous")
        self.assertEqual(dispatched, ["request-at-dispatch"])


if __name__ == "__main__":
    unittest.main()
