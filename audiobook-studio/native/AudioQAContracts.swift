import Foundation

struct AudioQAIdentity: Codable, Equatable {
    let audioSHA256: String?
    let pathIdentity: String
    let synthesisFingerprint: String?

    enum CodingKeys: String, CodingKey {
        case audioSHA256 = "audio_sha256"
        case pathIdentity = "path_identity"
        case synthesisFingerprint = "synthesis_fingerprint"
    }
}

struct AudioQAWavFacts: Codable, Equatable {
    let durationSeconds: Double
    let sampleRateHz: Int
    let channels: Int
    let sampleWidthBytes: Int
    let frameCount: Int
    let compressionType: String
    let dataBytes: Int

    enum CodingKeys: String, CodingKey {
        case durationSeconds = "duration_seconds"
        case sampleRateHz = "sample_rate_hz"
        case channels
        case sampleWidthBytes = "sample_width_bytes"
        case frameCount = "frame_count"
        case compressionType = "compression_type"
        case dataBytes = "data_bytes"
    }
}

struct AudioQASignalMetrics: Codable, Equatable {
    let available: Bool
    let reason: String?
    let peakFraction: Double?
    let clippedFraction: Double?
    let nearSilenceFraction: Double?
    let sampleCount: Int
    let streamChunkBytes: Int

    enum CodingKeys: String, CodingKey {
        case available, reason
        case peakFraction = "peak_fraction"
        case clippedFraction = "clipped_fraction"
        case nearSilenceFraction = "near_silence_fraction"
        case sampleCount = "sample_count"
        case streamChunkBytes = "stream_chunk_bytes"
    }
}

struct AudioQAProductionFacts: Codable, Equatable {
    let expectedSampleRateHz: Int
    let textCharacters: Int
    let minimumExpectedDurationSeconds: Double

    enum CodingKeys: String, CodingKey {
        case expectedSampleRateHz = "expected_sample_rate_hz"
        case textCharacters = "text_characters"
        case minimumExpectedDurationSeconds = "minimum_expected_duration_seconds"
    }
}

struct AudioQAFFmpegFacts: Codable, Equatable {
    let status: String
    let available: Bool
    let exitCode: Int?
    let path: String?
    let version: String?
    let source: String?

    enum CodingKeys: String, CodingKey {
        case status, available, path, version, source
        case exitCode = "exit_code"
    }
}

struct AudioQARecord: Codable, Equatable {
    let schemaVersion: Int
    let bookSlug: String
    let jobID: String
    let segmentID: String
    let audioPath: String
    let identity: AudioQAIdentity
    let productionFacts: AudioQAProductionFacts
    let automaticStatus: String
    let automaticReasons: [String]
    let automaticWarnings: [String]
    let wav: AudioQAWavFacts?
    let signalMetrics: AudioQASignalMetrics
    let ffmpeg: AudioQAFFmpegFacts
    let manualState: String
    let downstreamEligible: Bool
    let scannedAt: String
    let manualDecidedAt: String?
    let createdAt: String
    let updatedAt: String
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case identity, wav, ffmpeg
        case schemaVersion = "schema_version"
        case bookSlug = "book_slug"
        case jobID = "job_id"
        case segmentID = "segment_id"
        case audioPath = "audio_path"
        case automaticStatus = "automatic_status"
        case automaticReasons = "automatic_reasons"
        case automaticWarnings = "automatic_warnings"
        case signalMetrics = "signal_metrics"
        case productionFacts = "production_facts"
        case manualState = "manual_state"
        case downstreamEligible = "downstream_eligible"
        case scannedAt = "scanned_at"
        case manualDecidedAt = "manual_decided_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct AudioQAAuthority: Codable, Equatable {
    let provider: String
    let bookSlug: String
    let bookTitle: String
    let jobID: String
    let jobLabel: String
    let profileID: String
    let segmentID: String
    let segmentText: String
    let audioPath: String
    let manifestPath: String
    let synthesisFingerprint: String
    let expectedSampleRateHz: Int
    let textCharacters: Int

    enum CodingKeys: String, CodingKey {
        case provider
        case bookSlug = "book_slug"
        case bookTitle = "book_title"
        case jobID = "job_id"
        case jobLabel = "job_label"
        case profileID = "profile_id"
        case segmentID = "segment_id"
        case segmentText = "segment_text"
        case audioPath = "audio_path"
        case manifestPath = "manifest_path"
        case synthesisFingerprint = "synthesis_fingerprint"
        case expectedSampleRateHz = "expected_sample_rate_hz"
        case textCharacters = "text_characters"
    }
}

