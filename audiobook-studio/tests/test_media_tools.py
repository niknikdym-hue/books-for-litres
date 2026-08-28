from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media_tools import resolve_ffmpeg


class MediaToolResolverTests(unittest.TestCase):
    def _fake_ffmpeg(self, path: Path, version: str = "ffmpeg version test-1") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_explicit_override_is_path_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = self._fake_ffmpeg(root / "managed/ffmpeg")
            resolution = resolve_ffmpeg(
                root,
                env={"AUDIOBOOK_STUDIO_FFMPEG": str(executable), "PATH": ""},
                known_locations=[],
            )
            self.assertTrue(resolution.available)
            self.assertEqual(resolution.path, executable.resolve())
            self.assertEqual(resolution.source, "environment")
            self.assertEqual(resolution.version, "ffmpeg version test-1")

    def test_finder_empty_path_uses_known_absolute_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = self._fake_ffmpeg(root / "absolute/ffmpeg")
            resolution = resolve_ffmpeg(
                root,
                env={"PATH": ""},
                known_locations=[executable],
            )
            self.assertTrue(resolution.available)
            self.assertEqual(resolution.source, "known_macos_location")

    def test_invalid_override_falls_through_and_unavailable_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolution = resolve_ffmpeg(
                root,
                env={"AUDIOBOOK_STUDIO_FFMPEG": str(root / "missing"), "PATH": "/bin"},
                known_locations=[],
            )
            self.assertFalse(resolution.available)
            self.assertIsNone(resolution.path)
            self.assertEqual(resolution.source, "unavailable")


if __name__ == "__main__":
    unittest.main()
