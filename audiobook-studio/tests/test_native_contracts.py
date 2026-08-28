from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("xcrun"), "requires the macOS Xcode toolchain")
    def test_swift_decodes_canonical_snapshot_and_renders_billing_honestly(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            snapshot = temporary / "snapshot.json"
            binary = temporary / "native-contract-tests"
            environment = dict(os.environ)
            workspace = temporary / "workspace"
            books = workspace / "books"
            books.mkdir(parents=True)
            shutil.copy2(ROOT / "books/demo-book.json", books / "demo-book.json")
            environment["AUDIOBOOK_STUDIO_HOME"] = str(workspace)
            completed = subprocess.run(
                [sys.executable, str(ROOT / "audiobook_studio_app_runner.py"), "--ui-snapshot"],
                check=False,
                capture_output=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            snapshot.write_bytes(completed.stdout)
            sdk_path = subprocess.run(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            swift_version = subprocess.run(
                ["xcrun", "swiftc", "--version"], check=True, capture_output=True, text=True
            ).stdout
            cache_key = hashlib.sha256(f"{swift_version}|{sdk_path}".encode()).hexdigest()[:16]
            module_cache = Path(tempfile.gettempdir()) / "audiobook-studio-native-contract-cache" / cache_key
            (module_cache / "clang").mkdir(parents=True, exist_ok=True)
            (module_cache / "swift").mkdir(exist_ok=True)
            environment["CLANG_MODULE_CACHE_PATH"] = str(module_cache / "clang")
            environment["SWIFT_MODULECACHE_PATH"] = str(module_cache / "swift")

            compile_result = subprocess.run(
                [
                    "xcrun", "swiftc", "-parse-as-library",
                    str(ROOT / "native" / "StudioContracts.swift"),
                    str(ROOT / "native" / "AudioQAContracts.swift"),
                    str(ROOT / "native" / "EmbeddedAudioPlayer.swift"),
                    str(ROOT / "native" / "NativeContractTests.swift"),
                    "-target", "arm64-apple-macosx14.0",
                    "-sdk", sdk_path,
                    "-module-cache-path", str(module_cache / "swift"),
                    "-o", str(binary),
                    "-framework", "AVFoundation",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                [str(binary), str(snapshot)], check=False, capture_output=True, text=True
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)
            self.assertIn("NATIVE_CONTRACT_TESTS_PASS", run_result.stdout)


if __name__ == "__main__":
    unittest.main()
