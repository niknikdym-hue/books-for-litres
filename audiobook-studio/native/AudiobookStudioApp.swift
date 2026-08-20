import AppKit
import SwiftUI

private struct WorkspaceContract: Decodable {
    let workspaceRoot: String
    enum CodingKeys: String, CodingKey { case workspaceRoot = "workspace_root" }
}

private struct WorkspacePaths {
    let root: URL
    var runtimeRoot: URL { root.appendingPathComponent("runtime/studio-workspace", isDirectory: true) }
    var qwenPython: URL { root.appendingPathComponent("engines/qwen-mlx/.venv/bin/python") }

    static func load() -> WorkspacePaths {
        let environment = ProcessInfo.processInfo.environment
        if let override = environment["AUDIOBOOK_STUDIO_HOME"], !override.isEmpty {
            return WorkspacePaths(root: URL(fileURLWithPath: override, isDirectory: true))
        }

        let defaultRoot = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/New project/Audiobook-Studio", isDirectory: true)
        let contractURL = environment["AUDIOBOOK_STUDIO_PATH_CONTRACT"]
            .map { URL(fileURLWithPath: $0) }
            ?? defaultRoot.appendingPathComponent("settings/workspace-paths.json")
        if let data = try? Data(contentsOf: contractURL),
           let contract = try? JSONDecoder().decode(WorkspaceContract.self, from: data),
           !contract.workspaceRoot.isEmpty {
            return WorkspacePaths(root: URL(fileURLWithPath: contract.workspaceRoot, isDirectory: true))
        }
        return WorkspacePaths(root: defaultRoot)
    }
}

private let workspacePaths = WorkspacePaths.load()
private let studioDirectory = workspacePaths.runtimeRoot
private let pythonExecutable = workspacePaths.qwenPython.path

@MainActor
final class StudioModel: ObservableObject {
    @Published var books: [Book] = []
    @Published var voiceLibrary = VoiceLibrarySnapshot(qwen: [], yandex: [], openai: [])
    @Published var profile = YandexProfile(voice: "Lera", role: "neutral", speed: "1.04")
    @Published var estimate: YandexEstimate?
    @Published var cloudBilling: CloudBillingEnvelope?
    @Published var selectedBookID = ""
    @Published var selectedProfileID = ""
    @Published var engine: Engine = .yandex
    @Published var isLoading = true
    @Published var isRunning = false
    @Published var errorMessage: String?
    @Published var completedOutput: URL?
    @Published var showConfirmation = false
    @Published var hardLimitText = ""
    @Published var openAIHardLimitText = "1.00"
    @Published var localHealthText = ""
    @Published var billingRefreshText = ""
    @Published var technicalDetails: String?

    init() {
        if let requested = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_ENGINE"],
           let initialEngine = Engine(rawValue: requested) {
            engine = initialEngine
        }
        Task { await reload() }
    }

    var selectedBook: Book? { books.first { $0.id == selectedBookID } }
    var availableProfiles: [VoiceProfile] { voiceLibrary.profiles(for: engine) }
    var selectedProfile: VoiceProfile? { availableProfiles.first { $0.profileID == selectedProfileID } }
    var selectedBilling: CloudBillingSnapshot? { cloudBilling?.providers[engine] }

