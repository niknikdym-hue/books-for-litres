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
    @StateObject private var identityReview = DilonIdentityReviewController()

    private var selectedCandidate: DilonReviewCandidate? {
        guard let selectedCandidateID else { return nil }
        return snapshot.reviewCandidates.first { $0.candidateID == selectedCandidateID }
    }

    private var operatorCandidate: DilonReviewCandidate? {
        if let selectedCandidate { return selectedCandidate }
        return snapshot.reviewCandidates.count == 1 ? snapshot.reviewCandidates.first : nil
    }

    private var identityReviewKey: String {
        [
            snapshot.bookSlug,
            snapshot.jobID,
            snapshot.identityPreview?.buildIdentity ?? "",
            snapshot.identityPreview?.audioSHA256 ?? "",
        ].joined(separator: "\u{1f}")
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

    private func startCandidate(_ candidate: DilonReviewCandidate) {
        selectedCandidateID = candidate.candidateID
        player.loadAndPlay(candidateBinding(candidate))
    }

    private func fullyListened(_ candidate: DilonReviewCandidate) -> Bool {
        guard player.state == .finished,
              player.completedExactPlayback,
              let binding = player.binding else { return false }
        return binding.role == "dilon-opening-credit-review"
            && binding.bookSlug == snapshot.bookSlug
            && binding.jobID == snapshot.jobID
            && binding.segmentID == candidate.candidateID
            && binding.audioSHA256 == candidate.audioSHA256
            && binding.pathIdentity == candidate.pathIdentity
            && binding.synthesisFingerprint == candidate.synthesisFingerprint
    }

    private func fullyListenedIdentity(_ preview: DilonIdentityPreview) -> Bool {
        guard player.state == .finished,
              player.completedExactPlayback,
              let binding = player.binding else { return false }
        return binding.role == "dilon-identity-preview"
            && binding.bookSlug == snapshot.bookSlug
            && binding.jobID == snapshot.jobID
            && binding.segmentID == "identity-preview"
            && binding.audioSHA256 == preview.audioSHA256
            && binding.pathIdentity == preview.pathIdentity
            && binding.synthesisFingerprint == preview.buildIdentity
    }

    var body: some View {
        Section("Dilon Voices") {
            if !snapshot.isOfflineSafe {
                Label("Dilon Voices временно недоступен: проверка безопасности не пройдена.", systemImage: "xmark.shield.fill")
                    .foregroundStyle(.red)
            } else {
                if snapshot.reviewCandidates.count > 1 {
                    Picker("Вариант для проверки", selection: $selectedCandidateID) {
                        Text("Выберите вариант").tag(String?.none)
                        ForEach(Array(snapshot.reviewCandidates.enumerated()), id: \.element.id) { index, candidate in
                            Text("Вариант \(index + 1)").tag(Optional(candidate.candidateID))
                        }
                    }
                }

                if let candidate = operatorCandidate,
                   candidate.manualState == "PENDING_HUMAN_REVIEW" {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Нужно ваше действие", systemImage: "ear.fill")
                            .font(.headline)
                            .foregroundStyle(.blue)
                        Text("Прослушайте короткую заставку Dilon Voices")
                            .font(.title3.weight(.semibold))
                        if let openingCreditText = snapshot.dilonStatus.openingCreditText {
                            Text(openingCreditText)
                                .font(.body)
                                .textSelection(.enabled)
                        }
                        Text("Проверка качества уже пройдена автоматически. Ваше решение появится только после полного прослушивания.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    DilonAudioTransportCard(
                        player: player,
                        binding: candidateBinding(candidate),
                        playTitle: "Прослушать заставку",
                        onLoad: { startCandidate(candidate) }
                    )

                    Button("Одобрить этот вариант") {
                        guard fullyListened(candidate) else { return }
                        onApproveListenedCandidate(candidate)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!fullyListened(candidate) || candidate.automaticStatus == "FAIL")

                    Text(
                        fullyListened(candidate)
                            ? "Полное прослушивание подтверждено — можно одобрить этот вариант."
                            : "Для одобрения прослушайте вариант полностью. Перемотка вперёд разрешена для проверки, но после неё нужен новый полный проход с начала."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                } else if snapshot.reviewCandidates.isEmpty && snapshot.identityPreview == nil {
                    Label("Сейчас нет аудио, которое требует вашего решения.", systemImage: "checkmark.circle")
                        .foregroundStyle(.secondary)
                }

                if let preview = snapshot.identityPreview, preview.readOnly {
                    Divider()
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Финальная версия Dilon Voices")
                            .font(.title3.weight(.semibold))
                        Text("После технической проверки прослушайте финальную версию целиком перед подтверждением.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    DilonAudioTransportCard(
                        player: player,
                        binding: identityBinding(preview),
                        playTitle: "Прослушать финальную версию",
                        onLoad: { player.loadAndPlay(identityBinding(preview)) }
                    )

                    if identityReview.result?.identityAccepted == true {
                        Label("Финальная версия прослушана и принята", systemImage: "checkmark.shield.fill")
                            .foregroundStyle(.green)
                    } else {
                        Button("Подтвердить финальную версию") {
                            identityReview.approveListenedIdentity(
                                preview,
                                snapshot: snapshot,
                                player: player
                            )
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(
                            identityReview.isLoading
                                || snapshot.dilonStatus.technicalReady != true
                                || !fullyListenedIdentity(preview)
                        )
                    }

                    Text(
                        identityReview.result?.identityAccepted == true
                            ? "Подтверждение сохранено для этой точной версии аудио."
                            : "Подтверждение разблокируется только после полного прослушивания текущей финальной версии."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    if !identityReview.statusText.isEmpty {
                        Label(identityReview.statusText, systemImage: "checkmark.shield")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }
                    if let reviewError = identityReview.errorMessage {
                        Label(reviewError, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }

                DisclosureGroup("Диагностика") {
                    LabeledContent("Статус Dilon", value: snapshot.dilonStatus.state)
                    if let identity = snapshot.dilonStatus.cleanMaster?.masterIdentity {
                        LabeledContent("Clean master", value: String(identity.prefix(16)) + "…")
                    }
                    if let signatureState = snapshot.dilonStatus.signatureState {
                        LabeledContent("Музыка / signature", value: signatureState)
                    }
                    if snapshot.dilonStatus.technicalReady == true {
                        Label("Технический QA пройден", systemImage: "checkmark.shield.fill")
                            .foregroundStyle(.green)
                    }
                    if !snapshot.dilonStatus.blockers.isEmpty {
                        ForEach(snapshot.dilonStatus.blockers, id: \.self) { blocker in
                            Text("Blocker: \(blocker)")
                                .font(.caption.monospaced())
                        }
                    }
                    ForEach(snapshot.reviewCandidates) { candidate in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Candidate \(String(candidate.candidateID.prefix(12)))…")
                            Text("QA: \(candidate.automaticStatus) · manual: \(candidate.manualState)")
                            Text("SHA: \(candidate.audioSHA256)")
                            Text("Path identity: \(candidate.pathIdentity)")
                            Text("Fingerprint: \(candidate.synthesisFingerprint)")
                        }
                        .font(.caption.monospaced())
                    }
                    Label("Полная книга ещё не готова к выпуску", systemImage: "lock.fill")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .task(id: identityReviewKey) {
            identityReview.selectionDidChange(
                bookSlug: snapshot.bookSlug,
                jobID: snapshot.jobID,
                buildIdentity: snapshot.identityPreview?.buildIdentity
            )
        }
    }
}

@MainActor
private struct DilonAudioTransportCard: View {
    @ObservedObject var player: EmbeddedAudioPlayer
    let binding: AudioPlaybackBinding
    let playTitle: String
    let onLoad: () -> Void

    private var isCurrent: Bool { player.binding == binding }

    private var primaryTitle: String {
        guard isCurrent else { return playTitle }
        switch player.state {
        case .playing: return "Пауза"
        case .paused: return "Продолжить"
        case .finished: return "Прослушать снова"
        case .stopped, .ready: return "Воспроизвести"
        case .error: return "Открыть заново"
        }
    }

    private var primaryIcon: String {
        isCurrent && player.state == .playing ? "pause.fill" : "play.fill"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button {
                    if isCurrent {
                        player.togglePlayPause()
                    } else {
                        onLoad()
                    }
                } label: {
                    Label(primaryTitle, systemImage: primaryIcon)
                }
                .buttonStyle(.borderedProminent)

                Button {
                    player.stop()
                } label: {
                    Label("Стоп", systemImage: "stop.fill")
                }
                .disabled(!isCurrent || player.state == .stopped)
                Spacer()
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

            HStack(spacing: 8) {
                Text(isCurrent ? playbackStateLabel(player.state) : "Готово к воспроизведению")
                    .font(.caption)
                    .foregroundStyle(player.state == .error ? Color.red : Color.secondary)
                if isCurrent, player.completedExactPlayback {
                    Label("Полностью прослушано", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                }
            }

            if isCurrent, player.state == .finished, !player.completedExactPlayback {
                Text("После перемотки вперёд одобрение не разблокируется. Нажмите «Прослушать снова» и дайте записи дойти до конца без пропуска вперёд.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            if isCurrent, let error = player.errorMessage {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 12))
    }
}