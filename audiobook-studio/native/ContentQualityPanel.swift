import Foundation
import SwiftUI

private struct ContentQualityWorkspaceContract: Decodable {
    let workspaceRoot: String
    enum CodingKeys: String, CodingKey { case workspaceRoot = "workspace_root" }
}

private struct ContentQualityLocalPaths {
    let root: URL
    var runtimeRoot: URL { root.appendingPathComponent("runtime/studio-workspace", isDirectory: true) }
    var qwenPython: URL { root.appendingPathComponent("engines/qwen-mlx/.venv/bin/python") }

    static func load() -> ContentQualityLocalPaths {
        let environment = ProcessInfo.processInfo.environment
        if let override = environment["AUDIOBOOK_STUDIO_HOME"], !override.isEmpty {
            return ContentQualityLocalPaths(root: URL(fileURLWithPath: override, isDirectory: true))
        }
        let defaultRoot = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/New project/Audiobook-Studio", isDirectory: true)
        let contractURL = environment["AUDIOBOOK_STUDIO_PATH_CONTRACT"]
            .map { URL(fileURLWithPath: $0) }
            ?? defaultRoot.appendingPathComponent("settings/workspace-paths.json")
        if let data = try? Data(contentsOf: contractURL),
           let contract = try? JSONDecoder().decode(ContentQualityWorkspaceContract.self, from: data),
           !contract.workspaceRoot.isEmpty {
            return ContentQualityLocalPaths(
                root: URL(fileURLWithPath: contract.workspaceRoot, isDirectory: true)
            )
        }
        return ContentQualityLocalPaths(root: defaultRoot)
    }
}

private let contentQualityPaths = ContentQualityLocalPaths.load()
private let contentQualityPython = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_PYTHON"]
    ?? contentQualityPaths.qwenPython.path

struct ContentQualityRule: Codable, Identifiable, Hashable {
    let ruleID: String
    let value: String
    let matchType: String
    let action: String
    let profiles: [String]
    let origin: String
    let rationale: String?

    var id: String { ruleID }

    enum CodingKeys: String, CodingKey {
        case value, action, profiles, origin, rationale
        case ruleID = "rule_id"
        case matchType = "match_type"
    }
}

struct ContentQualityFinding: Codable, Identifiable, Hashable {
    let ruleID: String
    let matchedText: String
    let start: Int
    let end: Int
    let line: Int
    let column: Int
    let action: String
    let profile: String
    let origin: String
    let rationale: String?
    let textSHA256: String
    let resolved: Bool
    let resolutionID: String?

    var id: String {
        "\(profile)|\(ruleID)|\(start)|\(end)|\(textSHA256)"
    }

    enum CodingKeys: String, CodingKey {
        case start, end, line, column, action, profile, origin, rationale, resolved
        case ruleID = "rule_id"
        case matchedText = "matched_text"
        case textSHA256 = "text_sha256"
        case resolutionID = "resolution_id"
    }
}