    func reload() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot: StudioSnapshot = try await runBridgeJSON(["--ui-snapshot"])
            books = snapshot.books
            voiceLibrary = snapshot.voiceLibrary
            profile = snapshot.yandexProfile
            estimate = snapshot.yandexEstimate
            cloudBilling = snapshot.cloudBilling
            selectedBookID = books.first?.id ?? ""
            selectDefaultProfile()
            if let requestedProfile = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_PROFILE"],
               availableProfiles.contains(where: { $0.profileID == requestedProfile }) {
                selectedProfileID = requestedProfile
            }
            hardLimitText = snapshot.yandexSettings.hardLimitRub ?? ""
            openAIHardLimitText = snapshot.cloudBilling.providers.openai.hardLimit ?? "1.00"
            errorMessage = nil
        } catch {
            showError(error)
        }
    }

    func begin() {
        if engine == .openai { return }
        guard engine == .yandex else {
            errorMessage = "Для Qwen выберите подготовленную задачу. Автоматический запуск литературного master-а отключён."
            return
        }
        guard estimate?.allowedToStart == true else {
            errorMessage = pricingMessage
            return
        }
        showConfirmation = true
    }

    func selectDefaultProfile() {
        let preferred: String
        switch engine {
        case .qwen: preferred = "qwen_vivian"
        case .yandex: preferred = "yandex_lera"
        case .openai: preferred = "openai_onyx"
        }
        selectedProfileID = availableProfiles.first(where: { $0.profileID == preferred })?.profileID
            ?? availableProfiles.first?.profileID ?? ""
    }

    func refreshBilling(_ provider: Engine) {
        guard provider.isCloud else { return }
        Task {
            do {
                let _: CloudBillingSnapshot = try await runBridgeJSON([
                    "--billing-status", "--provider", provider.rawValue, "--refresh",
                ])
                billingRefreshText = "Статус обновлён. Недоступные provider-данные не считаются ошибкой Studio."
                await reload()
            } catch {
                billingRefreshText = "Не удалось выполнить read-only обновление billing."
                technicalDetails = error.localizedDescription
            }
        }
    }

    func confirmYandexDemo() {
        showConfirmation = false
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let output = try await runBridgeText(["--run-yandex-demo"])
                let path = output.split(whereSeparator: \ .isNewline).last.map(String.init) ?? ""
                if path.hasSuffix(".wav") {
                    completedOutput = URL(fileURLWithPath: path)
                }
                errorMessage = nil
            } catch {
                showError(error)
            }
        }
    }

    func checkYandexLocally() {
        Task {
            do {
                let _: LocalHealth = try await runBridgeJSON(["--yandex-local-health"])
                localHealthText = "Учётные данные доступны. Сетевая проверка не выполнялась."
            } catch {
                localHealthText = "Не удалось проверить учётные данные."
                showError(error)
            }
        }
    }

    func saveHardLimit() {
        Task {
            do {
                let _: LimitResult = try await runBridgeJSON(["--set-yandex-hard-limit", "--hard-limit-rub", hardLimitText])
                await reload()
            } catch {
                showError(error)
            }
        }
    }

    func saveOpenAIHardLimit() {
        Task {
            do {
                let _: BillingSettingResult = try await runBridgeJSON([
                    "--set-billing-setting", "--provider", "openai",
                    "--setting", "hard_limit", "--value", openAIHardLimitText,
                ])
                await reload()
            } catch {
                showError(error)
            }
        }
    }

    var pricingMessage: String {
        switch estimate?.blockedReason {
        case "stale_tariff": return "Стоимость не подтверждена: тариф устарел. Обновите тариф перед запуском книги."
        case "missing_tariff": return "Стоимость: тариф не настроен."
        case "missing_hard_limit": return "Задайте максимальную стоимость одной задачи в Настройках."
        case "hard_limit_exceeded": return "Оценка превышает лимит задачи. Измените лимит в Настройках."
        default: return "Запуск пока недоступен."
        }
    }

    private func runBridgeText(_ arguments: [String]) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: pythonExecutable)
            process.arguments = [studioDirectory.appendingPathComponent("audiobook_studio_app_runner.py").path] + arguments
            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr
            try process.run()
            process.waitUntilExit()
            let output = String(decoding: stdout.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            let error = String(decoding: stderr.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            guard process.terminationStatus == 0 else {
                throw BridgeError.message(error.isEmpty ? "Команда Studio завершилась с ошибкой." : error)
            }
            return output
        }.value
    }

    private func runBridgeJSON<T: Decodable>(_ arguments: [String]) async throws -> T {
        let output = try await runBridgeText(arguments)
        return try JSONDecoder().decode(T.self, from: Data(output.utf8))
    }

    private func showError(_ error: Error) {
        technicalDetails = error.localizedDescription
        errorMessage = "Не удалось выполнить действие. Откройте Технические подробности, если проблема повторится."
    }
}

