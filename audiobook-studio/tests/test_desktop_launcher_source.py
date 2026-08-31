from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "native" / "install_desktop_launcher.sh"
LAUNCHER = ROOT / "native" / "DesktopLauncher.swift"


class DesktopLauncherSourceTests(unittest.TestCase):
    def test_launcher_is_native_and_path_bound(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")
        source = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("xcrun swiftc", installer)
        self.assertIn("DesktopLauncher.swift", installer)
        self.assertIn("Mach-O", installer)
        self.assertNotIn("open -na", installer)
        self.assertNotIn("#!/bin/zsh\nset -euo pipefail\nreal_app=", installer)

        self.assertIn('private static let realBundleID = "ru.elena.audiobookstudio"', source)
        self.assertIn("builds/native-staging/Audiobook Studio.app", source)
        self.assertIn("NSWorkspace.shared.openApplication", source)
        self.assertIn("configuration.createsNewApplicationInstance = true", source)
        self.assertIn("app.bundleURL?.standardizedFileURL == realApp", source)
        self.assertIn("launchedApp.bundleURL?.standardizedFileURL == realApp", source)

    def test_launcher_reports_failure_outside_workspace(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("Library/Logs/Audiobook Studio", source)
        self.assertIn("Не удалось запустить Audiobook Studio", source)
        self.assertIn("NSAlert()", source)


if __name__ == "__main__":
    unittest.main()