struct ContentQualityScan: Codable, Hashable {
    let state: String
    let textSHA256: String
    let findings: [ContentQualityFinding]
    let blockingFindings: [ContentQualityFinding]
    let warningFindings: [ContentQualityFinding]
    let resolvedFindings: [ContentQualityFinding]
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case state, findings
        case textSHA256 = "text_sha256"
        case blockingFindings = "blocking_findings"
        case warningFindings = "warning_findings"
        case resolvedFindings = "resolved_findings"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct ContentQualityBookEnvelope: Codable, Hashable {
    let state: String
    let bookSlug: String
    let workingCopySHA256: String
    let normalizedSHA256: String
    let gateFingerprint: String
    let editorial: ContentQualityScan
    let technical: ContentQualityScan
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case state, editorial, technical
        case bookSlug = "book_slug"
        case workingCopySHA256 = "working_copy_sha256"
        case normalizedSHA256 = "normalized_sha256"
        case gateFingerprint = "gate_fingerprint"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct ContentQualityUserStoreStatus: Codable, Hashable {
    let path: String
    let exists: Bool
    let revision: Int
    let sha256: String
    let entries: Int
}

struct ContentQualityStatusEnvelope: Codable, Hashable {
    let contractVersion: String
    let schemaSHA256: String
    let corePackSHA256: String
    let technicalPackSHA256: String
    let coreEntries: [ContentQualityRule]
    let technicalEntries: [ContentQualityRule]
    let userStore: ContentQualityUserStoreStatus
    let userEntries: [ContentQualityRule]
    let lexiconFingerprint: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version"
        case schemaSHA256 = "schema_sha256"
        case corePackSHA256 = "core_pack_sha256"
        case technicalPackSHA256 = "technical_pack_sha256"
        case coreEntries = "core_entries"
        case technicalEntries = "technical_entries"
        case userStore = "user_store"
        case userEntries = "user_entries"
        case lexiconFingerprint = "lexicon_fingerprint"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct TTSTextManualReviewStatus: Codable, Hashable {
    let required: Bool
    let accepted: Bool
    let ready: Bool
    let acceptedSHA256: String?
    let acceptedAt: String?

    enum CodingKeys: String, CodingKey {
        case required, accepted, ready
        case acceptedSHA256 = "accepted_sha256"
        case acceptedAt = "accepted_at"
    }
}

struct TTSPronunciationEntry: Codable, Identifiable, Hashable {
    let overrideID: String
    let scope: String
    let word: String
    let vowelNumber: Int
    let display: String
    let start: Int?
    let end: Int?
    let textSHA256: String?
    let createdAt: String
    let actor: String

    var id: String { overrideID }

    enum CodingKeys: String, CodingKey {
        case scope, word, display, start, end, actor
        case overrideID = "override_id"
        case vowelNumber = "vowel_number"
        case textSHA256 = "text_sha256"
        case createdAt = "created_at"
    }
}

struct TTSTextReviewEnvelope: Codable, Hashable {
    let bookID: String
    let workingCopyPath: String
    let workingCopySHA256: String
    let workingCopyRevision: Int
    let text: String
    let manualReview: TTSTextManualReviewStatus
    let pronunciationRevision: Int
    let pronunciationEntries: [TTSPronunciationEntry]
    let preparationStatus: String?
    let selectedBackend: String
    let selectedProfileID: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case text
        case bookID = "book_id"
        case workingCopyPath = "working_copy_path"
        case workingCopySHA256 = "working_copy_sha256"
        case workingCopyRevision = "working_copy_revision"
        case manualReview = "manual_review"
        case pronunciationRevision = "pronunciation_revision"
        case pronunciationEntries = "pronunciation_entries"
        case preparationStatus = "preparation_status"
        case selectedBackend = "selected_backend"
        case selectedProfileID = "selected_profile_id"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct TTSOfflineEnvelope: Codable {
    let confirmationMessage: String?
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case confirmationMessage = "confirmation_message"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct TTSStressCandidate: Codable, Identifiable, Hashable {
    let vowelNumber: Int
    let characterIndex: Int
    let display: String
    let yandex: String

    var id: Int { vowelNumber }

    enum CodingKeys: String, CodingKey {
        case display, yandex
        case vowelNumber = "vowel_number"
        case characterIndex = "character_index"
    }
}

struct TTSStressCandidatesEnvelope: Codable {
    let word: String
    let candidates: [TTSStressCandidate]
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case word, candidates
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct TTSStressPreviewEnvelope: Codable, Hashable {
    let engine: String
    let word: String
    let vowelNumber: Int
    let display: String
    let providerMode: String
    let providerValue: String
    let explanation: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case engine, word, display, explanation
        case vowelNumber = "vowel_number"
        case providerMode = "provider_mode"
        case providerValue = "provider_value"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

private struct ContentQualityErrorEnvelope: Codable {
    let state: String?
    let blockers: [String]?
    let message: String?
}

private enum ContentQualityBridgeError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        if case let .message(value) = self { return value }
        return nil
    }
}

enum ContentQualityRuleAction: String, CaseIterable, Identifiable {
    case block = "BLOCK"
    case warn = "WARN"

    var id: String { rawValue }
    var label: String {
        self == .block ? "BLOCK — запрещать при написании" : "WARN — предупреждать"
    }
}

enum ContentQualityRuleScope: String, CaseIterable, Identifiable {
    case shared = "shared"
    case bookOnly = "book-only"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .shared: "BOOK OS + Audiobook Studio"
        case .bookOnly: "Только BOOK OS"
        }
    }

    var bridgeValue: String {
        switch self {
        case .shared: "BOOK_PROSE,AUDIOBOOK_PRE_SYNTHESIS"
        case .bookOnly: "BOOK_PROSE"
        }
    }
}

@MainActor
final class ContentQualityController: ObservableObject {
    @Published private(set) var status: ContentQualityStatusEnvelope?
    @Published private(set) var bookScan: ContentQualityBookEnvelope?
    @Published private(set) var ttsReview: TTSTextReviewEnvelope?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    @Published var newRuleValue = ""
    @Published var newRuleAction: ContentQualityRuleAction = .block
    @Published var newRuleScope: ContentQualityRuleScope = .shared
    @Published var manualJunkSearchEnabled = false
    @Published var workingTextDraft = ""
    @Published var stressWord = "" {
        didSet {
            guard stressWord != oldValue else { return }
            stressSelectionGeneration &+= 1
            stressCandidates = []
            stressPreview = nil
        }
    }
    @Published private(set) var stressCandidates: [TTSStressCandidate] = []
    @Published private(set) var stressPreview: TTSStressPreviewEnvelope?
    @Published private(set) var pronunciationSaveNotice: String?
    @Published private(set) var pronunciationDictionary: PronunciationDictionarySnapshot?
    @Published private(set) var isPronunciationDictionaryLoading = false
    @Published var pronunciationDictionarySearch = ""
    @Published var pronunciationDictionaryError: String?
    @Published var resolutionReason = ""
    @Published var findingForResolution: ContentQualityFinding?

    private var currentBookID = ""
    private var draftBookID = ""
    private var draftBaseSHA = ""
    private var stressSelectionGeneration = 0

    var workingTextHasUnsavedChanges: Bool {
        guard let review = ttsReview else { return false }
        return workingTextDraft != review.text
    }

    var filteredPronunciationDictionaryEntries: [PronunciationDictionaryEntry] {
        let query = pronunciationDictionarySearch
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
        let entries = pronunciationDictionary?.entries ?? []
        guard !query.isEmpty else { return entries }
        return entries.filter { entry in
            let values = [entry.word, entry.preferred?.display]
                + entry.variants.map(\.display)
            return values.compactMap { $0 }
                .contains { value in
                    value.folding(
                        options: [.caseInsensitive, .diacriticInsensitive],
                        locale: .current
                    ).contains(query)
                }
        }
    }

    func reloadPronunciationDictionary() async {
        isPronunciationDictionaryLoading = true
        defer { isPronunciationDictionaryLoading = false }
        do {
            let result: PronunciationDictionarySnapshot = try await runJSON(
                script: "audiobook_studio_app_runner.py",
                arguments: ["--pronunciation-dictionary-list"]
            )
            try assertOffline(result)
            pronunciationDictionary = result
            pronunciationDictionaryError = nil
        } catch {
            pronunciationDictionaryError = error.localizedDescription
        }
    }

    func setPreferredPronunciation(
        _ variant: PronunciationDictionaryVariant,
        for entry: PronunciationDictionaryEntry
    ) {
        mutatePronunciationDictionary([
            "--pronunciation-dictionary-set-preferred",
            "--entry-id", entry.entryID,
            "--vowel-number", String(variant.vowelNumber),
        ])
    }

    func disablePronunciation(_ entry: PronunciationDictionaryEntry) {
        mutatePronunciationDictionary([
            "--pronunciation-dictionary-disable",
            "--entry-id", entry.entryID,
        ])
    }

    func deletePronunciation(_ entry: PronunciationDictionaryEntry) {
        mutatePronunciationDictionary([
            "--pronunciation-dictionary-delete",
            "--entry-id", entry.entryID,
        ])
    }

    private func mutatePronunciationDictionary(_ arguments: [String]) {
        Task {
            isPronunciationDictionaryLoading = true
            defer { isPronunciationDictionaryLoading = false }
            do {
                let result: PronunciationDictionaryMutationResult = try await runJSON(
                    script: "audiobook_studio_app_runner.py",
                    arguments: arguments
                )
                try assertOffline(result)
                await reloadPronunciationDictionary()
            } catch {
                pronunciationDictionaryError = error.localizedDescription
            }
        }
    }

    func reload(bookID: String = "") async {
        if currentBookID != bookID {
            pronunciationSaveNotice = nil
        }
        currentBookID = bookID
        isLoading = true
        defer { isLoading = false }
        do {
            let loadedStatus: ContentQualityStatusEnvelope = try await runJSON(
                script: "content_quality_runner.py",
                arguments: ["--status"]
            )
            try assertOffline(loadedStatus)
            status = loadedStatus
            if !bookID.isEmpty {
                let review: TTSTextReviewEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: ["--status", "--book", bookID]
                )
                try assertOffline(review)
                ttsReview = review
                if draftBookID != bookID || draftBaseSHA != review.workingCopySHA256 {
                    workingTextDraft = review.text
                    draftBookID = bookID
                    draftBaseSHA = review.workingCopySHA256
                }
                var scanArguments = ["--scan-book", "--book", bookID]
                if manualJunkSearchEnabled {
                    scanArguments.append("--include-editorial")
                }
                let scan: ContentQualityBookEnvelope = try await runJSON(
                    script: "content_quality_runner.py",
                    arguments: scanArguments
                )
                try assertOffline(scan)
                bookScan = scan
            } else {
                ttsReview = nil
                bookScan = nil
                workingTextDraft = ""
                draftBookID = ""
                draftBaseSHA = ""
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setManualJunkSearchEnabled(_ enabled: Bool) {
        manualJunkSearchEnabled = enabled
        Task { await reload(bookID: currentBookID) }
    }

    func addUserRule() {
        let value = newRuleValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            errorMessage = "Введите слово или фразу. REGEX для пользовательских правил недоступен."
            return
        }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: ContentQualityMutationEnvelope = try await runJSON(
                    script: "content_quality_runner.py",
                    arguments: [
                        "--add-user-rule",
                        "--value", value,
                        "--action", newRuleAction.rawValue,
                        "--profiles", newRuleScope.bridgeValue,
                    ]
                )
                try assertOffline(result)
                newRuleValue = ""
                await reload(bookID: currentBookID)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func removeUserRule(_ rule: ContentQualityRule) {
        guard rule.origin == "USER" else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: ContentQualityMutationEnvelope = try await runJSON(
                    script: "content_quality_runner.py",
                    arguments: ["--remove-user-rule", "--rule-id", rule.ruleID]
                )
                try assertOffline(result)
                await reload(bookID: currentBookID)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func saveWorkingCopy(onSaved: (@MainActor () -> Void)? = nil) {
        guard let review = ttsReview, !currentBookID.isEmpty else { return }
        guard !workingTextDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = "Рабочий текст озвучки не может быть пустым."
            return
        }
        Task {
            isLoading = true
            defer { isLoading = false }
            let temporary = FileManager.default.temporaryDirectory
                .appendingPathComponent("audiobook-studio-text-\(UUID().uuidString).txt")
            do {
                try workingTextDraft.write(to: temporary, atomically: true, encoding: .utf8)
                defer { try? FileManager.default.removeItem(at: temporary) }
                let result: TTSOfflineEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: [
                        "--save-working-copy",
                        "--book", currentBookID,
                        "--input-file", temporary.path,
                        "--expected-sha256", review.workingCopySHA256,
                    ]
                )
                try assertOffline(result)
                draftBaseSHA = ""
                await reload(bookID: currentBookID)
                onSaved?()
            } catch {
                try? FileManager.default.removeItem(at: temporary)
                errorMessage = error.localizedDescription
            }
        }
    }

    func discardWorkingCopyDraft() {
        guard let review = ttsReview else { return }
        workingTextDraft = review.text
    }

    func setManualReviewRequired(_ required: Bool) {
        guard !currentBookID.isEmpty else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: TTSOfflineEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: [
                        "--set-manual-review-required",
                        "--book", currentBookID,
                        "--required", required ? "true" : "false",
                    ]
                )
                try assertOffline(result)
                await reload(bookID: currentBookID)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func acceptCurrentWorkingCopy() {
        guard !currentBookID.isEmpty, !workingTextHasUnsavedChanges else {
            if workingTextHasUnsavedChanges {
                errorMessage = "Сначала сохраните правки текста, затем примите текущую версию."
            }
            return
        }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: TTSOfflineEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: ["--accept-current-working-copy", "--book", currentBookID]
                )
                try assertOffline(result)
                await reload(bookID: currentBookID)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func loadStressCandidates() {
        let word = stressWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !word.isEmpty else {
            errorMessage = "Введите одно слово, в котором нужно указать ударение."
            return
        }
        let selectionGeneration = stressSelectionGeneration
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: TTSStressCandidatesEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: ["--stress-candidates", "--word", word]
                )
                try assertOffline(result)
                guard selectionGeneration == stressSelectionGeneration,
                      word == stressWord.trimmingCharacters(in: .whitespacesAndNewlines) else { return }
                stressCandidates = result.candidates
                stressPreview = nil
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func previewStress(_ candidate: TTSStressCandidate) {
        let word = stressWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !word.isEmpty else { return }
        let selectionGeneration = stressSelectionGeneration
        let engine = ttsReview?.selectedBackend.isEmpty == false
            ? (ttsReview?.selectedBackend ?? "yandex")
            : "yandex"
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: TTSStressPreviewEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: [
                        "--stress-preview",
                        "--word", word,
                        "--vowel-number", String(candidate.vowelNumber),
                        "--engine", engine,
                    ]
                )
                try assertOffline(result)
                guard selectionGeneration == stressSelectionGeneration,
                      word == stressWord.trimmingCharacters(in: .whitespacesAndNewlines) else { return }
                stressPreview = result
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func saveStressForBook() {
        let word = stressWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let preview = stressPreview,
              preview.word == word,
              !currentBookID.isEmpty else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: TTSOfflineEnvelope = try await runJSON(
                    script: "tts_text_review_runner.py",
                    arguments: [
                        "--add-pronunciation-override",
                        "--book", currentBookID,
                        "--word", preview.word,
                        "--vowel-number", String(preview.vowelNumber),
                        "--scope", "BOOK",
                    ]
                )
                try assertOffline(result)
                stressWord = ""
                await reload(bookID: currentBookID)
                pronunciationSaveNotice = result.confirmationMessage
                    ?? "Ударение сохранено в книге и добавлено в общий словарь."
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func requestResolution(_ finding: ContentQualityFinding) {
        guard finding.profile == "AUDIOBOOK_TTS_TECHNICAL",
              finding.action == "BLOCK", !finding.resolved else { return }
        resolutionReason = ""
        findingForResolution = finding
    }

    func cancelResolution() {
        findingForResolution = nil
        resolutionReason = ""
    }

    func confirmResolution() {
        guard let finding = findingForResolution, !currentBookID.isEmpty else { return }
        let reason = resolutionReason.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !reason.isEmpty else {
            errorMessage = "Для исключения укажите причину. Оно будет связано только с текущим SHA текста."
            return
        }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let result: ContentQualityResolutionEnvelope = try await runJSON(
                    script: "content_quality_runner.py",
                    arguments: [
                        "--resolve-finding",
                        "--book", currentBookID,
                        "--rule-id", finding.ruleID,
                        "--profile", finding.profile,
                        "--reason", reason,
                    ]
                )
                try assertOffline(result)
                findingForResolution = nil
                resolutionReason = ""
                await reload(bookID: currentBookID)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func assertOffline(_ value: ContentQualityStatusEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Контроль текста нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: ContentQualityBookEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Проверка текста нарушила offline contract.")
        }
    }

    private func assertOffline(_ value: ContentQualityMutationEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Изменение словаря нарушило offline contract.")
        }
    }

    private func assertOffline(_ value: ContentQualityResolutionEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Человеческое исключение нарушило offline contract.")
        }
    }

    private func assertOffline(_ value: TTSTextReviewEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Редактор текста нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: TTSOfflineEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Редактор текста нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: TTSStressCandidatesEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Подбор ударения нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: TTSStressPreviewEnvelope) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Подбор ударения нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: PronunciationDictionarySnapshot) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Словарь ударений нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: PronunciationDictionaryMutationResult) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw ContentQualityBridgeError.message("Изменение словаря ударений нарушило offline contract.")
        }
    }

    private func runText(script: String, arguments: [String]) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: contentQualityPython)
            process.arguments = [
                contentQualityPaths.runtimeRoot.appendingPathComponent(script).path
            ] + arguments
            let captureDirectory = FileManager.default.temporaryDirectory
                .appendingPathComponent("audiobook-studio-content-\(UUID().uuidString)", isDirectory: true)
            try FileManager.default.createDirectory(at: captureDirectory, withIntermediateDirectories: false)
            defer { try? FileManager.default.removeItem(at: captureDirectory) }
            let stdoutURL = captureDirectory.appendingPathComponent("stdout.json")
            let stderrURL = captureDirectory.appendingPathComponent("stderr.txt")
            FileManager.default.createFile(atPath: stdoutURL.path, contents: nil)
            FileManager.default.createFile(atPath: stderrURL.path, contents: nil)
            let stdout = try FileHandle(forWritingTo: stdoutURL)
            let stderr = try FileHandle(forWritingTo: stderrURL)
            process.standardOutput = stdout
            process.standardError = stderr
            try process.run()
            process.waitUntilExit()
            try stdout.close()
            try stderr.close()
            let output = String(decoding: try Data(contentsOf: stdoutURL), as: UTF8.self)
            let diagnostic = String(decoding: try Data(contentsOf: stderrURL), as: UTF8.self)
            guard process.terminationStatus == 0 else {
                if let data = output.data(using: .utf8),
                   let envelope = try? JSONDecoder().decode(ContentQualityErrorEnvelope.self, from: data) {
                    let codes = envelope.blockers?.joined(separator: ", ") ?? "offline_bridge_blocked"
                    throw ContentQualityBridgeError.message(
                        envelope.message ?? "Операция заблокирована: \(codes)"
                    )
                }
                throw ContentQualityBridgeError.message(
                    diagnostic.isEmpty ? "Локальная операция завершилась с ошибкой." : diagnostic
                )
            }
            return output
        }.value
    }

    private func runJSON<T: Decodable>(script: String, arguments: [String]) async throws -> T {
        let text = try await runText(script: script, arguments: arguments)
        return try JSONDecoder().decode(T.self, from: Data(text.utf8))
    }
}

