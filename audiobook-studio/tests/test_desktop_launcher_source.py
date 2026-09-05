from pathlib import Path
import re
import subprocess
import sys
import tempfile
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
        self.assertIn('source_ref="refs/heads/main"', updater)
        self.assertIn(
            'reviewed_source_sha="${AUDIOBOOK_STUDIO_REVIEWED_RELEASE_SHA:-${1:-}}"',
            updater,
        )
        self.assertIn(
            '/usr/bin/git -C "$checkout_root" fetch -q --no-tags --depth 1 origin "$source_ref"',
            updater,
        )
        self.assertIn(
            'source_sha="$(/usr/bin/git -C "$checkout_root" rev-parse --verify '
            "'FETCH_HEAD^{commit}')\"",
            updater,
        )
        self.assertIn('[[ "$source_sha" == "$reviewed_source_sha" ]]', updater)
        self.assertIn('/usr/bin/git -C "$checkout_root" checkout -q --detach "$source_sha"', updater)
        self.assertIn('[[ "$actual_sha" == "$source_sha" ]] || fail "source identity mismatch"', updater)
        self.assertIn('/bin/zsh "$source_root/native/build_native_app.sh" "$candidate_app"', updater)
        self.assertIn('/bin/zsh "$source_root/native/install_desktop_launcher.sh" "$candidate_app"', updater)
        self.assertIn('/usr/bin/open "$desktop_app"', updater)
        self.assertNotIn(".zip", updater.lower())
        self.assertNotIn("unzip", updater.lower())
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("Audiobook-Studio-preview.zip", workflow)
        self.assertIn("Validate owner local updater", workflow)
        self.assertIn("/bin/zsh -n native/update_desktop_from_github.sh", workflow)

    def test_owner_update_requires_exact_reviewed_current_main_instead_of_aging_pin(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")

        self.assertIsNone(
            re.search(r'^readonly source_sha="[0-9a-f]{40}"$', updater, re.MULTILINE),
            "The updater must not pin an aging install target.",
        )
        self.assertIn(
            'fail "set AUDIOBOOK_STUDIO_REVIEWED_RELEASE_SHA to the exact reviewed current-main commit"',
            updater,
        )
        self.assertIn(
            'fail "reviewed release is not current GitHub main (current: $source_sha)"',
            updater,
        )
        reviewed_gate = updater.index('[[ "${#reviewed_source_sha}" -eq 40')
        fetch_main = updater.index('/usr/bin/git -C "$checkout_root" fetch')
        identity_gate = updater.index('[[ "$source_sha" == "$reviewed_source_sha" ]]')
        checkout = updater.index('/usr/bin/git -C "$checkout_root" checkout')
        build = updater.index('/bin/zsh "$source_root/native/build_native_app.sh"')
        self.assertLess(reviewed_gate, fetch_main)
        self.assertLess(fetch_main, identity_gate)
        self.assertLess(identity_gate, checkout)
        self.assertLess(checkout, build)
        self.assertIn('print -- "Source ref: $source_ref"', updater)
        self.assertIn('print -- "Source: $source_sha"', updater)

    def test_owner_update_is_offline_for_studio_execution_and_preserves_production_data(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("OPENAI_API_KEY='' YANDEX_API_KEY='' YANDEX_CLOUD_API_KEY=''", updater)
        self.assertIn('assert value.get("provider_requests") == 0', updater)
        self.assertIn('assert value.get("remote_request_sent") is False', updater)
        self.assertIn('assert value.get("model_calls") == 0', updater)
        self.assertIn('assert value.get("paid_execution") is False', updater)
        self.assertIn('assert value.get("billing_changed") is False', updater)
        self.assertIn('book_sound_design.py', updater)
        self.assertIn('book_sound_runner.py', updater)
        self.assertIn('pronunciation_dictionary.py', updater)
        self.assertIn('for directory in backends contracts', updater)
        self.assertNotIn('rm -rf "$runtime_root/books"', updater)
        self.assertNotIn('rm -rf "$runtime_root/renders"', updater)
        self.assertNotIn('rm -rf "$runtime_root/cache"', updater)
        self.assertNotIn('rm -rf "$runtime_root/qa"', updater)
        self.assertNotIn('rm -rf "$runtime_root/billing"', updater)
        self.assertIn("rollback_runtime", updater)
        self.assertIn('archive_root="$HOME/Library/Application Support/Audiobook Studio/Archives"', updater)
        self.assertIn(
            'private_pronunciation_root="$workspace_root/settings/pronunciation"',
            updater,
        )
        self.assertIn(
            'private_pronunciation_dictionary="$private_pronunciation_root/user-dictionary-v1.json"',
            updater,
        )
        self.assertIn("private_pronunciation_snapshot()", updater)
        self.assertIn(
            'readonly private_pronunciation_before="$(private_pronunciation_snapshot)"',
            updater,
        )
        self.assertIn(
            'private_pronunciation_after="$(private_pronunciation_snapshot)"',
            updater,
        )
        self.assertIn(
            '[[ "$private_pronunciation_after" == "$private_pronunciation_before" ]]',
            updater,
        )
        snapshot_before = updater.index("private_pronunciation_before=")
        runtime_sync = updater.index('temporary_target="$runtime_root/.$name.update.$$"')
        snapshot_after = updater.index("private_pronunciation_after=")
        desktop_install = updater.index('/bin/zsh "$source_root/native/install_desktop_launcher.sh"')
        self.assertLess(snapshot_before, runtime_sync)
        self.assertLess(runtime_sync, snapshot_after)
        self.assertLess(snapshot_after, desktop_install)
        self.assertNotIn('rm -rf "$workspace_root/settings"', updater)
        self.assertNotIn('ditto "$source_root/settings"', updater)
        self.assertIn("settings/pronunciation dictionary", installer)
        self.assertNotIn('rm -rf "$workspace_root/settings"', installer)
        self.assertNotIn('ditto "$real_app" "$workspace_root', installer)

    def test_private_pronunciation_seal_covers_dictionary_lock_and_state(self) -> None:
        updater = UPDATER.read_text(encoding="utf-8")
        match = re.search(
            r"private_pronunciation_snapshot\(\) \{\n"
            r"  \"\$python_executable\" - \"\$private_pronunciation_root\" <<'PY'\n"
            r"(?P<script>.*?)\nPY\n\}",
            updater,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        snapshot_script = match.group("script")

        with tempfile.TemporaryDirectory() as directory:
            pronunciation = Path(directory) / "settings" / "pronunciation"
            pronunciation.mkdir(parents=True)
            dictionary = pronunciation / "user-dictionary-v1.json"
            lock = pronunciation / "user-dictionary-v1.json.lock"
            state = pronunciation / "migration-state-v1.json"
            dictionary.write_text('{"schema_version":1,"revision":1,"entries":[]}', encoding="utf-8")
            lock.write_bytes(b"")
            state.write_text('{"migration":"complete"}', encoding="utf-8")

            def seal() -> str:
                return subprocess.check_output(
                    [sys.executable, "-c", snapshot_script, str(pronunciation)],
                    text=True,
                ).strip()

            baseline = seal()
            self.assertEqual(seal(), baseline)
            dictionary.write_text('{"schema_version":1,"revision":2,"entries":[]}', encoding="utf-8")
            self.assertNotEqual(seal(), baseline)
            dictionary.write_text('{"schema_version":1,"revision":1,"entries":[]}', encoding="utf-8")
            lock.write_bytes(b"lock-state")
            self.assertNotEqual(seal(), baseline)
            lock.write_bytes(b"")
            state.write_text('{"migration":"pending"}', encoding="utf-8")
            self.assertNotEqual(seal(), baseline)


if __name__ == "__main__":
    unittest.main()
