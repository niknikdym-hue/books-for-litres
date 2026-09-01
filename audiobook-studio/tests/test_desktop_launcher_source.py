from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "native" / "install_desktop_launcher.sh"
OBSOLETE_LAUNCHER = ROOT / "native" / "DesktopLauncher.swift"


class DesktopInstallSourceTests(unittest.TestCase):
    def test_desktop_installs_real_signed_studio_bundle_directly(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertFalse(OBSOLETE_LAUNCHER.exists())
        self.assertIn('desktop_app="$HOME/Desktop/Audiobook Studio.app"', installer)
        self.assertIn('real_bundle_id', installer)
        self.assertIn('ru.elena.audiobookstudio', installer)
        self.assertIn('ditto --norsrc --noextattr "$real_app" "$desktop_staging"', installer)
        self.assertIn('codesign --verify --deep --strict "$real_app"', installer)
        self.assertIn('codesign --verify --deep --strict "$desktop_staging"', installer)
        self.assertIn('codesign --verify --deep --strict "$desktop_app"', installer)
        self.assertIn('installed_exec="$desktop_app/Contents/MacOS/Audiobook Studio"', installer)
        self.assertIn("Installed Desktop executable is not native Mach-O", installer)

    def test_no_desktop_launcher_indirection_remains(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertNotIn("DesktopLauncher.swift", installer)
        self.assertNotIn("ru.elena.audiobookstudio.launcher", installer)
        self.assertNotIn("NSWorkspace", installer)
        self.assertNotIn("open -na", installer)
        self.assertNotIn("openApplication", installer)
        self.assertNotIn("Audiobook Studio Launcher", installer)

    def test_existing_desktop_item_is_archived_before_atomic_replacement(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn('archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"', installer)
        self.assertIn('mv "$desktop_app" "$archive_previous"', installer)
        self.assertIn('mv "$desktop_staging" "$desktop_app"', installer)
        self.assertIn('mv "$archive_previous" "$desktop_app" || true', installer)


if __name__ == "__main__":
    unittest.main()
