import Foundation

struct OneShotIntentToken: Equatable {
    fileprivate let id: UUID
}

struct ConsumedOneShotIntent {
    fileprivate init() {}
}

struct OneShotIntentGate {
    private(set) var armedToken: OneShotIntentToken?

    var isArmed: Bool { armedToken != nil }

    mutating func arm() -> OneShotIntentToken {
        let token = OneShotIntentToken(id: UUID())
        armedToken = token
        return token
    }

    mutating func consume(_ token: OneShotIntentToken?) -> ConsumedOneShotIntent? {
        guard let token, token == armedToken else { return nil }
        armedToken = nil
        return ConsumedOneShotIntent()
    }

    mutating func cancel() {
        armedToken = nil
    }
}

struct Book: Codable, Identifiable, Hashable {
    let id: String
    let slug: String?
    let title: String
    let author: String
    let authorPronunciation: String?
    let jobs: [PreparedJob]
    let kind: String?
    let enabled: Bool?
    let status: String?
    let selectedBackend: String?
    let selectedProfileID: String?
    let sourceFilename: String?
    let sourcePath: String?
    let sourceSHA256: String?
    let sourceIntegrity: String?
    let sourceImmutable: Bool?
    let sourceReadOnly: Bool?
    let ttsWorkingCopyPath: String?
    let ttsWorkingCopyStatus: String?
    let ttsWorkingCopyCurrentSHA256: String?
    let preparationStatus: String?
    let preparationRevision: Int?
    let preparationIdentity: String?
    let preparedAt: String?
    let normalizedSHA256: String?
    let chapterCount: Int?
    let preparedSegmentCount: Int?

    enum CodingKeys: String, CodingKey {
        case id, slug, title, author, jobs, kind, enabled, status
        case authorPronunciation = "author_pronunciation"
        case selectedBackend = "selected_backend"
        case selectedProfileID = "selected_profile_id"
        case sourceFilename = "source_filename"
        case sourcePath = "source_path"
        case sourceSHA256 = "source_sha256"
        case sourceIntegrity = "source_integrity"
        case sourceImmutable = "source_immutable"
        case sourceReadOnly = "source_read_only"
        case ttsWorkingCopyPath = "tts_working_copy_path"
        case ttsWorkingCopyStatus = "tts_working_copy_status"
        case ttsWorkingCopyCurrentSHA256 = "tts_working_copy_current_sha256"
        case preparationStatus = "preparation_status"
        case preparationRevision = "preparation_revision"
        case preparationIdentity = "preparation_identity"
        case preparedAt = "prepared_at"
        case normalizedSHA256 = "normalized_sha256"
        case chapterCount = "chapter_count"
        case preparedSegmentCount = "prepared_segment_count"
    }
}

struct BookTextPreparationResult: Codable {
    let schemaVersion: Int
    let bookID: String
    let slug: String
    let sourceIntegrity: String
    let workingCopySHA256: String?
    let preparationStatus: String
    let preparationRevision: Int?
    let preparationIdentity: String?
    let preparedAt: String?
    let normalizedSHA256: String?
    let chapterCount: Int
    let segmentCount: Int
    let jobs: [PreparedJob]
    let normalizedPath: String?
    let structurePath: String?
    let segmentsPath: String?
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case slug, jobs
        case schemaVersion = "schema_version"
        case bookID = "book_id"
        case sourceIntegrity = "source_integrity"
        case workingCopySHA256 = "working_copy_sha256"
        case preparationStatus = "preparation_status"
        case preparationRevision = "preparation_revision"
        case preparationIdentity = "preparation_identity"
        case preparedAt = "prepared_at"
        case normalizedSHA256 = "normalized_sha256"
        case chapterCount = "chapter_count"
        case segmentCount = "segment_count"
        case normalizedPath = "normalized_path"
        case structurePath = "structure_path"
        case segmentsPath = "segments_path"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct BookVoiceSelectionResult: Codable {
    let bookID: String
    let selectedProfileID: String
    let voice: String
    let role: String
    let speed: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case voice, role, speed
        case bookID = "book_id"
        case selectedProfileID = "selected_profile_id"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct BookImportResult: Codable {
    let bookID: String
    let slug: String
    let title: String
    let author: String
    let authorPronunciation: String?
    let sourceSHA256: String?
    let sourcePath: String
    let sourceIntegrity: String
    let ttsWorkingCopyPath: String
    let ttsWorkingCopyStatus: String
    let selectedBackend: String
    let selectedProfileID: String
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case slug, title, author
        case authorPronunciation = "author_pronunciation"
        case bookID = "book_id"
        case sourceSHA256 = "source_sha256"
        case sourcePath = "source_path"
        case sourceIntegrity = "source_integrity"
        case ttsWorkingCopyPath = "tts_working_copy_path"
        case ttsWorkingCopyStatus = "tts_working_copy_status"
        case selectedBackend = "selected_backend"
        case selectedProfileID = "selected_profile_id"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct PreparedJob: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let segmentCount: Int
    let kind: String?

    enum CodingKeys: String, CodingKey {
        case id, label, kind
        case segmentCount = "segment_count"
    }
}

struct EngineDescriptor: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let kind: String
}

struct VoiceProfile: Codable, Identifiable, Hashable {
    let profileID: String
    let provider: String
    let engine: String
    let label: String
    let voiceSource: String
    let voice: String
    let language: String
    let status: String
    let role: String?
    let speed: String?
    let model: String?
    let instructions: String?
    let responseFormat: String?
    let frozen: Bool?
    let description: String?

