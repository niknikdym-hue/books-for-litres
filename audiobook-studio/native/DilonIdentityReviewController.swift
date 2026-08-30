import Foundation

struct DilonIdentityHumanReviewResult: Decodable {
    let state: String
    let decision: String
    let identityAccepted: Bool
    let humanListeningRequired: Bool
    let providerRequests: Int
    let remoteRequestSent: Bool
    let paidExecution: Bool
    let billingChanged: Bool
    let wholeBookReleaseReady: Bool

    enum CodingKeys: String, CodingKey {
        case state
        case decision
        case identityAccepted = "identity_accepted"
        case humanListeningRequired = "human_listening_required"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
        case wholeBookReleaseReady = "whole_book_release_ready"
    }

    var isOfflineSafe: Bool {
        providerRequests == 0
            && !remoteRequestSent
            && !paidExecution
            && !billingChanged
            && !wholeBookReleaseReady
    }
}

private enum DilonIdentityReviewControllerError: LocalizedError {
    case invalidSelection
    case exactListenedIdentityRequired
    case offlineContractViolation
    case staleSelection
    case approvalRejected
    case bridgeFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidSelection:
            return "Финальная версия Dilon Voices пока не выбрана."
        case .exactListenedIdentityRequired:
            return "Подтверждение доступно только после полного прослушивания текущей финальной версии."
        case .offlineContractViolation:
            return "Финальная версия Dilon Voices временно недоступна: проверка безопасности не пройдена."
        case .staleSelection:
            return "Финальная версия изменилась. Прослушайте текущий вариант заново."
        case .approvalRejected:
            return "Финальная версия не была сохранена как прослушанная и принятая."
        case let .bridgeFailed(message):
            return message.isEmpty ? "Локальная проверка финальной версии завершилась с ошибкой." : message
        }
    }
}

@MainActor
final class DilonIdentityReviewController: ObservableObject {
    @Published private(set) var result: DilonIdentityHumanReviewResult?
    @Published private(set) var isLoading = false
    @Published private(set) var statusText = ""
    @Published private(set) var errorMessage: String?

    private let pythonExecutable: URL
    private let reviewRunner: URL
    private var selectionGeneration: UInt64 = 0
    private var activeBookSlug = ""
    private var activeJobID = ""
    private var activeBuildIdentity = ""

    init(
        pythonExecutable: URL? = nil,
        reviewRunner: URL? = nil
    ) {
        let environment = ProcessInfo.processInfo.environment
        let workspaceRoot = environment["AUDIOBOOK_STUDIO_HOME"]
            .map { URL(fileURLWithPath: $0, isDirectory: true) }
            ?? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Documents/New project/Audiobook-Studio", isDirectory: true)
        let runtimeRoot = workspaceRoot.appendingPathComponent("runtime/studio-workspace", isDirectory: true)
        self.pythonExecutable = pythonExecutable
            ?? URL(fileURLWithPath: environment["AUDIOBOOK_STUDIO_PYTHON"]
                ?? workspaceRoot.appendingPathComponent("engines/qwen-mlx/.venv/bin/python").path)
        self.reviewRunner = reviewRunner
            ?? runtimeRoot.appendingPathComponent("dilon_identity_review_runner.py")
    }

    func selectionDidChange(
        bookSlug: String,
        jobID: String,
        buildIdentity: String?
    ) {
        selectionGeneration &+= 1
        activeBookSlug = bookSlug
        activeJobID = jobID
        activeBuildIdentity = buildIdentity ?? ""
        result = nil
        statusText = ""
        errorMessage = nil
        guard !bookSlug.isEmpty, !jobID.isEmpty, !activeBuildIdentity.isEmpty else { return }
        let expectedGeneration = selectionGeneration
        Task {
            await loadStatus(expectedGeneration: expectedGeneration)
        }
    }

