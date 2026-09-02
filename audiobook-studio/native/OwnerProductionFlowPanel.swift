import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

private struct OwnerSoundWorkspaceContract: Decodable {
    let workspaceRoot: String
    enum CodingKeys: String, CodingKey { case workspaceRoot = "workspace_root" }
}

private struct OwnerSoundPaths {
    let root: URL
    var runtimeRoot: URL { root.appendingPathComponent("runtime/studio-workspace", isDirectory: true) }
    var qwenPython: URL { root.appendingPathComponent("engines/qwen-mlx/.venv/bin/python") }

    static func load() -> OwnerSoundPaths {
        let environment = ProcessInfo.processInfo.environment
        if let override = environment["AUDIOBOOK_STUDIO_HOME"], !override.isEmpty {
            return OwnerSoundPaths(root: URL(fileURLWithPath: override, isDirectory: true))
        }
        let defaultRoot = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/New project/Audiobook-Studio", isDirectory: true)
        let contractURL = environment["AUDIOBOOK_STUDIO_PATH_CONTRACT"]
            .map { URL(fileURLWithPath: $0) }
            ?? defaultRoot.appendingPathComponent("settings/workspace-paths.json")
        if let data = try? Data(contentsOf: contractURL),
           let contract = try? JSONDecoder().decode(OwnerSoundWorkspaceContract.self, from: data),
           !contract.workspaceRoot.isEmpty {
            return OwnerSoundPaths(root: URL(fileURLWithPath: contract.workspaceRoot, isDirectory: true))
        }
        return OwnerSoundPaths(root: defaultRoot)
    }
}

private let ownerSoundPaths = OwnerSoundPaths.load()
private let ownerSoundPython = ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_PYTHON"]
    ?? ownerSoundPaths.qwenPython.path

struct BookSoundOption: Codable, Identifiable, Hashable {
    let soundID: String
    let label: String
    let description: String
    let path: String
    let sha256: String
    let durationSeconds: Double
    let origin: String
    let rights: String
    let genres: [String]?
    let sourceDurationSeconds: Double?
    let selectionStartSeconds: Double?
    let selectionDurationSeconds: Double?
    let isFavorite: Bool?

    var id: String { soundID }

    enum CodingKeys: String, CodingKey {
        case label, description, path, sha256, origin, rights, genres
        case soundID = "sound_id"
        case durationSeconds = "duration_seconds"
        case sourceDurationSeconds = "source_duration_seconds"
        case selectionStartSeconds = "selection_start_seconds"
        case selectionDurationSeconds = "selection_duration_seconds"
        case isFavorite = "is_favorite"
    }
}

struct GarageBandSoundDiscovery: Codable, Hashable {
    let requestedHistoricalLabel: String
    let requestedHistoricalAsset: String
    let similarLocalAsset: String
    let available: Bool
    let selectable: Bool
    let message: String

    enum CodingKeys: String, CodingKey {
        case available, selectable, message
        case requestedHistoricalLabel = "requested_historical_label"
        case requestedHistoricalAsset = "requested_historical_asset"
        case similarLocalAsset = "similar_local_asset"
    }
}

struct BookSoundStatus: Codable, Hashable {
    let bookSlug: String
    let enabled: Bool
    let soundID: String
    let applyBefore: String
    let clipStartSeconds: Double
    let clipDurationSeconds: Double
    let selected: BookSoundOption
    let options: [BookSoundOption]
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool
    let garageBandDiscovery: GarageBandSoundDiscovery?

    enum CodingKeys: String, CodingKey {
        case enabled, selected, options
        case bookSlug = "book_slug"
        case soundID = "sound_id"
        case applyBefore = "apply_before"
        case clipStartSeconds = "clip_start_seconds"
        case clipDurationSeconds = "clip_duration_seconds"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
        case garageBandDiscovery = "garageband_discovery"
    }
}

private struct BookSoundError: Codable {
    let message: String?
}

@MainActor
final class BookSoundController: NSObject, ObservableObject, NSSoundDelegate {
    @Published private(set) var status: BookSoundStatus?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    @Published private(set) var previewSoundID: String?
    @Published private(set) var previewIsPlaying = false
    @Published private(set) var previewIsPaused = false
    @Published var clipStartSeconds = 0.0
    @Published var clipDurationSeconds = 3.0
    @Published var selectedGenre = "Избранное"
    private var bookID = ""
    private var previewSound: NSSound?