    var id: String { profileID }

    enum CodingKeys: String, CodingKey {
        case provider, engine, label, voice, language, status, role, speed, model
        case instructions, frozen, description
        case profileID = "profile_id"
        case voiceSource = "voice_source"
        case responseFormat = "response_format"
    }
}

struct VoiceLibrarySnapshot: Codable {
    let qwen: [VoiceProfile]
    let yandex: [VoiceProfile]
    let openai: [VoiceProfile]

    func profiles(for engine: Engine) -> [VoiceProfile] {
        switch engine {
        case .qwen: qwen
        case .yandex: yandex
        case .openai: openai
        }
    }
}

struct YandexProfile: Codable {
    let voice: String
    let role: String
    let speed: String
}

struct YandexEstimate: Codable {
    let characters: Int
    let segments: Int
    let cachedSegments: Int
    let totalBillingUnits: Int
    let billableRemainingUnits: Int
    let currency: String
    let unitPrice: String?
    let estimatedTotalCost: String?
    let estimatedRemainingCost: String?
    let priceVerifiedAt: String?
    let priceStale: Bool
    let hardLimitRub: String?
    let allowedToStart: Bool
    let blockedReason: String?

    enum CodingKeys: String, CodingKey {
        case characters, segments, currency
        case cachedSegments = "cached_segments"
        case totalBillingUnits = "total_billing_units"
        case billableRemainingUnits = "billable_remaining_units"
        case unitPrice = "unit_price"
        case estimatedTotalCost = "estimated_total_cost"
        case estimatedRemainingCost = "estimated_remaining_cost"
        case priceVerifiedAt = "price_verified_at"
        case priceStale = "price_stale"
        case hardLimitRub = "hard_limit_rub"
        case allowedToStart = "allowed_to_start"
        case blockedReason = "blocked_reason"
    }
}

struct YandexSettings: Codable {
    let hardLimitRub: String?
    enum CodingKeys: String, CodingKey { case hardLimitRub = "hard_limit_rub" }
}

struct BillingProviderMetadata: Codable {
    let billingAccountIDConfigured: Bool?
    let billingAuthContract: String?
    let minimumReadOnlyRole: String?
    let providerBalanceStatus: String?
    let providerCostsStatus: String?
    let exactPrepaidBalanceStatus: String?
    let userConfirmedBalanceSource: String?