struct ContentQualityMutationEnvelope: Codable {
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct ContentQualityResolutionEnvelope: Codable {
    let state: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case state
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

struct PronunciationDictionaryView: View {
    @ObservedObject var controller: ContentQualityController
    @Environment(\.dismiss) private var dismiss
    @State private var entryPendingDeletion: PronunciationDictionaryEntry?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Словарь ударений")
                        .font(.title2.weight(.semibold))
                    Text("Studio запоминает ваши исправления и использует их в следующих книгах.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Готово") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }

            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Найти слово", text: $controller.pronunciationDictionarySearch)
                    .textFieldStyle(.plain)
                Spacer()
                Text(entryCountText)
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            .padding(10)
            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))

            if controller.isPronunciationDictionaryLoading,
               controller.pronunciationDictionary == nil {
                Spacer()
                ProgressView("Открывается словарь…")
                    .frame(maxWidth: .infinity)
                Spacer()
            } else if controller.filteredPronunciationDictionaryEntries.isEmpty {
                Spacer()
                ContentUnavailableView {
                    Label(
                        controller.pronunciationDictionarySearch.isEmpty
                            ? "Словарь пока пуст"
                            : "Ничего не найдено",
                        systemImage: "character.book.closed"
                    )
                } description: {
                    Text(
                        controller.pronunciationDictionarySearch.isEmpty
                            ? "Исправьте ударение в тексте книги — Studio автоматически запомнит его здесь."
                            : "Попробуйте другое слово или очистите поиск."
                    )
                }
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(controller.filteredPronunciationDictionaryEntries) { entry in
                            dictionaryEntry(entry)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }

            if let error = controller.pronunciationDictionaryError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(.red)
            }

            HStack {
                Label(
                    "Работает локально, без подключения к интернету. Изменения не запускают запись и не расходуют средства.",
                    systemImage: "lock.shield"
                )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Обновить список") {
                    Task { await controller.reloadPronunciationDictionary() }
                }
                .disabled(controller.isPronunciationDictionaryLoading)
            }
        }
        .padding(20)
        .frame(minWidth: 640, minHeight: 520)
        .task {
            await controller.reloadPronunciationDictionary()
        }
        .alert(
            "Удалить слово из словаря?",
            isPresented: Binding(
                get: { entryPendingDeletion != nil },
                set: { if !$0 { entryPendingDeletion = nil } }
            ),
            presenting: entryPendingDeletion
        ) { entry in
            Button("Удалить", role: .destructive) {
                controller.deletePronunciation(entry)
                entryPendingDeletion = nil
            }
            Button("Отмена", role: .cancel) {
                entryPendingDeletion = nil
            }
        } message: { entry in
            Text("«\(entry.word)» больше не будет автоматически исправляться в новых текстах. Уже подготовленные аудиофайлы не изменятся.")
        }
    }

    @ViewBuilder
    private func dictionaryEntry(_ entry: PronunciationDictionaryEntry) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 7) {
                        Text(entry.word).font(.headline)
                        Image(systemName: "arrow.right").foregroundStyle(.tertiary)
                        Text(entry.preferred?.display ?? "вариант не выбран")
                            .font(.headline)
                            .foregroundStyle(entry.preferred == nil ? .secondary : .primary)
                    }
                    modeLabel(entry.mode)
                }
                Spacer()
                if entry.mode != "DISABLED" {
                    Button("Отключить") { controller.disablePronunciation(entry) }
                        .disabled(controller.isPronunciationDictionaryLoading)
                }
                Button("Удалить", role: .destructive) {
                    entryPendingDeletion = entry
                }
                .disabled(controller.isPronunciationDictionaryLoading)
            }

            if entry.variants.count > 1 || entry.mode == "REVIEW_REQUIRED" {
                VStack(alignment: .leading, spacing: 7) {
                    Text("Варианты произношения")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 110), spacing: 8)],
                        alignment: .leading,
                        spacing: 8
                    ) {
                        ForEach(entry.variants) { variant in
                            Button {
                                controller.setPreferredPronunciation(variant, for: entry)
                            } label: {
                                Label(
                                    variant.display,
                                    systemImage: entry.preferred == variant
                                        ? "checkmark.circle.fill"
                                        : "circle"
                                )
                            }
                            .buttonStyle(.bordered)
                            .disabled(controller.isPronunciationDictionaryLoading)
                            .help("Сделать этот вариант основным и применять автоматически")
                        }
                    }
                    if entry.mode == "REVIEW_REQUIRED" {
                        Text("Выберите основной вариант, если он подходит в большинстве случаев. Для омонима в конкретной книге ударение можно исправить отдельно.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } else if entry.mode == "DISABLED", let variant = entry.variants.first {
                Button("Включить и применять «\(variant.display)»") {
                    controller.setPreferredPronunciation(variant, for: entry)
                }
                .disabled(controller.isPronunciationDictionaryLoading)
            }
        }
        .padding(12)
        .background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private func modeLabel(_ mode: String) -> some View {
        switch mode {
        case "AUTO":
            Label("AUTO · применяется автоматически", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case "REVIEW_REQUIRED":
            Label("Требует выбора", systemImage: "questionmark.circle.fill")
                .foregroundStyle(.orange)
        default:
            Label("Отключено", systemImage: "pause.circle.fill")
                .foregroundStyle(.secondary)
        }
    }

    private var entryCountText: String {
        let count = controller.pronunciationDictionarySearch.isEmpty
            ? (controller.pronunciationDictionary?.entries.count ?? 0)
            : controller.filteredPronunciationDictionaryEntries.count
        let lastTwo = count % 100
        let last = count % 10
        let noun: String
        if (11...14).contains(lastTwo) {
            noun = "записей"
        } else if last == 1 {
            noun = "запись"
        } else if (2...4).contains(last) {
            noun = "записи"
        } else {
            noun = "записей"
        }
        return "\(count) \(noun)"
    }
}

