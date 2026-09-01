from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "native" / "install_desktop_launcher.sh"
UPDATER = ROOT / "native" / "update_desktop_from_github.sh"
WORKFLOW = ROOT.parent / ".github" / "workflows" / "audiobook-studio-offline.yml"
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

    def test_owner_update_builds_locally_instead_of_delivering_downloaded_app_archive(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('repository_url="https://github.com/niknikdym-hue/books-for-litres.git"', updater)
        self.assertIn('source_sha="c61c87f4858b8999131e080aeeaf581d9b3bce48"', updater)
        self.assertIn('/usr/bin/git -C "$checkout_root" fetch -q --depth 1 origin "$source_sha"', updater)
        self.assertIn('/bin/zsh "$source_root/native/build_native_app.sh" "$candidate_app"', updater)
        self.assertIn('/bin/zsh "$source_root/native/install_desktop_launcher.sh" "$candidate_app"', updater)
        self.assertIn('/usr/bin/open "$desktop_app"', updater)
        self.assertNotIn(".zip", updater.lower())
        self.assertNotIn("unzip", updater.lower())
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("Audiobook-Studio-preview.zip", workflow)
        self.assertIn("Validate owner local updater", workflow)
        self.assertIn("/bin/zsh -n native/update_desktop_from_github.sh", workflow)

    def test_owner_update_is_offline_for_studio_execution_and_preserves_production_data(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")

        self.assertIn("OPENAI_API_KEY='' YANDEX_API_KEY='' YANDEX_CLOUD_API_KEY=''", updater)
        self.assertIn('assert value.get("provider_requests") == 0', updater)
        self.assertIn('assert value.get("remote_request_sent") is False', updater)
        self.assertIn('assert value.get("model_calls") == 0', updater)
        self.assertIn('assert value.get("paid_execution") is False', updater)
        self.assertIn('assert value.get("billing_changed") is False', updater)
        self.assertIn('for directory in backends contracts', updater)
        self.assertNotIn('rm -rf "$runtime_root/books"', updater)
        self.assertNotIn('rm -rf "$runtime_root/renders"', updater)
        self.assertNotIn('rm -rf "$runtime_root/cache"', updater)
        self.assertNotIn('rm -rf "$runtime_root/qa"', updater)
        self.assertNotIn('rm -rf "$runtime_root/billing"', updater)
        self.assertIn("rollback_runtime", updater)
        self.assertIn('archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"', updater)


if __name__ == "__main__":
    unittest.main()
