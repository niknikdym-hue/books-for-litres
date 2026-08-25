import Foundation

private func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() {
        FileHandle.standardError.write(Data("FAIL: \(message)\n".utf8))
        exit(1)
    }
}

@main
struct NativeContractTests {
    static func main() throws {
        var intentGate = OneShotIntentGate()
        require(!intentGate.isArmed, "one-shot intent initially unarmed")
        require(intentGate.consume(nil) == nil, "consume without arm fails closed")

        let firstIntent = intentGate.arm()
        require(intentGate.isArmed, "arm creates an intent")
        require(intentGate.consume(firstIntent) != nil, "armed intent consumes once")
        require(!intentGate.isArmed, "consume clears armed intent")
        require(intentGate.consume(firstIntent) == nil, "consumed intent cannot be reused")

        let cancelledIntent = intentGate.arm()
        intentGate.cancel()
        require(intentGate.consume(cancelledIntent) == nil, "cancel invalidates intent")

        let replacedIntent = intentGate.arm()
        let replacementIntent = intentGate.arm()
        require(replacedIntent != replacementIntent, "new arm creates a new intent")
        require(intentGate.consume(replacedIntent) == nil, "new arm invalidates previous intent")
        require(intentGate.consume(replacementIntent) != nil, "replacement intent consumes once")

        guard CommandLine.arguments.count == 2 else {
            throw NSError(domain: "NativeContractTests", code: 2)
        }
        let snapshotData = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let snapshot = try JSONDecoder().decode(StudioSnapshot.self, from: snapshotData)

        require(snapshot.engines.map(\.id) == ["qwen", "yandex", "openai"], "three engines")
        require(snapshot.voiceLibrary.qwen.count == 9, "nine Qwen voices")
        require(snapshot.voiceLibrary.yandex.count == 4, "four Yandex voices")
        require(snapshot.voiceLibrary.openai.count == 2, "two OpenAI voices")
        require(snapshot.voiceLibrary.openai.map(\.profileID) == ["openai_onyx", "openai_cedar"], "approved OpenAI profiles")
        require(snapshot.voiceLibrary.openai.map(\.label) == ["Onyx", "Cedar"], "OpenAI labels")
        require(snapshot.voiceLibrary.openai.allSatisfy { $0.model == "gpt-4o-mini-tts" }, "OpenAI model")
        require(snapshot.voiceLibrary.openai.allSatisfy { $0.responseFormat == "wav" }, "OpenAI WAV")
        require(snapshot.books.first?.jobs.first?.id == "short-test", "prepared jobs decode")
        require(snapshot.books.first?.jobs.first?.segmentCount == 1, "prepared job segment count")

        let yandex = snapshot.cloudBilling.providers.yandex
        let openai = snapshot.cloudBilling.providers.openai
        require(yandex.currency == "RUB", "Yandex RUB")
        require(openai.currency == "USD", "OpenAI USD")
        require(yandex.remaining == nil, "null Yandex remaining")
        require(openai.remaining == nil, "null OpenAI remaining")
        require(yandex.currentJobEstimateSource == "local_estimate", "Yandex estimate provenance")
        require(openai.currentJobEstimateSource == "unavailable", "OpenAI estimate unavailable")
        require(openai.hardLimit == "1.00", "OpenAI hard limit")
        require(!openai.paidExecutionEnabled, "OpenAI paid execution disabled")
        require(!snapshot.remoteRequestSent, "UI snapshot is offline")

        let preparationJSON = """
        {
          "schema_version": 1,
          "book_id": "native-preparation.json",
          "slug": "native-preparation",
          "source_integrity": "OK",
          "working_copy_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "preparation_status": "READY",
          "preparation_revision": 2,
          "preparation_identity": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          "prepared_at": "2026-08-23T12:00:00+00:00",
          "normalized_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
          "chapter_count": 2,
          "segment_count": 3,
          "jobs": [{"id":"short-test","label":"Безопасный короткий тест","segment_count":1}],
          "normalized_path": "prepared/normalized.txt",
          "structure_path": "prepared/structure.json",
          "segments_path": "prepared/segments.json",
          "remote_request_sent": false
        }
        """
        let preparation = try JSONDecoder().decode(
            BookTextPreparationResult.self,
            from: Data(preparationJSON.utf8)
        )
        require(preparation.preparationStatus == "READY", "preparation status decodes")
        require(preparation.preparationRevision == 2, "preparation revision decodes")
        require(preparation.chapterCount == 2 && preparation.segmentCount == 3, "preparation counts decode")
        require(preparation.normalizedPath == "prepared/normalized.txt", "preparation paths remain relative")
        require(!preparation.remoteRequestSent, "text preparation is offline")

        let staleJSON = """
        {
          "schema_version": 1,
          "provider": "yandex",
          "currency": "RUB",
          "spent": "12.34",
          "spent_source": "local_actual",
          "spent_as_of": "2026-08-21T10:00:00+00:00",
          "known_local_actual_spend": "12.34",
          "unknown_cost_events": 0,
          "remaining": "20.00",
          "remaining_source": "provider_reported",
          "remaining_as_of": "2026-08-21T10:00:00+00:00",
          "current_job_estimate": "4.22",
          "current_job_estimate_source": "local_estimate",
          "projected_remaining": "15.78",
          "projected_remaining_source": "local_estimate",
          "freshness": "stale",
          "status": "STALE",
          "warnings": ["provider_balance_stale"],
          "low_balance_threshold": null,
          "hard_limit": "10.00",
          "last_successful_refresh": "2026-08-21T10:00:00+00:00",
          "last_attempt": "2026-08-21T12:00:00+00:00",
          "stale_after_seconds": 3600,
          "provider_metadata": {"provider_balance_status": "billing_network_error"},
          "paid_execution_enabled": true,
          "remote_request_sent": true
        }
        """
        let stale = try JSONDecoder().decode(CloudBillingSnapshot.self, from: Data(staleJSON.utf8))
        require(stale.freshness == "stale", "stale decode")
        require(stale.warnings == ["provider_balance_stale"], "warnings decode")
        require(stale.hardLimit == "10.00", "hard limit decode")
        require(freshnessLabel(stale) == "Данные устарели", "stale rendering")
        require(provenanceLabel("provider_reported") == "Данные провайдера", "provider provenance")
        require(provenanceLabel("local_actual") == "Учтено Studio", "actual provenance")
        require(provenanceLabel("local_estimate") == "Расчёт Studio", "estimate provenance")
        require(formattedMoney(nil, currency: "RUB", source: "unavailable") == "Недоступно", "null is not zero")
        require(formattedMoney("4.22", currency: "RUB", source: "local_estimate").hasPrefix("≈"), "estimate marker")
        require(formattedMoney("4.22", currency: "RUB", source: "local_estimate").contains("₽"), "RUB symbol")
        require(formattedMoney("1.00", currency: "USD", source: "local_actual").hasPrefix("$"), "USD symbol")
        require(billingWarningLabel("provider_balance_stale") == "Последние данные об остатке устарели.", "warning rendering")

        let readyPlanJSON = """
        {
          "schema_version": 1,
          "plan_id": "11111111-1111-1111-1111-111111111111",
          "plan_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "state": "PREPARED",
          "created_at": "2026-08-21T12:00:00+00:00",
          "expires_at": "2099-08-21T12:10:00+00:00",
          "provider": "openai",
          "book_id": "demo-book",
          "book_file": "demo-book.json",
          "book_title": "Демонстрационная книга",
          "job_id": "short-test",
          "job_label": "Безопасный короткий тест",
          "profile_id": "openai_cedar",
          "model": "gpt-4o-mini-tts",
          "voice": "cedar",
          "response_format": "wav",
          "selected_segment_id": "s0001",
          "selected_segment_characters": 91,
          "selected_segment_utf8_bytes": 166,
          "selected_segment_number": 1,
          "total_segments": 2,
          "succeeded_segments": 0,
          "cached_segments": 0,
          "pending_segments": 2,
          "ambiguous_segments": 0,
          "failed_segments": 0,
          "network_miss_count_for_this_plan": 1,
          "max_network_requests": 1,
          "hard_limit": "1.00",
          "currency": "USD",
          "pricing_verified_at": "2026-08-20",
          "pricing_stale": false,
          "credential_available": true,
          "cost_estimate": null,
          "cost_estimate_source": "unavailable",
          "warnings": ["exact_future_audio_cost_unavailable"],
          "blockers": [],
          "decision": "READY_FOR_CONFIRMATION",
          "billing": \(staleJSON),
          "remote_request_sent": false
        }
        """
        let readyPlan = try JSONDecoder().decode(PaidRunPlan.self, from: Data(readyPlanJSON.utf8))
        require(readyPlan.decision == "READY_FOR_CONFIRMATION", "ready decision decode")
        require(readyPlan.canExecute, "ready plan can execute")
        require(readyPlan.maxNetworkRequests == 1, "one request maximum")
        require(readyPlan.costEstimate == nil, "future exact cost unavailable")
        require(readyPlan.costEstimateSource == "unavailable", "cost provenance unavailable")
        require(readyPlan.voice == "cedar" && readyPlan.model == "gpt-4o-mini-tts", "confirmation voice and model")
        require(readyPlan.bookTitle == "Демонстрационная книга", "confirmation book")
        require(readyPlan.jobLabel == "Безопасный короткий тест", "confirmation job")
        require(readyPlan.selectedSegmentNumber == 1 && readyPlan.totalSegments == 2, "confirmation segment")
        require(readyPlan.selectedSegmentCharacters == 91, "confirmation characters")
        let cachePlan = try JSONDecoder().decode(
            PaidRunPlan.self,
            from: Data(readyPlanJSON.replacingOccurrences(of: "READY_FOR_CONFIRMATION", with: "CACHE_ONLY").utf8)
        )
        require(cachePlan.decision == "CACHE_ONLY" && cachePlan.canExecute, "cache-only decode")
        let blockedPlan = try JSONDecoder().decode(
            PaidRunPlan.self,
            from: Data(readyPlanJSON.replacingOccurrences(of: "READY_FOR_CONFIRMATION", with: "BLOCKED").utf8)
        )
        require(!blockedPlan.canExecute, "blocked plan cannot execute")
        let expiredPlan = try JSONDecoder().decode(
            PaidRunPlan.self,
            from: Data(readyPlanJSON.replacingOccurrences(of: "2099-08-21", with: "2000-08-21").utf8)
        )
        require(expiredPlan.isExpired && !expiredPlan.canExecute, "expired plan cannot execute")
        require(
            paidRunBlockerLabel(["ambiguous_segment_requires_resolution"])
                == "Результат запроса не определён. Автоматический повтор запрещён.",
            "ambiguous UI has no retry"
        )

        let yandexChapterPlanJSON = """
        {
          "schema_version": 1,
          "plan_id": "22222222222222222222222222222222",
          "plan_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "state": "PREPARED",
          "created_at": "2026-08-23T12:00:00+00:00",
          "expires_at": "2099-08-23T12:10:00+00:00",
          "provider": "yandex",
          "book_id": "chapter-book",
          "book_file": "chapter-book.json",
          "book_title": "Книга",
          "job_id": "chapter-ch001",
          "job_label": "Начало",
          "profile_id": "yandex_lera",
          "voice": "lera",
          "role": "neutral",
          "speed": "1.04",
          "characters": 1200,
          "total_segments": 7,
          "cached_segments": 2,
          "max_network_requests": 5,
          "estimated_remaining_cost": "1.00",
          "hard_limit": "10.00",
          "currency": "RUB",
          "pricing_verified_at": "2026-08-23",
          "pricing_stale": false,
          "credential_available": true,
          "warnings": ["provider_balance_unavailable"],
          "blockers": [],
          "decision": "READY_FOR_CONFIRMATION",
          "billing": \(staleJSON),
          "remote_request_sent": false
        }
        """
        let yandexChapterPlan = try JSONDecoder().decode(
            YandexChapterRunPlan.self,
            from: Data(yandexChapterPlanJSON.utf8)
        )
        require(yandexChapterPlan.canExecute, "Yandex chapter plan can execute")
        require(yandexChapterPlan.maxNetworkRequests == 5, "Yandex chapter request cap")
        require(yandexChapterPlan.estimatedRemainingCost == "1.00", "Yandex chapter estimate")
        require(
            yandexChapterBlockerLabel(["ambiguous_segment_requires_resolution"])
                == "Результат Yandex-запроса не определён. Автоматический повтор запрещён.",
            "Yandex ambiguous UI has no retry"
        )

        print("NATIVE_CONTRACT_TESTS_PASS")
    }
}