private struct LocalHealth: Decodable { let ok: Bool }
private struct LimitResult: Decodable { let hardLimitRub: String?; enum CodingKeys: String, CodingKey { case hardLimitRub = "hard_limit_rub" } }
private struct BillingSettingResult: Decodable {
    let value: String
    let remoteRequestSent: Bool
    enum CodingKeys: String, CodingKey { case value; case remoteRequestSent = "remote_request_sent" }
}
private enum BridgeError: LocalizedError { case message(String); var errorDescription: String? { if case let .message(text) = self { return text }; return nil } }

@main
struct AudiobookStudioApp: App {
    @StateObject private var model = StudioModel()

    var body: some Scene {
        WindowGroup("Audiobook Studio") {
            StudioView(model: model)
                .frame(minWidth: 900, minHeight: 620)
        }
        .defaultSize(width: 1060, height: 720)
        Settings {
            SettingsView(model: model)
                .frame(width: 520)
        }
    }
}

struct StudioView: View {
    @ObservedObject var model: StudioModel
    @Environment(\.openSettings) private var openSettings
    @State private var openedDiagnosticSettings = false

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selectedBookID) {
                Section("БИБЛИОТЕКА") {
                    ForEach(model.books) { book in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(book.title).font(.headline)
                            Text(book.author).foregroundStyle(.secondary)
                            Text("Готово к подготовке озвучки").font(.caption).foregroundStyle(.secondary)
                        }
                        .tag(book.id)
                        .padding(.vertical, 4)
                    }
                }
                Section {
                    Label("Добавить книгу — скоро", systemImage: "plus")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationSplitViewColumnWidth(min: 230, ideal: 280)
        } detail: {
            VStack(spacing: 0) {
                Form {
                    Section("Подготовка озвучки") {
                        Picker("Движок", selection: $model.engine) {
                            ForEach(Engine.allCases) { engine in Text(engine.title).tag(engine) }
                        }
                        .pickerStyle(.segmented)
                        .onChange(of: model.engine) { _, _ in model.selectDefaultProfile() }

                        if model.engine == .qwen {
                            Picker("Голос", selection: $model.selectedProfileID) {
                                ForEach(model.availableProfiles) { Text($0.label).tag($0.profileID) }
                            }
                        } else if model.engine == .yandex {
                            Picker("Голос", selection: $model.selectedProfileID) {
                                ForEach(model.availableProfiles) { Text($0.label).tag($0.profileID) }
                            }
                            .disabled(true)
                            LabeledContent("Стиль", value: model.selectedProfile?.role ?? model.profile.role)
                            LabeledContent("Скорость", value: model.selectedProfile?.speed ?? model.profile.speed)
                            Text("Текущий production-профиль Lera зафиксирован; остальные approved-профили доступны в Voice Library.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            Picker("Голос", selection: $model.selectedProfileID) {
                                ForEach(model.availableProfiles) { Text($0.label).tag($0.profileID) }
                            }
                            LabeledContent("Модель", value: model.selectedProfile?.model ?? "gpt-4o-mini-tts")
                            LabeledContent("Формат", value: (model.selectedProfile?.responseFormat ?? "wav").uppercased())
                            LabeledContent("Статус", value: "Production backend готов")
                            Label("Платный запуск пока заблокирован до контрольной проверки.", systemImage: "lock.fill")
                                .font(.caption)
                                .foregroundStyle(.orange)
                        }
                    }

                    Section("Что озвучить") {
                        Picker("Режим", selection: .constant("demo")) {
                            Text("Тестовый фрагмент").tag("demo")
                            Text("Фрагмент — скоро").tag("fragment")
                            Text("Глава — скоро").tag("chapter")
                            Text("Вся книга — после подключения TTS-master").tag("book")
                        }
                        .disabled(true)
                        Text("Текущий литературный master автоматически не используется.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    if model.engine == .yandex, let estimate = model.estimate {
                        Section("Параметры задачи") {
                            Text("\(estimate.characters.formatted()) символов · \(estimate.segments) сегмента")
                            if estimate.cachedSegments > 0 {
                                Text("Уже готово: \(estimate.cachedSegments) · осталось отправить: \(estimate.billableRemainingUnits)")
                            }
                            Text(estimate.priceStale ? "Тариф требует проверки" : "Тариф проверен: \(russianDate(estimate.priceVerifiedAt))")
                                .foregroundStyle(estimate.priceStale ? .orange : .secondary)
                            DisclosureGroup("Подробности") {
                                Text("Единицы тарификации: \(estimate.totalBillingUnits)")
                                Text("Цена единицы: \(estimate.unitPrice ?? "не настроена") ₽")
                            }
                        }
                    }

                    if model.engine == .qwen {
                        Section("Расходы и лимиты") {
                            Label("Локальный движок · расходы API отсутствуют", systemImage: "laptopcomputer")
                                .foregroundStyle(.secondary)
                        }
                    } else if let billing = model.selectedBilling {
                        Section("Расходы и лимиты") {
                            BillingValueLine(
                                title: "Израсходовано",
                                value: formattedMoney(billing.spent, currency: billing.currency, source: billing.spentSource),
                                detail: provenanceLabel(billing.spentSource)
                            )
                            BillingValueLine(
                                title: "Остаток",
                                value: formattedMoney(billing.remaining, currency: billing.currency, source: billing.remainingSource),
                                detail: billingAvailabilityReason(billing) ?? provenanceLabel(billing.remainingSource)
                            )
                            BillingValueLine(
                                title: "Текущая задача",
                                value: formattedMoney(billing.currentJobEstimate, currency: billing.currency, source: billing.currentJobEstimateSource),
                                detail: billing.provider == "openai" && billing.currentJobEstimate == nil
                                    ? "Точная стоимость будущего аудио заранее неизвестна"
                                    : provenanceLabel(billing.currentJobEstimateSource)
                            )
                            BillingValueLine(
                                title: "После запуска",
                                value: formattedMoney(billing.projectedRemaining, currency: billing.currency, source: billing.projectedRemainingSource),
                                detail: provenanceLabel(billing.projectedRemainingSource)
                            )
                            BillingValueLine(
                                title: "Лимит задачи",
                                value: formattedMoney(billing.hardLimit, currency: billing.currency, source: "local_actual"),
                                detail: "Локальный защитный лимит"
                            )
                            HStack {
                                Text(freshnessLabel(billing))
                                    .font(.caption)
                                    .foregroundStyle(billing.freshness == "stale" ? .orange : .secondary)
                                Spacer()
                                Button("Обновить") { model.refreshBilling(model.engine) }
                            }
                            ForEach(billing.warnings.filter { $0 != "remaining_unavailable" }, id: \.self) { warning in
                                Label(billingWarningLabel(warning), systemImage: "exclamationmark.triangle")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .formStyle(.grouped)
                .padding(.top, 8)

                Divider()
                HStack {
                    VStack(alignment: .leading) {
                        Text(model.isRunning ? "Идёт озвучка" : (model.completedOutput == nil ? "Готово к запуску" : "Готово"))
                            .font(.headline)
                        if let output = model.completedOutput {
                            Text(output.lastPathComponent).foregroundStyle(.secondary)
                        } else if model.engine == .qwen {
                            Text("Выберите подготовленную задачу для Qwen.").foregroundStyle(.secondary)
                        } else if model.engine == .openai {
                            Text("OpenAI готов. Платный запуск будет разрешён после контрольной проверки.")
                                .foregroundStyle(.secondary)
                        } else {
                            Text("Тестовый фрагмент · Lera · neutral · 1.04").foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if let output = model.completedOutput {
                        Button("Прослушать") { NSWorkspace.shared.open(output) }
                        Button("Показать в Finder") { NSWorkspace.shared.activateFileViewerSelecting([output]) }
                    }
                    Button(
                        model.engine == .openai ? "Платный запуск заблокирован" :
                            (model.isRunning ? "Выполняется…" : "Начать озвучку")
                    ) { model.begin() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isRunning || model.isLoading || model.engine == .openai)
                }
                .padding()
                if let details = model.technicalDetails {
                    DisclosureGroup("Технические подробности") {
                        Text(details).font(.caption.monospaced())
                    }
                    .padding([.horizontal, .bottom])
                }
            }
            .overlay {
                if model.isLoading { ProgressView("Загрузка Studio…") }
            }
            .navigationTitle(model.selectedBook?.title ?? "Audiobook Studio")
            .toolbar { ToolbarItem { SettingsLink { Label("Настройки", systemImage: "gearshape") } } }
            .task {
                if ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_OPEN_SETTINGS_ON_LAUNCH"] == "1",
                   !openedDiagnosticSettings {
                    openedDiagnosticSettings = true
                    try? await Task.sleep(for: .milliseconds(400))
                    openSettings()
                }
            }
            .alert("Audiobook Studio", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
                Button("OK", role: .cancel) { model.errorMessage = nil }
            } message: { Text(model.errorMessage ?? "") }
            .confirmationDialog("Начать озвучку?", isPresented: $model.showConfirmation, titleVisibility: .visible) {
                Button("Начать озвучку") { model.confirmYandexDemo() }
                Button("Отмена", role: .cancel) {}
            } message: {
                Text("Yandex SpeechKit\n\(model.profile.voice) · \(model.profile.role) · \(model.profile.speed)\n\(model.estimate?.segments ?? 0) сегмента\n\(formattedMoney(model.estimate?.estimatedRemainingCost, currency: "RUB", source: "local_estimate"))")
            }
        }
    }
}

private struct BillingValueLine: View {
    let title: String
    let value: String
    let detail: String

    var body: some View {
        LabeledContent(title) {
            VStack(alignment: .trailing, spacing: 2) {
                Text(value).font(.body.weight(.semibold))
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct SettingsView: View {
    @ObservedObject var model: StudioModel
    @AppStorage("openFinderAfterCompletion") private var openFinderAfterCompletion = true
    @AppStorage("notificationsEnabled") private var notificationsEnabled = true

    var body: some View {
        ScrollViewReader { proxy in
            Form {
                Section("Общие") {
                    Toggle("Открывать Finder после завершения", isOn: $openFinderAfterCompletion)
                    Toggle("Показывать уведомления", isOn: $notificationsEnabled)
                    LabeledContent("Папка результатов", value: "Выбирается backend-ом")
                }
                Section("Qwen") {
                    LabeledContent("Статус", value: "Локальный backend")
                    Button("Проверить") { Task { await model.reload() } }
                }
                Section("Yandex SpeechKit") {
                    LabeledContent("Профиль", value: "Lera · neutral · 1.04")
                    HStack {
                        TextField("Максимальная стоимость задачи, ₽", text: $model.hardLimitText)
                        Button("Сохранить") { model.saveHardLimit() }
                    }
                    Text("Без лимита запуск полной книги блокируется.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Проверить подключение") { model.checkYandexLocally() }
                    if !model.localHealthText.isEmpty {
                        Text(model.localHealthText).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Section("OpenAI TTS") {
                    LabeledContent("Backend", value: "Production готов · paid run заблокирован")
                    HStack {
                        TextField("Максимальная стоимость задачи, $", text: $model.openAIHardLimitText)
                        Button("Сохранить") { model.saveOpenAIHardLimit() }
                    }
                    Text("Локальный лимит одной задачи; это не остаток на счёте.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .id("openai-settings")
                Section("Cloud Billing") {
                    LabeledContent("Yandex", value: billingSettingsStatus(model.cloudBilling?.providers.yandex))
                    LabeledContent("OpenAI", value: billingSettingsStatus(model.cloudBilling?.providers.openai))
                    HStack {
                        Button("Обновить Yandex") { model.refreshBilling(.yandex) }
                        Button("Обновить OpenAI") { model.refreshBilling(.openai) }
                    }
                    if !model.billingRefreshText.isEmpty {
                        Text(model.billingRefreshText).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .formStyle(.grouped)
            .task {
                if ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_SETTINGS_FOCUS"] == "openai" {
                    try? await Task.sleep(for: .milliseconds(500))
                    proxy.scrollTo("openai-settings", anchor: .top)
                }
            }
        }
        .padding()
    }
}

private func billingSettingsStatus(_ billing: CloudBillingSnapshot?) -> String {
    guard let billing else { return "Нет данных" }
    if billing.remaining == nil { return "Остаток недоступен" }
    return freshnessLabel(billing)
}

private func russianDate(_ date: String?) -> String {
    guard let date else { return "не указана" }
    let parts = date.split(separator: "-")
    guard parts.count == 3 else { return date }
    return "\(parts[2]).\(parts[1]).\(parts[0])"
}
