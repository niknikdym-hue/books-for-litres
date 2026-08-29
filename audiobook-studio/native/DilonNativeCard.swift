import SwiftUI

struct DilonNativeSnapshot: Decodable {
    let schemaVersion: Int
    let state: String
    let decision: String
    let bookSlug: String
    let jobID: String
    let dilonStatus: DilonNativeStatus
    let reviewCandidates: [DilonReviewCandidate]
    let identityPreview: DilonIdentityPreview?
    let capabilities: DilonNativeCapabilities
    let wholeBookReleaseReady: Bool
    let providerRequests: Int
    let remoteRequestSent: Bool
    let paidExecution: Bool
    let billingChanged: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case state
        case decision
        case bookSlug = "book_slug"
        case jobID = "job_id"
        case dilonStatus = "dilon_status"
        case reviewCandidates = "review_candidates"
        case identityPreview = "identity_preview"
        case capabilities
        case wholeBookReleaseReady = "whole_book_release_ready"
        case providerRequests = "provider_requests"
        case remoteRequestSent = "remote_request_sent"
        case paidExecution = "paid_execution"
        case billingChanged = "billing_changed"
    }

    var isOfflineSafe: Bool {
        providerRequests == 0 && !remoteRequestSent && !paidExecution && !billingChanged
            && !wholeBookReleaseReady
            && !capabilities.providerExecutionAvailable
            && !capabilities.paidExecutionAvailable
            && !capabilities.automaticReviewApproval
    }
}

struct DilonNativeStatus: Decodable {
    let state: String
    let decision: String
    let openingCreditText: String?
    let cleanMaster: DilonCleanMasterSummary?
    let technicalQA: DilonTechnicalQASummary?
    let signatureState: String?
    let humanListeningRequired: Bool?
    let technicalReady: Bool?
    let blockers: [String]

    enum CodingKeys: String, CodingKey {
        case state
        case decision
        case openingCreditText = "opening_credit_text"
        case cleanMaster = "clean_master"
        case technicalQA = "technical_qa"
        case signatureState = "signature_state"
        case humanListeningRequired = "human_listening_required"
        case technicalReady = "technical_ready"
        case blockers
    }
}

struct DilonCleanMasterSummary: Decodable {
    let masterIdentity: String?
    let audioSHA256: String?

    enum CodingKeys: String, CodingKey {
        case masterIdentity = "master_identity"
        case audioSHA256 = "audio_sha256"
    }
}

struct DilonTechnicalQASummary: Decodable {
    let state: String?
    let decision: String?
    let outputSHA256: String?

    enum CodingKeys: String, CodingKey {
        case state
        case decision
        case outputSHA256 = "output_sha256"
    }
}

struct DilonNativeCapabilities: Decodable {
    let prepareOpeningCreditOffline: Bool
    let reviewCandidateOffline: Bool
    let identityPreviewOffline: Bool
    let providerExecutionAvailable: Bool
    let paidExecutionAvailable: Bool
    let automaticReviewApproval: Bool

    enum CodingKeys: String, CodingKey {
        case prepareOpeningCreditOffline = "prepare_opening_credit_offline"
        case reviewCandidateOffline = "review_candidate_offline"
        case identityPreviewOffline = "identity_preview_offline"
        case providerExecutionAvailable = "provider_execution_available"
        case paidExecutionAvailable = "paid_execution_available"
        case automaticReviewApproval = "automatic_review_approval"
    }
}

struct DilonReviewCandidate: Decodable, Identifiable, Equatable {
    let candidateID: String
    let candidateDigest: String
    let audioPath: String
    let audioSHA256: String
    let pathIdentity: String
    let synthesisFingerprint: String
    let automaticStatus: String
    let manualState: String
    let isCurrentApproved: Bool

    var id: String { candidateID }

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case candidateDigest = "candidate_digest"
        case audioPath = "audio_path"
        case audioSHA256 = "audio_sha256"
        case pathIdentity = "path_identity"
        case synthesisFingerprint = "synthesis_fingerprint"
        case automaticStatus = "automatic_status"
        case manualState = "manual_state"
        case isCurrentApproved = "is_current_approved"
    }
}

struct DilonIdentityPreview: Decodable, Equatable {
    let buildIdentity: String
    let audioPath: String
    let audioSHA256: String
    let pathIdentity: String
    let readOnly: Bool

    enum CodingKeys: String, CodingKey {
        case buildIdentity = "build_identity"
        case audioPath = "audio_path"
        case audioSHA256 = "audio_sha256"
        case pathIdentity = "path_identity"
        case readOnly = "read_only"
    }
}

@MainActor
struct DilonNativeCard: View {
    let snapshot: DilonNativeSnapshot
    @ObservedObject var player: EmbeddedAudioPlayer
    @Binding var selectedCandidateID: String?
    let onApproveListenedCandidate: (DilonReviewCandidate) -> Void

