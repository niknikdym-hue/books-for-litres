import AppKit
import SwiftUI
import UniformTypeIdentifiers

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
private let pythonExecutable = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_PYTHON"]
    ?? workspacePaths.qwenPython.path

private struct OpenAIExecutionSelection: Equatable {
    let engine: Engine
    let bookID: String
    let jobID: String
    let profileID: String
}

private struct YandexChapterSelection: Equatable {
    let bookID: String
    let jobID: String
    let profileID: String
}

private enum PendingOpenAIAction: Equatable {
    case prepare(OpenAIExecutionSelection)
    case materializeCache(OpenAIExecutionSelection, planID: String, planDigest: String)
}

private enum PlanExecutionAuthorization {
    case paidConfirmation
    case cacheOnly(ConsumedOneShotIntent)
}

@MainActor
final class StudioModel: ObservableObject {
    @Published var books: [Book] = []
    @Published var voiceLibrary = VoiceLibrarySnapshot(qwen: [], yandex: [], openai: [])
    @Published var profile = YandexProfile(voice: "Lera", role: "neutral", speed: "1.04")
    @Published var estimate: YandexEstimate?
    @Published var cloudBilling: CloudBillingEnvelope?
    @Published var selectedBookID = "" {
        didSet { if oldValue != selectedBookID { executionSelectionDidChange() } }
    }
    @Published var selectedJobID = "" {
        didSet { if oldValue != selectedJobID { executionSelectionDidChange() } }
    }
    @Published var selectedProfileID = "" {
        didSet { if oldValue != selectedProfileID { executionSelectionDidChange() } }
    }
    @Published var engine: Engine = .yandex {
        didSet { if oldValue != engine { executionSelectionDidChange() } }
    }
    @Published var isLoading = true
    @Published var isRunning = false
    @Published var errorMessage: String?
    @Published var completedOutput: URL?
    @Published private(set) var showPrepareConfirmation = false
    @Published private(set) var showCacheOnlyConfirmation = false
    @Published var showPaidConfirmation = false
    @Published var paidPlan: PaidRunPlan?
    @Published var paidStatusText = ""
    @Published var yandexChapterPlan: YandexChapterRunPlan?
    @Published var yandexChapterStatusText = ""
    @Published var showYandexChapterConfirmation = false
    @Published var remainingPaidSegments: Int?
    @Published var hardLimitText = ""
    @Published var openAIHardLimitText = "1.00"
    @Published var localHealthText = ""
    @Published var billingRefreshText = ""
    @Published var technicalDetails: String?
    @Published var isAddingBook = false
    @Published var isPreparingBookText = false
    @Published private(set) var showBookTextPreparationConfirmation = false
    private var openAIIntentGate = OneShotIntentGate()
    private var pendingOpenAIIntentToken: OneShotIntentToken?
    private var pendingOpenAIAction: PendingOpenAIAction?
    private var pendingBookTextPreparationID: String?

    init() {
        if let requested = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_ENGINE"],
           let initialEngine = Engine(rawValue: requested) {
            engine = initialEngine
        }
        Task { await reload() }
    }

    var selectedBook: Book? { books.first { $0.id == selectedBookID } }
    var selectedJob: PreparedJob? { selectedBook?.jobs.first { $0.id == selectedJobID } }
    var chapterJobs: [PreparedJob] { selectedBook?.jobs.filter { $0.kind == "chapter" } ?? [] }
    var availableProfiles: [VoiceProfile] { voiceLibrary.profiles(for: engine) }
    var selectedProfile: VoiceProfile? { availableProfiles.first { $0.profileID == selectedProfileID } }
    var selectedBilling: CloudBillingSnapshot? { cloudBilling?.providers[engine] }