    enum CodingKeys: String, CodingKey {
        case billingAccountIDConfigured = "billing_account_id_configured"
        case billingAuthContract = "billing_auth_contract"
        case minimumReadOnlyRole = "minimum_read_only_role"
        case providerBalanceStatus = "provider_balance_status"
        case providerCostsStatus = "provider_costs_status"
        case exactPrepaidBalanceStatus = "exact_prepaid_balance_status"
        case userConfirmedBalanceSource = "user_confirmed_balance_source"
    }
}

struct CloudBillingSnapshot: Codable {
    let schemaVersion: Int
    let provider: String
    let currency: String
    let spent: String?
    let spentSource: String
    let spentAsOf: String?
    let knownLocalActualSpend: String
    let unknownCostEvents: Int
    let remaining: String?
    let remainingSource: String
    let remainingAsOf: String?
    let currentJobEstimate: String?
    let currentJobEstimateSource: String
    let projectedRemaining: String?
    let projectedRemainingSource: String
    let freshness: String
    let status: String
    let warnings: [String]
    let lowBalanceThreshold: String?
    let hardLimit: String?
    let lastSuccessfulRefresh: String?
    let lastAttempt: String?
    let staleAfterSeconds: Int
    let providerMetadata: BillingProviderMetadata
    let paidExecutionEnabled: Bool
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case provider, currency, spent, remaining, freshness, status, warnings
        case schemaVersion = "schema_version"
        case spentSource = "spent_source"
        case spentAsOf = "spent_as_of"
        case knownLocalActualSpend = "known_local_actual_spend"
        case unknownCostEvents = "unknown_cost_events"
        case remainingSource = "remaining_source"
        case remainingAsOf = "remaining_as_of"
        case currentJobEstimate = "current_job_estimate"
        case currentJobEstimateSource = "current_job_estimate_source"
        case projectedRemaining = "projected_remaining"
        case projectedRemainingSource = "projected_remaining_source"
        case lowBalanceThreshold = "low_balance_threshold"
        case hardLimit = "hard_limit"
        case lastSuccessfulRefresh = "last_successful_refresh"
        case lastAttempt = "last_attempt"
        case staleAfterSeconds = "stale_after_seconds"
        case providerMetadata = "provider_metadata"
        case paidExecutionEnabled = "paid_execution_enabled"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct BillingProviders: Codable {
    var yandex: CloudBillingSnapshot
    var openai: CloudBillingSnapshot

    subscript(engine: Engine) -> CloudBillingSnapshot? {
        get {
            switch engine {
            case .qwen: nil
            case .yandex: yandex
            case .openai: openai
            }
        }
        set {
            guard let newValue else { return }
            switch engine {
            case .qwen: break
            case .yandex: yandex = newValue
            case .openai: openai = newValue
            }
        }
    }
}

struct CloudBillingEnvelope: Codable {
    let schemaVersion: Int
    var providers: BillingProviders
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case providers
        case schemaVersion = "schema_version"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct PaidRunPlan: Codable, Identifiable {
    let schemaVersion: Int
    let planID: String
    let planDigest: String
    let state: String
    let createdAt: String
    let expiresAt: String
    let provider: String
    let bookID: String
    let bookFile: String
    let bookTitle: String
    let jobID: String
    let jobLabel: String
    let profileID: String
    let model: String
    let voice: String
    let responseFormat: String
    let selectedSegmentID: String?
    let selectedSegmentCharacters: Int
    let selectedSegmentUtf8Bytes: Int
    let selectedSegmentNumber: Int?
    let totalSegments: Int
    let succeededSegments: Int
    let cachedSegments: Int
    let pendingSegments: Int
    let ambiguousSegments: Int
    let failedSegments: Int
    let networkMissCountForThisPlan: Int
    let maxNetworkRequests: Int
    let hardLimit: String?
    let currency: String
    let pricingVerifiedAt: String
    let pricingStale: Bool
    let credentialAvailable: Bool
    let costEstimate: String?
    let costEstimateSource: String
    let warnings: [String]
    let blockers: [String]
    let decision: String
    let billing: CloudBillingSnapshot
    let remoteRequestSent: Bool

    var id: String { planID }
    var isExpired: Bool {
        guard let date = ISO8601DateFormatter().date(from: expiresAt) else { return true }
        return date <= Date()
    }
    var canExecute: Bool {
        state == "PREPARED"
            && !isExpired
            && blockers.isEmpty
            && maxNetworkRequests == 1
            && (decision == "READY_FOR_CONFIRMATION" || decision == "CACHE_ONLY")
    }

    enum CodingKeys: String, CodingKey {
        case provider, voice, currency, warnings, blockers, decision, billing, state, model
        case schemaVersion = "schema_version"
        case planID = "plan_id"
        case planDigest = "plan_digest"
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case bookID = "book_id"
        case bookFile = "book_file"
        case bookTitle = "book_title"
        case jobID = "job_id"
        case jobLabel = "job_label"
        case profileID = "profile_id"
        case responseFormat = "response_format"
        case selectedSegmentID = "selected_segment_id"
        case selectedSegmentCharacters = "selected_segment_characters"
        case selectedSegmentUtf8Bytes = "selected_segment_utf8_bytes"
        case selectedSegmentNumber = "selected_segment_number"
        case totalSegments = "total_segments"
        case succeededSegments = "succeeded_segments"
        case cachedSegments = "cached_segments"
        case pendingSegments = "pending_segments"
        case ambiguousSegments = "ambiguous_segments"
        case failedSegments = "failed_segments"
        case networkMissCountForThisPlan = "network_miss_count_for_this_plan"
        case maxNetworkRequests = "max_network_requests"
        case hardLimit = "hard_limit"
        case pricingVerifiedAt = "pricing_verified_at"
        case pricingStale = "pricing_stale"
        case credentialAvailable = "credential_available"
        case costEstimate = "cost_estimate"
        case costEstimateSource = "cost_estimate_source"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct PaidRunExecutionResult: Codable {
    let planID: String
    let state: String
    let decision: String
    let manifest: String
    let networkRequests: Int
    let selectedSegmentID: String?
    let outputPath: String?
    let qaTargets: [OpenAIQATarget]?
    let manifestState: String
    let remainingSegments: Int
    let automaticRetryCount: Int
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case state, decision, manifest
        case planID = "plan_id"
        case networkRequests = "network_requests"
        case selectedSegmentID = "selected_segment_id"
        case outputPath = "output_path"
        case qaTargets = "qa_targets"
        case manifestState = "manifest_state"
        case remainingSegments = "remaining_segments"
        case automaticRetryCount = "automatic_retry_count"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct OpenAIQATarget: Codable, Identifiable, Equatable {
    let segmentID: String
    let outputPath: String
    let manifestPath: String
    let synthesisFingerprint: String

    var id: String { segmentID }

    enum CodingKeys: String, CodingKey {
        case segmentID = "segment_id"
        case outputPath = "output_path"
        case manifestPath = "manifest_path"
        case synthesisFingerprint = "synthesis_fingerprint"
    }
}

struct OpenAIQATargetList: Codable {
    let schemaVersion: Int
    let qaTargets: [OpenAIQATarget]
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case qaTargets = "qa_targets"
        case remoteRequestSent = "remote_request_sent"
    }
}

func audioQASelectionMatches(
    selectedBook: Book?,
    selectedJobID: String,
    selectedProfileID: String,
    authority: AudioQAAuthority
) -> Bool {
    selectedBook?.slug == authority.bookSlug
        && selectedJobID == authority.jobID
        && selectedProfileID == authority.profileID
}

struct YandexChapterRunPlan: Codable, Identifiable {
    let schemaVersion: Int
    let planID: String
    let planDigest: String
    let state: String
    let createdAt: String
    let expiresAt: String
    let provider: String
    let bookID: String
    let bookFile: String
    let bookTitle: String
    let jobID: String
    let jobLabel: String
    let profileID: String
    let voice: String
    let role: String
    let speed: String
    let characters: Int
    let totalSegments: Int
    let cachedSegments: Int
    let maxNetworkRequests: Int
    let estimatedRemainingCost: String?
    let hardLimit: String?
    let currency: String
    let pricingVerifiedAt: String?
    let pricingStale: Bool
    let credentialAvailable: Bool
    let warnings: [String]
    let blockers: [String]
    let decision: String
    let billing: CloudBillingSnapshot
    let remoteRequestSent: Bool

    var id: String { planID }
    var isExpired: Bool {
        guard let date = ISO8601DateFormatter().date(from: expiresAt) else { return true }
        return date <= Date()
    }
    var canExecute: Bool {
        state == "PREPARED"
            && !isExpired
            && blockers.isEmpty
            && (decision == "READY_FOR_CONFIRMATION" || decision == "CACHE_ONLY")
    }

    enum CodingKeys: String, CodingKey {
        case provider, voice, role, speed, characters, currency, warnings, blockers, decision, billing, state
        case schemaVersion = "schema_version"
        case planID = "plan_id"
        case planDigest = "plan_digest"
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case bookID = "book_id"
        case bookFile = "book_file"
        case bookTitle = "book_title"
        case jobID = "job_id"
        case jobLabel = "job_label"
        case profileID = "profile_id"
        case totalSegments = "total_segments"
        case cachedSegments = "cached_segments"
        case maxNetworkRequests = "max_network_requests"
        case estimatedRemainingCost = "estimated_remaining_cost"
        case hardLimit = "hard_limit"
        case pricingVerifiedAt = "pricing_verified_at"
        case pricingStale = "pricing_stale"
        case credentialAvailable = "credential_available"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct YandexChapterRunResult: Codable {
    let schemaVersion: Int
    let planID: String
    let state: String
    let decision: String
    let manifest: String
    let outputPath: String
    let networkRequests: Int
    let maxNetworkRequests: Int
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case state, decision, manifest
        case schemaVersion = "schema_version"
        case planID = "plan_id"
        case outputPath = "output_path"
        case networkRequests = "network_requests"
        case maxNetworkRequests = "max_network_requests"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct YandexChapterProblemSegment: Codable, Identifiable {
    let segmentID: String
    let segmentNumber: Int
    let text: String
    let status: String
    let requestID: String?
    let message: String?
    let retryApproved: Bool

    var id: String { segmentID }

    enum CodingKeys: String, CodingKey {
        case text, status, message
        case segmentID = "segment_id"
        case segmentNumber = "segment_number"
        case requestID = "request_id"
        case retryApproved = "retry_approved"
    }
}

struct YandexChapterProgress: Codable {
    let schemaVersion: Int
    let provider: String
    let bookID: String
    let jobID: String
    let profileID: String
    let manifestPath: String
    let manifestExists: Bool
    let totalSegments: Int
    let completedSegments: Int
    let cachedSegments: Int
    let pendingSegments: Int
    let ambiguousSegments: [YandexChapterProblemSegment]
    let failedSegments: [YandexChapterProblemSegment]
    let chapterReady: Bool
    let providerRequests: Int
    let remoteRequestSent: Bool
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case provider
        case schemaVersion = "schema_version"
        case bookID = "book_id"
        case jobID = "job_id"
        case profileID = "profile_id"
        case manifestPath = "manifest_path"
        case manifestExists = "manifest_exists"
        case totalSegments = "total_segments"
        case completedSegments = "completed_segments"
        case cachedSegments = "cached_segments"
        case pendingSegments = "pending_segments"
        case ambiguousSegments = "ambiguous_segments"
        case failedSegments = "failed_segments"
        case chapterReady = "chapter_ready"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct YandexRetryApprovalResult: Codable {
    let schemaVersion: Int
    let provider: String
    let bookID: String
    let jobID: String
    let profileID: String
    let segmentID: String
    let state: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case provider, state
        case schemaVersion = "schema_version"
        case bookID = "book_id"
        case jobID = "job_id"
        case profileID = "profile_id"
        case segmentID = "segment_id"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct StudioSnapshot: Codable {
    let workspaceRoot: String
    let engines: [EngineDescriptor]
    let books: [Book]
    let voiceLibrary: VoiceLibrarySnapshot
    let yandexProfile: YandexProfile
    let yandexEstimate: YandexEstimate
    let yandexSettings: YandexSettings
    let cloudBilling: CloudBillingEnvelope
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case engines, books
        case workspaceRoot = "workspace_root"
        case voiceLibrary = "voice_library"
        case yandexProfile = "yandex_profile"
        case yandexEstimate = "yandex_estimate"
        case yandexSettings = "yandex_settings"
        case cloudBilling = "cloud_billing"
        case remoteRequestSent = "remote_request_sent"
    }
}

enum Engine: String, CaseIterable, Codable, Identifiable {
    case qwen
    case yandex
    case openai

    var id: String { rawValue }

    var title: String {
        switch self {
        case .qwen: "Qwen — локально"
        case .yandex: "Yandex SpeechKit — облако"
        case .openai: "OpenAI TTS — облако"
        }
    }

    var isCloud: Bool { self != .qwen }
}

func provenanceLabel(_ source: String) -> String {
    switch source {
    case "provider_reported": "Данные провайдера"
    case "local_actual": "Учтено Studio"
    case "local_estimate": "Расчёт Studio"
    case "user_confirmed": "Указано пользователем"
    default: "Нет данных"
    }
}

func formattedMoney(_ value: String?, currency: String, source: String) -> String {
    guard let value, let amount = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")) else {
        return "Недоступно"
    }
    let formatter = NumberFormatter()
    formatter.numberStyle = .decimal
    formatter.minimumFractionDigits = 2
    formatter.maximumFractionDigits = 2
    formatter.locale = currency == "RUB" ? Locale(identifier: "ru_RU") : Locale(identifier: "en_US")
    let number = formatter.string(from: amount as NSDecimalNumber) ?? value
    let rendered = currency == "RUB" ? "\(number) ₽" : currency == "USD" ? "$\(number)" : "\(number) \(currency)"
    return source == "local_estimate" ? "≈\(rendered)" : rendered
}

func freshnessLabel(_ billing: CloudBillingSnapshot) -> String {
    if billing.freshness == "stale" { return "Данные устарели" }
    if let date = billing.lastSuccessfulRefresh ?? billing.remainingAsOf {
        return "Обновлено: \(formattedTimestamp(date))"
    }
    return "Данные провайдера ещё не получены"
}

func formattedTimestamp(_ value: String) -> String {
    let parser = ISO8601DateFormatter()
    guard let date = parser.date(from: value) else { return value }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "ru_RU")
    formatter.dateStyle = .short
    formatter.timeStyle = .short
    return formatter.string(from: date)
}

func billingWarningLabel(_ warning: String) -> String {
    switch warning {
    case "remaining_unavailable": "Остаток недоступен."
    case "provider_balance_stale": "Последние данные об остатке устарели."
    case "provider_costs_stale": "Данные о расходах провайдера устарели."
    case "local_actual_spend_incomplete": "Не для всех запросов известна точная стоимость."
    case "openai_local_spend_since_confirmation_incomplete": "Расчётный остаток OpenAI невозможен: есть запросы с неизвестной стоимостью."
    case "openai_balance_may_exclude_usage_outside_audiobook_studio": "Расчёт может не учитывать использование OpenAI вне Audiobook Studio."
    case "user_confirmed_balance_stale": "Указанный пользователем остаток устарел."
    case "low_balance": "Остаток ниже заданного порога."
    case "projected_low_balance": "После запуска остаток может стать ниже заданного порога."
    default: warning
    }
}

func billingAvailabilityReason(_ billing: CloudBillingSnapshot) -> String? {
    if billing.provider == "openai" && billing.remaining == nil {
        return "Точный prepaid-остаток OpenAI недоступен через поддерживаемый contract."
    }
    switch billing.providerMetadata.providerBalanceStatus {
    case "billing_account_id_missing": return "Не настроен Yandex billing account ID."
    case "billing_iam_credential_unavailable": return "Нет отдельного Yandex Billing IAM credential."
    case "billing_permission_unavailable": return "Нет read-only доступа к Yandex Billing API."
    case "billing_network_error": return "Не удалось обновить данные Yandex Billing."
    case "unavailable": return "Данные Yandex Billing пока недоступны."
    default: return nil
    }
}

func paidRunBlockerLabel(_ blockers: [String]) -> String {
    if blockers.contains("ambiguous_segment_requires_resolution") {
        return "Результат запроса не определён. Автоматический повтор запрещён."
    }
    if blockers.contains("failed_segment_requires_resolution") {
        return "Неустранённая ошибка сегмента блокирует запуск."
    }
    if blockers.contains("missing_credential") {
        return "Ключ OpenAI недоступен в macOS Keychain."
    }
    if blockers.contains("stale_pricing") { return "Данные о тарифе OpenAI устарели." }
    if blockers.contains("missing_hard_limit") || blockers.contains("hard_limit_not_positive") {
        return "Задайте положительный лимит политики Studio для OpenAI."
    }
    return "Платный запуск заблокирован проверками безопасности."
}

func yandexChapterBlockerLabel(_ blockers: [String]) -> String {
    if blockers.contains("ambiguous_segment_requires_resolution") {
        return "Результат Yandex-запроса не определён. Автоматический повтор запрещён."
    }
    if blockers.contains("failed_segment_requires_resolution") {
        return "Неустранённая ошибка сегмента блокирует производство главы."
    }
    if blockers.contains("missing_credential") {
        return "Ключ Yandex SpeechKit недоступен в macOS Keychain."
    }
    if blockers.contains("stale_tariff") { return "Тариф Yandex требует проверки." }
    if blockers.contains("missing_tariff") { return "Тариф Yandex не настроен." }
    if blockers.contains("missing_hard_limit") || blockers.contains("hard_limit_exceeded") {
        return "Проверьте лимит стоимости задачи Yandex в Настройках."
    }
    if blockers.contains("chapter_request_cap_exceeded") {
        return "Глава превышает безопасный лимит запросов V1 и должна быть разделена."
    }
    if blockers.contains("insufficient_balance") { return "Остатка Yandex недостаточно для этой главы." }
    return "Производство главы заблокировано проверками безопасности."
}
