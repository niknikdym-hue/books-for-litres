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
    var label: String { self == .block ? "BLOCK — остановить" : "WARN — проверить" }
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
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    @Published var newRuleValue = ""
    @Published var newRuleAction: ContentQualityRuleAction = .block
    @Published var newRuleScope: ContentQualityRuleScope = .shared
    @Published var resolutionReason = ""
    @Published var findingForResolution: ContentQualityFinding?

    private var currentBookID = ""

    func reload(bookID: String = "") async {
        currentBookID = bookID
        isLoading = true
        defer { isLoading = false }
        do {
            let loadedStatus: ContentQualityStatusEnvelope = try await runJSON(["--status"])
            try assertOffline(loadedStatus)
            status = loadedStatus
            if !bookID.isEmpty {
                let scan: ContentQualityBookEnvelope = try await runJSON([
                    "--scan-book", "--book", bookID,
                ])
                try assertOffline(scan)
                bookScan = scan
            } else {
                bookScan = nil
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
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
                let result: ContentQualityMutationEnvelope = try await runJSON([
                    "--add-user-rule",
                    "--value", value,
                    "--action", newRuleAction.rawValue,
                    "--profiles", newRuleScope.bridgeValue,
                ])
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
                let result: ContentQualityMutationEnvelope = try await runJSON([
                    "--remove-user-rule", "--rule-id", rule.ruleID,
                ])
                try assertOffline(result)
                await reload(bookID: currentBookID)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func requestResolution(_ finding: ContentQualityFinding) {
        guard finding.action == "BLOCK", !finding.resolved else { return }
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
                let result: ContentQualityResolutionEnvelope = try await runJSON([
                    "--resolve-finding",
                    "--book", currentBookID,
                    "--rule-id", finding.ruleID,
                    "--profile", finding.profile,
                    "--reason", reason,
                ])
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
        guard value.providerRequests == 0,
              !value.remoteRequestSent,
              value.modelCalls == 0,
              !value.paidExecution,
              !value.billingChanged else {
            throw ContentQualityBridgeError.message("Контроль текста нарушил offline contract.")
        }
    }

    private func assertOffline(_ value: ContentQualityBookEnvelope) throws {
        guard value.providerRequests == 0,
              !value.remoteRequestSent,
              value.modelCalls == 0,
              !value.paidExecution,
              !value.billingChanged else {
            throw ContentQualityBridgeError.message("Проверка текста нарушила offline contract.")
        }
    }

    private func assertOffline(_ value: ContentQualityMutationEnvelope) throws {
        guard value.providerRequests == 0,
              !value.remoteRequestSent,
              value.modelCalls == 0,
              !value.paidExecution,
              !value.billingChanged else {
            throw ContentQualityBridgeError.message("Изменение словаря нарушило offline contract.")
        }
    }

    private func assertOffline(_ value: ContentQualityResolutionEnvelope) throws {
        guard value.providerRequests == 0,
              !value.remoteRequestSent,
              value.modelCalls == 0,
              !value.paidExecution,
              !value.billingChanged else {
            throw ContentQualityBridgeError.message("Человеческое исключение нарушило offline contract.")
        }
    }

    private func runText(_ arguments: [String]) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: contentQualityPython)
            process.arguments = [
                contentQualityPaths.runtimeRoot
                    .appendingPathComponent("content_quality_runner.py").path
            ] + arguments
            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr
            try process.run()
            process.waitUntilExit()
            let output = String(
                decoding: stdout.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self
            )
            let diagnostic = String(
                decoding: stderr.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self
            )
            guard process.terminationStatus == 0 else {
                if let data = output.data(using: .utf8),
                   let envelope = try? JSONDecoder().decode(ContentQualityErrorEnvelope.self, from: data) {
                    let codes = envelope.blockers?.joined(separator: ", ") ?? "content_quality_blocked"
                    throw ContentQualityBridgeError.message(
                        envelope.message ?? "Контроль текста заблокирован: \(codes)"
                    )
                }
                throw ContentQualityBridgeError.message(
                    diagnostic.isEmpty ? "Контроль текста завершился с ошибкой." : diagnostic
                )
            }
            return output
        }.value
    }

    private func runJSON<T: Decodable>(_ arguments: [String]) async throws -> T {
        let text = try await runText(arguments)
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

struct ContentQualitySettingsPanel: View {
    @StateObject private var controller = ContentQualityController()
    let selectedBookID: String

    var body: some View {
        Group {
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
                    TextField("Новое слово или фраза", text: $controller.newRuleValue)
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
                    Text("Новая редакционная запись по умолчанию действует в BOOK_PROSE и AUDIOBOOK_PRE_SYNTHESIS. Пользовательский REGEX в v1 запрещён.")
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
                    Text("Проверка только читает exact working/prepared identity. Литературный текст автоматически не изменяется.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    contentQualityFindings(
                        title: "Общие редакционные",
                        scan: scan.editorial,
                        controller: controller
                    )
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
                } else {
                    Button("Проверить выбранную книгу") {
                        Task { await controller.reload(bookID: selectedBookID) }
                    }
                }
            }

            if let status = controller.status {
                Section("Общие редакционные правила") {
                    DisclosureGroup("System core · \(status.coreEntries.count) правил") {
                        ForEach(status.coreEntries) { rule in
                            contentQualityRuleLine(rule)
                        }
                    }
                    Text("Профиль: AUDIOBOOK_PRE_SYNTHESIS. BLOCK останавливает подготовку/новый синтез; WARN требует человеческой проверки.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("TTS-технические правила") {
                    DisclosureGroup("Audiobook overlay · \(status.technicalEntries.count) правил") {
                        ForEach(status.technicalEntries) { rule in
                            contentQualityRuleLine(rule)
                        }
                    }
                    Text("Профиль AUDIOBOOK_TTS_TECHNICAL не загружается в BOOK OS и не вводит механических запретов на нормальные числа, тире, кавычки или литературную пунктуацию.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let error = controller.errorMessage {
                Section("Словарь мусора — ошибка") {
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
            Text("Разрешить BLOCK только для текущего текста?")
                .font(.title3.weight(.semibold))
            Text("\"\(finding.matchedText)\"")
                .textSelection(.enabled)
            Text("Правило \(finding.ruleID) · строка \(finding.line), позиция \(finding.column)")
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
            Text("Разрешение связано с точным SHA текста. Любое изменение текста автоматически делает его неприменимым.")
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
                if finding.action == "BLOCK", !finding.resolved {
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
    case "PASS": "Нет блокеров"
    case "WARN": "Есть замечания"
    case "BLOCKED": "Синтез заблокирован"
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