    func reload(bookID: String) async {
        if self.bookID != bookID {
            stopPreview()
        }
        self.bookID = bookID
        guard !bookID.isEmpty else {
            status = nil
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let loaded: BookSoundStatus = try await runJSON([
                "--book", bookID,
                "--status",
            ])
            try assertOffline(loaded)
            accept(loaded)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setEnabled(_ enabled: Bool) {
        guard let status else { return }
        save(enabled: enabled, soundID: status.soundID)
    }

    func select(_ soundID: String) {
        guard let status else { return }
        save(enabled: status.enabled, soundID: soundID)
    }

    func choose(_ soundID: String) {
        save(enabled: true, soundID: soundID)
    }

    func saveExcerpt() {
        guard let status else { return }
        save(
            enabled: status.enabled,
            soundID: status.soundID,
            clipStartSeconds: clipStartSeconds,
            clipDurationSeconds: clipDurationSeconds
        )
    }

    func chooseGenre(_ genre: String) {
        selectedGenre = genre
    }

    func toggleFavorite(_ option: BookSoundOption) {
        guard !bookID.isEmpty, option.origin == "APPLE_GARAGEBAND_DIGITAL_MATERIAL" else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let loaded: BookSoundStatus = try await runJSON([
                    "--book", bookID,
                    "--sound-id", option.soundID,
                    "--favorite", (option.isFavorite ?? false) ? "false" : "true",
                ])
                try assertOffline(loaded)
                accept(loaded)
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    var availableGenres: [String] {
        let values = Set(status?.options.flatMap { $0.genres ?? [] } ?? [])
        let order = ["Нон-фикшн", "Художественная проза", "Детектив / триллер", "Хоррор / мистика", "Лёгкое / романтическое"]
        return ["Все", "Избранное"] + order.filter(values.contains)
    }

    var filteredOptions: [BookSoundOption] {
        guard let status else { return [] }
        if selectedGenre == "Все" { return status.options }
        if selectedGenre == "Избранное" { return status.options.filter { $0.isFavorite ?? false } }
        return status.options.filter { ($0.genres ?? []).contains(selectedGenre) }
    }

    func preview(_ option: BookSoundOption) {
        if previewSoundID == option.soundID, let previewSound {
            if previewIsPlaying {
                previewSound.pause()
                previewIsPlaying = false
                previewIsPaused = true
            } else if previewIsPaused {
                previewSound.resume()
                previewIsPlaying = true
                previewIsPaused = false
            }
            return
        }
        stopPreview()
        guard FileManager.default.fileExists(atPath: option.path),
              let sound = NSSound(contentsOfFile: option.path, byReference: true) else {
            errorMessage = "Не удалось открыть выбранный звук."
            return
        }
        previewSound = sound
        previewSoundID = option.soundID
        previewIsPlaying = true
        previewIsPaused = false
        sound.delegate = self
        sound.play()
    }

    func previewAdjacent(_ offset: Int) {
        guard let status else { return }
        let options = filteredOptions.isEmpty ? status.options : filteredOptions
        guard !options.isEmpty else { return }
        let currentIndex = previewSoundID.flatMap { id in
            options.firstIndex(where: { $0.soundID == id })
        } ?? options.firstIndex(where: { $0.soundID == status.soundID }) ?? 0
        let target = (currentIndex + offset + options.count) % options.count
        preview(options[target])
    }

    func stopPreview() {
        previewSound?.stop()
        previewSound = nil
        previewSoundID = nil
        previewIsPlaying = false
        previewIsPaused = false
    }

    func sound(_ sound: NSSound, didFinishPlaying finishedPlaying: Bool) {
        guard sound === previewSound else { return }
        previewSound = nil
        previewSoundID = nil
        previewIsPlaying = false
        previewIsPaused = false
    }

    func importCustomSound() {
        guard !bookID.isEmpty else { return }
        let panel = NSOpenPanel()
        panel.title = "Выберите звук перед главой"
        panel.prompt = "Добавить звук"
        panel.allowedContentTypes = [.wav]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let rightsAlert = NSAlert()
        rightsAlert.messageText = "Подтвердите право на использование"
        rightsAlert.informativeText = "Подтвердите, что вы создали этот звук сами или получили право включать его в аудиокнигу, публиковать и распространять её, в том числе коммерчески. Studio сохранит ваше подтверждение для этого файла."
        rightsAlert.alertStyle = .informational
        rightsAlert.addButton(withTitle: "Подтверждаю права и добавляю")
        rightsAlert.addButton(withTitle: "Отмена")
        guard rightsAlert.runModal() == .alertFirstButtonReturn else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let loaded: BookSoundStatus = try await runJSON([
                    "--book", bookID,
                    "--import-file", url.path,
                    "--label", url.deletingPathExtension().lastPathComponent,
                    "--confirm-rights",
                ])
                try assertOffline(loaded)
                accept(loaded)
                selectedGenre = "Все"
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func save(
        enabled: Bool,
        soundID: String,
        clipStartSeconds: Double? = nil,
        clipDurationSeconds: Double? = nil
    ) {
        guard !bookID.isEmpty else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                var arguments = [
                    "--book", bookID,
                    "--set",
                    "--enabled", enabled ? "true" : "false",
                    "--sound-id", soundID,
                ]
                if let clipStartSeconds, let clipDurationSeconds {
                    arguments += [
                        "--clip-start-seconds", String(format: "%.6f", clipStartSeconds),
                        "--clip-duration-seconds", String(format: "%.6f", clipDurationSeconds),
                    ]
                }
                let loaded: BookSoundStatus = try await runJSON(arguments)
                try assertOffline(loaded)
                accept(loaded)
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func accept(_ loaded: BookSoundStatus) {
        status = loaded
        clipStartSeconds = loaded.clipStartSeconds
        clipDurationSeconds = loaded.clipDurationSeconds
        if !availableGenres.contains(selectedGenre) {
            selectedGenre = "Все"
        }
    }

    private func assertOffline(_ value: BookSoundStatus) throws {
        guard value.providerRequests == 0, !value.remoteRequestSent, value.modelCalls == 0,
              !value.paidExecution, !value.billingChanged else {
            throw NSError(
                domain: "AudiobookStudio.BookSound",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Настройка звука нарушила offline contract."]
            )
        }
    }

    private func runJSON<T: Decodable>(_ arguments: [String]) async throws -> T {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: ownerSoundPython)
            process.arguments = [
                ownerSoundPaths.runtimeRoot.appendingPathComponent("book_sound_runner.py").path
            ] + arguments
            let captureDirectory = FileManager.default.temporaryDirectory
                .appendingPathComponent("audiobook-studio-sound-\(UUID().uuidString)", isDirectory: true)
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
            let data = try Data(contentsOf: stdoutURL)
            let diagnostic = String(decoding: try Data(contentsOf: stderrURL), as: UTF8.self)
            guard process.terminationStatus == 0 else {
                if let envelope = try? JSONDecoder().decode(BookSoundError.self, from: data),
                   let message = envelope.message {
                    throw NSError(
                        domain: "AudiobookStudio.BookSound",
                        code: Int(process.terminationStatus),
                        userInfo: [NSLocalizedDescriptionKey: message]
                    )
                }
                throw NSError(
                    domain: "AudiobookStudio.BookSound",
                    code: Int(process.terminationStatus),
                    userInfo: [
                        NSLocalizedDescriptionKey: diagnostic.isEmpty
                            ? "Не удалось применить настройку звука."
                            : diagnostic
                    ]
                )
            }
            return try JSONDecoder().decode(T.self, from: data)
        }.value
    }
}

enum OwnerProductionStep: Int, CaseIterable, Identifiable {
    case text = 1
    case pronunciation
    case chapterSound
    case narrator
    case chapter
    case review
    case release

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .text: return "Текст"
        case .pronunciation: return "Ударения"
        case .chapterSound: return "Звук глав"
        case .narrator: return "Диктор"
        case .chapter: return "Глава"
        case .review: return "Запись"
        case .release: return "Выпуск"
        }
    }
}

struct OwnerProductionFlowPanel: View {
    @ObservedObject var model: StudioModel
    @StateObject private var textController = ContentQualityController()
    @StateObject private var soundController = BookSoundController()
    @Binding var activeStep: OwnerProductionStep
    @Binding var acknowledgedSteps: Set<OwnerProductionStep>
    let selectedBookID: String
    let selectedBookSlug: String
    let onOpenHelp: (OwnerProductionStep) -> Void

