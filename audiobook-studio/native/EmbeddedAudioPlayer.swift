import AVFoundation
import Combine
import CryptoKit
import Foundation

enum AudioPlaybackState: String, Equatable {
    case ready
    case playing
    case paused
    case stopped
    case finished
    case error
}

struct AudioPlaybackStateMachine: Equatable {
    private(set) var state: AudioPlaybackState = .stopped
    private(set) var elapsed: TimeInterval = 0
    private(set) var duration: TimeInterval = 0

    mutating func load(duration: TimeInterval) {
        self.duration = max(0, duration)
        elapsed = 0
        state = .ready
    }

    mutating func play() {
        if state == .finished { elapsed = 0 }
        state = .playing
    }

    mutating func pause() {
        guard state == .playing else { return }
        state = .paused
    }

    mutating func seek(to value: TimeInterval) {
        elapsed = min(max(0, value), duration)
        if elapsed >= duration, duration > 0 {
            state = .finished
        } else if state == .finished {
            state = .paused
        }
    }

    mutating func stop() {
        elapsed = 0
        state = .stopped
    }

    mutating func finish() {
        elapsed = duration
        state = .finished
    }

    mutating func fail() {
        state = .error
    }
}

struct AudioPlaybackBinding: Equatable {
    let url: URL
    let audioSHA256: String
    let pathIdentity: String
    let synthesisFingerprint: String
    let provider: String
    let profileID: String
    let bookSlug: String
    let jobID: String
    let segmentID: String
    let role: String
}

private struct AudioFileSnapshot: Equatable {
    let size: UInt64
    let modificationDate: Date
    let fileNumber: UInt64

    init(url: URL) throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let size = attributes[.size] as? NSNumber,
              let modificationDate = attributes[.modificationDate] as? Date,
              let fileNumber = attributes[.systemFileNumber] as? NSNumber,
              (attributes[.type] as? FileAttributeType) == .typeRegular else {
            throw CocoaError(.fileReadCorruptFile)
        }
        self.size = size.uint64Value
        self.modificationDate = modificationDate
        self.fileNumber = fileNumber.uint64Value
    }
}

@MainActor
final class EmbeddedAudioPlayer: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var machine = AudioPlaybackStateMachine()
    @Published private(set) var binding: AudioPlaybackBinding?
    @Published private(set) var errorMessage: String?

    var onIdentityInvalidated: (() -> Void)?

    private var audioPlayer: AVAudioPlayer?
    private var timer: Timer?
    private var fileSnapshot: AudioFileSnapshot?

    var state: AudioPlaybackState { machine.state }
    var elapsed: TimeInterval { machine.elapsed }
    var duration: TimeInterval { machine.duration }
    var isLoaded: Bool { binding != nil && audioPlayer != nil }

    func loadAndPlay(_ newBinding: AudioPlaybackBinding) {
        clear(markStopped: true)
        do {
            guard Self.pathIdentity(newBinding.url) == newBinding.pathIdentity else {
                throw PlayerError.identityChanged
            }
            guard try Self.sha256(newBinding.url) == newBinding.audioSHA256 else {
                throw PlayerError.identityChanged
            }
            let snapshot = try AudioFileSnapshot(url: newBinding.url)
            let player = try AVAudioPlayer(contentsOf: newBinding.url)
            player.delegate = self
            guard player.prepareToPlay(), player.duration > 0 else {
                throw PlayerError.cannotDecode
            }
            audioPlayer = player
            binding = newBinding
            fileSnapshot = snapshot
            machine.load(duration: player.duration)
            errorMessage = nil
            player.play()
            machine.play()
            startTimer()
        } catch {
            machine.fail()
            errorMessage = playbackErrorLabel(error)
            invalidateIdentity()
        }
    }

    func togglePlayPause() {
        guard validateLoadedIdentity(), let player = audioPlayer else { return }
        if player.isPlaying {
            player.pause()
            machine.seek(to: player.currentTime)
            machine.pause()
            stopTimer()
        } else {
            if machine.state == .finished { player.currentTime = 0 }
            player.play()
            machine.play()
            startTimer()
        }
    }

    func stop() {
        audioPlayer?.stop()
        audioPlayer?.currentTime = 0
        machine.stop()
        stopTimer()
    }

    func seek(to value: TimeInterval) {
        guard validateLoadedIdentity(), let player = audioPlayer else { return }
        let target = min(max(0, value), player.duration)
        player.currentTime = target
        machine.seek(to: target)
    }

    func clear(markStopped: Bool = true) {
        audioPlayer?.stop()
        audioPlayer = nil
        binding = nil
        fileSnapshot = nil
        stopTimer()
        errorMessage = nil
        if markStopped { machine.stop() }
    }

    func validateLoadedIdentity(rehash: Bool = false) -> Bool {
        guard let binding, let fileSnapshot else { return false }
        do {
            guard Self.pathIdentity(binding.url) == binding.pathIdentity else {
                throw PlayerError.identityChanged
            }
            guard try AudioFileSnapshot(url: binding.url) == fileSnapshot else {
                throw PlayerError.identityChanged
            }
            if rehash, try Self.sha256(binding.url) != binding.audioSHA256 {
                throw PlayerError.identityChanged
            }
            return true
        } catch {
            audioPlayer?.stop()
            machine.fail()
            errorMessage = playbackErrorLabel(error)
            invalidateIdentity()
            return false
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            guard self.audioPlayer === player else { return }
            stopTimer()
            if flag {
                machine.finish()
            } else {
                machine.fail()
                errorMessage = "Не удалось завершить воспроизведение WAV."
                invalidateIdentity()
            }
        }
    }

    private func startTimer() {
        stopTimer()
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.validateLoadedIdentity(), let player = self.audioPlayer else {
                    return
                }
                self.machine.seek(to: player.currentTime)
            }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func invalidateIdentity() {
        stopTimer()
        binding = nil
        fileSnapshot = nil
        onIdentityInvalidated?()
    }

    private nonisolated static func sha256(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var digest = SHA256()
        while true {
            let data = try handle.read(upToCount: 1_048_576) ?? Data()
            if data.isEmpty { break }
            digest.update(data: data)
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private nonisolated static func pathIdentity(_ url: URL) -> String {
        let resolved = url.resolvingSymlinksInPath().standardizedFileURL.path
        return SHA256.hash(data: Data(resolved.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}

private enum PlayerError: Error {
    case identityChanged
    case cannotDecode
}

private func playbackErrorLabel(_ error: Error) -> String {
    if let playerError = error as? PlayerError {
        switch playerError {
        case .identityChanged:
            return "Файл изменился после загрузки. Откройте текущую версию заново."
        case .cannotDecode:
            return "Не удалось подготовить WAV к воспроизведению."
        }
    }
    return "Ошибка воспроизведения: \(error.localizedDescription)"
}

func playbackStateLabel(_ state: AudioPlaybackState) -> String {
    switch state {
    case .ready: return "Готово"
    case .playing: return "Воспроизводится"
    case .paused: return "Пауза"
    case .stopped: return "Остановлено"
    case .finished: return "Завершено"
    case .error: return "Ошибка воспроизведения"
    }
}

func audioTimeLabel(_ value: TimeInterval) -> String {
    guard value.isFinite, value >= 0 else { return "00:00" }
    let seconds = Int(value.rounded(.down))
    return String(format: "%02d:%02d", seconds / 60, seconds % 60)
}
