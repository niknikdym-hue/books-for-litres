import Foundation
import SwiftUI

private struct DilonNativeReviewApprovalResult: Decodable {
    let state: String
    let decision: String
    let providerRequests: Int
    let remoteRequestSent: Bool
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case state
        case decision
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }

    var isOfflineSafe: Bool {
        providerRequests == 0 && !remoteRequestSent && !paidExecution && !billingChanged
    }
}

private enum DilonNativeFlowError: LocalizedError {
    case invalidSelection
    case offlineContractViolation
    case staleSelection
    case exactListenedIdentityRequired
    case approvalRejected
    case bridgeFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidSelection:
            return "Выберите каноническую книгу и главу для Dilon Voices."
        case .offlineContractViolation:
            return "Dilon native flow нарушил offline safety contract."
        case .staleSelection:
            return "Выбор книги или главы изменился. Обновите Dilon Voices."
        case .exactListenedIdentityRequired:
            return "Одобрение доступно только после полного прослушивания exact candidate identity."
        case .approvalRejected:
            return "Opening credit не был опубликован как одобренный."
        case let .bridgeFailed(message):
            return message.isEmpty ? "Dilon offline bridge завершился с ошибкой." : message
        }
    }
}

@MainActor
final class DilonNativeFlowController: ObservableObject {
    @Published private(set) var snapshot: DilonNativeSnapshot?
    @Published var selectedCandidateID: String?
    @Published private(set) var isLoading = false
    @Published private(set) var statusText = ""
    @Published private(set) var errorMessage: String?

    private let pythonExecutable: URL
    private let snapshotRunner: URL
    private let reviewRunner: URL
    private var selectionGeneration: UInt64 = 0
    private var activeBookName = ""
    private var activeJobID = ""

    init(
        pythonExecutable: URL? = nil,
        snapshotRunner: URL? = nil,
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
        self.snapshotRunner = snapshotRunner
            ?? runtimeRoot.appendingPathComponent("dilon_native_snapshot_runner.py")
        self.reviewRunner = reviewRunner
            ?? runtimeRoot.appendingPathComponent("dilon_opening_credit_review_runner.py")
    }

    func selectionDidChange(
        bookName: String,
        jobID: String,
        player: EmbeddedAudioPlayer
    ) {
        selectionGeneration &+= 1
        activeBookName = bookName
        activeJobID = jobID
        selectedCandidateID = nil
        snapshot = nil
        statusText = ""
        errorMessage = nil
        player.clear()

        guard !bookName.isEmpty, !jobID.isEmpty else { return }
        let expectedGeneration = selectionGeneration
        Task {
            _ = await loadSnapshot(
                bookName: bookName,
                jobID: jobID,
                expectedGeneration: expectedGeneration
            )
        }
    }

    func refresh(player: EmbeddedAudioPlayer) {
        guard !activeBookName.isEmpty, !activeJobID.isEmpty else {
            errorMessage = DilonNativeFlowError.invalidSelection.localizedDescription
            return
        }
        selectionGeneration &+= 1
        selectedCandidateID = nil
        snapshot = nil
        statusText = ""
        errorMessage = nil
        player.clear()
        let expectedGeneration = selectionGeneration
        let bookName = activeBookName
        let jobID = activeJobID
        Task {
            _ = await loadSnapshot(
                bookName: bookName,
                jobID: jobID,
                expectedGeneration: expectedGeneration
            )
        }
    }