    private var book: Book? { model.selectedBook }

    var body: some View {
        Group {
            if activeStep == .chapterSound {
                HStack {
                    Label("Шаг 3 из 7 · Звук перед главами", systemImage: "music.note")
                        .font(.callout.weight(.semibold))
                    Spacer()
                    Button("Подробнее") { onOpenHelp(activeStep) }
                        .buttonStyle(.link)
                }
                .accessibilityIdentifier("chapter-sound-compact-step-header")
            } else {
                Section("Путь к готовой аудиокниге") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Сейчас открыт шаг \(activeStep.rawValue) из 7 — \(activeStep.title.lowercased()).")
                        .font(.callout.weight(.medium))
                    FlowLayout(spacing: 6) {
                        ForEach(OwnerProductionStep.allCases) { step in
                            stepButton(step)
                        }
                    }
                    HStack {
                        Text(activeStepHelp)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("Подробнее") { onOpenHelp(activeStep) }
                            .buttonStyle(.link)
                    }
                }
                .padding(.vertical, 2)
                }
            }

            if activeStep == .text {
                Section("1. Проверьте текст") {
                if let review = textController.ttsReview {
                    HStack {
                        Label(
                            review.preparationStatus == "READY" ? "Текст подготовлен" : "Текст требует подготовки",
                            systemImage: review.preparationStatus == "READY" ? "checkmark.circle.fill" : "pencil.circle"
                        )
                        .foregroundStyle(review.preparationStatus == "READY" ? Color.green : Color.orange)
                        Spacer()
                        Text("Версия \(review.workingCopyRevision)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if textStepDone {
                        navigationButton("Дальше: проверить ударения", destination: .pronunciation)
                            .buttonStyle(.borderedProminent)
                    }
                    Text("Здесь можно исправить текст, который услышит читатель. Оригинал книги останется без изменений.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    TextEditor(text: $textController.workingTextDraft)
                        .frame(minHeight: 180)
                        .font(.body)
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
                    HStack {
                        Button("Сохранить изменения") { textController.saveWorkingCopy() }
                            .buttonStyle(.borderedProminent)
                            .disabled(textController.isLoading || !textController.workingTextHasUnsavedChanges)
                        Button("Отменить правки") { textController.discardWorkingCopyDraft() }
                            .disabled(textController.isLoading || !textController.workingTextHasUnsavedChanges)
                    }
                    Toggle(
                        "Перед записью требовать моё подтверждение текста",
                        isOn: Binding(
                            get: { textController.ttsReview?.manualReview.required ?? false },
                            set: { textController.setManualReviewRequired($0) }
                        )
                    )
                    if review.manualReview.required {
                        Button(
                            review.manualReview.ready ? "Текст принят" : "Принять текущий текст"
                        ) {
                            textController.acceptCurrentWorkingCopy()
                        }
                        .disabled(
                            review.manualReview.ready
                            || textController.workingTextHasUnsavedChanges
                            || textController.isLoading
                        )
                    }
                    if review.preparationStatus != "READY" {
                        Button(review.preparationStatus == "STALE" ? "Подготовить текст заново" : "Подготовить текст") {
                            model.requestBookTextPreparation()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isPreparingBookText || textController.workingTextHasUnsavedChanges)
                        Text("После правок сохраните текст и подготовьте главы заново. Запись сама не начнётся.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else if textController.isLoading {
                    ProgressView("Открывается текст…")
                } else if book?.sourceIntegrity != "OK" {
                    Label("Сначала нужно восстановить целостность исходного текста", systemImage: "exclamationmark.shield.fill")
                        .foregroundStyle(.red)
                } else {
                    Text("Первый шаг — подготовить рабочую копию текста для диктора.")
                        .foregroundStyle(.secondary)
                    Button("Подготовить текст") { model.requestBookTextPreparation() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isPreparingBookText)
                }
                }
            }

            if activeStep == .pronunciation {
                Section("2. Проверьте ударения") {
                Text("Заставка: «Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.»")
                    .font(.callout.weight(.medium))
                Text("Ударение в фамилии уже закреплено на первом слоге: ДИлон.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    TextField("Слово, например: замок", text: $textController.stressWord)
                    Button("Варианты ударения") { textController.loadStressCandidates() }
                        .disabled(
                            textController.isLoading
                            || textController.stressWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        )
                }
                if !textController.stressCandidates.isEmpty {
                    FlowLayout(spacing: 8) {
                        ForEach(textController.stressCandidates) { candidate in
                            Button(candidate.display) { textController.previewStress(candidate) }
                        }
                    }
                }
                if let preview = textController.stressPreview {
                    HStack {
                        Text("Выбрано: \(preview.display)").bold()
                        Spacer()
                        Button("Запомнить для этой книги") { textController.saveStressForBook() }
                            .buttonStyle(.borderedProminent)
                    }
                    Text("Studio сама передаст выбранное ударение диктору.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let review = textController.ttsReview, !review.pronunciationEntries.isEmpty {
                    DisclosureGroup("Сохранённые ударения · \(review.pronunciationEntries.count)") {
                        ForEach(review.pronunciationEntries) { entry in
                            Text("\(entry.word) → \(entry.display)")
                        }
                    }
                }
                navigationButton("Дальше: звук перед главами", destination: .chapterSound)
                }
            }

            if activeStep == .chapterSound {
                Section("3. Выберите звук перед главами — по желанию") {
                if let status = soundController.status {
                    Toggle(
                        "Добавлять короткий звук перед каждой главой",
                        isOn: Binding(
                            get: { soundController.status?.enabled ?? false },
                            set: { soundController.setEnabled($0) }
                        )
                    )
                    navigationButton("Дальше: выбрать диктора", destination: .narrator)
                    HStack(spacing: 12) {
                        Image(systemName: "speaker.slash.circle.fill")
                            .foregroundStyle(.secondary)
                            .frame(width: 36, height: 36)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Без звукового оформления").font(.headline)
                            Text("Главы начнутся сразу с голоса. Это вариант по умолчанию.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if !status.enabled {
                            Label("Выбран", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                        } else {
                            Button("Выбрать") { soundController.setEnabled(false) }
                        }
                    }
                    .padding(.vertical, 4)
                    HStack {
                        Text("Подборка по жанрам").font(.callout.weight(.semibold))
                        Picker("Жанр", selection: $soundController.selectedGenre) {
                            ForEach(soundController.availableGenres, id: \.self) { genre in
                                Text(genre).tag(genre)
                            }
                        }
                        .labelsHidden()
                        .pickerStyle(.menu)
                        Spacer()
                        Text(soundOptionCountText(soundController.filteredOptions.count))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    HStack(spacing: 8) {
                        Button("Предыдущий", systemImage: "backward.end.fill") {
                            soundController.previewAdjacent(-1)
                        }
                        .disabled(soundController.filteredOptions.count < 2)
                        if let previewID = soundController.previewSoundID,
                           let preview = status.options.first(where: { $0.soundID == previewID }) {
                            Button(soundController.previewIsPlaying ? "Пауза" : "Продолжить",
                                   systemImage: soundController.previewIsPlaying ? "pause.fill" : "play.fill") {
                                soundController.preview(preview)
                            }
                            Text("Сейчас: \(preview.label)")
                                .font(.caption.weight(.medium))
                                .lineLimit(1)
                        } else {
                            Button("Слушать", systemImage: "play.fill") {
                                soundController.preview(status.selected)
                            }
                        }
                        Button("Следующий", systemImage: "forward.end.fill") {
                            soundController.previewAdjacent(1)
                        }
                        .disabled(soundController.filteredOptions.count < 2)
                        Button("Стоп", systemImage: "stop.fill") {
                            soundController.stopPreview()
                        }
                        .disabled(soundController.previewSoundID == nil)
                    }
                    .buttonStyle(.bordered)
                    ForEach(soundController.filteredOptions) { option in
                        HStack(spacing: 12) {
                            Button {
                                soundController.preview(option)
                            } label: {
                                Image(systemName:
                                    soundController.previewSoundID == option.soundID && soundController.previewIsPlaying
                                    ? "pause.fill" : "play.fill"
                                )
                                    .frame(width: 28, height: 28)
                            }
                            .help(soundController.previewSoundID == option.soundID && soundController.previewIsPlaying
                                  ? "Поставить на паузу" : "Прослушать вариант")
                            .buttonStyle(.bordered)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(option.label).font(.headline)
                                Text("\(option.description) · \(option.durationSeconds.formatted(.number.precision(.fractionLength(1)))) с")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                if option.origin == "APPLE_GARAGEBAND_DIGITAL_MATERIAL" {
                                    Text("Разрешён внутри аудиокниги; исходный аудиофрагмент нельзя выгружать отдельно.")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                } else if option.origin == "USER_IMPORTED" {
                                    Label("Вы подтвердили право использовать этот звук в аудиокниге.", systemImage: "checkmark.shield")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            if option.origin == "APPLE_GARAGEBAND_DIGITAL_MATERIAL" {
                                Button {
                                    soundController.toggleFavorite(option)
                                } label: {
                                    Image(systemName: (option.isFavorite ?? false) ? "heart.fill" : "heart")
                                        .foregroundStyle((option.isFavorite ?? false) ? .pink : .secondary)
                                }
                                .buttonStyle(.plain)
                                .help((option.isFavorite ?? false) ? "Убрать из избранного" : "Добавить в избранное")
                            }
                            if status.enabled, status.soundID == option.soundID {
                                Label("Выбран", systemImage: "checkmark.circle.fill")
                                    .foregroundStyle(.green)
                            } else {
                                Button("Выбрать") {
                                    soundController.choose(option.soundID)
                                }
                            }
                        }
                        .padding(.vertical, 4)
                    }
                    if status.enabled {
                        GroupBox("Какой фрагмент вставлять") {
                            VStack(alignment: .leading, spacing: 10) {
                                let fullDuration = status.selected.sourceDurationSeconds
                                    ?? status.options.first(where: { $0.soundID == status.soundID })?.durationSeconds
                                    ?? status.selected.durationSeconds
                                let minimumDuration = min(0.5, fullDuration)
                                HStack {
                                    Text("Начало")
                                    Slider(
                                        value: $soundController.clipStartSeconds,
                                        in: 0...max(0.01, fullDuration - soundController.clipDurationSeconds),
                                        step: 0.1
                                    )
                                    Text("\(soundController.clipStartSeconds.formatted(.number.precision(.fractionLength(1)))) с")
                                        .monospacedDigit().frame(width: 46, alignment: .trailing)
                                }
                                HStack {
                                    Text("Длительность")
                                    Slider(
                                        value: $soundController.clipDurationSeconds,
                                        in: minimumDuration...max(minimumDuration, min(4.0, fullDuration - soundController.clipStartSeconds)),
                                        step: 0.1
                                    )
                                    Text("\(soundController.clipDurationSeconds.formatted(.number.precision(.fractionLength(1)))) с")
                                        .monospacedDigit().frame(width: 46, alignment: .trailing)
                                }
                                HStack {
                                    Button("Сохранить фрагмент", systemImage: "scissors") {
                                        soundController.stopPreview()
                                        soundController.saveExcerpt()
                                    }
                                    .buttonStyle(.borderedProminent)
                                    Button("Прослушать сохранённый фрагмент", systemImage: "play.fill") {
                                        soundController.preview(status.selected)
                                    }
                                    Text("Можно взять начало, середину или конец записи.")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(.top, 4)
                        }
                    }
                    if status.garageBandDiscovery?.available == true {
                        let garageBandCount = status.options.filter {
                            $0.origin == "APPLE_GARAGEBAND_DIGITAL_MATERIAL"
                        }.count
                        Label(
                            "Доступно профессиональных звуков GarageBand: \(garageBandCount)",
                            systemImage: "checkmark.seal"
                        )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Button("Добавить свой звук…") { soundController.importCustomSound() }
                    Text("Выберите короткий WAV-файл. Studio скопирует его в папку этой книги; оригинал останется без изменений.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Выбор хранится отдельно для каждой книги: у другой книги можно выбрать другой звук или полностью отключить эту опцию.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Звук добавится после записи голоса. Его можно менять без повторной озвучки.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if soundController.isLoading {
                    ProgressView("Готовятся варианты звука…")
                }
                if let error = soundController.errorMessage {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
                }
            }
        }
        .task(id: selectedBookID) {
            async let textLoad: Void = textController.reload(bookID: selectedBookID)
            async let soundLoad: Void = soundController.reload(bookID: selectedBookSlug)
            _ = await (textLoad, soundLoad)
            if activeStep == .text,
               textStepDone,
               ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_SECTION"] == nil {
                activeStep = .pronunciation
            }
        }
    }

    private var textStepDone: Bool {
        guard let review = textController.ttsReview else { return false }
        return !textController.workingTextHasUnsavedChanges && review.manualReview.ready
    }

    private var textStepDetail: String {
        guard let review = textController.ttsReview else { return "Сначала подготовьте рабочий текст книги." }
        if textController.workingTextHasUnsavedChanges { return "Есть несохранённые изменения." }
        if review.manualReview.required && !review.manualReview.ready { return "Нужно принять текущий текст." }
        return "Рабочий текст готов к следующему шагу."
    }

    private var soundStepDetail: String {
        guard let status = soundController.status else { return "Загрузка вариантов…" }
        return status.enabled
            ? "Выбран «\(status.selected.label)» — он будет поставлен перед каждой главой."
            : "Необязательно. Сейчас звук перед главами выключен."
    }

    private func soundOptionCountText(_ count: Int) -> String {
        let lastTwo = count % 100
        let last = count % 10
        let noun: String
        if (11...14).contains(lastTwo) {
            noun = "вариантов"
        } else if last == 1 {
            noun = "вариант"
        } else if (2...4).contains(last) {
            noun = "варианта"
        } else {
            noun = "вариантов"
        }
        return "\(count) \(noun)"
    }

    private var activeStepHelp: String {
        switch activeStep {
        case .text: return textStepDetail
        case .pronunciation: return "Проверьте имена и слова, которые диктор может произнести неверно. Этот шаг можно пропустить."
        case .chapterSound: return soundStepDetail
        case .narrator: return "Выберите способ озвучки и голос."
        case .chapter: return "Выберите главу, с которой хотите работать сейчас."
        case .review: return "Запишите главу, прослушайте результат и решите: принять или исправить."
        case .release: return "Соберите принятую главу и следите за готовностью всей книги."
        }
    }

    private func stepIsDone(_ step: OwnerProductionStep) -> Bool {
        switch step {
        case .text: return textStepDone
        case .pronunciation, .chapterSound, .narrator, .chapter:
            return acknowledgedSteps.contains(step)
        case .review: return model.audioQA?.record.manualState == "APPROVED"
        case .release: return model.litresExport?.bookExport.ready == true
        }
    }

    @ViewBuilder
    private func stepButton(_ step: OwnerProductionStep) -> some View {
        let selected = activeStep == step
        Button {
            activeStep = step
        } label: {
            HStack(spacing: 5) {
                if stepIsDone(step) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                } else {
                    Text(String(step.rawValue))
                        .font(.caption.bold())
                        .frame(width: 18, height: 18)
                        .background(Circle().fill(selected ? Color.accentColor.opacity(0.18) : Color.secondary.opacity(0.12)))
                }
                Text(step.title).font(.caption.weight(selected ? .semibold : .regular))
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(selected ? Color.accentColor.opacity(0.12) : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(selected ? Color.accentColor : Color.secondary.opacity(0.2))
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Шаг \(step.rawValue): \(step.title)")
        .accessibilityValue(selected ? "Текущий" : (stepIsDone(step) ? "Готово" : "Не завершён"))
    }

    private func navigationButton(_ title: String, destination: OwnerProductionStep) -> some View {
        Button(title) {
            acknowledgedSteps.insert(activeStep)
            activeStep = destination
        }
            .buttonStyle(.borderedProminent)
    }
}

private struct FlowLayout: Layout {
    let spacing: CGFloat

    func sizeThatFits(
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) -> CGSize {
        let width = proposal.width ?? 0
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + (x == 0 ? 0 : spacing)
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: width, height: y + rowHeight)
    }

    func placeSubviews(
        in bounds: CGRect,
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