    func approveListenedIdentity(
        _ preview: DilonIdentityPreview,
        snapshot: DilonNativeSnapshot,
        player: EmbeddedAudioPlayer
    ) {
        guard snapshot.isOfflineSafe,
              snapshot.bookSlug == activeBookSlug,
              snapshot.jobID == activeJobID,
              preview.buildIdentity == activeBuildIdentity,
              snapshot.dilonStatus.technicalReady == true,
              player.state == .finished,
              player.completedExactPlayback,
              player.validateLoadedIdentity(rehash: true),
              let binding = player.binding,
              binding.role == "dilon-identity-preview",
              binding.bookSlug == snapshot.bookSlug,
              binding.jobID == snapshot.jobID,
              binding.segmentID == "identity-preview",
              binding.audioSHA256 == preview.audioSHA256,
              binding.pathIdentity == preview.pathIdentity,
              binding.synthesisFingerprint == preview.buildIdentity else {
            errorMessage = DilonIdentityReviewControllerError.exactListenedIdentityRequired.localizedDescription
            return
        }

        let expectedGeneration = selectionGeneration
        let expectedBook = activeBookSlug
        let expectedJob = activeJobID
        let expectedBuild = activeBuildIdentity
        isLoading = true
        statusText = ""
        errorMessage = nil
        do {
            let approval: DilonIdentityHumanReviewResult = try runJSONSync(
                arguments: [
                    "--approve",
                    "--book", expectedBook,
                    "--job", expectedJob,
                    "--listened-build-identity", binding.synthesisFingerprint,
                    "--listened-audio-sha256", binding.audioSHA256,
                    "--listened-path-identity", binding.pathIdentity,
                ]
            )
            guard approval.isOfflineSafe else {
                throw DilonIdentityReviewControllerError.offlineContractViolation
            }
            guard approval.state == "APPROVED",
                  approval.decision == "IDENTITY_REVIEW_COMPLETE",
                  approval.identityAccepted,
                  !approval.humanListeningRequired else {
                throw DilonIdentityReviewControllerError.approvalRejected
            }
            guard selectionGeneration == expectedGeneration,
                  activeBookSlug == expectedBook,
                  activeJobID == expectedJob,
                  activeBuildIdentity == expectedBuild else {
                throw DilonIdentityReviewControllerError.staleSelection
            }
            result = approval
            statusText = "Финальная версия Dilon Voices принята после полного прослушивания."
            errorMessage = nil
            isLoading = false
        } catch {
            guard selectionGeneration == expectedGeneration else { return }
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }

    private func loadStatus(expectedGeneration: UInt64) async {
        isLoading = true
        defer {
            if selectionGeneration == expectedGeneration { isLoading = false }
        }
        do {
            let status: DilonIdentityHumanReviewResult = try await runJSON(
                arguments: [
                    "--status",
                    "--book", activeBookSlug,
                    "--job", activeJobID,
                ]
            )
            guard status.isOfflineSafe else {
                throw DilonIdentityReviewControllerError.offlineContractViolation
            }
            guard selectionGeneration == expectedGeneration else {
                throw DilonIdentityReviewControllerError.staleSelection
            }
            result = status
            if status.identityAccepted {
                statusText = "Финальная версия Dilon Voices уже принята после полного прослушивания."
            }
            errorMessage = nil
        } catch {
            guard selectionGeneration == expectedGeneration else { return }
            result = nil
            errorMessage = error.localizedDescription
        }
    }

    private func runJSONSync<T: Decodable>(arguments: [String]) throws -> T {
        let process = Process()
        process.executableURL = pythonExecutable
        process.arguments = [reviewRunner.path] + arguments
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        process.waitUntilExit()
        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        let error = String(
            decoding: stderr.fileHandleForReading.readDataToEndOfFile(),
            as: UTF8.self
        )
        guard process.terminationStatus == 0 else {
            throw DilonIdentityReviewControllerError.bridgeFailed(error)
        }
        return try JSONDecoder().decode(T.self, from: output)
    }

    private func runJSON<T: Decodable>(arguments: [String]) async throws -> T {
        let python = pythonExecutable
        let runner = reviewRunner
        return try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = python
            process.arguments = [runner.path] + arguments
            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr
            try process.run()
            process.waitUntilExit()
            let output = stdout.fileHandleForReading.readDataToEndOfFile()
            let error = String(
                decoding: stderr.fileHandleForReading.readDataToEndOfFile(),
                as: UTF8.self
            )
            guard process.terminationStatus == 0 else {
                throw DilonIdentityReviewControllerError.bridgeFailed(error)
            }
            return try JSONDecoder().decode(T.self, from: output)
        }.value
    }
}