import AppKit
import Foundation
import SwiftUI

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

    var id: String { soundID }

    enum CodingKeys: String, CodingKey {
        case label, description, path, sha256, origin, rights
        case soundID = "sound_id"
        case durationSeconds = "duration_seconds"
    }
}

struct BookSoundStatus: Codable, Hashable {
    let bookSlug: String
    let enabled: Bool
    let soundID: String
    let applyBefore: String
    let selected: BookSoundOption
    let options: [BookSoundOption]
    let providerRequests: Int
    let remoteRequestSent: Bool
    let modelCalls: Int
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case enabled, selected, options
        case bookSlug = "book_slug"
        case soundID = "sound_id"
        case applyBefore = "apply_before"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case modelCalls = "model_calls"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }
}

private struct BookSoundError: Codable {
    let message: String?
}

@MainActor
final class BookSoundController: ObservableObject {
    @Published private(set) var status: BookSoundStatus?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    private var bookID = ""
    private var previewSound: NSSound?

    func reload(bookID: String) async {
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
            status = loaded
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

    func preview(_ option: BookSoundOption) {
        previewSound?.stop()
        guard FileManager.default.fileExists(atPath: option.path),
              let sound = NSSound(contentsOfFile: option.path, byReference: true) else {
            errorMessage = "Не удалось открыть выбранный звук."
            return
        }
        previewSound = sound
        sound.play()
    }

    private func save(enabled: Bool, soundID: String) {
        guard !bookID.isEmpty else { return }
        Task {
            isLoading = true
            defer { isLoading = false }
            do {
                let loaded: BookSoundStatus = try await runJSON([
                    "--book", bookID,
                    "--set",
                    "--enabled", enabled ? "true" : "false",
                    "--sound-id", soundID,
                ])
                try assertOffline(loaded)
                status = loaded
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
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
            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr
            try process.run()
            process.waitUntilExit()
            let data = stdout.fileHandleForReading.readDataToEndOfFile()
            let diagnostic = String(
                decoding: stderr.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self
            )
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

struct OwnerProductionFlowPanel: View {
    @ObservedObject var model: StudioModel
    @StateObject private var textController = ContentQualityController()
    @StateObject private var soundController = BookSoundController()
    let selectedBookID: String

    private var book: Book? { model.selectedBook }

    var body: some View {
        Group {
            Section("Путь к готовой аудиокниге") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Идите сверху вниз. Studio сама показывает, что уже готово и что делать дальше.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    ownerStep(1, "Текст", detail: textStepDetail, done: textStepDone)
                    ownerStep(2, "Ударения", detail: "Проверьте имена и слова, которые диктор может произнести неверно.", done: false)
                    ownerStep(3, "Звук глав", detail: soundStepDetail, done: !(soundController.status?.enabled ?? false) || soundController.status != nil)
                    ownerStep(4, "Диктор", detail: "Выберите движок и голос.", done: model.selectedProfile != nil)
                    ownerStep(5, "Глава", detail: "Выберите конкретную главу для записи.", done: model.selectedJob != nil)
                    ownerStep(6, "Запись и прослушивание", detail: "Запустите запись, затем прослушайте WAV и примите или отправьте на перезапись.", done: model.audioQA?.record.manualState == "APPROVED")
                    ownerStep(7, "Сборка и выпуск", detail: "После приёмки Studio собирает главу, делает мастеринг и пакет для ЛитРес.", done: model.litresExport?.chapterExport != nil)
                }
                .padding(.vertical, 4)
            }

            Section("1. Текст для озвучки") {
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
                    Text("Это рабочая копия для диктора. Исходный текст книги не меняется.")
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
                        Text("После правок сначала сохраните текст, затем подготовьте главы заново. Старое аудио автоматически не запускается.")
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

            Section("2. Ударения и произношение") {
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
                    HStack(spacing: 8) {
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
                    Text("Studio сама переведёт это ударение в формат выбранного TTS-движка.")
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
            }

            Section("3. Звук перед главами — по желанию автора") {
                if let status = soundController.status {
                    Toggle(
                        "Добавлять короткий звук перед каждой главой",
                        isOn: Binding(
                            get: { soundController.status?.enabled ?? false },
                            set: { soundController.setEnabled($0) }
                        )
                    )
                    Picker(
                        "Вариант",
                        selection: Binding(
                            get: { soundController.status?.soundID ?? status.soundID },
                            set: { soundController.select($0) }
                        )
                    ) {
                        ForEach(status.options) { option in
                            Text(option.label).tag(option.soundID)
                        }
                    }
                    .disabled(!status.enabled)
                    if let selected = status.options.first(where: { $0.soundID == status.soundID }) {
                        Text(selected.description)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        HStack {
                            Button("Прослушать звук") { soundController.preview(selected) }
                            if status.enabled {
                                Label("Будет добавлен перед каждой главой этой книги", systemImage: "checkmark.circle")
                                    .foregroundStyle(.green)
                            } else {
                                Text("Сейчас книга записывается без звука перед главами.")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    Text("Выбор хранится отдельно для каждой книги: у другой книги можно выбрать другой звук или полностью отключить эту опцию.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Звук добавляется только на этапе сборки готовой главы — после озвучки и проверки речи. Смена звука не требует заново оплачивать TTS.")
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
        .task(id: selectedBookID) {
            async let textLoad: Void = textController.reload(bookID: selectedBookID)
            async let soundLoad: Void = soundController.reload(bookID: selectedBookID)
            _ = await (textLoad, soundLoad)
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

    @ViewBuilder
    private func ownerStep(_ number: Int, _ title: String, detail: String, done: Bool) -> some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle().fill(done ? Color.green.opacity(0.16) : Color.secondary.opacity(0.12))
                    .frame(width: 28, height: 28)
                if done {
                    Image(systemName: "checkmark").foregroundStyle(.green).font(.caption.bold())
                } else {
                    Text(String(number)).font(.caption.bold())
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