struct AudioQACurrentEnvelope: Codable {
    let schemaVersion: Int
    let authority: AudioQAAuthority
    let record: AudioQARecord
    let eligible: Bool
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case authority, record, eligible
        case schemaVersion = "schema_version"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct AudioQAStatusEnvelope: Codable {
    let schemaVersion: Int
    let record: AudioQARecord?
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case record
        case schemaVersion = "schema_version"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct AudioQADownstreamEnvelope: Codable {
    let schemaVersion: Int
    let eligible: Bool
    let record: AudioQARecord?
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case eligible, record
        case schemaVersion = "schema_version"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct ChapterAssemblyFFmpeg: Codable, Equatable {
    let available: Bool
    let path: String?
    let version: String?
    let source: String
}

struct ChapterAssemblyTarget: Codable, Equatable {
    let container: String
    let codec: String
    let sampleRateHz: Int
    let channels: Int
    let sampleWidthBytes: Int

    enum CodingKeys: String, CodingKey {
        case container, codec, channels
        case sampleRateHz = "sample_rate_hz"
        case sampleWidthBytes = "sample_width_bytes"
    }
}

struct ChapterAssemblyOutput: Codable, Equatable {
    let path: String
    let pathIdentity: String
    let sha256: String
    let wav: AudioQAWavFacts

    enum CodingKeys: String, CodingKey {
        case path, sha256, wav
        case pathIdentity = "path_identity"
    }
}

struct ChapterAssemblyManifest: Codable, Equatable {
    let schemaVersion: Int
    let status: String
    let assemblyIdentity: String
    let output: ChapterAssemblyOutput
    let providerRequests: Int
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case status, output
        case schemaVersion = "schema_version"
        case assemblyIdentity = "assembly_identity"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct ChapterAssemblyStatus: Codable {
    struct SegmentBlocker: Codable, Hashable {
        let segmentID: String
        let reason: String

        enum CodingKeys: String, CodingKey {
            case reason
            case segmentID = "segment_id"
        }
    }

    struct SegmentCounts: Codable {
        let expected: Int
        let produced: Int
        let approved: Int
        let blocked: Int
    }

    let schemaVersion: Int
    let state: String
    let decision: String
    let blockers: [String]
    let blockerMessage: String?
    let assemblyIdentity: String
    let target: ChapterAssemblyTarget
    let ffmpeg: ChapterAssemblyFFmpeg
    let outputPath: String?
    let manifestPath: String?
    let assembly: ChapterAssemblyManifest?
    let segmentCounts: SegmentCounts?
    let segmentBlockers: [SegmentBlocker]?
    let providerRequests: Int
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case state, decision, blockers, target, ffmpeg, assembly
        case schemaVersion = "schema_version"
        case blockerMessage = "blocker_message"
        case assemblyIdentity = "assembly_identity"
        case outputPath = "output_path"
        case manifestPath = "manifest_path"
        case segmentCounts = "segment_counts"
        case segmentBlockers = "segment_blockers"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct ChapterAssemblyEnvelope: Codable {
    let schemaVersion: Int
    let qa: AudioQACurrentEnvelope
    let assembly: ChapterAssemblyStatus
    let providerRequests: Int
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case qa, assembly
        case schemaVersion = "schema_version"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
    }
}

func audioQAStatusLabel(_ status: String) -> String {
    switch status {
    case "PASS": return "Техническая проверка пройдена"
    case "WARN": return "Нужна проверка предупреждений"
    case "FAIL": return "Технический брак"
    default: return status
    }
}

func audioQAManualLabel(_ state: String) -> String {
    switch state {
    case "UNREVIEWED": return "Не проверено"
    case "APPROVED": return "Одобрено"
    case "REJECTED": return "Отклонено"
    case "REGENERATE_REQUESTED": return "Запрошена перегенерация"
    case "STALE": return "Одобрение устарело"
    default: return state
    }
}

func audioQAWarningLabel(_ code: String) -> String {
    switch code {
    case "ffmpeg_unavailable": return "Расширенная техническая проверка недоступна"
    case "gross_clipping": return "Обнаружены участки возможного клиппинга"
    case "near_total_silence": return "Аудио почти полностью состоит из тишины"
    case "signal_metrics_unavailable": return "Расширенный анализ сигнала недоступен"
    default: return "Техническое предупреждение"
    }
}

func audioQAReasonLabel(_ code: String) -> String {
    switch code {
    case "ffmpeg_decode_failed": return "FFmpeg не смог проверить декодирование WAV"
    case "missing_file": return "Аудиофайл не найден"
    case "invalid_or_truncated_wav": return "WAV повреждён или записан не полностью"
    case "audio_changed_during_scan": return "Аудиофайл изменился во время проверки"
    default: return "Техническая проверка не пройдена"
    }
}

func chapterAssemblyStateLabel(_ state: String, decision: String) -> String {
    if decision == "ALREADY_ASSEMBLED" { return "Глава собрана" }
    if decision == "BLOCKED" { return "Требуется FFmpeg" }
    switch state {
    case "STALE": return "Сборка устарела"
    case "PREPARED": return "Готово к сборке"
    case "READY": return "Глава собрана"
    default: return "Недоступно"
    }
}

func audioQAProviderLabel(_ provider: String) -> String {
    switch provider {
    case "yandex": return "Yandex SpeechKit"
    case "openai": return "OpenAI TTS"
    case "qwen": return "Qwen · локально"
    default: return provider
    }
}

func audioQAVoiceLabel(_ profileID: String) -> String {
    switch profileID {
    case "yandex_lera": return "Lera"
    case "openai_cedar": return "Cedar"
    case "openai_onyx": return "Onyx"
    default:
        return profileID
            .split(separator: "_")
            .last
            .map { String($0).capitalized } ?? profileID
    }
}
