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
        var player = AudioPlaybackStateMachine()
        player.load(duration: 347.0)
        require(player.state == .ready && player.elapsed == 0, "player loads ready")
        player.play()
        require(player.state == .playing, "player play state")
        player.seek(to: 42)
        require(player.elapsed == 42, "player seek")
        player.pause()
        require(player.state == .paused && player.elapsed == 42, "player pause preserves position")
        player.play()
        require(player.state == .playing && player.elapsed == 42, "player resume preserves position")
        player.finish()
        require(player.state == .finished && player.elapsed == 347, "player EOF")
        player.seek(to: 42)
        require(player.state == .paused && player.elapsed == 42, "seek backward leaves EOF")
        player.finish()
        player.play()
        require(player.state == .playing && player.elapsed == 0, "play after EOF restarts")
        player.stop()
        require(player.state == .stopped && player.elapsed == 0, "player stop resets")
        player.load(duration: 10)
        require(player.state == .ready && player.duration == 10, "loading another audio replaces state")
        require(audioTimeLabel(347) == "05:47", "audio duration label")
        require(
            audioQAWarningLabel("ffmpeg_unavailable")
                == "Расширенная техническая проверка недоступна",
            "raw FFmpeg warning is humanized"
        )
        require(
            audioQAWarningLabel("ffmpeg_unavailable") != "ffmpeg_unavailable",
            "raw warning code is not primary text"
        )

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
        let targetListJSON = """
        {
          "schema_version": 1,
          "qa_targets": [
            {
              "segment_id": "s0001",
              "output_path": "/tmp/s0001.wav",
              "manifest_path": "/tmp/MANIFEST.json",
              "synthesis_fingerprint": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            },
            {
              "segment_id": "s0002",
              "output_path": "/tmp/s0002.wav",
              "manifest_path": "/tmp/MANIFEST.json",
              "synthesis_fingerprint": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
            }
          ],
          "remote_request_sent": false
        }
        """
        let targetList = try JSONDecoder().decode(
            OpenAIQATargetList.self,
            from: Data(targetListJSON.utf8)
        )
        require(targetList.qaTargets.count == 2, "OpenAI QA target list decodes")
        require(!targetList.remoteRequestSent, "OpenAI QA target list is offline")
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

        let audioQAJSON = """
        {
          "schema_version": 1,
          "authority": {
            "provider": "yandex", "book_slug": "demo-book", "book_title": "Демо",
            "job_id": "chapter-ch001", "job_label": "Глава 1", "profile_id": "yandex_lera",
            "segment_id": "chapter-ch001", "segment_text": "Точный текст",
            "audio_path": "/tmp/chapter.wav", "manifest_path": "/tmp/MANIFEST.json",
            "synthesis_fingerprint": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            "expected_sample_rate_hz": 22050, "text_characters": 12
          },
          "record": {
            "schema_version": 2, "book_slug": "demo-book", "job_id": "chapter-ch001",
            "segment_id": "chapter-ch001", "audio_path": "/tmp/chapter.wav",
            "identity": {
              "audio_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "path_identity": "/tmp/chapter.wav",
              "synthesis_fingerprint": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            },
            "production_facts": {
              "expected_sample_rate_hz": 22050, "text_characters": 12,
              "minimum_expected_duration_seconds": 0.15
            },
            "automatic_status": "PASS", "automatic_reasons": [], "automatic_warnings": [],
            "wav": {
              "duration_seconds": 1.0, "sample_rate_hz": 22050, "channels": 1,
              "sample_width_bytes": 2, "frame_count": 22050, "compression_type": "NONE",
              "data_bytes": 44100
            },
            "signal_metrics": {
              "available": true, "reason": null, "peak_fraction": 0.5,
              "clipped_fraction": 0.0, "near_silence_fraction": 0.1,
              "sample_count": 22050, "stream_chunk_bytes": 65536
            },
            "ffmpeg": {"status": "PASS", "available": true, "exit_code": 0},
            "manual_state": "UNREVIEWED", "downstream_eligible": false,
            "scanned_at": "2026-08-27T12:00:00+00:00", "manual_decided_at": null,
            "created_at": "2026-08-27T12:00:00+00:00", "updated_at": "2026-08-27T12:00:00+00:00",
            "remote_request_sent": false
          },
          "eligible": false, "remote_request_sent": false
        }
        """
        let audioQA = try JSONDecoder().decode(AudioQACurrentEnvelope.self, from: Data(audioQAJSON.utf8))
        require(audioQA.record.schemaVersion == 2, "audio QA schema v2 decodes")
        require(audioQA.authority.expectedSampleRateHz == 22050, "provider-specific sample rate decodes")
        require(audioQA.record.signalMetrics.streamChunkBytes == 65536, "streaming metric decodes")
        require(!audioQA.eligible && !audioQA.remoteRequestSent, "QA gate fails closed offline")

        let selectedBook = try JSONDecoder().decode(
            Book.self,
            from: Data("""
            {"id":"demo-book.json","slug":"demo-book","title":"Демо","author":"Studio","jobs":[]}
            """.utf8)
        )
        require(
            audioQASelectionMatches(
                selectedBook: selectedBook,
                selectedJobID: "chapter-ch001",
                selectedProfileID: "yandex_lera",
                authority: audioQA.authority
            ),
            "filename ID and canonical slug match for QA decisions"
        )
        let changedBook = try JSONDecoder().decode(
            Book.self,
            from: Data("""
            {"id":"other-book.json","slug":"other-book","title":"Другая","author":"Studio","jobs":[]}
            """.utf8)
        )
        require(
            !audioQASelectionMatches(
                selectedBook: changedBook,
                selectedJobID: "chapter-ch001",
                selectedProfileID: "yandex_lera",
                authority: audioQA.authority
            ),
            "changed book selection fails closed"
        )

        let assemblyJSON = """
        {
          "schema_version": 1,
          "qa": \(audioQAJSON),
          "assembly": {
            "schema_version": 1, "state": "READY", "decision": "ALREADY_ASSEMBLED",
            "blockers": [], "blocker_message": null,
            "assembly_identity": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "target": {"container":"WAV","codec":"LPCM","sample_rate_hz":48000,"channels":1,"sample_width_bytes":2},
            "ffmpeg": {"available":true,"path":"/opt/homebrew/bin/ffmpeg","version":"ffmpeg version 9","source":"known_macos_location"},
            "output_path": "/tmp/chapter.wav", "manifest_path": "/tmp/MANIFEST.json",
            "assembly": {
              "schema_version": 1, "status": "READY",
              "assembly_identity": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
              "output": {
                "path":"/tmp/chapter.wav",
                "path_identity":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "wav":{"duration_seconds":347.0,"sample_rate_hz":48000,"channels":1,"sample_width_bytes":2,"frame_count":16656000,"compression_type":"NONE","data_bytes":33312000}
              },
              "provider_requests":0,"remote_request_sent":false
            },
            "provider_requests": 0, "remote_request_sent": false
          },
          "provider_requests": 0, "remote_request_sent": false
        }
        """
        let assembly = try JSONDecoder().decode(
            ChapterAssemblyEnvelope.self,
            from: Data(assemblyJSON.utf8)
        )
        require(assembly.assembly.assembly?.output.wav.sampleRateHz == 48000, "assembly target decodes")
        require(assembly.assembly.assembly?.providerRequests == 0, "assembly remains offline")
        require(chapterAssemblyStateLabel(assembly.assembly.state, decision: assembly.assembly.decision) == "Глава собрана", "assembly label")

        let masteringStatusJSON = """
        {
          "schema_version":1,"state":"READY","decision":"ALREADY_MASTERED","blockers":[],"blocker_message":null,
          "master_preset":{"id":"spoken_word_master_v1","version":1,"target_integrated_lufs":-19.0,"true_peak_ceiling_dbtp":-3.0},
          "master_preset_hash":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
          "master_identity":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
          "ffmpeg":{"available":true,"path":"/opt/homebrew/bin/ffmpeg","version":"ffmpeg version 9","source":"known_macos_location"},
          "manifest_path":"/tmp/master/MANIFEST.json",
          "master":{
            "schema_version":1,"status":"READY","master_identity":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            "output":{"path":"/tmp/master.wav","path_identity":"1111111111111111111111111111111111111111111111111111111111111111","sha256":"2222222222222222222222222222222222222222222222222222222222222222","wav":{"duration_seconds":348.0,"sample_rate_hz":48000,"channels":1,"sample_width_bytes":2,"frame_count":16704000,"compression_type":"NONE","data_bytes":33408000}},
            "verification":{"loudness":{"input_i":-19.0,"input_tp":-3.2},"signal":{"rms_dbfs":-20.5,"estimated_noise_floor_dbfs":-58.0,"clipped_samples":0},"boundary_silence":{"leading_silence_seconds":0.5,"trailing_silence_seconds":1.0}},
            "provider_requests":0,"remote_request_sent":false,"billing_changed":false
          },
          "provider_requests":0,"remote_request_sent":false,"billing_changed":false
        }
        """
        let assemblyObject = try JSONSerialization.jsonObject(with: Data(assemblyJSON.utf8)) as! [String: Any]
        let assemblyStatusData = try JSONSerialization.data(withJSONObject: assemblyObject["assembly"]!)
        let assemblyStatusJSON = String(data: assemblyStatusData, encoding: .utf8)!
        let masteringJSON = """
        {"schema_version":1,"assembly":
        """ + assemblyStatusJSON + """
        ,"mastering":
        """ + masteringStatusJSON + """
        ,"provider_requests":0,"remote_request_sent":false,"billing_changed":false}
        """
        let mastering = try JSONDecoder().decode(MasteringEnvelope.self, from: Data(masteringJSON.utf8))
        require(mastering.mastering.master?.verification.loudness.inputI == -19.0, "master loudness decodes")
        require(mastering.mastering.master?.output.wav.channels == 1, "clean master remains mono")
        require(masteringStateLabel(mastering.mastering.state, decision: mastering.mastering.decision) == "Clean master готов", "master state label")
        require(masteringStateLabel("RECOVERY_REQUIRED", decision: "READY_TO_REPAIR") == "Требуется восстановить текущий master", "master recovery label")

        let exportJSON = """
        {
          "schema_version":1,"mastering":
        """ + masteringStatusJSON + """
        ,
          "export":{"schema_version":1,"state":"READY","decision":"ALREADY_EXPORTED","blockers":[],"blocker_message":null,
            "profile":{"id":"litres_author_v1","version":1,"channels":2,"bitrate_bps":128000},
            "profile_hash":"3333333333333333333333333333333333333333333333333333333333333333",
            "candidate_identity":"4444444444444444444444444444444444444444444444444444444444444444","encoder":"libmp3lame",
            "chapter_export":{"candidate_identity":"4444444444444444444444444444444444444444444444444444444444444444","job_id":"chapter-ch001","chapter_title":"Введение","position":1,"path":"/tmp/001.mp3","path_identity":"5555555555555555555555555555555555555555555555555555555555555555","sha256":"6666666666666666666666666666666666666666666666666666666666666666","facts":{"duration_seconds":348.0,"sample_rate_hz":48000,"channels":2,"channel_layout":"stereo","bitrate_bps":128000,"size_bytes":5600000,"decodable":true}},
            "book_export":{"expected_chapters":16,"ready_chapters":1,"progress":"1/16","ready":false,"blockers":["missing_chapters","missing_cover"]},
            "manifest_path":"/tmp/export/MANIFEST.json","provider_requests":0,"remote_request_sent":false,"billing_changed":false
          },
          "provider_requests":0,"remote_request_sent":false,"billing_changed":false
        }
        """
        let export = try JSONDecoder().decode(LitresExportEnvelope.self, from: Data(exportJSON.utf8))
        require(export.export.chapterExport?.facts.channels == 2, "LitRes MP3 is stereo")
        require(litresExportStateLabel("RECOVERY_REQUIRED", decision: "READY_TO_REPAIR") == "Требуется восстановить выпускной пакет", "export recovery label")
        require(export.export.chapterExport?.facts.bitrateBps == 128000, "LitRes bitrate decodes")
        require(export.export.bookExport.progress == "1/16" && !export.export.bookExport.ready, "whole book stays incomplete")
        require(litresExportStateLabel(export.export.state, decision: export.export.decision) == "MP3 главы готов", "export state label")

        let releaseAuthorityJSON = """
        {"schema_version":1,"book_slug":"demo-book","rights_blocked":true,
         "book_pointer_invalidated":true,"state":"INVALIDATED",
         "provider_requests":0,"remote_request_sent":false,"billing_changed":false}
        """
        let releaseAuthority = try JSONDecoder().decode(
            LitresReleaseAuthorityStatus.self,
            from: Data(releaseAuthorityJSON.utf8)
        )
        require(releaseAuthority.rightsBlocked, "release rights blocker decodes")
        require(releaseAuthority.bookPointerInvalidated, "release pointer invalidation decodes")
        require(releaseAuthority.providerRequests == 0 && !releaseAuthority.remoteRequestSent, "release reconciliation stays offline")

        let releaseSweepJSON = """
        {"schema_version":1,"processed_books":1,"failed_book_ids":[],
         "quarantine_failed_book_ids":[],
         "results":[\(releaseAuthorityJSON)],"provider_requests":0,
         "remote_request_sent":false,"billing_changed":false}
        """
        let releaseSweep = try JSONDecoder().decode(
            LitresReleaseAuthoritySweep.self,
            from: Data(releaseSweepJSON.utf8)
        )
        require(releaseSweep.processedBooks == 1 && releaseSweep.failedBookIDs.isEmpty, "release sweep decodes")
        require(releaseSweep.quarantineFailedBookIDs.isEmpty, "release quarantine failures decode")
        require(releaseSweep.results.first?.bookPointerInvalidated == true, "release sweep carries exact result")

        print("NATIVE_CONTRACT_TESTS_PASS")
    }
}
