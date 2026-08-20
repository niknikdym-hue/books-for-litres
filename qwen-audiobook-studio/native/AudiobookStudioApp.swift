import AppKit
import SwiftUI

private let studioDirectory = URL(fileURLWithPath: "/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio")
private let pythonExecutable = "/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python"

struct Book: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let author: String
}

struct Voice: Codable, Identifiable, Hashable {
    let id: String
    let label: String
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

struct StudioSnapshot: Codable {
    let books: [Book]
    let qwenVoices: [Voice]
    let yandexProfile: YandexProfile
    let yandexEstimate: YandexEstimate
    let yandexSettings: YandexSettings
    let remoteRequestSent: Bool

    enum CodingKeys: String, CodingKey {
        case books
        case qwenVoices = "qwen_voices"
        case yandexProfile = "yandex_profile"
        case yandexEstimate = "yandex_estimate"
        case yandexSettings = "yandex_settings"
        case remoteRequestSent = "remote_request_sent"
    }
}

struct YandexSettings: Codable {
    let hardLimitRub: String?
    enum CodingKeys: String, CodingKey { case hardLimitRub = "hard_limit_rub" }
}

enum Engine: String, CaseIterable, Identifiable {
    case qwen
    case yandex

    var id: String { rawValue }
    var title: String { self == .qwen ? "Qwen — локально" : "Yandex SpeechKit — облако" }
}

@MainActor
final class StudioModel: ObservableObject {
    @Published var books: [Book] = []
    @Published var voices: [Voice] = []
    @Published var profile = YandexProfile(voice: "Lera", role: "neutral", speed: "1.04")
    @Published var estimate: YandexEstimate?
    @Published var selectedBookID = ""
    @Published var selectedVoiceID = "Vivian"
    @Published var engine: Engine = .yandex
    @Published var isLoading = true
    @Published var isRunning = false
    @Published var errorMessage: String?
    @Published var completedOutput: URL?
    @Published var showConfirmation = false
    @Published var hardLimitText = ""
    @Published var localHealthText = ""
    @Published var technicalDetails: String?

    init() {
        Task { await reload() }
    }

    var selectedBook: Book? { books.first { $0.id == selectedBookID } }

    func reload() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot: StudioSnapshot = try await runBridgeJSON(["--ui-snapshot"])
            books = snapshot.books
            voices = snapshot.qwenVoices
            profile = snapshot.yandexProfile
            estimate = snapshot.yandexEstimate
            selectedBookID = books.first?.id ?? ""
            selectedVoiceID = voices.first(where: { $0.id == "Vivian" })?.id ?? voices.first?.id ?? ""
            hardLimitText = snapshot.yandexSettings.hardLimitRub ?? ""
            errorMessage = nil
        } catch {
            showError(error)
        }
    }

    func begin() {
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

                        if model.engine == .qwen {
                            Picker("Голос", selection: $model.selectedVoiceID) {
                                ForEach(model.voices) { Text($0.label).tag($0.id) }
                            }
                            Text("Локально · без тарификации API")
                                .foregroundStyle(.secondary)
                        } else {
                            LabeledContent("Голос", value: model.profile.voice)
                            LabeledContent("Стиль", value: model.profile.role)
                            LabeledContent("Скорость", value: model.profile.speed)
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
                        Section("Оценка") {
                            Text("\(estimate.characters.formatted()) символов · \(estimate.segments) сегмента")
                            if estimate.cachedSegments > 0 {
                                Text("Уже готово: \(estimate.cachedSegments) · осталось отправить: \(estimate.billableRemainingUnits)")
                            }
                            Text("Дополнительная стоимость: \(rubles(estimate.estimatedRemainingCost))")
                                .font(.title3.weight(.semibold))
                            Text("Всего при новом запуске: \(rubles(estimate.estimatedTotalCost))")
                                .foregroundStyle(.secondary)
                            Text(estimate.priceStale ? "Тариф требует проверки" : "Тариф проверен: \(russianDate(estimate.priceVerifiedAt))")
                                .foregroundStyle(estimate.priceStale ? .orange : .secondary)
                            Text("Лимит задачи: \(estimate.hardLimitRub.map { rubles($0) } ?? "не задан")")
                                .foregroundStyle(.secondary)
                            DisclosureGroup("Подробности") {
                                Text("Единицы тарификации: \(estimate.totalBillingUnits)")
                                Text("Цена единицы: \(estimate.unitPrice ?? "не настроена") ₽")
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
                        } else {
                            Text("Тестовый фрагмент · Lera · neutral · 1.04").foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if let output = model.completedOutput {
                        Button("Прослушать") { NSWorkspace.shared.open(output) }
                        Button("Показать в Finder") { NSWorkspace.shared.activateFileViewerSelecting([output]) }
                    }
                    Button(model.isRunning ? "Выполняется…" : "Начать озвучку") { model.begin() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isRunning || model.isLoading)
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
            .alert("Audiobook Studio", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
                Button("OK", role: .cancel) { model.errorMessage = nil }
            } message: { Text(model.errorMessage ?? "") }
            .confirmationDialog("Начать озвучку?", isPresented: $model.showConfirmation, titleVisibility: .visible) {
                Button("Начать озвучку") { model.confirmYandexDemo() }
                Button("Отмена", role: .cancel) {}
            } message: {
                Text("Yandex SpeechKit\n\(model.profile.voice) · \(model.profile.role) · \(model.profile.speed)\n\(model.estimate?.segments ?? 0) сегмента\n\(rubles(model.estimate?.estimatedRemainingCost))")
            }
        }
    }
}

struct SettingsView: View {
    @ObservedObject var model: StudioModel
    @AppStorage("openFinderAfterCompletion") private var openFinderAfterCompletion = true
    @AppStorage("notificationsEnabled") private var notificationsEnabled = true

    var body: some View {
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
        }
        .formStyle(.grouped)
        .padding()
    }
}

private func rubles(_ value: String?) -> String {
    guard let value, let amount = Decimal(string: value) else { return "тариф не настроен" }
    let formatter = NumberFormatter()
    formatter.locale = Locale(identifier: "ru_RU")
    formatter.numberStyle = .decimal
    formatter.minimumFractionDigits = 2
    formatter.maximumFractionDigits = 2
    return "~\(formatter.string(from: amount as NSDecimalNumber) ?? value) ₽"
}

private func russianDate(_ date: String?) -> String {
    guard let date else { return "не указана" }
    let parts = date.split(separator: "-")
    guard parts.count == 3 else { return date }
    return "\(parts[2]).\(parts[1]).\(parts[0])"
}
