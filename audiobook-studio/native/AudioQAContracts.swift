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

    enum CodingKeys: String, CodingKey {
        case available, reason
        case peakFraction = "peak_fraction"
        case clippedFraction = "clipped_fraction"
        case nearSilenceFraction = "near_silence_fraction"
    }
}

struct AudioQAFFmpegFacts: Codable, Equatable {
    let status: String
    let available: Bool
    let exitCode: Int?

    enum CodingKeys: String, CodingKey {
        case status, available
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
        case manualState = "manual_state"
        case downstreamEligible = "downstream_eligible"
        case scannedAt = "scanned_at"
        case manualDecidedAt = "manual_decided_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
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
