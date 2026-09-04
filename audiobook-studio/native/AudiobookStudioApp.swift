import AppKit
import SwiftUI
import UniformTypeIdentifiers

private let audiobookTextFileType = UTType(filenameExtension: "txt", conformingTo: .plainText) ?? .plainText

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
    @Published var audioQA: AudioQACurrentEnvelope?
    @Published private(set) var audioQAPlaybackIdentity: AudioQAIdentity?
    @Published private(set) var downstreamApprovedOutput: URL?
    @Published private(set) var chapterAssembly: ChapterAssemblyStatus?
    @Published private(set) var mastering: MasteringStatus?
    @Published private(set) var litresExport: LitresExportStatus?
    @Published private(set) var bookDelivery: BookDeliveryStatus?
    let audioPlayer = EmbeddedAudioPlayer()
    @Published var audioQAStatusText = ""
    @Published private(set) var openAIQATargets: [OpenAIQATarget] = []
    @Published private(set) var showPrepareConfirmation = false
    @Published private(set) var showCacheOnlyConfirmation = false
    @Published var showPaidConfirmation = false
    @Published var paidPlan: PaidRunPlan?
    @Published var paidStatusText = ""
    @Published var yandexChapterPlan: YandexChapterRunPlan?
    @Published var yandexChapterProgress: YandexChapterProgress?
    @Published var yandexChapterStatusText = ""
    @Published var showYandexChapterConfirmation = false
    @Published var showYandexRetryConfirmation = false
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
    private var yandexChapterPlanSelection: YandexChapterSelection?
    private var pendingYandexRetrySelection: YandexChapterSelection?
    private var pendingYandexRetrySegmentID: String?
    private var openAIQASelection: OpenAIExecutionSelection?
    private var executionSelectionGeneration: UInt64 = 0
    private var bookProfileSelections: [String: String] = [:]

    init() {
        if let requested = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_ENGINE"],
           let initialEngine = Engine(rawValue: requested) {
            engine = initialEngine
        }
        audioPlayer.onIdentityInvalidated = { [weak self] in
            self?.audioQAPlaybackIdentity = nil
        }
        Task { await reload() }
    }

    var selectedBook: Book? { books.first { $0.id == selectedBookID } }
    var selectedJob: PreparedJob? { selectedBook?.jobs.first { $0.id == selectedJobID } }
    var chapterJobs: [PreparedJob] { selectedBook?.jobs.filter { $0.kind == "chapter" } ?? [] }
    var availableProfiles: [VoiceProfile] { voiceLibrary.profiles(for: engine) }
    var selectedProfile: VoiceProfile? { availableProfiles.first { $0.profileID == selectedProfileID } }
    var selectedBilling: CloudBillingSnapshot? {
        if engine == .yandex, let plan = yandexChapterPlan {
            return plan.billing
        }
        return cloudBilling?.providers[engine]
    }

    func reload(preferredBookID: String? = nil) async {
        invalidateOpenAIIntent()
        isLoading = true
        defer { isLoading = false }
        books = []
        selectedBookID = ""
        selectedJobID = ""
        audioQA = nil
        audioQAPlaybackIdentity = nil
        downstreamApprovedOutput = nil
        chapterAssembly = nil
        mastering = nil
        litresExport = nil
        bookDelivery = nil
        completedOutput = nil
        audioPlayer.clear()
        do {
            let releaseSweep: LitresReleaseAuthoritySweep = try await runBridgeJSON([
                "--reconcile-all-litres-release-authorities",
            ])
            guard !releaseSweep.remoteRequestSent,
                  releaseSweep.providerRequests == 0,
                  !releaseSweep.billingChanged,
                  releaseSweep.failedBookIDs.isEmpty,
                  releaseSweep.quarantineFailedBookIDs.isEmpty,
                  releaseSweep.results.allSatisfy({
                      !$0.remoteRequestSent && $0.providerRequests == 0 && !$0.billingChanged
                  }) else {
                throw BridgeError.message("Проверка прав выпуска не завершена безопасно.")
            }
            let snapshot: StudioSnapshot = try await runBridgeJSON(["--ui-snapshot"])
            books = snapshot.books
            bookProfileSelections = Dictionary(uniqueKeysWithValues: snapshot.books.compactMap { book in
                guard let profileID = book.selectedProfileID, !profileID.isEmpty else { return nil }
                return (book.id, profileID)
            })
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
            await refreshBookDeliveryStatus()
            errorMessage = nil
        } catch {
            showError(error)
        }
    }

    private func reconcileLitresReleaseAuthority(bookID: String) async throws {
        let releaseAuthority: LitresReleaseAuthorityStatus = try await runBridgeJSON([
            "--reconcile-litres-release-authority",
            "--book", bookID,
        ])
        guard !releaseAuthority.remoteRequestSent,
              releaseAuthority.providerRequests == 0,
              !releaseAuthority.billingChanged else {
            throw BridgeError.message("Проверка прав выпуска нарушила offline contract.")
        }
    }

    func addBook(
        sourceURL: URL,
        title: String,
        author: String,
        authorPronunciation: String,
        slug: String
    ) async -> Bool {
        isAddingBook = true
        defer { isAddingBook = false }
        let accessing = sourceURL.startAccessingSecurityScopedResource()
        defer { if accessing { sourceURL.stopAccessingSecurityScopedResource() } }
        do {
            let result: BookImportResult = try await runBridgeJSON([
                "--add-book", "--source-file", sourceURL.path,
                "--title", title,
                "--author", author,
                "--author-pronunciation", authorPronunciation,
                "--slug", slug,
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

    private func selectedBookIDForTextPreparation() -> String? {
        guard let book = selectedBook, book.kind == "production" else {
            errorMessage = "Подготовка текста доступна только для книг, добавленных в Studio."
            return nil
        }
        if book.sourceIntegrity == "DOWNLOAD_REQUIRED"
            || book.preparationStatus == "DOWNLOAD_REQUIRED" {
            errorMessage = "Часть файлов книги находится только в iCloud. В Finder выберите папку книги и нажмите «Загрузить сейчас», затем повторите проверку."
            return nil
        }
        guard book.sourceIntegrity == "OK" else {
            errorMessage = "Целостность исходного файла не подтверждена. Подготовка заблокирована."
            return nil
        }
        return book.id
    }

    func requestBookTextPreparation() {
        guard let bookID = selectedBookIDForTextPreparation() else { return }
        pendingBookTextPreparationID = bookID
        showBookTextPreparationConfirmation = true
    }

    func prepareBookTextAfterSave() {
        guard let bookID = selectedBookIDForTextPreparation() else { return }
        performBookTextPreparation(bookID: bookID)
    }

    private func performBookTextPreparation(bookID: String) {
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
        performBookTextPreparation(bookID: bookID)
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
            errorMessage = "Для локального голоса выберите подготовленную главу. Автоматическая запись всей книги отключена."
            return
        }
        if yandexChapterPlan?.canExecute == true,
           yandexChapterPlanSelection == currentYandexChapterSelection() {
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
        case .yandex: preferred = bookProfileSelections[selectedBookID] ?? "yandex_lera"
        case .openai: preferred = "openai_onyx"
        }
        selectedProfileID = availableProfiles.first(where: { $0.profileID == preferred })?.profileID
            ?? availableProfiles.first?.profileID ?? ""
        paidPlan = nil
        yandexChapterPlan = nil
        yandexChapterPlanSelection = nil
        showPaidConfirmation = false
        showYandexChapterConfirmation = false
    }

    func selectYandexProfile(_ profileID: String) {
        guard engine == .yandex,
              let book = selectedBook, book.kind == "production",
              availableProfiles.contains(where: { $0.profileID == profileID }) else {
            errorMessage = "Выбранный голос недоступен для этой книги."
            return
        }
        let previous = selectedProfileID
        selectedProfileID = profileID
        Task {
            do {
                let result: BookVoiceSelectionResult = try await runBridgeJSON([
                    "--set-book-voice",
                    "--book", book.id,
                    "--profile-id", profileID,
                ])
                guard result.selectedProfileID == profileID,
                      result.providerRequests == 0,
                      !result.remoteRequestSent,
                      !result.paidExecution,
                      !result.billingChanged else {
                    throw BridgeError.message("Studio не подтвердила безопасное сохранение диктора.")
                }
                guard selectedBookID == book.id else { return }
                bookProfileSelections[book.id] = profileID
                errorMessage = nil
            } catch {
                if selectedBookID == book.id, selectedProfileID == profileID {
                    selectedProfileID = previous
                }
                showError(error)
            }
        }
    }

    func selectDefaultJob() {
        invalidateOpenAIIntent()
        selectedJobID = engine == .yandex
            ? (chapterJobs.first?.id ?? "")
            : (selectedBook?.jobs.first?.id ?? "")
        paidPlan = nil
        yandexChapterPlan = nil
        yandexChapterPlanSelection = nil
        showPaidConfirmation = false
        showYandexChapterConfirmation = false
    }

    private func prepareYandexChapterRun() {
        guard let selection = currentYandexChapterSelection() else {
            errorMessage = "Выберите подготовленную главу для Yandex SpeechKit."
            return
        }
        Task { await prepareYandexChapterRun(selection: selection) }
    }

    private func prepareYandexChapterRun(selection: YandexChapterSelection) async {
        guard currentYandexChapterSelection() == selection else {
            errorMessage = "Выбор главы изменился. Подготовьте Yandex-план заново."
            return
        }
        isRunning = true
        defer { isRunning = false }
        do {
            let plan: YandexChapterRunPlan = try await runBridgeJSON([
                "--prepare-yandex-chapter-run",
                "--book", selection.bookID,
                "--job", selection.jobID,
                "--profile-id", selection.profileID,
            ])
            guard !plan.remoteRequestSent else {
                throw BridgeError.message("Подготовка Yandex-плана нарушила offline contract.")
            }
            guard currentYandexChapterSelection() == selection else {
                yandexChapterPlan = nil
                yandexChapterPlanSelection = nil
                showYandexChapterConfirmation = false
                throw BridgeError.message("Выбор главы изменился. Подготовьте Yandex-план заново.")
            }
            yandexChapterPlan = plan
            yandexChapterPlanSelection = selection
            technicalDetails = nil
            if plan.canExecute {
                yandexChapterStatusText = plan.decision == "CACHE_ONLY"
                    ? "Глава уже готова; новая платная запись не требуется."
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

    func confirmYandexChapterRun() {
        let planExpired = yandexChapterPlan?.isExpired == true
        guard let plan = yandexChapterPlan,
              plan.canExecute,
              let plannedSelection = yandexChapterPlanSelection,
              currentYandexChapterSelection() == plannedSelection else {
            yandexChapterPlan = nil
            yandexChapterPlanSelection = nil
            showYandexChapterConfirmation = false
            errorMessage = planExpired
                ? "Срок действия плана главы истёк. Подготовьте запуск заново."
                : "Выбор главы или профиль изменился. Подготовьте Yandex-план заново."
            return
        }
        showYandexChapterConfirmation = false
        let expectedSelectionGeneration = executionSelectionGeneration
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
                yandexChapterPlanSelection = nil
                guard executionSelectionGeneration == expectedSelectionGeneration,
                      currentYandexChapterSelection() == plannedSelection else { return }
                completedOutput = URL(fileURLWithPath: result.outputPath)
                yandexChapterStatusText = result.networkRequests == 0
                    ? "Studio использовала уже готовую главу без нового обращения."
                    : "Глава записана. Новых обращений: \(result.networkRequests)."
                errorMessage = nil
                await refreshYandexChapterProgress(expectedSelection: plannedSelection)
                await loadAudioQA(
                    provider: "yandex",
                    selection: plannedSelection,
                    audioPath: result.outputPath,
                    manifestPath: result.manifest,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            } catch {
                yandexChapterPlan = nil
                yandexChapterPlanSelection = nil
                showYandexChapterConfirmation = false
                await refreshYandexChapterProgress(expectedSelection: plannedSelection)
                if let progress = yandexChapterProgress,
                   let problem = progress.ambiguousSegments.first {
                    yandexChapterStatusText = "Запись остановлена: готово \(progress.completedSegments) из \(progress.totalSegments). Автоповтора не было."
                    technicalDetails = error.localizedDescription
                    errorMessage = "Запись остановилась на части \(problem.segmentNumber). Уже готовые части сохранены. Откройте карточку «Запись остановлена», чтобы решить, продолжать ли запись."
                } else {
                    yandexChapterStatusText = ""
                    showError(error)
                }
            }
        }
    }

    func refreshYandexChapterProgress() async {
        guard let selection = currentYandexChapterSelection() else {
            yandexChapterProgress = nil
            return
        }
        await refreshYandexChapterProgress(expectedSelection: selection)
    }

    private func refreshYandexChapterProgress(expectedSelection: YandexChapterSelection) async {
        do {
            let progress: YandexChapterProgress = try await runBridgeJSON([
                "--yandex-chapter-progress",
                "--book", expectedSelection.bookID,
                "--job", expectedSelection.jobID,
                "--profile-id", expectedSelection.profileID,
            ])
            guard currentYandexChapterSelection() == expectedSelection else { return }
            guard progress.providerRequests == 0,
                  !progress.remoteRequestSent,
                  !progress.paidExecution,
                  !progress.billingChanged else {
                throw BridgeError.message("Проверка состояния главы нарушила offline contract.")
            }
            yandexChapterProgress = progress
        } catch {
            guard currentYandexChapterSelection() == expectedSelection else { return }
            yandexChapterProgress = nil
            technicalDetails = error.localizedDescription
        }
    }

    func requestYandexAmbiguousRetry(_ problem: YandexChapterProblemSegment) {
        guard let selection = currentYandexChapterSelection(),
              yandexChapterProgress?.ambiguousSegments.contains(where: { $0.segmentID == problem.segmentID }) == true else {
            errorMessage = "Проблемная часть изменилась. Обновите состояние главы."
            return
        }
        pendingYandexRetrySelection = selection
        pendingYandexRetrySegmentID = problem.segmentID
        showYandexRetryConfirmation = true
    }

    func cancelYandexAmbiguousRetry() {
        pendingYandexRetrySelection = nil
        pendingYandexRetrySegmentID = nil
        showYandexRetryConfirmation = false
    }

    func confirmYandexAmbiguousRetry() {
        guard let selection = pendingYandexRetrySelection,
              let segmentID = pendingYandexRetrySegmentID,
              currentYandexChapterSelection() == selection else {
            cancelYandexAmbiguousRetry()
            errorMessage = "Выбор книги, главы или диктора изменился."
            return
        }
        cancelYandexAmbiguousRetry()
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: YandexRetryApprovalResult = try await runBridgeJSON([
                    "--approve-yandex-ambiguous-retry",
                    "--book", selection.bookID,
                    "--job", selection.jobID,
                    "--profile-id", selection.profileID,
                    "--segment-id", segmentID,
                ])
                guard currentYandexChapterSelection() == selection else { return }
                guard result.state == "RETRY_APPROVED",
                      result.providerRequests == 0,
                      !result.remoteRequestSent,
                      !result.paidExecution,
                      !result.billingChanged else {
                    throw BridgeError.message("Разрешение повтора нарушило offline contract.")
                }
                await refreshYandexChapterProgress(expectedSelection: selection)
                yandexChapterStatusText = "Повтор разрешён локально. Сейчас Studio покажет обновлённую стоимость; запись ещё не началась."
                await prepareYandexChapterRun(selection: selection)
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
                    paidStatusText = "План подготовлен. Требуется подтверждение одной части записи."
                } else if plan.decision == "CACHE_ONLY" {
                    paidStatusText = "Готовое аудио найдено. Платный запрос не требуется."
                } else if plan.blockers.contains("ambiguous_segment_requires_resolution") {
                    errorMessage = "Результат запроса не определён. Автоматический повтор запрещён."
                    technicalDetails = plan.blockers.joined(separator: "\n")
                } else if plan.blockers.contains("failed_segment_requires_resolution") {
                    errorMessage = "Неустранённая ошибка части записи блокирует запуск."
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
        let executionSelection = currentOpenAISelection()
        let expectedSelectionGeneration = executionSelectionGeneration
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
                guard executionSelectionGeneration == expectedSelectionGeneration,
                      currentOpenAISelection() == executionSelection else { return }
                let targets = result.qaTargets ?? []
                openAIQATargets = targets
                openAIQASelection = executionSelection
                if targets.count == 1, let target = targets.first {
                    completedOutput = URL(fileURLWithPath: target.outputPath)
                    await loadAudioQA(
                        provider: "openai",
                        bookID: plan.bookID,
                        jobID: plan.jobID,
                        profileID: plan.profileID,
                        audioPath: target.outputPath,
                        manifestPath: target.manifestPath,
                        expectedTarget: target,
                        expectedSelectionGeneration: expectedSelectionGeneration
                    )
                } else if let path = result.outputPath, !path.isEmpty {
                    completedOutput = URL(fileURLWithPath: path)
                    await loadAudioQA(
                        provider: "openai",
                        bookID: plan.bookID,
                        jobID: plan.jobID,
                        profileID: plan.profileID,
                        audioPath: path,
                        manifestPath: result.manifest,
                        expectedSelectionGeneration: expectedSelectionGeneration
                    )
                }
                paidStatusText = result.networkRequests == 0
                    ? (targets.count > 1
                        ? "Готовое аудио использовано без нового обращения. Выберите конкретную часть для проверки."
                        : "Готовое аудио использовано без нового запроса.")
                    : "Часть готова. Осталось: \(result.remainingSegments)"
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
                billingRefreshText = "Статус обновлён. Если сервис не сообщает остаток, Studio честно покажет «Недоступно»."
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
              let profile = selectedProfile,
              profile.provider == "yandex",
              profile.status == "approved" else { return nil }
        return YandexChapterSelection(
            bookID: selectedBookID,
            jobID: selectedJobID,
            profileID: selectedProfileID
        )
    }

    private func executionSelectionDidChange() {
        executionSelectionGeneration &+= 1
        audioPlayer.clear()
        invalidateOpenAIIntent()
        paidPlan = nil
        yandexChapterPlan = nil
        yandexChapterPlanSelection = nil
        yandexChapterProgress = nil
        pendingYandexRetrySelection = nil
        pendingYandexRetrySegmentID = nil
        yandexChapterStatusText = ""
        showPaidConfirmation = false
        showYandexChapterConfirmation = false
        showYandexRetryConfirmation = false
        audioQA = nil
        audioQAPlaybackIdentity = nil
        downstreamApprovedOutput = nil
        chapterAssembly = nil
        mastering = nil
        litresExport = nil
        audioQAStatusText = ""
        openAIQATargets = []
        openAIQASelection = nil
    }

    func openCurrentAudioForQA() {
        guard engine == .qwen || engine == .yandex || engine == .openai,
              selectedBook != nil,
              selectedJob != nil,
              selectedProfile != nil else {
            errorMessage = "Выберите готовую задачу и профиль для проверки аудио."
            return
        }
        audioPlayer.clear()
        audioQAPlaybackIdentity = nil
        let expectedSelectionGeneration = executionSelectionGeneration
        let expectedEngine = engine
        let expectedBookID = selectedBookID
        let expectedJobID = selectedJobID
        let expectedProfileID = selectedProfileID
        Task {
            isRunning = true
            defer { isRunning = false }
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            if expectedEngine == .openai {
                await loadOpenAIQATargets(
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            } else {
                await loadAudioQA(
                    provider: expectedEngine.rawValue,
                    bookID: expectedBookID,
                    jobID: expectedJobID,
                    profileID: expectedProfileID,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            }
        }
    }

    func refreshOpenAIQATargets() {
        let expectedSelectionGeneration = executionSelectionGeneration
        Task {
            isRunning = true
            defer { isRunning = false }
            await loadOpenAIQATargets(
                expectedSelectionGeneration: expectedSelectionGeneration
            )
        }
    }

    private func loadOpenAIQATargets(expectedSelectionGeneration: UInt64) async {
        guard executionSelectionGeneration == expectedSelectionGeneration else { return }
        guard let selection = currentOpenAISelection() else {
            errorMessage = "Выберите текущую OpenAI-задачу и профиль."
            return
        }
        do {
            let result: OpenAIQATargetList = try await runBridgeJSON([
                "--audio-qa-openai-targets",
                "--book", selection.bookID,
                "--job", selection.jobID,
                "--profile-id", selection.profileID,
            ])
            guard !result.remoteRequestSent else {
                throw BridgeError.message("Список готовых частей OpenAI не прошёл локальную проверку безопасности.")
            }
            guard executionSelectionGeneration == expectedSelectionGeneration,
                  currentOpenAISelection() == selection else { return }
            openAIQATargets = result.qaTargets
            openAIQASelection = selection
            if let current = audioQA,
               !result.qaTargets.contains(where: {
                   $0.segmentID == current.authority.segmentID
                       && $0.outputPath == current.authority.audioPath
                       && $0.manifestPath == current.authority.manifestPath
                       && $0.synthesisFingerprint == current.authority.synthesisFingerprint
               }) {
                audioPlayer.clear()
                audioQA = nil
                audioQAPlaybackIdentity = nil
                downstreamApprovedOutput = nil
            }
            if result.qaTargets.count == 1, let target = result.qaTargets.first {
                await loadAudioQA(
                    provider: "openai",
                    bookID: selection.bookID,
                    jobID: selection.jobID,
                    profileID: selection.profileID,
                    audioPath: target.outputPath,
                    manifestPath: target.manifestPath,
                    expectedTarget: target,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            } else if result.qaTargets.isEmpty {
                audioQA = nil
                errorMessage = "Готовых частей OpenAI для проверки не найдено."
            } else {
                paidStatusText = "Выберите конкретную часть OpenAI для проверки."
                errorMessage = nil
            }
        } catch {
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            showError(error)
        }
    }

    func playExactAudioForQA() {
        guard let envelope = audioQA else { return }
        let audio = URL(fileURLWithPath: envelope.record.audioPath)
        guard audio.path == envelope.authority.audioPath else {
            errorMessage = "Открытый аудиофайл больше не совпадает с текущей версией главы."
            return
        }
        guard let sha = envelope.record.identity.audioSHA256,
              let fingerprint = envelope.record.identity.synthesisFingerprint else {
            errorMessage = "Не удалось подтвердить точную версию текущего аудиофайла."
            return
        }
        let binding = AudioPlaybackBinding(
            url: audio,
            audioSHA256: sha,
            pathIdentity: envelope.record.identity.pathIdentity,
            synthesisFingerprint: fingerprint,
            provider: envelope.authority.provider,
            profileID: envelope.authority.profileID,
            bookSlug: envelope.authority.bookSlug,
            jobID: envelope.authority.jobID,
            segmentID: envelope.authority.segmentID,
            role: "qa-source"
        )
        audioPlayer.loadAndPlay(binding)
        if audioPlayer.binding == binding {
            audioQAPlaybackIdentity = envelope.record.identity
            errorMessage = nil
        } else {
            audioQAPlaybackIdentity = nil
            errorMessage = audioPlayer.errorMessage
        }
    }

    func decideAudioQA(_ decision: String) {
        guard let envelope = audioQA,
              audioQASelectionMatches(
                selectedBook: selectedBook,
                selectedJobID: selectedJobID,
                selectedProfileID: selectedProfileID,
                authority: envelope.authority
              ) else {
            errorMessage = "Выбор изменился. Откройте текущее аудио для проверки заново."
            return
        }
        if decision == "APPROVED" {
            guard audioQAPlaybackIdentity == envelope.record.identity,
                  audioPlayer.binding?.audioSHA256 == envelope.record.identity.audioSHA256,
                  audioPlayer.binding?.pathIdentity == envelope.record.identity.pathIdentity,
                  audioPlayer.binding?.synthesisFingerprint == envelope.record.identity.synthesisFingerprint,
                  audioPlayer.binding?.provider == envelope.authority.provider,
                  audioPlayer.binding?.profileID == envelope.authority.profileID,
                  audioPlayer.binding?.bookSlug == envelope.authority.bookSlug,
                  audioPlayer.binding?.jobID == envelope.authority.jobID,
                  audioPlayer.binding?.segmentID == envelope.authority.segmentID,
                  audioPlayer.validateLoadedIdentity(rehash: true) else {
                errorMessage = "Перед одобрением прослушайте именно текущую версию аудио."
                return
            }
        }
        guard let sha = envelope.record.identity.audioSHA256,
              let fingerprint = envelope.record.identity.synthesisFingerprint else {
            errorMessage = "Не удалось подтвердить точную версию текущего аудиофайла."
            return
        }
        let expectedSelectionGeneration = executionSelectionGeneration
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: AudioQACurrentEnvelope = try await runBridgeJSON(
                    audioQAArguments(for: envelope.authority, mode: "--audio-qa-decide") + [
                        "--decision", decision,
                        "--reviewed-audio-sha256", sha,
                        "--reviewed-path-identity", envelope.record.identity.pathIdentity,
                        "--reviewed-fingerprint", fingerprint,
                    ]
                )
                guard !result.remoteRequestSent else {
                    throw BridgeError.message("Audio QA нарушил offline contract.")
                }
                guard executionSelectionGeneration == expectedSelectionGeneration,
                      audioQASelectionMatches(
                          selectedBook: selectedBook,
                          selectedJobID: selectedJobID,
                          selectedProfileID: selectedProfileID,
                          authority: envelope.authority
                      ) else { return }
                audioQA = result
                audioQAPlaybackIdentity = nil
                await refreshAudioQADownstream(
                    authority: result.authority,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
                guard executionSelectionGeneration == expectedSelectionGeneration else { return }
                audioQAStatusText = decision == "REGENERATE_REQUESTED"
                    ? "Запрос новой записи сохранён. Studio ничего не запустит без обычного подтверждения."
                    : audioQAManualLabel(result.record.manualState)
                errorMessage = nil
            } catch {
                guard executionSelectionGeneration == expectedSelectionGeneration else { return }
                showError(error)
            }
        }
    }

    func openOpenAIQATarget(_ target: OpenAIQATarget) {
        guard let selection = openAIQASelection,
              currentOpenAISelection() == selection,
              openAIQATargets.contains(target) else {
            openAIQATargets = []
            openAIQASelection = nil
            errorMessage = "Выбор изменился. Обновите список готовых частей."
            return
        }
        audioPlayer.clear()
        audioQAPlaybackIdentity = nil
        let expectedSelectionGeneration = executionSelectionGeneration
        Task {
            isRunning = true
            defer { isRunning = false }
            await loadAudioQA(
                provider: "openai",
                bookID: selection.bookID,
                jobID: selection.jobID,
                profileID: selection.profileID,
                audioPath: target.outputPath,
                manifestPath: target.manifestPath,
                expectedTarget: target,
                expectedSelectionGeneration: expectedSelectionGeneration
            )
        }
    }

    private func loadAudioQA(
        provider: String,
        selection: YandexChapterSelection,
        audioPath: String = "",
        manifestPath: String = "",
        expectedSelectionGeneration: UInt64
    ) async {
        await loadAudioQA(
            provider: provider,
            bookID: selection.bookID,
            jobID: selection.jobID,
            profileID: selection.profileID,
            audioPath: audioPath,
            manifestPath: manifestPath,
            expectedSelectionGeneration: expectedSelectionGeneration
        )
    }

    private func loadAudioQA(
        provider: String,
        bookID: String,
        jobID: String,
        profileID: String,
        audioPath: String = "",
        manifestPath: String = "",
        expectedTarget: OpenAIQATarget? = nil,
        expectedSelectionGeneration: UInt64
    ) async {
        guard executionSelectionGeneration == expectedSelectionGeneration else { return }
        do {
            var arguments = [
                "--audio-qa-current", "--provider", provider,
                "--book", bookID, "--job", jobID, "--profile-id", profileID,
            ]
            if !audioPath.isEmpty { arguments += ["--audio-path", audioPath] }
            if !manifestPath.isEmpty { arguments += ["--manifest-path", manifestPath] }
            let result: AudioQACurrentEnvelope = try await runBridgeJSON(arguments)
            guard !result.remoteRequestSent else {
                throw BridgeError.message("Audio QA нарушил offline contract.")
            }
            if let expectedTarget {
                guard result.authority.segmentID == expectedTarget.segmentID,
                      result.authority.audioPath == expectedTarget.outputPath,
                      result.authority.manifestPath == expectedTarget.manifestPath,
                      result.authority.synthesisFingerprint == expectedTarget.synthesisFingerprint else {
                    throw BridgeError.message("Выбранная часть OpenAI больше не совпадает с текущей записью.")
                }
            }
            guard selectedBookID == bookID,
                  selectedJobID == jobID,
                  selectedProfileID == profileID,
                  executionSelectionGeneration == expectedSelectionGeneration else { return }
            audioPlayer.clear()
            audioQA = result
            audioQAPlaybackIdentity = nil
            chapterAssembly = nil
            mastering = nil
            litresExport = nil
            completedOutput = URL(fileURLWithPath: result.record.audioPath)
            await refreshAudioQADownstream(
                authority: result.authority,
                expectedSelectionGeneration: expectedSelectionGeneration
            )
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            audioQAStatusText = audioQAManualLabel(result.record.manualState)
            errorMessage = nil
        } catch {
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            showError(error)
        }
    }

    private func audioQAArguments(for authority: AudioQAAuthority, mode: String) -> [String] {
        [
            mode, "--provider", authority.provider,
            "--book", authority.bookSlug,
            "--job", authority.jobID,
            "--profile-id", authority.profileID,
            "--audio-path", authority.audioPath,
            "--manifest-path", authority.manifestPath,
        ]
    }

    private func refreshAudioQADownstream(
        authority: AudioQAAuthority,
        expectedSelectionGeneration: UInt64
    ) async {
        let expectedEngine = engine
        let expectedBookSlug = selectedBook?.slug
        let expectedJobID = selectedJobID
        let expectedProfileID = selectedProfileID
        guard expectedEngine.rawValue == authority.provider,
              expectedBookSlug == authority.bookSlug,
              expectedJobID == authority.jobID,
              expectedProfileID == authority.profileID else { return }
        do {
            let result: AudioQACurrentEnvelope = try await runBridgeJSON(
                audioQAArguments(for: authority, mode: "--audio-qa-downstream")
            )
            guard !result.remoteRequestSent else {
                throw BridgeError.message("Downstream QA gate нарушил offline contract.")
            }
            guard engine == expectedEngine,
                  selectedBook?.slug == expectedBookSlug,
                  selectedJobID == expectedJobID,
                  selectedProfileID == expectedProfileID,
                  executionSelectionGeneration == expectedSelectionGeneration,
                  result.authority == authority else { return }
            audioQA = result
            downstreamApprovedOutput = result.eligible
                ? URL(fileURLWithPath: result.record.audioPath)
                : nil
            if result.eligible {
                await refreshChapterAssembly(
                    authority: result.authority,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            } else {
                chapterAssembly = nil
                mastering = nil
                litresExport = nil
            }
        } catch {
            guard engine == expectedEngine,
                  selectedBook?.slug == expectedBookSlug,
                  selectedJobID == expectedJobID,
                  selectedProfileID == expectedProfileID,
                  executionSelectionGeneration == expectedSelectionGeneration else { return }
            downstreamApprovedOutput = nil
            technicalDetails = error.localizedDescription
        }
    }

    private func refreshChapterAssembly(
        authority: AudioQAAuthority,
        expectedSelectionGeneration: UInt64
    ) async {
        guard executionSelectionGeneration == expectedSelectionGeneration else { return }
        do {
            let result: ChapterAssemblyEnvelope = try await runBridgeJSON([
                "--chapter-assembly-status",
                "--provider", authority.provider,
                "--book", authority.bookSlug,
                "--job", authority.jobID,
                "--profile-id", authority.profileID,
                "--audio-path", authority.audioPath,
                "--manifest-path", authority.manifestPath,
            ])
            guard !result.remoteRequestSent,
                  result.providerRequests == 0,
                  !result.assembly.remoteRequestSent,
                  result.assembly.providerRequests == 0 else {
                throw BridgeError.message("Сборка главы нарушила offline contract.")
            }
            guard executionSelectionGeneration == expectedSelectionGeneration,
                  audioQA?.authority == authority else { return }
            chapterAssembly = result.assembly
            if result.assembly.assembly != nil {
                await refreshMastering(
                    authority: authority,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            } else {
                mastering = nil
                litresExport = nil
            }
        } catch {
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            chapterAssembly = nil
            mastering = nil
            litresExport = nil
            technicalDetails = error.localizedDescription
        }
    }

    func assembleCurrentChapter() {
        guard let qa = audioQA,
              qa.eligible,
              downstreamApprovedOutput != nil else {
            errorMessage = "Для сборки требуется точное текущее одобренное аудио."
            return
        }
        let expectedSelectionGeneration = executionSelectionGeneration
        let authority = qa.authority
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: ChapterAssemblyEnvelope = try await runBridgeJSON([
                    "--assemble-chapter",
                    "--provider", authority.provider,
                    "--book", authority.bookSlug,
                    "--job", authority.jobID,
                    "--profile-id", authority.profileID,
                    "--audio-path", authority.audioPath,
                    "--manifest-path", authority.manifestPath,
                ])
                guard !result.remoteRequestSent,
                      result.providerRequests == 0,
                      !result.assembly.remoteRequestSent,
                      result.assembly.providerRequests == 0 else {
                    throw BridgeError.message("Сборка главы нарушила offline contract.")
                }
                guard executionSelectionGeneration == expectedSelectionGeneration,
                      audioQA?.authority == authority else { return }
                chapterAssembly = result.assembly
                if result.assembly.assembly != nil {
                    await refreshMastering(
                        authority: authority,
                        expectedSelectionGeneration: expectedSelectionGeneration
                    )
                }
                errorMessage = nil
            } catch {
                guard executionSelectionGeneration == expectedSelectionGeneration else { return }
                showError(error)
            }
        }
    }

    func playAssembledChapter() {
        guard let output = chapterAssembly?.assembly?.output,
              let qa = audioQA else {
            errorMessage = "Собранная глава пока недоступна."
            return
        }
        let binding = AudioPlaybackBinding(
            url: URL(fileURLWithPath: output.path),
            audioSHA256: output.sha256,
            pathIdentity: output.pathIdentity,
            synthesisFingerprint: chapterAssembly?.assemblyIdentity ?? "",
            provider: qa.authority.provider,
            profileID: qa.authority.profileID,
            bookSlug: qa.authority.bookSlug,
            jobID: qa.authority.jobID,
            segmentID: qa.authority.segmentID,
            role: "assembled-chapter"
        )
        audioQAPlaybackIdentity = nil
        audioPlayer.loadAndPlay(binding)
        if audioPlayer.binding != binding {
            errorMessage = audioPlayer.errorMessage
        }
    }

    func revealCurrentAudioInFinder() {
        guard let url = audioPlayer.binding?.url
            ?? audioQA.map({ URL(fileURLWithPath: $0.record.audioPath) }) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func revealAssembledChapterInFinder() {
        guard let path = chapterAssembly?.assembly?.output.path else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    private func derivedAudioArguments(mode: String, authority: AudioQAAuthority) -> [String] {
        [
            mode,
            "--provider", authority.provider,
            "--book", authority.bookSlug,
            "--job", authority.jobID,
            "--profile-id", authority.profileID,
            "--audio-path", authority.audioPath,
            "--manifest-path", authority.manifestPath,
        ]
    }

    private func refreshMastering(
        authority: AudioQAAuthority,
        expectedSelectionGeneration: UInt64
    ) async {
        guard executionSelectionGeneration == expectedSelectionGeneration else { return }
        do {
            try await reconcileLitresReleaseAuthority(bookID: authority.bookSlug)
            guard executionSelectionGeneration == expectedSelectionGeneration,
                  audioQA?.authority == authority else { return }
            let result: MasteringEnvelope = try await runBridgeJSON(
                derivedAudioArguments(mode: "--mastering-status", authority: authority)
            )
            guard !result.remoteRequestSent,
                  result.providerRequests == 0,
                  !result.billingChanged,
                  !result.mastering.remoteRequestSent,
                  result.mastering.providerRequests == 0,
                  !result.mastering.billingChanged else {
                throw BridgeError.message("Мастеринг нарушил offline contract.")
            }
            guard executionSelectionGeneration == expectedSelectionGeneration,
                  audioQA?.authority == authority else { return }
            mastering = result.mastering
            if result.mastering.master != nil,
               result.mastering.decision == "ALREADY_MASTERED" {
                await refreshLitresExport(
                    authority: authority,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
            } else {
                litresExport = nil
            }
        } catch {
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            mastering = nil
            litresExport = nil
            technicalDetails = error.localizedDescription
        }
    }

    func createCurrentMaster() {
        guard let authority = audioQA?.authority,
              chapterAssembly?.assembly != nil else {
            errorMessage = "Для мастеринга требуется точная текущая сборка главы."
            return
        }
        let expectedSelectionGeneration = executionSelectionGeneration
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: MasteringEnvelope = try await runBridgeJSON(
                    derivedAudioArguments(mode: "--create-master", authority: authority)
                )
                guard !result.remoteRequestSent,
                      result.providerRequests == 0,
                      !result.billingChanged,
                      result.mastering.master != nil else {
                    throw BridgeError.message("Мастер-файл не удалось безопасно сохранить.")
                }
                guard executionSelectionGeneration == expectedSelectionGeneration,
                      audioQA?.authority == authority else { return }
                mastering = result.mastering
                await refreshLitresExport(
                    authority: authority,
                    expectedSelectionGeneration: expectedSelectionGeneration
                )
                errorMessage = nil
            } catch {
                guard executionSelectionGeneration == expectedSelectionGeneration else { return }
                showError(error)
            }
        }
    }

    private func refreshLitresExport(
        authority: AudioQAAuthority,
        expectedSelectionGeneration: UInt64
    ) async {
        guard executionSelectionGeneration == expectedSelectionGeneration else { return }
        do {
            let result: LitresExportEnvelope = try await runBridgeJSON(
                derivedAudioArguments(mode: "--litres-export-status", authority: authority)
            )
            guard !result.remoteRequestSent,
                  result.providerRequests == 0,
                  !result.billingChanged,
                  !result.export.remoteRequestSent,
                  result.export.providerRequests == 0,
                  !result.export.billingChanged else {
                throw BridgeError.message("Экспорт нарушил offline contract.")
            }
            guard executionSelectionGeneration == expectedSelectionGeneration,
                  audioQA?.authority == authority else { return }
            litresExport = result.export
            await refreshBookDeliveryStatus()
        } catch {
            guard executionSelectionGeneration == expectedSelectionGeneration else { return }
            litresExport = nil
            technicalDetails = error.localizedDescription
        }
    }

    func createCurrentLitresExport() {
        guard let authority = audioQA?.authority,
              mastering?.master != nil else {
            errorMessage = "Перед экспортом подготовьте актуальный мастер-файл."
            return
        }
        let expectedSelectionGeneration = executionSelectionGeneration
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: LitresExportEnvelope = try await runBridgeJSON(
                    derivedAudioArguments(mode: "--create-litres-export", authority: authority)
                )
                guard !result.remoteRequestSent,
                      result.providerRequests == 0,
                      !result.billingChanged,
                      result.export.chapterExport != nil else {
                    throw BridgeError.message("MP3 главы не был безопасно опубликован.")
                }
                guard executionSelectionGeneration == expectedSelectionGeneration,
                      audioQA?.authority == authority else { return }
                litresExport = result.export
                await refreshBookDeliveryStatus()
                errorMessage = nil
            } catch {
                guard executionSelectionGeneration == expectedSelectionGeneration else { return }
                showError(error)
            }
        }
    }

    func playCleanMaster() {
        guard let output = mastering?.master?.output,
              let qa = audioQA else { return }
        let binding = AudioPlaybackBinding(
            url: URL(fileURLWithPath: output.path),
            audioSHA256: output.sha256,
            pathIdentity: output.pathIdentity,
            synthesisFingerprint: mastering?.masterIdentity ?? "",
            provider: qa.authority.provider,
            profileID: qa.authority.profileID,
            bookSlug: qa.authority.bookSlug,
            jobID: qa.authority.jobID,
            segmentID: qa.authority.segmentID,
            role: "clean-master"
        )
        audioQAPlaybackIdentity = nil
        audioPlayer.loadAndPlay(binding)
        if audioPlayer.binding != binding { errorMessage = audioPlayer.errorMessage }
    }

    func playLitresMP3() {
        guard let output = litresExport?.chapterExport,
              let qa = audioQA else { return }
        let binding = AudioPlaybackBinding(
            url: URL(fileURLWithPath: output.path),
            audioSHA256: output.sha256,
            pathIdentity: output.pathIdentity,
            synthesisFingerprint: output.candidateIdentity,
            provider: qa.authority.provider,
            profileID: qa.authority.profileID,
            bookSlug: qa.authority.bookSlug,
            jobID: qa.authority.jobID,
            segmentID: qa.authority.segmentID,
            role: "litres-mp3"
        )
        audioQAPlaybackIdentity = nil
        audioPlayer.loadAndPlay(binding)
        if audioPlayer.binding != binding { errorMessage = audioPlayer.errorMessage }
    }

    func revealCleanMasterInFinder() {
        guard let path = mastering?.master?.output.path else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func revealLitresMP3InFinder() {
        guard let path = litresExport?.chapterExport?.path else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func refreshBookDeliveryStatus() async {
        guard let book = selectedBook, book.kind == "production" else {
            bookDelivery = nil
            return
        }
        let expectedBookID = book.id
        do {
            let result: BookDeliveryEnvelope = try await runBridgeJSON([
                "--delivery-selection-status", "--book", expectedBookID,
            ])
            guard !result.remoteRequestSent,
                  result.providerRequests == 0,
                  !result.paidExecution,
                  !result.billingChanged,
                  !result.delivery.remoteRequestSent,
                  result.delivery.providerRequests == 0,
                  !result.delivery.paidExecution,
                  !result.delivery.billingChanged else {
                throw BridgeError.message("Проверка формата выпуска нарушила offline contract.")
            }
            guard selectedBookID == expectedBookID else { return }
            bookDelivery = result.delivery
        } catch {
            guard selectedBookID == expectedBookID else { return }
            bookDelivery = nil
            technicalDetails = error.localizedDescription
        }
    }

    func selectBookDeliveryProfile(_ profileID: String) {
        guard let book = selectedBook,
              book.kind == "production",
              bookDelivery?.profiles.contains(where: { $0.id == profileID }) == true else {
            errorMessage = "Выбранный формат выпуска недоступен."
            return
        }
        let expectedBookID = book.id
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: BookDeliveryEnvelope = try await runBridgeJSON([
                    "--set-delivery-profile", "--book", expectedBookID,
                    "--delivery-profile-id", profileID,
                ])
                guard !result.remoteRequestSent,
                      result.providerRequests == 0,
                      !result.paidExecution,
                      !result.billingChanged,
                      result.delivery.selectedProfileID == profileID else {
                    throw BridgeError.message("Studio не подтвердила безопасное сохранение формата.")
                }
                guard selectedBookID == expectedBookID else { return }
                bookDelivery = result.delivery
                errorMessage = nil
            } catch {
                guard selectedBookID == expectedBookID else { return }
                showError(error)
            }
        }
    }

    func createBookDelivery() {
        guard let book = selectedBook,
              let delivery = bookDelivery,
              delivery.selectedProfileID != nil else {
            errorMessage = "Сначала выберите формат выпуска."
            return
        }
        guard delivery.bookReady else {
            errorMessage = "Сборка станет доступна, когда все главы будут приняты и подготовлены."
            return
        }
        let expectedBookID = book.id
        Task {
            isRunning = true
            defer { isRunning = false }
            do {
                let result: BookDeliveryEnvelope = try await runBridgeJSON([
                    "--create-book-delivery", "--book", expectedBookID,
                ])
                guard !result.remoteRequestSent,
                      result.providerRequests == 0,
                      !result.paidExecution,
                      !result.billingChanged,
                      result.delivery.delivery != nil else {
                    throw BridgeError.message("Готовый выпуск не удалось безопасно сохранить.")
                }
                guard selectedBookID == expectedBookID else { return }
                bookDelivery = result.delivery
                errorMessage = nil
            } catch {
                guard selectedBookID == expectedBookID else { return }
                showError(error)
            }
        }
    }

    func revealBookDeliveryInFinder() {
        guard let path = bookDelivery?.delivery?.output.path else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func openBookDelivery() {
        guard let path = bookDelivery?.delivery?.output.path else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
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
            let captureDirectory = FileManager.default.temporaryDirectory
                .appendingPathComponent("audiobook-studio-bridge-\(UUID().uuidString)", isDirectory: true)
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
            let error = String(decoding: try Data(contentsOf: stderrURL), as: UTF8.self)
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

    private var diagnosticWindowSize: CGSize? {
        switch ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_DIAGNOSTIC_WINDOW_SIZE"] {
        case "minimum": return CGSize(width: 900, height: 620)
        case "standard": return CGSize(width: 1060, height: 720)
        default: return nil
        }
    }

    var body: some Scene {
        WindowGroup("Audiobook Studio") {
            StudioView(model: model)
                .frame(minWidth: 900, minHeight: 620)
                .task {
                    guard let diagnosticWindowSize else { return }
                    // SwiftUI restores saved window bounds after `defaultSize`. The
                    // diagnostic render contract must exercise both accepted sizes.
                    for _ in 0..<12 {
                        try? await Task.sleep(for: .milliseconds(100))
                        if let window = NSApplication.shared.windows.first(where: { $0.title == "Audiobook Studio" }) {
                            window.setContentSize(diagnosticWindowSize)
                            break
                        }
                    }
                }
        }
        .defaultSize(
            width: diagnosticWindowSize?.width ?? 1060,
            height: diagnosticWindowSize?.height ?? 720
        )
        Settings {
            SettingsView(model: model)
                .frame(width: 520)
        }
    }
}

private enum StudioHelpTopic: String, CaseIterable, Identifiable {
    case quickStart, text, pronunciation, narrators, recording, regeneration
    case sound, listening, approval, mastering, export, costs

    var id: String { rawValue }

    var title: String {
        switch self {
        case .quickStart: return "Быстрый старт"
        case .text: return "Текст"
        case .pronunciation: return "Ударения"
        case .narrators: return "Дикторы"
        case .recording: return "Запись"
        case .regeneration: return "Как исправить фрагмент"
        case .sound: return "Звуки перед главами"
        case .listening: return "Прослушивание"
        case .approval: return "Одобрение"
        case .mastering: return "Мастеринг"
        case .export: return "Экспорт"
        case .costs: return "Расходы и лимиты"
        }
    }

    var explanation: String {
        switch self {
        case .quickStart:
            return "Выберите книгу и двигайтесь по разделам слева. Studio показывает один текущий шаг и не запускает запись без вашего действия."
        case .text:
            return "Проверьте рабочий текст для озвучки, сохраните изменения и примите его. Оригинальный файл книги не меняется."
        case .pronunciation:
            return "Введите сложное слово, прослушайте варианты ударения и сохраните подходящий вариант для этой книги."
        case .narrators:
            return "Выберите способ озвучки и голос. Технические параметры скрыты в раскрывающемся блоке."
        case .recording:
            return "Выберите главу и подготовьте запуск. Если запись платная, Studio отдельно покажет стоимость и попросит подтверждение."
        case .regeneration:
            return "После прослушивания нажмите «Исправить…»: вернитесь к тексту, поправьте ударение или выберите другого диктора. Затем снова откройте «Запись» и подготовьте новую версию. Если настройки уже верны, выберите «Записать заново с текущими настройками». Studio никогда не повторяет платный запрос автоматически."
        case .sound:
            return "Оставьте вариант «Без звукового оформления», выберите встроенный звук или добавьте свой WAV. Звук можно менять после записи голоса."
        case .listening:
            return "Откройте готовое аудио и прослушайте именно выбранную главу встроенным плеером."
        case .approval:
            return "Одобряйте главу только после прослушивания. После одобрения откроется сборка; до этого выпуск заблокирован."
        case .mastering:
            return "После сборки Studio выравнивает громкость и проверяет техническое качество итогового файла."
        case .export:
            return "Экспорт создаёт файл для публикации. Прогресс показывает, сколько глав всей книги уже готово."
        case .costs:
            return "Защитные лимиты находятся в Настройках. Подготовка плана бесплатна; платная запись требует отдельного подтверждения."
        }
    }
}

private struct StudioHelpView: View {
    let selectedTopic: StudioHelpTopic
    let onShowIntroduction: () -> Void

    private let quickStart = [
        "Добавьте или выберите книгу.",
        "Проверьте текст, который будет озвучен.",
        "Проверьте ударения в сложных словах.",
        "Выберите звук перед главами или оставьте книгу без него.",
        "Выберите диктора.",
        "Выберите главу.",
        "Подготовьте и запустите запись.",
        "Прослушайте результат.",
        "Исправьте ошибки или запросите перезапись.",
        "Примите готовую главу.",
        "Повторите запись для остальных глав.",
        "Соберите аудиокнигу.",
        "Сделайте мастеринг.",
        "Подготовьте выпуск.",
    ]

    var body: some View {
        Group {
            Section("Помощь · \(selectedTopic.title)") {
                Text(selectedTopic.explanation)
                    .font(.body)
                Button("Показать введение снова", action: onShowIntroduction)
            }
            Section("Быстрый старт") {
                ForEach(Array(quickStart.enumerated()), id: \.offset) { index, item in
                    HStack(alignment: .top, spacing: 10) {
                        Text("\(index + 1)")
                            .font(.caption.bold())
                            .frame(width: 24, height: 24)
                            .background(Circle().fill(Color.accentColor.opacity(0.14)))
                        Text(item)
                    }
                }
            }
            Section("Помощь по разделам") {
                ForEach(StudioHelpTopic.allCases.filter { $0 != .quickStart }) { topic in
                    DisclosureGroup(topic.title) {
                        Text(topic.explanation).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

private struct StudioOnboardingView: View {
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "waveform.and.book.pages")
                .font(.system(size: 42))
                .foregroundStyle(.tint)
            Text("Добро пожаловать в Audiobook Studio")
                .font(.largeTitle.weight(.semibold))
            Text("Добавьте книгу → подготовьте текст → выберите голос → запишите первую главу")
                .font(.title3)
                .foregroundStyle(.secondary)
            Text("Разделы слева проведут вас по всей работе. Подробные подсказки всегда доступны в «Помощи».")
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Начать") { isPresented = false }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(32)
        .frame(width: 620)
    }
}

private struct YandexRecoverySection: View {
    let progress: YandexChapterProgress
    let problem: YandexChapterProblemSegment
    let isRunning: Bool
    let planReady: Bool
    let onContinue: () -> Void
    let onRefresh: () -> Void

    private var continueTitle: String {
        if planReady { return "Продолжение подготовлено" }
        if isRunning { return "Подготавливаем продолжение…" }
        return problem.retryApproved ? "Подготовить продолжение записи" : "Разрешить повтор и продолжить"
    }

    var body: some View {
        Section("Запись остановлена") {
            Label(
                "Готово \(progress.completedSegments) из \(progress.totalSegments) частей",
                systemImage: "exclamationmark.triangle.fill"
            )
            .font(.headline)
            .foregroundStyle(.orange)
            Text("Введение ещё не записано полностью. Все готовые части сохранены и повторно оплачиваться не будут.")
            LabeledContent("Остановлено на части", value: "\(problem.segmentNumber) из \(progress.totalSegments)")
            VStack(alignment: .leading, spacing: 4) {
                Text("Текст книги, на котором остановилась запись")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text("«\(problem.text)»")
                    .font(.callout)
            }
            Text("Ответ Yandex не был получен из-за сетевого тайм-аута. Studio не может знать, был ли этот запрос учтён провайдером, поэтому автоматический повтор запрещён.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Button(continueTitle, action: onContinue)
                .buttonStyle(.borderedProminent)
                .disabled(isRunning || planReady)
                Button("Проверить состояние ещё раз", action: onRefresh)
                    .disabled(isRunning)
            }
            Text(planReady
                ? "Стоимость обновлена. Подтвердите озвучку главы в открывшемся окне; повторно подготавливать продолжение не нужно."
                : problem.retryApproved
                    ? "Повтор этой части уже разрешён. Studio готовит свежую стоимость и затем попросит отдельное подтверждение платной записи."
                    : "После разрешения Studio сначала покажет новую стоимость оставшихся частей. Запись начнётся только после вашего следующего подтверждения.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

@MainActor
struct StudioView: View {
    @ObservedObject var model: StudioModel
    @StateObject private var dilonFlow = DilonNativeFlowController()
    @Environment(\.openSettings) private var openSettings
    @State private var openedDiagnosticSettings = false
    @State private var showBookImporter = false
    @State private var showAddBookSheet = false
    @State private var selectedSourceURL: URL?
    @State private var newBookTitle = ""
    @State private var newBookAuthor = ""
    @State private var newBookAuthorPronunciation = ""
    @State private var newBookSlug = ""
    @State private var activeOwnerStep: OwnerProductionStep = .text
    @State private var acknowledgedOwnerSteps: Set<OwnerProductionStep> = []
    @State private var showingHelp = false
    @State private var helpTopic: StudioHelpTopic = .quickStart
    @State private var showOnboarding = false
    @AppStorage("hasSeenAuthorOnboarding") private var hasSeenAuthorOnboarding = false

    private var dilonSelectionKey: String {
        "\(model.selectedBookID)\u{1f}\(model.selectedJobID)"
    }

    private var yandexProgressSelectionKey: String {
        "\(model.engine.rawValue)\u{1f}\(model.selectedBookID)\u{1f}\(model.selectedJobID)\u{1f}\(model.selectedProfileID)"
    }

    private func syncDilonSelection() {
        guard let book = model.selectedBook, book.kind == "production",
              let job = model.selectedJob, job.kind == "chapter" else {
            dilonFlow.selectionDidChange(
                bookName: "", jobID: "", player: model.audioPlayer
            )
            return
        }
        dilonFlow.selectionDidChange(
            bookName: book.id, jobID: job.id, player: model.audioPlayer
        )
    }

    private func openHelp(_ topic: StudioHelpTopic) {
        helpTopic = topic
        showingHelp = true
    }

    private func applyDiagnosticInitialSectionIfRequested() -> Bool {
        switch ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_SECTION"] {
        case "help": openHelp(.quickStart)
        case "pronunciation": showingHelp = false; activeOwnerStep = .pronunciation
        case "sound": showingHelp = false; activeOwnerStep = .chapterSound
        case "recording": showingHelp = false; activeOwnerStep = .narrator
        case "release": showingHelp = false; activeOwnerStep = .release
        default: return false
        }
        return true
    }

    private func helpTopic(for step: OwnerProductionStep) -> StudioHelpTopic {
        switch step {
        case .text: return .text
        case .pronunciation: return .pronunciation
        case .chapterSound: return .sound
        case .narrator: return .narrators
        case .chapter, .review: return .recording
        case .release: return .export
        }
    }

    private func recoverySection(
        progress: YandexChapterProgress,
        problem: YandexChapterProblemSegment
    ) -> AnyView {
        AnyView(YandexRecoverySection(
            progress: progress,
            problem: problem,
            isRunning: model.isRunning,
            planReady: model.yandexChapterPlan?.canExecute == true,
            onContinue: {
                guard !model.isRunning, model.yandexChapterPlan?.canExecute != true else { return }
                if problem.retryApproved {
                    model.begin()
                } else {
                    model.requestYandexAmbiguousRetry(problem)
                }
            },
            onRefresh: { Task { await model.refreshYandexChapterProgress() } }
        ))
    }

    @ViewBuilder
    private func sidebarButton(
        _ title: String,
        systemImage: String,
        active: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .fontWeight(active ? .semibold : .regular)
                .foregroundStyle(active ? Color.accentColor : Color.primary)
        }
        .buttonStyle(.plain)
        .padding(.vertical, 3)
    }

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selectedBookID) {
                Section("РАБОТА С КНИГОЙ") {
                    sidebarButton("Книга", systemImage: "book.pages", active: !showingHelp && activeOwnerStep == .text) {
                        showingHelp = false
                        activeOwnerStep = .text
                    }
                    sidebarButton("Произношение", systemImage: "textformat.abc", active: !showingHelp && activeOwnerStep == .pronunciation) {
                        showingHelp = false
                        activeOwnerStep = .pronunciation
                    }
                    sidebarButton("Звуковое оформление", systemImage: "music.note", active: !showingHelp && activeOwnerStep == .chapterSound) {
                        showingHelp = false
                        activeOwnerStep = .chapterSound
                    }
                    sidebarButton(
                        "Запись",
                        systemImage: "waveform",
                        active: !showingHelp && [.narrator, .chapter, .review].contains(activeOwnerStep)
                    ) {
                        showingHelp = false
                        activeOwnerStep = .narrator
                    }
                    sidebarButton("Сборка и выпуск", systemImage: "shippingbox", active: !showingHelp && activeOwnerStep == .release) {
                        showingHelp = false
                        activeOwnerStep = .release
                    }
                }
                Section("СПРАВКА") {
                    sidebarButton("Помощь", systemImage: "questionmark.circle", active: showingHelp) {
                        openHelp(.quickStart)
                    }
                    sidebarButton("Настройки", systemImage: "gearshape", active: false) {
                        openSettings()
                    }
                }
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
                    VStack(alignment: .leading, spacing: 5) {
                        Button {
                            showBookImporter = true
                        } label: {
                            Label("Добавить книгу", systemImage: "plus")
                        }
                        .disabled(model.isAddingBook)
                        Text("TXT · UTF-8 · до 20 МБ")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("Вся книга — одним файлом")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 230, ideal: 280)
        } detail: {
            VStack(spacing: 0) {
                Form {
                    if showingHelp {
                        StudioHelpView(
                            selectedTopic: helpTopic,
                            onShowIntroduction: { showOnboarding = true }
                        )
                    } else if let book = model.selectedBook, book.kind == "production" {
                        Section("Книга") {
                            Text(book.title).font(.title2.weight(.semibold))
                            Text(book.author).foregroundStyle(.secondary)
                            HStack {
                                Label(
                                    book.sourceIntegrity == "OK" ? "Исходник защищён" : "Нужно проверить исходник",
                                    systemImage: book.sourceIntegrity == "OK" ? "checkmark.shield.fill" : "exclamationmark.shield.fill"
                                )
                                .foregroundStyle(book.sourceIntegrity == "OK" ? Color.green : Color.red)
                                Spacer()
                                Text(bookPreparationSidebarLabel(book))
                                    .foregroundStyle(book.preparationStatus == "STALE" ? Color.orange : Color.secondary)
                            }
                            DisclosureGroup("Технические сведения") {
                                LabeledContent("Source filename", value: book.sourceFilename ?? "Недоступно")
                                LabeledContent("Source SHA-256", value: book.sourceSHA256 ?? "Недоступно")
                                LabeledContent("TTS working copy", value: book.ttsWorkingCopyStatus == "CREATED" ? "Создана" : "Недоступно")
                                LabeledContent("Backend", value: book.selectedBackend ?? "Не выбран")
                                LabeledContent("Voice profile", value: book.selectedProfileID ?? "Не выбран")
                            }
                            .font(.caption)
                        }

                        OwnerProductionFlowPanel(
                            model: model,
                            activeStep: $activeOwnerStep,
                            acknowledgedSteps: $acknowledgedOwnerSteps,
                            selectedBookID: book.id,
                            selectedBookSlug: book.slug ?? book.id,
                            onOpenHelp: { openHelp(helpTopic(for: $0)) }
                        )

                    if activeOwnerStep == .narrator {
                        Section("4. Выберите диктора") {
                        Picker("Способ озвучки", selection: $model.engine) {
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
                            Picker(
                                "Голос",
                                selection: Binding(
                                    get: { model.selectedProfileID },
                                    set: { model.selectYandexProfile($0) }
                                )
                            ) {
                                ForEach(model.availableProfiles) { Text($0.label).tag($0.profileID) }
                            }
                            .pickerStyle(.radioGroup)
                            LabeledContent("Стиль", value: model.selectedProfile?.role ?? model.profile.role)
                            LabeledContent("Скорость", value: model.selectedProfile?.speed ?? model.profile.speed)
                            Text("Выбор сохранится только для этой книги.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            Picker("Голос", selection: $model.selectedProfileID) {
                                ForEach(model.availableProfiles) { Text($0.label).tag($0.profileID) }
                            }
                            Label("Каждый новый фрагмент потребует отдельного подтверждения.", systemImage: "checkmark.shield")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            DisclosureGroup("Технические параметры голоса") {
                                LabeledContent("Модель", value: model.selectedProfile?.model ?? "gpt-4o-mini-tts")
                                LabeledContent("Формат", value: (model.selectedProfile?.responseFormat ?? "wav").uppercased())
                            }
                        }
                        Button("Подробнее о дикторах") { openHelp(.narrators) }
                            .buttonStyle(.link)
                        }
                        Button("Дальше: выбрать главу") {
                            acknowledgedOwnerSteps.insert(.narrator)
                            activeOwnerStep = .chapter
                        }
                            .buttonStyle(.borderedProminent)
                    }

                    if activeOwnerStep == .chapter {
                        Section("5. Выберите главу") {
                        if let narrator = model.selectedProfile {
                            Label("Диктор: \(narrator.label)", systemImage: "person.wave.2.fill")
                                .font(.headline)
                        }
                        if model.selectedBook?.jobs.isEmpty ?? true {
                            Text("Подготовленных задач пока нет")
                                .foregroundStyle(.secondary)
                        } else if model.engine == .openai {
                            if let book = model.selectedBook, !book.jobs.isEmpty {
                                Picker("Подготовленная задача", selection: $model.selectedJobID) {
                                    ForEach(book.jobs) { job in
                                        Text(job.label).tag(job.id)
                                    }
                                }
                                .onChange(of: model.selectedJobID) { _, _ in model.paidPlan = nil }
                            } else {
                                Text("Для книги нет подготовленных задач.")
                                    .foregroundStyle(.secondary)
                            }
                            Text("Studio подготовит только один следующий фрагмент. Вся книга автоматически не запускается.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else if model.engine == .yandex {
                            if model.chapterJobs.isEmpty {
                                Text("Для книги нет подготовленных глав.")
                                    .foregroundStyle(.secondary)
                            } else {
                                Picker("Подготовленная глава", selection: $model.selectedJobID) {
                                    ForEach(model.chapterJobs) { job in
                                        Text(job.label).tag(job.id)
                                    }
                                }
                            }
                            Text("Перед записью Studio покажет стоимость и число возможных запросов. Ничего не отправится без подтверждения.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else if let book = model.selectedBook, !book.jobs.isEmpty {
                            Picker("Подготовленная задача", selection: $model.selectedJobID) {
                                ForEach(book.jobs) { job in
                                    Text(job.label).tag(job.id)
                                }
                            }
                        } else {
                            Text("Для книги нет подготовленных задач.")
                                .foregroundStyle(.secondary)
                        }
                        Button("Как выбрать главу и начать запись?") { openHelp(.recording) }
                            .buttonStyle(.link)
                        }
                        Button("Дальше: записать и прослушать") {
                            acknowledgedOwnerSteps.insert(.chapter)
                            activeOwnerStep = .review
                        }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.selectedJob == nil || model.selectedProfile == nil)
                    }

                    if activeOwnerStep == .review,
                       model.engine == .openai, let plan = model.paidPlan {
                        Section("План запуска") {
                            LabeledContent("Состояние", value: plan.decision == "CACHE_ONLY" ? "Готовое аудио найдено" : "Готово к подтверждению")
                            if let number = plan.selectedSegmentNumber {
                                LabeledContent("Часть записи", value: "\(number) из \(plan.totalSegments)")
                            }
                            LabeledContent("Новых платных запросов", value: "максимум \(plan.maxNetworkRequests)")
                            LabeledContent("Точная будущая стоимость", value: "Недоступно")
                            if !model.paidStatusText.isEmpty {
                                Text(model.paidStatusText).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }

                    if activeOwnerStep == .review,
                       model.engine == .yandex,
                       let progress = model.yandexChapterProgress,
                       let problem = progress.ambiguousSegments.first {
                        recoverySection(progress: progress, problem: problem)
                    }

                    if activeOwnerStep == .review,
                       model.engine == .yandex, let plan = model.yandexChapterPlan {
                        Section("Параметры задачи") {
                            Text("\(plan.characters.formatted()) символов · \(plan.totalSegments) частей для записи")
                            if plan.cachedSegments > 0 {
                                Text("Уже готовых частей: \(plan.cachedSegments)")
                            }
                            LabeledContent("Новых платных обращений", value: "максимум \(plan.maxNetworkRequests)")
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
                    } else if activeOwnerStep == .review,
                              model.engine == .yandex, let job = model.selectedJob {
                        Section("Параметры задачи") {
                            Text("Подготовленная глава · \(job.segmentCount) частей текста")
                            Text("Количество запросов и оценка стоимости появятся после локальной подготовки плана.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } else if activeOwnerStep == .review,
                              model.engine == .yandex, let estimate = model.estimate {
                        Section("Диагностический тариф") {
                            Text(estimate.priceStale ? "Тариф требует проверки" : "Тариф проверен: \(russianDate(estimate.priceVerifiedAt))")
                                .foregroundStyle(estimate.priceStale ? .orange : .secondary)
                            DisclosureGroup("Подробности") {
                                Text("Единицы тарификации: \(estimate.totalBillingUnits)")
                                Text("Цена единицы: \(estimate.unitPrice ?? "не настроена") ₽")
                            }
                        }
                    }

                    if activeOwnerStep == .review {
                        AudioQAReviewSection(model: model, activeStep: $activeOwnerStep)
                        Button("Как прослушать, исправить или принять главу?") { openHelp(.regeneration) }
                            .buttonStyle(.link)
                        Button("Дальше: собрать готовую книгу") { activeOwnerStep = .release }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.audioQA?.record.manualState != "APPROVED")
                    }

                    if activeOwnerStep == .release {
                        OwnerReleaseSection(model: model)
                        Button("Подробнее о мастеринге и выпуске") { openHelp(.mastering) }
                            .buttonStyle(.link)
                    }

                    if activeOwnerStep == .release, let snapshot = dilonFlow.snapshot {
                        DilonNativeCard(
                            snapshot: snapshot,
                            player: model.audioPlayer,
                            selectedCandidateID: $dilonFlow.selectedCandidateID,
                            onApproveListenedCandidate: { candidate in
                                dilonFlow.approveListenedCandidate(
                                    candidate, player: model.audioPlayer
                                )
                            }
                        )
                        if !dilonFlow.statusText.isEmpty {
                            Section("Фирменная заставка") {
                                Label(dilonFlow.statusText, systemImage: "checkmark.shield.fill")
                                    .foregroundStyle(.green)
                            }
                        }
                    } else if activeOwnerStep == .release,
                              model.selectedBook?.kind == "production",
                              model.selectedJob?.kind == "chapter" {
                        Section("Dilon Voices") {
                            if dilonFlow.isLoading {
                                ProgressView("Проверяется фирменная заставка…")
                            } else if let error = dilonFlow.errorMessage {
                                Label(error, systemImage: "lock.shield")
                                    .foregroundStyle(.secondary)
                                Button("Проверить снова") {
                                    dilonFlow.refresh(player: model.audioPlayer)
                                }
                            } else {
                                Label("Фирменная заставка пока недоступна", systemImage: "lock.fill")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    } else {
                        Section {
                            VStack(alignment: .leading, spacing: 12) {
                                Label("Начните с книги", systemImage: "book.closed")
                                    .font(.title2.weight(.semibold))
                                Text("Добавьте файл книги — Studio проведёт вас от проверки текста до готового аудио.")
                                    .foregroundStyle(.secondary)
                                BookImportRequirements()
                                Button("Выбрать TXT-файл") { showBookImporter = true }
                                    .buttonStyle(.borderedProminent)
                            }
                            .padding(.vertical, 24)
                        }
                    }

                }
                .formStyle(.grouped)
                .padding(.top, 8)

                if model.selectedBook?.kind == "production", activeOwnerStep == .review {
                    Divider()
                    HStack {
                        VStack(alignment: .leading) {
                            Text(model.isRunning ? "Идёт запись главы" : "Запись и прослушивание")
                                .font(.headline)
                            if let output = model.completedOutput {
                                Text(output.lastPathComponent).foregroundStyle(.secondary)
                            } else {
                                Text("Сначала подготовьте запуск. Запись начнётся только после отдельного подтверждения, если оно требуется.")
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        if let output = model.completedOutput {
                            Button("Прослушать") { NSWorkspace.shared.open(output) }
                            Button("Показать в Finder") { NSWorkspace.shared.activateFileViewerSelecting([output]) }
                        }
                        if model.audioQA == nil
                            || model.audioQA?.record.manualState == "REJECTED"
                            || model.audioQA?.record.manualState == "REGENERATE_REQUESTED" {
                            Button(primaryButtonTitle(model)) { model.begin() }
                                .buttonStyle(.borderedProminent)
                                .disabled(
                                    model.isRunning || model.isLoading || model.isAddingBook
                                        || model.isPreparingBookText
                                        || (model.selectedBook?.jobs.isEmpty ?? true)
                                        || (model.engine == .yandex && model.selectedJob?.kind != "chapter")
                                )
                        }
                    }
                    .padding()
                    if let details = model.technicalDetails {
                        DisclosureGroup("Технические подробности") {
                            Text(details).font(.caption.monospaced())
                        }
                        .padding([.horizontal, .bottom])
                    }
                }
            }
            .overlay {
                if model.isLoading { ProgressView("Загрузка Studio…") }
            }
            .navigationTitle(showingHelp ? "Как пользоваться Audiobook Studio" : (model.selectedBook?.title ?? "Audiobook Studio"))
            .task(id: dilonSelectionKey) {
                syncDilonSelection()
            }
            .task(id: yandexProgressSelectionKey) {
                await model.refreshYandexChapterProgress()
            }
            .onChange(of: model.selectedBookID) { _, _ in
                model.cancelBookTextPreparation()
                model.selectDefaultJob()
                model.selectDefaultProfile()
                Task { await model.refreshBookDeliveryStatus() }
                acknowledgedOwnerSteps = []
                if !applyDiagnosticInitialSectionIfRequested() {
                    showingHelp = false
                    activeOwnerStep = .text
                }
            }
            .toolbar { ToolbarItem { SettingsLink { Label("Настройки", systemImage: "gearshape") } } }
            .task {
                _ = applyDiagnosticInitialSectionIfRequested()
                if !hasSeenAuthorOnboarding,
                   ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_SKIP_ONBOARDING"] != "1" {
                    showOnboarding = true
                }
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
                    Text("Yandex SpeechKit\nГлава: \(plan.jobLabel)\nГолос: \(plan.voice.capitalized) · \(plan.role) · \(plan.speed)\nЧастей записи: \(plan.totalSegments)\nНовых платных обращений: максимум \(plan.maxNetworkRequests)\nОценка: \(formattedMoney(plan.estimatedRemainingCost, currency: plan.currency, source: "local_estimate"))\nЛимит Studio: \(formattedMoney(plan.hardLimit, currency: plan.currency, source: "local_actual"))")
                }
            }
            .confirmationDialog(
                "Разрешить новый запрос для проблемной части?",
                isPresented: $model.showYandexRetryConfirmation,
                titleVisibility: .visible
            ) {
                Button("Разрешить подготовку повтора") { model.confirmYandexAmbiguousRetry() }
                Button("Отмена", role: .cancel) { model.cancelYandexAmbiguousRetry() }
            } message: {
                Text("Предыдущий запрос завершился неопределённо и мог быть учтён Yandex. Это действие пока ничего не отправляет: Studio только снимет блокировку и покажет обновлённую стоимость. Новый платный запуск потребует отдельного подтверждения.")
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
                Text("Исходный файл не изменится. Studio подготовит отдельный рабочий текст; запись и платные обращения не запускаются.")
            }
            .fileImporter(
                isPresented: $showBookImporter,
                allowedContentTypes: [audiobookTextFileType],
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case let .success(urls):
                    guard let url = urls.first else { return }
                    selectedSourceURL = url
                    newBookTitle = url.deletingPathExtension().lastPathComponent
                    newBookAuthor = ""
                    newBookAuthorPronunciation = ""
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
                    authorPronunciation: $newBookAuthorPronunciation,
                    slug: $newBookSlug,
                    isPresented: $showAddBookSheet
                )
            }
            .sheet(isPresented: $showOnboarding, onDismiss: {
                hasSeenAuthorOnboarding = true
            }) {
                StudioOnboardingView(isPresented: $showOnboarding)
            }
        }
    }
}

private struct AudioQAReviewSection: View {
    @ObservedObject var model: StudioModel
    @Binding var activeStep: OwnerProductionStep

    var body: some View {
        Group {
            if model.engine == .openai, model.openAIQATargets.count > 1 {
                Section("Выберите часть записи для проверки") {
                    ForEach(model.openAIQATargets) { target in
                        Button("Проверить часть \(target.segmentID)") {
                            model.openOpenAIQATarget(target)
                        }
                        .disabled(model.isRunning)
                    }
                    Text("Выберите одну конкретную часть: Studio не позволит случайно одобрить другой файл.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Обновить список") {
                        model.refreshOpenAIQATargets()
                    }
                    .disabled(model.isRunning)
                }
            }
            if let qa = model.audioQA {
                Section("6. Прослушивание и приёмка") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(qa.authority.jobLabel)
                                    .font(.title3.weight(.semibold))
                                Text("\(qa.authority.bookTitle) · \(audioQAProviderLabel(qa.authority.provider))")
                                    .foregroundStyle(.secondary)
                                Text("Голос: \(audioQAVoiceLabel(qa.authority.profileID))")
                                    .font(.callout)
                            }
                            Spacer()
                            Label(
                                audioQAStatusLabel(qa.record.automaticStatus),
                                systemImage: qa.record.automaticStatus == "FAIL"
                                    ? "xmark.octagon.fill" : "checkmark.seal.fill"
                            )
                            .foregroundStyle(qa.record.automaticStatus == "FAIL" ? Color.red : Color.green)
                        }
                        if let wav = qa.record.wav {
                            Text("\(audioTimeLabel(wav.durationSeconds)) · \(wav.sampleRateHz.formatted()) Гц · \(wav.channels == 1 ? "моно" : "\(wav.channels) канала")")
                                .font(.callout.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                    }

                    AudioTransportCard(
                        player: model.audioPlayer,
                        role: "qa-source",
                        playTitle: "Прослушать главу",
                        onLoad: model.playExactAudioForQA,
                        onReveal: model.revealCurrentAudioInFinder
                    )

                    LabeledContent("Ваше решение", value: audioQAManualLabel(qa.record.manualState))
                    DisclosureGroup("Текст этой записи · \(qa.authority.textCharacters) символов") {
                        Text(qa.authority.segmentText).textSelection(.enabled)
                    }
                    ForEach(qa.record.automaticReasons, id: \.self) { reason in
                        Label(audioQAReasonLabel(reason), systemImage: "xmark.octagon").foregroundStyle(.red)
                    }
                    ForEach(qa.record.automaticWarnings, id: \.self) { warning in
                        Label(audioQAWarningLabel(warning), systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    }
                    HStack {
                        Button("Одобрить") { model.decideAudioQA("APPROVED") }
                            .buttonStyle(.borderedProminent)
                            .disabled(
                                model.isRunning
                                    || qa.record.automaticStatus == "FAIL"
                                    || model.audioQAPlaybackIdentity != qa.record.identity
                            )
                        Menu("Исправить…") {
                            Button("Исправить текст") { activeStep = .text }
                            Button("Исправить ударение") { activeStep = .pronunciation }
                            Button("Выбрать другого диктора") { activeStep = .narrator }
                            Divider()
                            Button("Записать заново с текущими настройками") {
                                model.decideAudioQA("REGENERATE_REQUESTED")
                            }
                            Button("Отклонить этот вариант", role: .destructive) {
                                model.decideAudioQA("REJECTED")
                            }
                        }
                        .disabled(model.isRunning)
                    }
                    Label(
                        model.downstreamApprovedOutput == nil
                            ? "Следующий этап недоступен до точного одобрения"
                            : "Готово к следующему этапу",
                        systemImage: model.downstreamApprovedOutput == nil ? "lock.fill" : "checkmark.shield.fill"
                    )
                    .foregroundStyle(model.downstreamApprovedOutput == nil ? Color.secondary : Color.green)

                    DisclosureGroup("Технические подробности") {
                        LabeledContent("Сегмент", value: qa.authority.segmentID)
                        LabeledContent("SHA-256", value: qa.record.identity.audioSHA256 ?? "Недоступно")
                        LabeledContent("Synthesis fingerprint", value: qa.record.identity.synthesisFingerprint ?? "Недоступно")
                        LabeledContent("Path identity", value: qa.record.identity.pathIdentity)
                        LabeledContent("WAV", value: qa.record.audioPath)
                        LabeledContent("Manifest", value: qa.authority.manifestPath)
                        LabeledContent("FFmpeg", value: qa.record.ffmpeg.version ?? "Недоступно")
                        if let path = qa.record.ffmpeg.path {
                            LabeledContent("FFmpeg path", value: path)
                        }
                        if !qa.record.automaticReasons.isEmpty {
                            Text("Коды ошибок: \(qa.record.automaticReasons.joined(separator: ", "))")
                        }
                        if !qa.record.automaticWarnings.isEmpty {
                            Text("Коды предупреждений: \(qa.record.automaticWarnings.joined(separator: ", "))")
                        }
                    }
                    if !model.audioQAStatusText.isEmpty {
                        Text(model.audioQAStatusText).font(.caption).foregroundStyle(.secondary)
                    }
                }
            } else if model.engine == .qwen || model.engine == .yandex || model.engine == .openai {
                Section("6. Прослушивание и приёмка") {
                    Button("Открыть готовое аудио для проверки") { model.openCurrentAudioForQA() }
                        .disabled(model.isRunning || model.selectedJob == nil || model.selectedProfile == nil)
                    Text("Studio откроет уже готовое аудио. Новая запись и платные запросы не запускаются.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}

private struct OwnerReleaseSection: View {
    @ObservedObject var model: StudioModel

    var body: some View {
        Section("7. Соберите готовую аудиокнигу") {
            Text("Сначала подготовьте принятые главы, затем выберите, как сохранить готовую книгу.")
                .foregroundStyle(.secondary)
            BookDeliveryCard(model: model)
            if let qa = model.audioQA {
                ChapterAssemblyCard(model: model, qa: qa)
                if model.chapterAssembly?.assembly != nil {
                    MasteringCard(model: model)
                }
            } else {
                Label("Для подготовки файлов глав сначала запишите и примите главу на шаге 6", systemImage: "lock.fill")
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct AudioTransportCard: View {
    @ObservedObject var player: EmbeddedAudioPlayer
    let role: String
    let playTitle: String
    let onLoad: () -> Void
    let onReveal: () -> Void

    private var isCurrent: Bool { player.binding?.role == role }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button {
                    if isCurrent { player.togglePlayPause() } else { onLoad() }
                } label: {
                    Label(
                        isCurrent && player.state == .playing ? "Пауза" : playTitle,
                        systemImage: isCurrent && player.state == .playing ? "pause.fill" : "play.fill"
                    )
                }
                .buttonStyle(.borderedProminent)
                Button("Стоп", systemImage: "stop.fill") { player.stop() }
                    .disabled(!isCurrent || player.state == .stopped)
                Spacer()
                Button("Показать в Finder", systemImage: "folder") { onReveal() }
                    .buttonStyle(.borderless)
            }
            HStack(spacing: 10) {
                Text(audioTimeLabel(isCurrent ? player.elapsed : 0))
                    .monospacedDigit()
                    .frame(width: 44, alignment: .leading)
                Slider(
                    value: Binding(
                        get: { isCurrent ? player.elapsed : 0 },
                        set: { player.seek(to: $0) }
                    ),
                    in: 0...max(isCurrent ? player.duration : 0, 0.001)
                )
                .disabled(!isCurrent || player.duration <= 0)
                Text(audioTimeLabel(isCurrent ? player.duration : 0))
                    .monospacedDigit()
                    .frame(width: 44, alignment: .trailing)
            }
            Text(isCurrent ? playbackStateLabel(player.state) : "Готово к воспроизведению")
                .font(.caption)
                .foregroundStyle(player.state == .error ? Color.red : Color.secondary)
            if isCurrent, let error = player.errorMessage {
                Text(error).font(.caption).foregroundStyle(.red)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 12))
    }
}

private struct ChapterAssemblyCard: View {
    @ObservedObject var model: StudioModel
    let qa: AudioQACurrentEnvelope

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !qa.eligible {
                Label("Сборка главы недоступна — требуется одобрение", systemImage: "lock.fill")
                    .font(.headline)
                    .foregroundStyle(.secondary)
            } else if let assembly = model.chapterAssembly {
                HStack {
                    Label(
                        "Мастер-файл главы",
                        systemImage: assembly.assembly == nil ? "waveform.badge.plus" : "waveform.badge.checkmark"
                    )
                    .font(.headline)
                    Spacer()
                    Text(chapterAssemblyStateLabel(assembly.state, decision: assembly.decision))
                        .foregroundStyle(assembly.decision == "BLOCKED" ? Color.orange : Color.secondary)
                }
                Text("Готовый мастер-файл главы можно прослушать перед выпуском.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let counts = assembly.segmentCounts, counts.expected > 1 {
                    Text("Готово \(counts.produced) из \(counts.expected) частей")
                    Text("Одобрено \(counts.approved) из \(counts.expected)")
                    if counts.blocked > 0 {
                        Text("Сборка главы недоступна")
                            .foregroundStyle(.orange)
                    }
                }
                if let blockerMessage = assembly.blockerMessage {
                    Label(blockerMessage, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                } else if assembly.assembly == nil {
                    Button("Собрать главу") { model.assembleCurrentChapter() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isRunning || assembly.decision != "READY_TO_ASSEMBLE")
                } else {
                    AudioTransportCard(
                        player: model.audioPlayer,
                        role: "assembled-chapter",
                        playTitle: "Прослушать мастер-файл",
                        onLoad: model.playAssembledChapter,
                        onReveal: model.revealAssembledChapterInFinder
                    )
                }
                DisclosureGroup("Технические подробности сборки") {
                    LabeledContent("Assembly identity", value: assembly.assemblyIdentity)
                    LabeledContent("FFmpeg", value: assembly.ffmpeg.version ?? "Недоступно")
                    if let manifestPath = assembly.manifestPath {
                        LabeledContent("Manifest", value: manifestPath)
                    }
                    if let output = assembly.assembly?.output {
                        LabeledContent("SHA-256", value: output.sha256)
                        LabeledContent("WAV", value: output.path)
                    }
                    if !assembly.blockers.isEmpty {
                        Text("Blockers: \(assembly.blockers.joined(separator: ", "))")
                    }
                    ForEach(assembly.segmentBlockers ?? [], id: \.self) { blocker in
                        Text("\(blocker.segmentID): \(blocker.reason)")
                    }
                }
            } else {
                Label("Проверяется готовность сборки главы", systemImage: "clock")
                    .font(.headline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct MasteringCard: View {
    @ObservedObject var model: StudioModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Мастеринг", systemImage: model.mastering?.master == nil ? "dial.medium" : "checkmark.seal")
                    .font(.headline)
                Spacer()
                if let mastering = model.mastering {
                    Text(masteringStateLabel(mastering.state, decision: mastering.decision))
                        .foregroundStyle(mastering.decision == "BLOCKED" ? Color.orange : Color.secondary)
                }
            }
            if let mastering = model.mastering {
                Text("Studio выровняет громкость и проверит качество итоговой главы.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Технические параметры доступны ниже в подробностях.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let blocker = mastering.blockerMessage {
                    Label(blocker, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                } else if mastering.master == nil {
                    Button("Подготовить мастер") { model.createCurrentMaster() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isRunning || mastering.decision != "READY_TO_MASTER")
                } else {
                    if mastering.decision == "READY_TO_REPAIR" {
                        Button("Восстановить мастер-файл") { model.createCurrentMaster() }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.isRunning)
                    }
                    AudioTransportCard(
                        player: model.audioPlayer,
                        role: "clean-master",
                        playTitle: "Прослушать мастер-файл",
                        onLoad: model.playCleanMaster,
                        onReveal: model.revealCleanMasterInFinder
                    )
                }
                ForEach(mastering.master?.warnings ?? [], id: \.self) { warning in
                    Label(
                        warning == "excessive_leading_boundary_silence"
                            ? "В начале главы необычно длинная тишина"
                            : "В конце главы необычно длинная тишина",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                }
                DisclosureGroup("Технические подробности мастеринга") {
                    LabeledContent("Preset", value: mastering.masterPreset.id)
                    LabeledContent("Preset hash", value: mastering.masterPresetHash)
                    LabeledContent("Master identity", value: mastering.masterIdentity)
                    LabeledContent("FFmpeg", value: mastering.ffmpeg.version ?? "Недоступно")
                    if let manifest = mastering.manifestPath {
                        LabeledContent("Manifest", value: manifest)
                    }
                    if let master = mastering.master {
                        LabeledContent("SHA-256", value: master.output.sha256)
                        LabeledContent("LUFS-I", value: master.verification.loudness.inputI.formatted())
                        LabeledContent("True peak", value: "\(master.verification.loudness.inputTp.formatted()) dBTP")
                        LabeledContent("RMS", value: "\(master.verification.signal.rmsDbfs.formatted()) dBFS")
                        LabeledContent("Начальная тишина", value: "\(master.verification.boundarySilence.leadingSilenceSeconds.formatted()) с")
                        LabeledContent("Конечная тишина", value: "\(master.verification.boundarySilence.trailingSilenceSeconds.formatted()) с")
                    }
                }
            } else {
                Text("Проверяется текущая версия главы…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct BookDeliveryCard: View {
    @ObservedObject var model: StudioModel

    private func blockerLabel(_ code: String) -> String {
        switch code {
        case "missing_chapters": return "Подготовлены не все главы"
        case "missing_cover": return "Обложка не выбрана"
        case "duplicate_chapters": return "Обнаружены дубли глав"
        case "unknown_extra_chapters": return "Есть главы вне текущей структуры книги"
        case "unproven_third_party_assets": return "Не подтверждены права на сторонние материалы"
        case "chapter_cue_rights_unverified": return "Подтвердите право использовать выбранный звук перед главами"
        default: return "Книга пока не готова к выпуску"
        }
    }

    private func profileIcon(_ id: String) -> String {
        switch id {
        case "chapters": return "list.number"
        case "m4b": return "book.closed.fill"
        case "mp3": return "waveform"
        default: return "archivebox.fill"
        }
    }

    @ViewBuilder
    private func chapterFiles(_ export: LitresExportStatus?) -> some View {
        if model.mastering?.master == nil {
            Label("Сначала подготовьте мастер-файл текущей главы", systemImage: "lock.fill")
                .foregroundStyle(.secondary)
        } else if let export {
            if let blocker = export.blockerMessage {
                Label(blocker, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
            } else if export.decision == "READY_TO_REPACKAGE" {
                Button("Обновить файл главы") { model.createCurrentLitresExport() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isRunning)
            } else if export.decision == "READY_TO_REPAIR" {
                Button("Восстановить файл главы") { model.createCurrentLitresExport() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isRunning)
            } else if export.chapterExport == nil {
                Button("Создать файл текущей главы") { model.createCurrentLitresExport() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isRunning || export.decision != "READY_TO_EXPORT")
            } else if let chapter = export.chapterExport {
                Text("Глава готова · \(audioTimeLabel(chapter.facts.durationSeconds)) · \(ByteCountFormatter.string(fromByteCount: Int64(chapter.facts.sizeBytes), countStyle: .file))")
                    .font(.callout)
                AudioTransportCard(
                    player: model.audioPlayer,
                    role: "litres-mp3",
                    playTitle: "Прослушать готовую главу",
                    onLoad: model.playLitresMP3,
                    onReveal: model.revealLitresMP3InFinder
                )
            }
        } else {
            ProgressView("Проверяется текущая глава…")
                .controlSize(.small)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Формат выпуска", systemImage: "square.and.arrow.down")
                .font(.headline)
            Text("Выберите один вариант. Studio запомнит его только для этой книги.")
                .font(.callout)
                .foregroundStyle(.secondary)

            if let delivery = model.bookDelivery {
                VStack(spacing: 8) {
                    ForEach(delivery.profiles) { profile in
                        let selected = delivery.selectedProfileID == profile.id
                        Button {
                            model.selectBookDeliveryProfile(profile.id)
                        } label: {
                            HStack(alignment: .top, spacing: 12) {
                                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                                    .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                                    .font(.title3)
                                Image(systemName: profileIcon(profile.id))
                                    .frame(width: 22)
                                    .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(profile.title).fontWeight(.semibold)
                                    Text(profile.description)
                                        .font(.callout)
                                        .foregroundStyle(.secondary)
                                    Text(profile.detail)
                                        .font(.caption)
                                        .foregroundStyle(.tertiary)
                                }
                                Spacer()
                            }
                            .contentShape(Rectangle())
                            .padding(10)
                            .background(
                                selected ? Color.accentColor.opacity(0.09) : Color.secondary.opacity(0.045),
                                in: RoundedRectangle(cornerRadius: 10)
                            )
                            .overlay {
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(selected ? Color.accentColor.opacity(0.55) : Color.secondary.opacity(0.12))
                            }
                        }
                        .buttonStyle(.plain)
                        .disabled(model.isRunning)
                    }
                }

                if delivery.selectedProfileID == nil {
                    Label("Выберите формат, чтобы продолжить", systemImage: "hand.tap")
                        .font(.callout.weight(.medium))
                        .foregroundStyle(.secondary)
                    Button("Собрать аудиокнигу") {}
                        .buttonStyle(.borderedProminent)
                        .disabled(true)
                } else if delivery.selectedProfileID == "chapters" {
                    Divider()
                    chapterFiles(model.litresExport)
                } else {
                    Divider()
                    Text("Готово \(delivery.readyChapters) из \(delivery.expectedChapters) глав")
                        .font(.callout.weight(.medium))
                    if let artifact = delivery.delivery {
                        Label("Аудиокнига собрана", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                        Text("\(ByteCountFormatter.string(fromByteCount: Int64(artifact.output.sizeBytes), countStyle: .file))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        HStack {
                            if delivery.selectedProfileID != "hq_archive" {
                                Button("Открыть") { model.openBookDelivery() }
                                    .buttonStyle(.borderedProminent)
                            }
                            Button("Показать в Finder") { model.revealBookDeliveryInFinder() }
                        }
                    } else if delivery.bookReady {
                        Button("Собрать аудиокнигу") { model.createBookDelivery() }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.isRunning)
                    } else {
                        Button("Собрать аудиокнигу") {}
                            .buttonStyle(.borderedProminent)
                            .disabled(true)
                        Label("Единый файл станет доступен, когда все главы будут приняты и подготовлены", systemImage: "lock.fill")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        ForEach(delivery.blockers, id: \.self) { blocker in
                            Text("• \(blockerLabel(blocker))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                DisclosureGroup("Технические сведения") {
                    if let artifact = delivery.delivery {
                        LabeledContent("SHA-256", value: artifact.output.sha256)
                        LabeledContent("Файл", value: artifact.output.path)
                    }
                    LabeledContent("Сетевые запросы", value: "0")
                    LabeledContent("Платные действия", value: "0")
                }
                .font(.caption)
            } else {
                ProgressView("Проверяются форматы выпуска…")
                    .controlSize(.small)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct AddBookSheet: View {
    @ObservedObject var model: StudioModel
    let sourceURL: URL?
    @Binding var title: String
    @Binding var author: String
    @Binding var authorPronunciation: String
    @Binding var slug: String
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Добавить книгу").font(.title2.weight(.semibold))
            BookImportRequirements()
            LabeledContent("TXT-файл", value: sourceURL?.lastPathComponent ?? "Не выбран")
            TextField("Название", text: $title)
            TextField("Автор", text: $author)
                .onChange(of: author) { oldValue, newValue in
                    if authorPronunciation.isEmpty || authorPronunciation == oldValue {
                        authorPronunciation = newValue
                    }
                }
            TextField("Как диктор должен произнести имя автора", text: $authorPronunciation)
            Text("Поставьте ударение прямо в имени: например, «Еле́на Ди́лон».")
                .font(.caption)
                .foregroundStyle(.secondary)
            DisclosureGroup("Дополнительно") {
                TextField("Короткое имя книги", text: $slug)
                Text("Обычно менять его не нужно.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text("Studio сохранит оригинал без изменений и создаст отдельный текст для озвучки.")
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
                            authorPronunciation: authorPronunciation,
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
                        || authorPronunciation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || slug.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || model.isAddingBook
                )
            }
        }
        .padding(24)
        .frame(width: 480)
    }
}

private struct BookImportRequirements: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("Поддерживается TXT в кодировке UTF-8 · до 20 МБ", systemImage: "doc.text")
                .font(.subheadline.weight(.medium))
            Text("Загрузите всю книгу одним файлом. Заголовки глав лучше размещать на отдельных строках — Studio распознает их при подготовке текста.")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("Оригинал останется без изменений; для редактирования и озвучки будет создана отдельная копия.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
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
                Text("Подготовка плана ничего не записывает и не списывает средства. Новая платная запись потребует отдельного подтверждения.")
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
                Text("Studio использует уже готовое аудио. Новое платное обращение не отправляется.")
            }
            .confirmationDialog(
                "Подтвердить одну платную запись OpenAI?",
                isPresented: $model.showPaidConfirmation,
                titleVisibility: .visible
            ) {
                if model.paidPlan?.canExecute == true,
                   model.paidPlan?.decision == "READY_FOR_CONFIRMATION" {
                Button("Подтвердить одну платную запись") { model.confirmPaidRequest() }
                }
                Button("Отмена", role: .cancel) { model.showPaidConfirmation = false }
            } message: {
                if let plan = model.paidPlan {
                    Text("OpenAI\nГолос: \(plan.voice.capitalized)\nМодель: \(plan.model)\nКнига: \(plan.bookTitle)\nЗадача: \(plan.jobLabel)\nЧасть записи: \(plan.selectedSegmentNumber ?? 0) из \(plan.totalSegments)\nСимволов: \(plan.selectedSegmentCharacters)\nГотового аудио нет\nНовых платных обращений: максимум 1\nТочная будущая стоимость: Недоступно\nЛимит Studio: \(formattedMoney(plan.hardLimit, currency: plan.currency, source: "local_actual"))\nДоступный остаток: \(formattedMoney(plan.billing.remaining, currency: plan.currency, source: plan.billing.remainingSource))\n\nOpenAI не сообщает точную стоимость будущего аудио до записи. После подтверждения Studio сможет отправить максимум одно новое платное обращение.")
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
        return "Подготовить следующую часть"
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
                    LabeledContent("Папка результатов", value: "Папка проекта Audiobook Studio")
                }
                Section("Локальная запись") {
                    LabeledContent("Статус", value: "Работает на этом Mac")
                    Button("Проверить готовность") { Task { await model.reload() } }
                }
                Section("Yandex SpeechKit") {
                    LabeledContent("Диктор текущей книги", value: model.engine == .yandex ? (model.selectedProfile?.label ?? "Не выбран") : "Выберите в разделе «Запись»")
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
                    LabeledContent("Подтверждение", value: "Перед каждым новым платным фрагментом")
                    HStack {
                        TextField("Максимальная стоимость задачи, $", text: $model.openAIHardLimitText)
                        Button("Сохранить") { model.saveOpenAIHardLimit() }
                    }
                    Text("Локальный лимит одной задачи; это не остаток на счёте.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .id("openai-settings")
                Section("Данные сервисов") {
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
                Section("Расходы и лимиты") {
                    if model.engine == .qwen {
                        Label("Локальный движок · расходы API отсутствуют", systemImage: "laptopcomputer")
                            .foregroundStyle(.secondary)
                    } else if let billing = model.selectedBilling {
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
                        Button("Обновить данные") { model.refreshBilling(model.engine) }
                    }
                    Text("Расходы вынесены из рабочего экрана записи и находятся только в Настройках.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("Текст и произношение") {
                    Text("Редактор текста, ударения и контроль качества находятся в шагах 1–2 выбранной книги. Так вы всегда меняете именно тот текст, который собираетесь записывать.")
                        .foregroundStyle(.secondary)
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
