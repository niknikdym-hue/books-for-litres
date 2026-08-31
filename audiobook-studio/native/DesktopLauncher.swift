import AppKit
import Foundation

@main
enum AudiobookStudioDesktopLauncher {
    private static let realBundleID = "ru.elena.audiobookstudio"
    private static let relativeRealApp = "Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app"

    static func main() {
        let fileManager = FileManager.default
        let home = fileManager.homeDirectoryForCurrentUser
        let realApp = home.appendingPathComponent(relativeRealApp, isDirectory: true).standardizedFileURL

        guard fileManager.fileExists(atPath: realApp.path) else {
            fail("Не найдена актуальная программа:\n\(realApp.path)")
        }

        guard let bundle = Bundle(url: realApp), bundle.bundleIdentifier == realBundleID else {
            fail("Файл Audiobook Studio повреждён или имеет неверную идентичность. Ожидался bundle id \(realBundleID).")
        }

        let current = NSRunningApplication.runningApplications(withBundleIdentifier: realBundleID)
            .filter { app in
                guard let url = app.bundleURL?.standardizedFileURL else { return false }
                return url == realApp
            }

        for app in current {
            _ = app.terminate()
        }

        let gracefulDeadline = Date().addingTimeInterval(4.0)
        while Date() < gracefulDeadline {
            let stillRunning = NSRunningApplication.runningApplications(withBundleIdentifier: realBundleID)
                .contains { $0.bundleURL?.standardizedFileURL == realApp && !$0.isTerminated }
            if !stillRunning { break }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }

        let remaining = NSRunningApplication.runningApplications(withBundleIdentifier: realBundleID)
            .filter { $0.bundleURL?.standardizedFileURL == realApp && !$0.isTerminated }
        for app in remaining {
            _ = app.forceTerminate()
        }

        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        configuration.createsNewApplicationInstance = true

        var completed = false
        var launchedApp: NSRunningApplication?
        var launchError: Error?

        NSWorkspace.shared.openApplication(at: realApp, configuration: configuration) { app, error in
            launchedApp = app
            launchError = error
            completed = true
        }

        let launchDeadline = Date().addingTimeInterval(10.0)
        while !completed && Date() < launchDeadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }

        guard completed else {
            fail("macOS не завершила запуск актуальной Audiobook Studio за 10 секунд.")
        }
        if let launchError {
            fail("macOS не смогла открыть актуальную Audiobook Studio:\n\(launchError.localizedDescription)")
        }
        guard let launchedApp,
              launchedApp.bundleIdentifier == realBundleID,
              launchedApp.bundleURL?.standardizedFileURL == realApp else {
            fail("macOS открыла не тот экземпляр Audiobook Studio.")
        }

        launchedApp.activate(options: [.activateIgnoringOtherApps])
    }

    private static func fail(_ message: String) -> Never {
        let logDirectory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Audiobook Studio", isDirectory: true)
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        let logFile = logDirectory.appendingPathComponent("desktop-launcher.log")
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(message.replacingOccurrences(of: "\n", with: " | "))\n"
        if let data = line.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: logFile.path), let handle = try? FileHandle(forWritingTo: logFile) {
                defer { try? handle.close() }
                try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            } else {
                try? data.write(to: logFile, options: .atomic)
            }
        }

        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Не удалось запустить Audiobook Studio"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        _ = alert.runModal()
        Foundation.exit(1)
    }
}