    func reload(preferredBookID: String? = nil) async {
        invalidateOpenAIIntent()
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot: StudioSnapshot = try await runBridgeJSON(["--ui-snapshot"])
            books = snapshot.books
            voiceLibrary = snapshot.voiceLibrary
            profile = snapshot.yandexProfile
            estimate = snapshot.yandexEstimate
            cloudBilling = snapshot.cloudBilling
            selectedBookID = preferredBookID.flatMap { requested in
                books.contains(where: { $0.id == requested }) ? requested : nil
            } ?? books.first?.id ?? ""
            selectDefaultJob()
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

    func addBook(sourceURL: URL, title: String, author: String, slug: String) async -> Bool {
        isAddingBook = true
        defer { isAddingBook = false }
        let accessing = sourceURL.startAccessingSecurityScopedResource()
        defer { if accessing { sourceURL.stopAccessingSecurityScopedResource() } }
        do {
            let result: BookImportResult = try await runBridgeJSON([
                "--add-book", "--source-file", sourceURL.path,
                "--title", title, "--author", author, "--slug", slug,
            ])
            guard !result.remoteRequestSent else {
                throw BridgeError.message("Add Book нарушил offline contract.")
            }
            await reload(preferredBookID: result.bookID)
            errorMessage = nil
            return true
        } catch {
            showError(error)
            return false
        }
    }

    func requestBookTextPreparation() {
        guard let book = selectedBook, book.kind == "production" else {
            errorMessage = "Подготовка текста доступна только для книг из production-библиотеки."
            return
        }
        guard book.sourceIntegrity == "OK" else {
            errorMessage = "Целостность исходного файла не подтверждена. Подготовка заблокирована."
            return
        }
        pendingBookTextPreparationID = book.id
        showBookTextPreparationConfirmation = true
    }

    func cancelBookTextPreparation() {
        pendingBookTextPreparationID = nil
        showBookTextPreparationConfirmation = false
    }

    func confirmBookTextPreparation() {
        guard let bookID = pendingBookTextPreparationID,
              selectedBookID == bookID,
              selectedBook?.kind == "production" else {
            cancelBookTextPreparation()
            errorMessage = "Выбранная книга изменилась. Начните подготовку текста заново."
            return
        }
        cancelBookTextPreparation()
        Task {
            isPreparingBookText = true
            defer { isPreparingBookText = false }
            do {
                let result: BookTextPreparationResult = try await runBridgeJSON([
                    "--prepare-book-text", "--book", bookID,
                ])
                guard !result.remoteRequestSent else {
                    throw BridgeError.message("Подготовка текста нарушила offline contract.")
                }
                guard result.preparationStatus == "READY" else {
                    throw BridgeError.message("Текст не достиг состояния READY.")
                }
                await reload(preferredBookID: bookID)
                errorMessage = nil
            } catch {
                showError(error)
            }
        }
    }

    func begin() {
        if engine == .openai {
            if let plan = paidPlan, plan.decision == "CACHE_ONLY", plan.canExecute {
                requestCacheOnlyMaterializationConfirmation(for: plan)
            } else {
                requestOpenAIPrepareConfirmation()
            }
            return
        }
        guard engine == .yandex else {
            errorMessage = "Для Qwen выберите подготовленную задачу. Автоматический запуск литературного master-а отключён."
            return
        }
        if yandexChapterPlan?.canExecute == true {
            showYandexChapterConfirmation = true
        } else {
            prepareYandexChapterRun()
        }
    }

    func selectDefaultProfile() {
        invalidateOpenAIIntent()
        let preferred: String
        switch engine {
        case .qwen: preferred = "qwen_vivian"
        case .yandex: preferred = "yandex_lera"
        case .openai: preferred = "openai_onyx"
        }
        selectedProfileID = availableProfiles.first(where: { $0.profileID == preferred })?.profileID
            ?? availableProfiles.first?.profileID ?? ""
        paidPlan = nil
        showPaidConfirmation = false
    }

    func selectDefaultJob() {
        invalidateOpenAIIntent()
        selectedJobID = engine == .yandex
            ? (chapterJobs.first?.id ?? "")
            : (selectedBook?.jobs.first?.id ?? "")
        paidPlan = nil
        yandexChapterPlan = nil
        showPaidConfirmation = false
        showYandexChapterConfirmation = false
    }

    private func prepareYandexChapterRun() {
        guard let selection = currentYandexChapterSelection() else {
            errorMessage = "Выберите подготовленную главу для Yandex SpeechKit."
            return
        }
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let plan: YandexChapterRunPlan = try await runBridgeJSON([
                    "--prepare-yandex-chapter-run",
                    "--book", selection.bookID,
                    "--job", selection.jobID,
                    "--profile-id", selection.profileID,
                ])
                yandexChapterPlan = plan
                technicalDetails = nil
                guard !plan.remoteRequestSent else {
                    throw BridgeError.message("Подготовка Yandex-плана нарушила offline contract.")
                }
                if plan.canExecute {
                    yandexChapterStatusText = plan.decision == "CACHE_ONLY"
                        ? "Глава уже есть в проверенном кэше; новый запрос не требуется."
                        : "План главы подготовлен. Требуется отдельное подтверждение."
                    showYandexChapterConfirmation = true
                    errorMessage = nil
                } else {
                    errorMessage = yandexChapterBlockerLabel(plan.blockers)
                    technicalDetails = plan.blockers.joined(separator: "\n")
                }
            } catch {
                showError(error)
            }
        }
    }

    func confirmYandexChapterRun() {
        guard let plan = yandexChapterPlan, plan.canExecute else {
            errorMessage = yandexChapterPlan?.isExpired == true
                ? "Срок действия плана главы истёк. Подготовьте запуск заново."
                : "Сначала подготовьте действующий план главы."
            return
        }
        showYandexChapterConfirmation = false
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: YandexChapterRunResult = try await runBridgeJSON([
                    "--execute-yandex-chapter-plan",
                    "--plan-id", plan.planID,
                    "--plan-digest", plan.planDigest,
                ])
                yandexChapterPlan = nil
                completedOutput = URL(fileURLWithPath: result.outputPath)
                yandexChapterStatusText = result.networkRequests == 0
                    ? "Глава материализована из кэша без нового запроса."
                    : "Глава озвучена. Provider-запросов: \(result.networkRequests)."
                errorMessage = nil
            } catch {
                showError(error)
            }
        }
    }

    func confirmOpenAIPrepare() {
        guard case let .prepare(expectedSelection) = pendingOpenAIAction,
              currentOpenAISelection() == expectedSelection,
              let authorization = openAIIntentGate.consume(pendingOpenAIIntentToken) else {
            invalidateOpenAIIntent()
            errorMessage = "Подтверждение подготовки устарело. Начните действие заново."
            return
        }
        clearConsumedOpenAIIntent()
        preparePaidRun(authorizedBy: authorization, selection: expectedSelection)
    }

    func cancelOpenAIIntent() {
        invalidateOpenAIIntent()
    }

    func confirmCacheOnlyMaterialization() {
        guard case let .materializeCache(expectedSelection, planID, planDigest) = pendingOpenAIAction,
              currentOpenAISelection() == expectedSelection,
              paidPlan?.planID == planID,
              paidPlan?.planDigest == planDigest,
              paidPlan?.decision == "CACHE_ONLY",
              let authorization = openAIIntentGate.consume(pendingOpenAIIntentToken) else {
            invalidateOpenAIIntent()
            errorMessage = "Подтверждение использования готового аудио устарело. Начните действие заново."
            return
        }
        clearConsumedOpenAIIntent()
        executePaidPlan(authorizedBy: .cacheOnly(authorization))
    }

    func confirmPaidRequest() {
        guard paidPlan?.decision == "READY_FOR_CONFIRMATION", paidPlan?.canExecute == true else {
            errorMessage = "Сначала подготовьте действующий план запуска."
            return
        }
        executePaidPlan(authorizedBy: .paidConfirmation)
    }

    private func requestOpenAIPrepareConfirmation() {
        guard let selection = currentOpenAISelection() else {
            errorMessage = "Для книги нет подготовленных задач."
            return
        }
        invalidateOpenAIIntent()
        pendingOpenAIIntentToken = openAIIntentGate.arm()
        pendingOpenAIAction = .prepare(selection)
        showPrepareConfirmation = true
    }

    private func requestCacheOnlyMaterializationConfirmation(for plan: PaidRunPlan) {
        guard let selection = currentOpenAISelection() else {
            errorMessage = "Для книги нет подготовленных задач."
            return
        }
        invalidateOpenAIIntent()
        pendingOpenAIIntentToken = openAIIntentGate.arm()
        pendingOpenAIAction = .materializeCache(
            selection,
            planID: plan.planID,
            planDigest: plan.planDigest
        )
        showCacheOnlyConfirmation = true
    }

    private func preparePaidRun(
        authorizedBy authorization: ConsumedOneShotIntent,
        selection: OpenAIExecutionSelection
    ) {
        _ = authorization
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let plan: PaidRunPlan = try await runBridgeJSON([
                    "--prepare-paid-run", "--provider", "openai",
                    "--book", selection.bookID,
                    "--job", selection.jobID,
                    "--profile-id", selection.profileID,
                ])
                paidPlan = plan
                technicalDetails = nil
                if plan.decision == "READY_FOR_CONFIRMATION" {
                    showPaidConfirmation = plan.canExecute
                    paidStatusText = "План подготовлен. Требуется подтверждение одного сегмента."
                } else if plan.decision == "CACHE_ONLY" {
                    paidStatusText = "Готовое аудио найдено. Платный запрос не требуется."
                } else if plan.blockers.contains("ambiguous_segment_requires_resolution") {
                    errorMessage = "Результат запроса не определён. Автоматический повтор запрещён."
                    technicalDetails = plan.blockers.joined(separator: "\n")
                } else if plan.blockers.contains("failed_segment_requires_resolution") {
                    errorMessage = "Неустранённая ошибка сегмента блокирует запуск."
                    technicalDetails = plan.blockers.joined(separator: "\n")
                } else {
                    errorMessage = paidRunBlockerLabel(plan.blockers)
                    technicalDetails = plan.blockers.joined(separator: "\n")
                }
            } catch {
                showError(error)
            }
        }
    }

    private func executePaidPlan(authorizedBy authorization: PlanExecutionAuthorization) {
        guard let plan = paidPlan, plan.canExecute else {
            errorMessage = paidPlan?.isExpired == true
                ? "Срок действия плана истёк. Подготовьте новый запуск."
                : "Сначала подготовьте действующий план запуска."
            return
        }
        switch authorization {
        case .paidConfirmation:
            guard plan.decision == "READY_FOR_CONFIRMATION" else {
                errorMessage = "Платное подтверждение не соответствует текущему плану."
                return
            }
        case .cacheOnly:
            guard plan.decision == "CACHE_ONLY" else {
                errorMessage = "Готовое аудио больше не соответствует текущему плану."
                return
            }
        }
        showPaidConfirmation = false
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: PaidRunExecutionResult = try await runBridgeJSON([
                    "--execute-paid-plan", "--plan-id", plan.planID,
                    "--plan-digest", plan.planDigest,
                ])
                paidPlan = nil
                remainingPaidSegments = result.remainingSegments
                if let path = result.outputPath, !path.isEmpty {
                    completedOutput = URL(fileURLWithPath: path)
                }
                paidStatusText = result.networkRequests == 0
                    ? "Готовое аудио использовано без нового запроса."
                    : "Сегмент готов. Осталось: \(result.remainingSegments)"
                errorMessage = nil
            } catch {
                showError(error)
            }
        }
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

    private func currentOpenAISelection() -> OpenAIExecutionSelection? {
        guard engine == .openai,
              selectedBook != nil,
              selectedJob != nil,
              selectedProfile != nil else { return nil }
        return OpenAIExecutionSelection(
            engine: engine,
            bookID: selectedBookID,
            jobID: selectedJobID,
            profileID: selectedProfileID
        )
    }

    private func currentYandexChapterSelection() -> YandexChapterSelection? {
        guard engine == .yandex,
              selectedBook?.preparationStatus == "READY",
              selectedJob?.kind == "chapter",
              selectedProfileID == "yandex_lera" else { return nil }
        return YandexChapterSelection(
            bookID: selectedBookID,
            jobID: selectedJobID,
            profileID: selectedProfileID
        )
    }

    private func executionSelectionDidChange() {
        invalidateOpenAIIntent()
        paidPlan = nil
        yandexChapterPlan = nil
        yandexChapterStatusText = ""
        showPaidConfirmation = false
        showYandexChapterConfirmation = false
    }

    private func invalidateOpenAIIntent() {
        openAIIntentGate.cancel()
        pendingOpenAIIntentToken = nil
        pendingOpenAIAction = nil
        showPrepareConfirmation = false
        showCacheOnlyConfirmation = false
    }

    private func clearConsumedOpenAIIntent() {
        pendingOpenAIIntentToken = nil
        pendingOpenAIAction = nil
        showPrepareConfirmation = false
        showCacheOnlyConfirmation = false
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
        invalidateOpenAIIntent()
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
    @State private var showBookImporter = false
    @State private var showAddBookSheet = false
    @State private var selectedSourceURL: URL?
    @State private var newBookTitle = ""
    @State private var newBookAuthor = ""
    @State private var newBookSlug = ""

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selectedBookID) {
                Section("БИБЛИОТЕКА") {
                    ForEach(model.books) { book in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(book.title).font(.headline)
                            Text(book.author).foregroundStyle(.secondary)
                            Text(bookPreparationSidebarLabel(book))
                                .font(.caption)
                                .foregroundStyle(book.preparationStatus == "STALE" ? .orange : .secondary)
                        }
                        .tag(book.id)
                        .padding(.vertical, 4)
                    }
                }
                Section {
                    Button {
                        showBookImporter = true
                    } label: {
                        Label("Добавить книгу", systemImage: "plus")
                    }
                    .disabled(model.isAddingBook)
                }
            }
            .navigationSplitViewColumnWidth(min: 230, ideal: 280)
        } detail: {
            VStack(spacing: 0) {
                Form {
                    if let book = model.selectedBook, book.kind == "production" {
                        Section("Книга") {
                            LabeledContent("Название", value: book.title)
                            LabeledContent("Автор", value: book.author)
                            LabeledContent("Source filename", value: book.sourceFilename ?? "Недоступно")
                            LabeledContent("Source SHA-256", value: book.sourceSHA256 ?? "Недоступно")
                            LabeledContent("Source integrity", value: book.sourceIntegrity ?? "Недоступно")
                            LabeledContent("TTS working copy", value: book.ttsWorkingCopyStatus == "CREATED" ? "Создана" : "Недоступно")
                            LabeledContent("Backend", value: book.selectedBackend ?? "Не выбран")
                            LabeledContent("Voice profile", value: book.selectedProfileID ?? "Не выбран")
                        }

                        Section("Подготовка текста") {
                            if book.sourceIntegrity != "OK" {
                                Label("Целостность исходного файла не подтверждена", systemImage: "exclamationmark.shield")
                                    .foregroundStyle(.red)
                                Text("Подготовка заблокирована; сохранённый SHA исходника не изменяется автоматически.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            } else if book.preparationStatus == "READY" {
                                Label("Текст подготовлен", systemImage: "checkmark.circle.fill")
                                    .foregroundStyle(.green)
                                LabeledContent("Глав", value: String(book.chapterCount ?? 0))
                                LabeledContent("Сегментов", value: String(book.preparedSegmentCount ?? 0))
                                LabeledContent("Ревизия", value: String(book.preparationRevision ?? 0))
                                LabeledContent("TTS working copy", value: "Актуальна")
                            } else if book.preparationStatus == "STALE" {
                                Label("Подготовка устарела", systemImage: "exclamationmark.triangle.fill")
                                    .foregroundStyle(.orange)
                                Text("TTS working copy изменилась. Старые задачи скрыты и не могут быть запущены.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Button("Подготовить заново") { model.requestBookTextPreparation() }
                                    .disabled(model.isPreparingBookText)
                            } else {
                                Text("Текст ещё не подготовлен")
                                    .foregroundStyle(.secondary)
                                Button("Подготовить текст") { model.requestBookTextPreparation() }
                                    .disabled(model.isPreparingBookText)
                            }
                        }
                    }

                    Section("Подготовка озвучки") {
                        Picker("Движок", selection: $model.engine) {
                            ForEach(Engine.allCases) { engine in Text(engine.title).tag(engine) }
                        }
                        .pickerStyle(.segmented)
                        .onChange(of: model.engine) { _, _ in
                            model.selectDefaultProfile()
                            model.selectDefaultJob()
                        }

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
                            LabeledContent("Статус", value: "Безопасный запуск одного сегмента")
                            Label("Каждый новый платный сегмент требует отдельного плана и подтверждения.", systemImage: "checkmark.shield")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    Section("Что озвучить") {
                        if model.selectedBook?.jobs.isEmpty ?? true {
                            Text("Подготовленных задач пока нет")
                                .foregroundStyle(.secondary)
                        } else if model.engine == .openai {
                            if let book = model.selectedBook, !book.jobs.isEmpty {
                                Picker("Подготовленная задача", selection: $model.selectedJobID) {
                                    ForEach(book.jobs) { job in
                                        Text("\(job.label) · \(job.segmentCount) сегм.").tag(job.id)
                                    }
                                }
                                .onChange(of: model.selectedJobID) { _, _ in model.paidPlan = nil }
                            } else {
                                Text("Для книги нет подготовленных задач.")
                                    .foregroundStyle(.secondary)
                            }
                            Text("Studio выберет только первый допустимый MISS-сегмент. Вся книга автоматически не запускается.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else if model.engine == .yandex {
                            if model.chapterJobs.isEmpty {
                                Text("Для книги нет подготовленных глав.")
                                    .foregroundStyle(.secondary)
                            } else {
                                Picker("Подготовленная глава", selection: $model.selectedJobID) {
                                    ForEach(model.chapterJobs) { job in
                                        Text("\(job.label) · \(job.segmentCount) лит. сегм.").tag(job.id)
                                    }
                                }
                            }
                            Text("Studio сначала создаёт локальный неизменяемый план, затем отдельно показывает стоимость и число возможных provider-запросов.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else if let book = model.selectedBook, !book.jobs.isEmpty {
                            Picker("Подготовленная задача", selection: $model.selectedJobID) {
                                ForEach(book.jobs) { job in
                                    Text("\(job.label) · \(job.segmentCount) сегм.").tag(job.id)
                                }
                            }
                        } else {
                            Text("Для книги нет подготовленных задач.")
                                .foregroundStyle(.secondary)
                        }
                    }

                    if model.engine == .openai, let plan = model.paidPlan {
                        Section("План запуска") {
                            LabeledContent("Решение", value: plan.decision == "CACHE_ONLY" ? "Готовое аудио" : plan.decision)
                            if let number = plan.selectedSegmentNumber {
                                LabeledContent("Сегмент", value: "\(number) из \(plan.totalSegments)")
                            }
                            LabeledContent("Новых платных запросов", value: "максимум \(plan.maxNetworkRequests)")
                            LabeledContent("Точная будущая стоимость", value: "Недоступно")
                            if !model.paidStatusText.isEmpty {
                                Text(model.paidStatusText).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }

                    if model.engine == .yandex, let plan = model.yandexChapterPlan {
                        Section("Параметры задачи") {
                            Text("\(plan.characters.formatted()) символов · \(plan.totalSegments) provider-сегм.")
                            if plan.cachedSegments > 0 {
                                Text("Проверенный кэш: \(plan.cachedSegments)")
                            }
                            LabeledContent("Новых запросов", value: "максимум \(plan.maxNetworkRequests)")
                            LabeledContent(
                                "Оценка главы",
                                value: formattedMoney(plan.estimatedRemainingCost, currency: plan.currency, source: "local_estimate")
                            )
                            Text(plan.pricingStale ? "Тариф требует проверки" : "Тариф проверен: \(russianDate(plan.pricingVerifiedAt))")
                                .foregroundStyle(plan.pricingStale ? .orange : .secondary)
                            if !model.yandexChapterStatusText.isEmpty {
                                Text(model.yandexChapterStatusText).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    } else if model.engine == .yandex, let job = model.selectedJob {
                        Section("Параметры задачи") {
                            Text("Подготовленная глава · \(job.segmentCount) литературных сегм.")
                            Text("Точная provider-сегментация и стоимость появятся после локальной подготовки плана.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } else if model.engine == .yandex, let estimate = model.estimate {
                        Section("Диагностический тариф") {
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
                            Text(model.paidStatusText.isEmpty
                                ? "Выберите подготовленную задачу. Один план разрешает максимум один новый запрос."
                                : model.paidStatusText)
                                .foregroundStyle(.secondary)
                        } else {
                            Text(model.yandexChapterStatusText.isEmpty
                                ? "Подготовленная глава · Lera · neutral · 1.04"
                                : model.yandexChapterStatusText)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if let output = model.completedOutput {
                        Button("Прослушать") { NSWorkspace.shared.open(output) }
                        Button("Показать в Finder") { NSWorkspace.shared.activateFileViewerSelecting([output]) }
                    }
                    Button(primaryButtonTitle(model)) { model.begin() }
                        .buttonStyle(.borderedProminent)
                        .disabled(
                            model.isRunning || model.isLoading || model.isAddingBook
                                || model.isPreparingBookText
                                || (model.selectedBook?.jobs.isEmpty ?? true)
                                || (model.engine == .yandex && model.selectedJob?.kind != "chapter")
                        )
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
            .onChange(of: model.selectedBookID) { _, _ in
                model.cancelBookTextPreparation()
                model.selectDefaultJob()
            }
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
            .confirmationDialog("Озвучить подготовленную главу?", isPresented: $model.showYandexChapterConfirmation, titleVisibility: .visible) {
                if model.yandexChapterPlan?.canExecute == true {
                    Button(model.yandexChapterPlan?.decision == "CACHE_ONLY" ? "Использовать готовое аудио" : "Подтвердить озвучку главы") {
                        model.confirmYandexChapterRun()
                    }
                }
                Button("Отмена", role: .cancel) {}
            } message: {
                if let plan = model.yandexChapterPlan {
                    Text("Yandex SpeechKit\nГлава: \(plan.jobLabel)\nГолос: \(plan.voice.capitalized) · \(plan.role) · \(plan.speed)\nProvider-сегментов: \(plan.totalSegments)\nНовых запросов: максимум \(plan.maxNetworkRequests)\nОценка: \(formattedMoney(plan.estimatedRemainingCost, currency: plan.currency, source: "local_estimate"))\nЛимит Studio: \(formattedMoney(plan.hardLimit, currency: plan.currency, source: "local_actual"))")
                }
            }
            .modifier(OpenAIConfirmationDialogs(model: model))
            .confirmationDialog(
                "Подготовить текст книги?",
                isPresented: Binding(
                    get: { model.showBookTextPreparationConfirmation },
                    set: { if !$0 { model.cancelBookTextPreparation() } }
                ),
                titleVisibility: .visible
            ) {
                Button("Подготовить текст") { model.confirmBookTextPreparation() }
                Button("Отмена", role: .cancel) { model.cancelBookTextPreparation() }
            } message: {
                Text("Исходный файл не изменится. Будет обработана только TTS working copy. Платных и provider-запросов нет.")
            }
            .fileImporter(
                isPresented: $showBookImporter,
                allowedContentTypes: [.plainText],
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case let .success(urls):
                    guard let url = urls.first else { return }
                    selectedSourceURL = url
                    newBookTitle = url.deletingPathExtension().lastPathComponent
                    newBookAuthor = ""
                    newBookSlug = suggestedBookSlug(newBookTitle)
                    showAddBookSheet = true
                case let .failure(error):
                    model.errorMessage = "Не удалось выбрать TXT: \(error.localizedDescription)"
                }
            }
            .sheet(isPresented: $showAddBookSheet) {
                AddBookSheet(
                    model: model,
                    sourceURL: selectedSourceURL,
                    title: $newBookTitle,
                    author: $newBookAuthor,
                    slug: $newBookSlug,
                    isPresented: $showAddBookSheet
                )
            }
        }
    }
}

private struct AddBookSheet: View {
    @ObservedObject var model: StudioModel
    let sourceURL: URL?
    @Binding var title: String
    @Binding var author: String
    @Binding var slug: String
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Добавить книгу").font(.title2.weight(.semibold))
            LabeledContent("TXT-файл", value: sourceURL?.lastPathComponent ?? "Не выбран")
            TextField("Название", text: $title)
            TextField("Автор", text: $author)
            TextField("ID / slug", text: $slug)
            Text("Оригинал будет сохранён read-only. Для будущей подготовки создаётся отдельная TTS working copy.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Отмена", role: .cancel) { isPresented = false }
                Button("Добавить") {
                    guard let sourceURL else { return }
                    Task {
                        if await model.addBook(
                            sourceURL: sourceURL,
                            title: title,
                            author: author,
                            slug: slug
                        ) {
                            isPresented = false
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    sourceURL == nil || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || author.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || slug.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || model.isAddingBook
                )
            }
        }
        .padding(24)
        .frame(width: 480)
    }
}

private func suggestedBookSlug(_ value: String) -> String {
    let lowered = value.lowercased()
    let mapped = lowered.map { character -> Character in
        character.isLetter || character.isNumber || character == "-" || character == "_" ? character : "-"
    }
    let compact = String(mapped).replacingOccurrences(of: "-+", with: "-", options: .regularExpression)
    let trimmed = compact.trimmingCharacters(in: CharacterSet(charactersIn: "-_"))
    return trimmed.isEmpty ? "new-book" : String(trimmed.prefix(80))
}

private func bookPreparationSidebarLabel(_ book: Book) -> String {
    guard book.kind == "production" else { return "Готово к подготовке озвучки" }
    if book.sourceIntegrity != "OK" { return "Проверка исходника не пройдена" }
    switch book.preparationStatus {
    case "READY": return "Текст подготовлен"
    case "STALE": return "Подготовка устарела"
    default: return "Текст ожидает подготовки"
    }
}

private struct OpenAIConfirmationDialogs: ViewModifier {
    @ObservedObject var model: StudioModel

    func body(content: Content) -> some View {
        content
            .confirmationDialog(
                "Подготовить OpenAI-план?",
                isPresented: Binding(
                    get: { model.showPrepareConfirmation },
                    set: { if !$0 { model.cancelOpenAIIntent() } }
                ),
                titleVisibility: .visible
            ) {
                Button("Подготовить план") { model.confirmOpenAIPrepare() }
                Button("Отмена", role: .cancel) { model.cancelOpenAIIntent() }
            } message: {
                Text("Подготовка плана не отправляет TTS-запрос и не списывает средства. После подготовки платный запрос потребует отдельного подтверждения.")
            }
            .confirmationDialog(
                "Использовать готовое OpenAI-аудио?",
                isPresented: Binding(
                    get: { model.showCacheOnlyConfirmation },
                    set: { if !$0 { model.cancelOpenAIIntent() } }
                ),
                titleVisibility: .visible
            ) {
                Button("Использовать готовое аудио") { model.confirmCacheOnlyMaterialization() }
                Button("Отмена", role: .cancel) { model.cancelOpenAIIntent() }
            } message: {
                Text("Готовое аудио будет материализовано локально. Новый provider-запрос не отправляется.")
            }
            .confirmationDialog(
                "Подтвердить платный OpenAI TTS-запрос?",
                isPresented: $model.showPaidConfirmation,
                titleVisibility: .visible
            ) {
                if model.paidPlan?.canExecute == true,
                   model.paidPlan?.decision == "READY_FOR_CONFIRMATION" {
                    Button("Подтвердить 1 платный запрос") { model.confirmPaidRequest() }
                }
                Button("Отмена", role: .cancel) { model.showPaidConfirmation = false }
            } message: {
                if let plan = model.paidPlan {
                    Text("OpenAI TTS\nГолос: \(plan.voice.capitalized)\nМодель: \(plan.model)\nКнига: \(plan.bookTitle)\nЗадача: \(plan.jobLabel)\nСегмент: \(plan.selectedSegmentNumber ?? 0) из \(plan.totalSegments)\nСимволов: \(plan.selectedSegmentCharacters)\nКэш: MISS\nНовых платных запросов: максимум 1\nТочная будущая стоимость: Недоступно\nЛимит политики Studio: \(formattedMoney(plan.hardLimit, currency: plan.currency, source: "local_actual"))\nOpenAI balance: \(formattedMoney(plan.billing.remaining, currency: plan.currency, source: plan.billing.remainingSource))\n\nOpenAI не сообщает точную стоимость будущего аудио до синтеза. После подтверждения Studio сможет отправить максимум один новый платный TTS-запрос.")
                }
            }
    }
}

@MainActor
private func primaryButtonTitle(_ model: StudioModel) -> String {
    if model.isRunning { return "Выполняется…" }
    if model.engine == .yandex {
        if model.yandexChapterPlan?.decision == "CACHE_ONLY", model.yandexChapterPlan?.canExecute == true {
            return "Использовать готовую главу"
        }
        if model.yandexChapterPlan?.canExecute == true { return "Озвучить главу" }
        return "Подготовить запуск главы"
    }
    guard model.engine == .openai else { return "Начать озвучку" }
    if model.paidPlan?.decision == "CACHE_ONLY", model.paidPlan?.canExecute == true {
        return "Использовать готовое аудио"
    }
    if let remaining = model.remainingPaidSegments, remaining > 0 {
        return "Подготовить следующий сегмент"
    }
    return "Подготовить запуск"
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
                    LabeledContent("Backend", value: "Production готов · one-time approval")
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