    func approveListenedCandidate(
        _ candidate: DilonReviewCandidate,
        player: EmbeddedAudioPlayer
    ) {
        guard let currentSnapshot = snapshot,
              currentSnapshot.isOfflineSafe,
              currentSnapshot.reviewCandidates.contains(candidate),
              currentSnapshot.bookSlug.isEmpty == false,
              currentSnapshot.jobID == activeJobID,
              player.state == .finished,
              player.validateLoadedIdentity(rehash: true),
              let binding = player.binding,
              binding.role == "dilon-opening-credit-review",
              binding.bookSlug == currentSnapshot.bookSlug,
              binding.jobID == currentSnapshot.jobID,
              binding.segmentID == candidate.candidateID,
              binding.audioSHA256 == candidate.audioSHA256,
              binding.pathIdentity == candidate.pathIdentity,
              binding.synthesisFingerprint == candidate.synthesisFingerprint else {
            errorMessage = DilonNativeFlowError.exactListenedIdentityRequired.localizedDescription
            return
        }

        let expectedGeneration = selectionGeneration
        let expectedBookName = activeBookName
        let expectedJobID = activeJobID
        let expectedBookSlug = currentSnapshot.bookSlug
        let listenedBinding = binding
        isLoading = true
        statusText = ""
        errorMessage = nil

        Task {
            do {
                let approval: DilonNativeReviewApprovalResult = try await runJSON(
                    executable: reviewRunner,
                    arguments: [
                        "--approve-candidate",
                        "--book", expectedBookSlug,
                        "--job", expectedJobID,
                        "--candidate-id", candidate.candidateID,
                        "--candidate-digest", candidate.candidateDigest,
                        "--decision", "APPROVE",
                        "--listened-audio-sha256", listenedBinding.audioSHA256,
                        "--listened-path-identity", listenedBinding.pathIdentity,
                        "--listened-synthesis-fingerprint", listenedBinding.synthesisFingerprint,
                    ]
                )
                guard approval.isOfflineSafe else {
                    throw DilonNativeFlowError.offlineContractViolation
                }
                guard approval.state == "APPROVED", approval.decision == "REVIEW_COMPLETE" else {
                    throw DilonNativeFlowError.approvalRejected
                }
                guard selectionGeneration == expectedGeneration,
                      activeBookName == expectedBookName,
                      activeJobID == expectedJobID else {
                    throw DilonNativeFlowError.staleSelection
                }

                player.clear()
                selectedCandidateID = nil
                let refreshed = await loadSnapshot(
                    bookName: expectedBookName,
                    jobID: expectedJobID,
                    expectedGeneration: expectedGeneration,
                    markLoading: false
                )
                guard refreshed, selectionGeneration == expectedGeneration else { return }
                statusText = "Opening credit одобрен по exact listened identity."
                errorMessage = nil
            } catch {
                guard selectionGeneration == expectedGeneration else { return }
                errorMessage = error.localizedDescription
            }
            if selectionGeneration == expectedGeneration {
                isLoading = false
            }
        }
    }

    @discardableResult
    private func loadSnapshot(
        bookName: String,
        jobID: String,
        expectedGeneration: UInt64,
        markLoading: Bool = true
    ) async -> Bool {
        if markLoading { isLoading = true }
        defer {
            if markLoading, selectionGeneration == expectedGeneration {
                isLoading = false
            }
        }
        do {
            let result: DilonNativeSnapshot = try await runJSON(
                executable: snapshotRunner,
                arguments: ["--snapshot", "--book", bookName, "--job", jobID]
            )
            guard result.isOfflineSafe else {
                throw DilonNativeFlowError.offlineContractViolation
            }
            guard selectionGeneration == expectedGeneration,
                  activeBookName == bookName,
                  activeJobID == jobID else {
                throw DilonNativeFlowError.staleSelection
            }
            snapshot = result
            if let selectedCandidateID,
               !result.reviewCandidates.contains(where: { $0.candidateID == selectedCandidateID }) {
                self.selectedCandidateID = nil
            }
            errorMessage = nil
            return true
        } catch {
            guard selectionGeneration == expectedGeneration else { return false }
            snapshot = nil
            selectedCandidateID = nil
            errorMessage = error.localizedDescription
            return false
        }
    }

    private func runJSON<T: Decodable>(
        executable: URL,
        arguments: [String]
    ) async throws -> T {
        let python = pythonExecutable
        return try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = python
            process.arguments = [executable.path] + arguments
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
                throw DilonNativeFlowError.bridgeFailed(error)
            }
            return try JSONDecoder().decode(T.self, from: output)
        }.value
    }
}
