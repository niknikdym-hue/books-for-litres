import Foundation

struct Book: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let author: String
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