    private var selectedCandidate: DilonReviewCandidate? {
        guard let selectedCandidateID else { return nil }
        return snapshot.reviewCandidates.first { $0.candidateID == selectedCandidateID }
    }

    private func candidateBinding(_ candidate: DilonReviewCandidate) -> AudioPlaybackBinding {
        AudioPlaybackBinding(
            url: URL(fileURLWithPath: candidate.audioPath),
            audioSHA256: candidate.audioSHA256,
            pathIdentity: candidate.pathIdentity,
            synthesisFingerprint: candidate.synthesisFingerprint,
            provider: "yandex",
            profileID: "yandex_lera",
            bookSlug: snapshot.bookSlug,
            jobID: snapshot.jobID,
            segmentID: candidate.candidateID,
            role: "dilon-opening-credit-review"
        )
    }

    private func identityBinding(_ preview: DilonIdentityPreview) -> AudioPlaybackBinding {
        AudioPlaybackBinding(
            url: URL(fileURLWithPath: preview.audioPath),
            audioSHA256: preview.audioSHA256,
            pathIdentity: preview.pathIdentity,
            synthesisFingerprint: preview.buildIdentity,
            provider: "derived",
            profileID: "dilon_identity_v1",
            bookSlug: snapshot.bookSlug,
            jobID: snapshot.jobID,
            segmentID: "identity-preview",
            role: "dilon-identity-preview"
        )
    }

    private func fullyListened(_ candidate: DilonReviewCandidate) -> Bool {
        guard player.state == .finished, let binding = player.binding else { return false }
        return binding.role == "dilon-opening-credit-review"
            && binding.bookSlug == snapshot.bookSlug
            && binding.jobID == snapshot.jobID
            && binding.segmentID == candidate.candidateID
            && binding.audioSHA256 == candidate.audioSHA256
            && binding.pathIdentity == candidate.pathIdentity
            && binding.synthesisFingerprint == candidate.synthesisFingerprint
    }

    var body: some View {
        Section("Dilon Voices") {
            if !snapshot.isOfflineSafe {
                Label("Dilon snapshot нарушил offline safety contract", systemImage: "xmark.shield.fill")
                    .foregroundStyle(.red)
            } else {
                LabeledContent("Статус", value: snapshot.dilonStatus.state)
                if let identity = snapshot.dilonStatus.cleanMaster?.masterIdentity {
                    LabeledContent("Clean master", value: String(identity.prefix(16)) + "…")
                }
                if let openingCreditText = snapshot.dilonStatus.openingCreditText {
                    Text(openingCreditText)
                        .textSelection(.enabled)
                }
                if let signatureState = snapshot.dilonStatus.signatureState {
                    LabeledContent("Музыка / signature", value: signatureState)
                }
                if !snapshot.dilonStatus.blockers.isEmpty {
                    ForEach(snapshot.dilonStatus.blockers, id: \.self) { blocker in
                        Label(blocker, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                    }
                }

                if !snapshot.reviewCandidates.isEmpty {
                    Picker("Opening credit для проверки", selection: $selectedCandidateID) {
                        Text("Выберите явно").tag(String?.none)
                        ForEach(snapshot.reviewCandidates) { candidate in
                            Text(String(candidate.candidateID.prefix(12)) + "…")
                                .tag(Optional(candidate.candidateID))
                        }
                    }

                    if let candidate = selectedCandidate {
                        HStack {
                            Button("Прослушать opening credit") {
                                player.loadAndPlay(candidateBinding(candidate))
                            }
                            .buttonStyle(.borderedProminent)

                            Button("Одобрить прослушанный вариант") {
                                guard fullyListened(candidate) else { return }
                                onApproveListenedCandidate(candidate)
                            }
                            .disabled(!fullyListened(candidate) || candidate.automaticStatus == "FAIL")
                        }
                        Text(
                            fullyListened(candidate)
                                ? "Полное прослушивание exact identity подтверждено."
                                : "Одобрение разблокируется только после полного прослушивания этого exact SHA/path/fingerprint."
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                } else {
                    Label("Нет подготовленного opening-credit candidate", systemImage: "waveform.badge.exclamationmark")
                        .foregroundStyle(.secondary)
                }

                if let preview = snapshot.identityPreview, preview.readOnly {
                    Button("Прослушать текущий Dilon identity") {
                        player.loadAndPlay(identityBinding(preview))
                    }
                    .buttonStyle(.bordered)
                    Text("Identity preview доступен только для independently revalidated CURRENT output.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if snapshot.dilonStatus.technicalReady == true {
                    Label("Технический QA пройден", systemImage: "checkmark.shield.fill")
                        .foregroundStyle(.green)
                }
                Label("Whole-book release остаётся заблокирован", systemImage: "lock.fill")
                    .foregroundStyle(.secondary)
            }
        }
    }
}