struct ContentQualitySettingsPanel: View {
    @StateObject private var controller = ContentQualityController()
    let selectedBookID: String

    var body: some View {
        Group {
            Section("Текст перед озвучкой") {
                if selectedBookID.isEmpty {
                    Text("Выберите production-книгу в основном окне Studio.")
                        .foregroundStyle(.secondary)
                } else if let review = controller.ttsReview {
                    HStack {
                        LabeledContent("TTS working copy", value: "revision \(review.workingCopyRevision)")
                        Spacer()
                        Text(review.preparationStatus ?? "NOT_PREPARED")
                            .font(.caption.monospaced())
                            .foregroundStyle(review.preparationStatus == "READY" ? .green : .orange)
                    }
                    Text("Оригинал книги остаётся read-only. Здесь редактируется только рабочая копия для озвучки.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Toggle(
                        "Требовать ручную приёмку текущего текста перед озвучкой",
                        isOn: Binding(
                            get: { controller.ttsReview?.manualReview.required ?? false },
                            set: { controller.setManualReviewRequired($0) }
                        )
                    )
                    if review.manualReview.required {
                        Label(
                            review.manualReview.ready
                                ? "Текущий SHA принят владельцем"
                                : "Требуется ручная приёмка текущего SHA",
                            systemImage: review.manualReview.ready
                                ? "person.crop.circle.badge.checkmark"
                                : "person.crop.circle.badge.exclamationmark"
                        )
                        .foregroundStyle(review.manualReview.ready ? .green : .orange)
                    } else {
                        Text("Ручная приёмка выключена: автоматическая подготовка текста остаётся доступной.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    TextEditor(text: $controller.workingTextDraft)
                        .font(.body.monospaced())
                        .frame(minHeight: 220)
                        .overlay(
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(.quaternary)
                        )
                    HStack {
                        Button("Сохранить правки") { controller.saveWorkingCopy() }
                            .buttonStyle(.borderedProminent)
                            .disabled(controller.isLoading || !controller.workingTextHasUnsavedChanges)
                        Button("Отменить несохранённые") { controller.discardWorkingCopyDraft() }
                            .disabled(controller.isLoading || !controller.workingTextHasUnsavedChanges)
                        Spacer()
                        Button("Принять текущий текст") { controller.acceptCurrentWorkingCopy() }
                            .disabled(
                                controller.isLoading
                                || controller.workingTextHasUnsavedChanges
                                || !review.manualReview.required
                                || review.manualReview.ready
                            )
                    }
                    if controller.workingTextHasUnsavedChanges {
                        Label(
                            "Есть несохранённые правки. После сохранения старая подготовка станет STALE и потребуется подготовить текст заново.",
                            systemImage: "pencil.and.outline"
                        )
                        .font(.caption)
                        .foregroundStyle(.orange)
                    }
                    DisclosureGroup("Техническая идентичность") {
                        LabeledContent("Working SHA", value: review.workingCopySHA256)
                        LabeledContent("Файл", value: review.workingCopyPath)
                    }
                    .font(.caption)
                } else if controller.isLoading {
                    ProgressView("Загрузка рабочей копии…")
                }
            }

            Section("Ударения и произношение") {
                if let review = controller.ttsReview {
                    LabeledContent(
                        "Текущий диктор",
                        value: [review.selectedBackend, review.selectedProfileID]
                            .filter { !$0.isEmpty }
                            .joined(separator: " · ")
                    )
                    Text("Studio хранит ударение provider-neutral. Для выбранного движка она показывает, как это решение будет передано диктору.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack {
                        TextField("Слово, например: замок", text: $controller.stressWord)
                        Button("Показать варианты") { controller.loadStressCandidates() }
                            .disabled(controller.isLoading || controller.stressWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    if !controller.stressCandidates.isEmpty {
                        HStack(spacing: 8) {
                            Text("Ударение:")
                            ForEach(controller.stressCandidates) { candidate in
                                Button(candidate.display) { controller.previewStress(candidate) }
                            }
                        }
                    }
                    if let preview = controller.stressPreview {
                        VStack(alignment: .leading, spacing: 6) {
                            Label("Выбрано: \(preview.display)", systemImage: "waveform.badge.magnifyingglass")
                                .font(.headline)
                            LabeledContent("Для \(preview.engine)", value: preview.providerMode)
                            Text(preview.providerValue)
                                .font(.callout.monospaced())
                                .textSelection(.enabled)
                            Text(preview.explanation)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Button("Сохранить и запомнить ударение") { controller.saveStressForBook() }
                                .buttonStyle(.borderedProminent)
                                .disabled(controller.isLoading)
                        }
                        .padding(.vertical, 4)
                    }
                    if let notice = controller.pronunciationSaveNotice {
                        Label(notice, systemImage: "checkmark.circle.fill")
                            .font(.callout.weight(.medium))
                            .foregroundStyle(.green)
                    }
                    if !review.pronunciationEntries.isEmpty {
                        DisclosureGroup("Сохранённые ударения · \(review.pronunciationEntries.count)") {
                            ForEach(review.pronunciationEntries) { entry in
                                HStack {
                                    Text(entry.word)
                                    Image(systemName: "arrow.right")
                                    Text(entry.display).bold()
                                    Spacer()
                                    Text(entry.scope == "BOOK" ? "эта книга" : "точное место")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Text("Исправление сохранится для этой книги и автоматически попадёт в общий Словарь ударений. Прослушивание короткой пробы будет отдельным provider-действием с явным подтверждением; этот редактор сам платные запросы не запускает.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Выберите production-книгу, чтобы управлять ударениями.")
                        .foregroundStyle(.secondary)
                }
            }

            Section("Словарь мусора") {
                if let status = controller.status {
                    LabeledContent("Общая база", value: "v\(status.contractVersion) · revision \(status.userStore.revision)")
                    Text(status.userStore.path)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    if status.userEntries.isEmpty {
                        Text("Пользовательских правил пока нет")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(status.userEntries) { rule in
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(rule.value)
                                    Text("\(rule.action) · \(rule.profiles.joined(separator: " + "))")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Удалить", role: .destructive) {
                                    controller.removeUserRule(rule)
                                }
                                .buttonStyle(.borderless)
                                .disabled(controller.isLoading)
                            }
                        }
                    }
                    TextField("Добавить слово/фразу в словарь мусора", text: $controller.newRuleValue)
                    Picker("Действие", selection: $controller.newRuleAction) {
                        ForEach(ContentQualityRuleAction.allCases) { value in
                            Text(value.label).tag(value)
                        }
                    }
                    Picker("Где применять", selection: $controller.newRuleScope) {
                        ForEach(ContentQualityRuleScope.allCases) { value in
                            Text(value.label).tag(value)
                        }
                    }
                    Button("Добавить правило") { controller.addUserRule() }
                        .disabled(controller.isLoading || controller.newRuleValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Text("Это один общий пользовательский словарь для BOOK OS и Audiobook Studio. BLOCK стопорит мусор на этапе написания книги; Studio сама литературный текст не правит.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Пользовательский REGEX в v1 запрещён.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if controller.isLoading {
                    ProgressView("Загрузка словаря…")
                } else {
                    Button("Загрузить словарь") {
                        Task { await controller.reload(bookID: selectedBookID) }
                    }
                }
            }

            Section("Контроль текста") {
                Toggle(
                    "Искать мусорные слова и фразы в этой книге",
                    isOn: Binding(
                        get: { controller.manualJunkSearchEnabled },
                        set: { controller.setManualJunkSearchEnabled($0) }
                    )
                )
                Text("Редакционный поиск запускается только по вашему выбору. Он ничего не исправляет и не запрещает озвучку. TTS-технический контроль выполняется автоматически.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if selectedBookID.isEmpty {
                    Text("Выберите production-книгу в основном окне Studio.")
                        .foregroundStyle(.secondary)
                } else if let scan = controller.bookScan {
                    HStack {
                        Label(
                            contentQualityStateLabel(scan.state),
                            systemImage: contentQualityStateIcon(scan.state)
                        )
                        .foregroundStyle(contentQualityStateColor(scan.state))
                        Spacer()
                        Button("Проверить снова") {
                            Task { await controller.reload(bookID: selectedBookID) }
                        }
                        .disabled(controller.isLoading)
                    }
                    if controller.manualJunkSearchEnabled {
                        contentQualityFindings(
                            title: "Мусор — ручная проверка",
                            scan: scan.editorial,
                            controller: controller
                        )
                    } else {
                        Text("Поиск мусора выключен.")
                            .foregroundStyle(.secondary)
                    }
                    contentQualityFindings(
                        title: "TTS-технические",
                        scan: scan.technical,
                        controller: controller
                    )
                    DisclosureGroup("Evidence") {
                        LabeledContent("Working SHA", value: scan.workingCopySHA256)
                        LabeledContent("Prepared SHA", value: scan.normalizedSHA256)
                        LabeledContent("Lexicon gate", value: scan.gateFingerprint)
                    }
                    .font(.caption)
                } else if controller.isLoading {
                    ProgressView("Проверка текста…")
                }
            }

            if let status = controller.status {
                Section("Общие редакционные правила") {
                    DisclosureGroup("System core · \(status.coreEntries.count) правил") {
                        ForEach(status.coreEntries) { rule in
                            contentQualityRuleLine(rule)
                        }
                    }
                    Text("В Audiobook Studio эти правила используются только по ручному включению поиска. BLOCK здесь — серьёзность находки, а не автоматический запрет синтеза.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("TTS-технические правила") {
                    DisclosureGroup("Audiobook overlay · \(status.technicalEntries.count) правил") {
                        ForEach(status.technicalEntries) { rule in
                            contentQualityRuleLine(rule)
                        }
                    }
                    Text("AUDIOBOOK_TTS_TECHNICAL — обязательный production gate: служебные URL, Markdown, placeholders и подобные артефакты не должны уходить диктору.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let error = controller.errorMessage {
                Section("Audiobook Studio — ошибка") {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }
            }
        }
        .task(id: selectedBookID) {
            await controller.reload(bookID: selectedBookID)
        }
        .sheet(item: $controller.findingForResolution) { finding in
            ContentQualityResolutionSheet(controller: controller, finding: finding)
        }
    }
}

private struct ContentQualityResolutionSheet: View {
    @ObservedObject var controller: ContentQualityController
    let finding: ContentQualityFinding

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Разрешить технический BLOCK только для текущего текста?")
                .font(.title3.weight(.semibold))
            Text("\"\(finding.matchedText)\"")
                .textSelection(.enabled)
            Text("Правило \(finding.ruleID) · строка \(finding.line), позиция \(finding.column)")
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
            Text("Любое изменение текста автоматически делает его неприменимым.")
                .font(.callout)
            TextField("Причина человеческого исключения", text: $controller.resolutionReason, axis: .vertical)
                .lineLimit(3...6)
            HStack {
                Spacer()
                Button("Отмена", role: .cancel) { controller.cancelResolution() }
                Button("Разрешить для этого SHA") { controller.confirmResolution() }
                    .buttonStyle(.borderedProminent)
                    .disabled(controller.resolutionReason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(24)
        .frame(minWidth: 520)
    }
}

@ViewBuilder
private func contentQualityFindings(
    title: String,
    scan: ContentQualityScan,
    controller: ContentQualityController
) -> some View {
    DisclosureGroup("\(title) · \(contentQualityStateLabel(scan.state))") {
        if scan.findings.isEmpty {
            Text("Замечаний нет")
                .foregroundStyle(.secondary)
        }
        ForEach(scan.findings) { finding in
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(finding.action)
                        .font(.caption.weight(.bold))
                        .foregroundStyle(finding.action == "BLOCK" ? Color.red : Color.orange)
                    Text(finding.ruleID)
                        .font(.caption.monospaced())
                    if finding.resolved {
                        Label("Разрешено для SHA", systemImage: "person.crop.circle.badge.checkmark")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }
                }
                Text("\"\(finding.matchedText)\"")
                    .textSelection(.enabled)
                Text("строка \(finding.line), позиция \(finding.column) · offsets \(finding.start)…\(finding.end)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                if let rationale = finding.rationale, !rationale.isEmpty {
                    Text(rationale)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if finding.profile == "AUDIOBOOK_TTS_TECHNICAL",
                   finding.action == "BLOCK", !finding.resolved {
                    Button("Человеческое исключение для этого SHA…") {
                        controller.requestResolution(finding)
                    }
                    .buttonStyle(.borderless)
                }
            }
            .padding(.vertical, 3)
        }
    }
}

@ViewBuilder
private func contentQualityRuleLine(_ rule: ContentQualityRule) -> some View {
    VStack(alignment: .leading, spacing: 2) {
        HStack {
            Text(rule.action)
                .font(.caption.weight(.bold))
                .foregroundStyle(rule.action == "BLOCK" ? Color.red : Color.orange)
            Text(rule.ruleID)
                .font(.caption.monospaced())
        }
        Text(rule.matchType == "REGEX" ? "Системный pattern" : rule.value)
        if let rationale = rule.rationale, !rationale.isEmpty {
            Text(rationale)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
    .padding(.vertical, 2)
}

private func contentQualityStateLabel(_ state: String) -> String {
    switch state {
    case "PASS": "Технических блокеров нет"
    case "WARN": "Есть замечания для просмотра"
    case "BLOCKED": "TTS-технический блокер"
    default: state
    }
}

private func contentQualityStateIcon(_ state: String) -> String {
    switch state {
    case "PASS": "checkmark.shield.fill"
    case "WARN": "exclamationmark.triangle.fill"
    default: "xmark.octagon.fill"
    }
}

private func contentQualityStateColor(_ state: String) -> Color {
    switch state {
    case "PASS": .green
    case "WARN": .orange
    default: .red
    }
}
