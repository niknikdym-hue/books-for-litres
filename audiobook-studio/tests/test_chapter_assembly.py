from __future__ import annotations

import copy
import json
import os
import stat
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_qa_review import path_identity, sha256_file
from chapter_assembly import (
    ChapterAssemblyError,
    ChapterAssemblyService,
    assembly_input_from_qa,
)
from media_tools import FFmpegResolution


class ChapterAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "workspace"
        self.root.mkdir()
        self.root = self.root.resolve()
        self.source_dir = self.root / "renders/yandex/demo/chapter-ch001/yandex_lera"
        self.source_dir.mkdir(parents=True)
        self.source = self.source_dir / "source.wav"
        self.manifest = self.source_dir / "MANIFEST.json"
        self._write_wav(self.source, 22_050)
        self.manifest.write_text('{"status":"DONE"}', encoding="utf-8")
        self.service = ChapterAssemblyService(self.root, self.root / "chapters")
        self.authority = {
            "provider": "yandex",
            "book_slug": "demo-book",
            "book_title": "Демо",
            "job_id": "chapter-ch001",
            "job_label": "Глава 1",
            "profile_id": "yandex_lera",
            "segment_id": "chapter-ch001",
            "audio_path": str(self.source),
            "manifest_path": str(self.manifest),
            "synthesis_fingerprint": "f" * 64,
        }
        self.record = {
            "provider": "yandex",
            "profile_id": "yandex_lera",
            "book_slug": "demo-book",
            "job_id": "chapter-ch001",
            "segment_id": "chapter-ch001",
            "audio_path": str(self.source),
            "identity": {
                "audio_sha256": sha256_file(self.source),
                "path_identity": path_identity(self.source),
                "synthesis_fingerprint": "f" * 64,
            },
            "automatic_status": "PASS",
            "manual_state": "APPROVED",
            "downstream_eligible": True,
            "wav": self._facts(self.source),
        }
        self.fake_ffmpeg = self.root / "tools/fake-ffmpeg"
        self._write_fake_ffmpeg(self.fake_ffmpeg)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _write_wav(path: Path, rate: int, seconds: float = 0.1) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = int(rate * seconds)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(b"".join(
                struct.pack("<h", ((index % 100) - 50) * 100)
                for index in range(frames)
            ))

    @staticmethod
    def _facts(path: Path) -> dict:
        with wave.open(str(path), "rb") as source:
            return {
                "sample_rate_hz": source.getframerate(),
                "channels": source.getnchannels(),
                "sample_width_bytes": source.getsampwidth(),
                "duration_seconds": source.getnframes() / source.getframerate(),
                "compression_type": source.getcomptype(),
            }

    @staticmethod
    def _write_fake_ffmpeg(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!" + sys.executable + "\n"
            "import pathlib, struct, sys, wave\n"
            "if '-version' in sys.argv:\n"
            " print('ffmpeg version deterministic-test'); raise SystemExit(0)\n"
            "src=pathlib.Path(sys.argv[sys.argv.index('-i')+1]); dst=pathlib.Path(sys.argv[-1])\n"
            "with wave.open(str(src),'rb') as r:\n"
            " data=r.readframes(r.getnframes()); old=r.getframerate(); samples=[x[0] for x in struct.iter_unpack('<h',data)]\n"
            "count=max(1,round(len(samples)*48000/old)); converted=[samples[min(len(samples)-1,(i*old)//48000)] for i in range(count)]\n"
            "with wave.open(str(dst),'wb') as w:\n"
            " w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(b''.join(struct.pack('<h',x) for x in converted))\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _input(self) -> dict:
        return assembly_input_from_qa(self.authority, self.record)

    def _available(self) -> FFmpegResolution:
        return FFmpegResolution(
            True, self.fake_ffmpeg, "ffmpeg version deterministic-test", "environment"
        )

    def test_approved_22050_input_assembles_to_48000_and_is_idempotent(self):
        source_sha = sha256_file(self.source)
        with mock.patch.object(self.service, "_resolution", return_value=self._available()):
            first = self.service.assemble(self._input())
            second = self.service.assemble(self._input())
        self.assertEqual(first["assembly_identity"], second["assembly_identity"])
        self.assertEqual(first["output"]["sha256"], second["output"]["sha256"])
        self.assertEqual(first["output"]["wav"]["sample_rate_hz"], 48_000)
        self.assertEqual(first["output"]["wav"]["channels"], 1)
        self.assertEqual(first["output"]["wav"]["sample_width_bytes"], 2)
        self.assertTrue(first["normalization"]["performed"])
        self.assertEqual(first["provider_requests"], 0)
        self.assertEqual(sha256_file(self.source), source_sha)

    def test_canonical_48000_input_avoids_conversion(self):
        self._write_wav(self.source, 48_000)
        self.record["identity"]["audio_sha256"] = sha256_file(self.source)
        self.record["wav"] = self._facts(self.source)
        with mock.patch.object(self.service, "_resolution", return_value=FFmpegResolution(False, None, None, "unavailable")):
            result = self.service.assemble(self._input())
        self.assertFalse(result["normalization"]["performed"])
        self.assertEqual(result["output"]["sha256"], sha256_file(self.source))

    def test_missing_ffmpeg_blocks_conversion_but_not_input_qa(self):
        with mock.patch.object(self.service, "_resolution", return_value=FFmpegResolution(False, None, None, "unavailable")):
            prepared = self.service.prepare(self._input())
            self.assertEqual(prepared["decision"], "BLOCKED")
            self.assertEqual(prepared["blockers"], ["missing_ffmpeg"])
            with self.assertRaisesRegex(ChapterAssemblyError, "требуется FFmpeg"):
                self.service.assemble(self._input())

    def test_manual_and_downstream_gates_fail_closed(self):
        for field, value, code in (
            ("manual_state", "UNREVIEWED", "manual_approval_required"),
            ("manual_state", "REJECTED", "manual_approval_required"),
            ("downstream_eligible", False, "downstream_blocked"),
            ("automatic_status", "FAIL", "automatic_qa_failed"),
        ):
            record = copy.deepcopy(self.record)
            record[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(ChapterAssemblyError) as raised:
                    assembly_input = assembly_input_from_qa(self.authority, record)
                    self.service.prepare(assembly_input)
                self.assertEqual(raised.exception.code, code)

    def test_authority_fingerprint_and_path_mismatch_block_before_service(self):
        for mutation in ("fingerprint", "path"):
            record = copy.deepcopy(self.record)
            if mutation == "fingerprint":
                record["identity"]["synthesis_fingerprint"] = "e" * 64
            else:
                record["audio_path"] = str(self.source.with_name("other.wav"))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                ChapterAssemblyError, "production authority"
            ):
                assembly_input_from_qa(self.authority, record)

    def test_changed_sha_path_identity_and_wav_facts_block(self):
        mutations = {
            "sha": lambda value: value["source"].__setitem__("audio_sha256", "0" * 64),
            "path": lambda value: value["source"].__setitem__("path_identity", "0" * 64),
            "wav": lambda value: value["wav"].__setitem__("sample_rate_hz", 44_100),
        }
        for label, mutate in mutations.items():
            value = self._input()
            mutate(value)
            with self.subTest(label=label), self.assertRaises(ChapterAssemblyError):
                self.service.prepare(value)

    def test_corrupt_wav_and_symlinked_source_block(self):
        original = self.source.read_bytes()
        self.source.write_bytes(b"not-a-wave")
        value = self._input()
        value["source"]["audio_sha256"] = sha256_file(self.source)
        value["ordered_inputs"][0]["audio_sha256"] = sha256_file(self.source)
        with self.assertRaises(Exception):
            self.service.prepare(value)
        self.source.write_bytes(original)
        link = self.source_dir / "linked.wav"
        link.symlink_to(self.source)
        authority = dict(self.authority, audio_path=str(link))
        record = copy.deepcopy(self.record)
        record["audio_path"] = str(link)
        record["identity"]["audio_sha256"] = sha256_file(link)
        record["identity"]["path_identity"] = path_identity(link)
        with self.assertRaisesRegex(ChapterAssemblyError, "символическую ссылку"):
            self.service.prepare(assembly_input_from_qa(authority, record))

    def test_traversal_unicode_provider_isolation_and_no_credentials(self):
        value = self._input()
        value["book_slug"] = "../escape"
        with self.assertRaises(ChapterAssemblyError):
            self.service.prepare(value)
        unicode_authority = dict(self.authority, book_slug="книга-тест")
        unicode_record = copy.deepcopy(self.record)
        unicode_record["book_slug"] = "книга-тест"
        with mock.patch.object(self.service, "_resolution", return_value=self._available()):
            result = self.service.assemble(assembly_input_from_qa(unicode_authority, unicode_record))
        self.assertIn("книга-тест", result["output"]["path"])
        self.assertNotIn("credential", json.dumps(result).lower())
        second = self._input()
        second["provider"] = "openai"
        with mock.patch.object(self.service, "_resolution", return_value=self._available()):
            other = self.service.assemble(second)
        self.assertNotEqual(result["assembly_identity"], other["assembly_identity"])

    def test_atomic_ffmpeg_failure_leaves_no_ready_manifest(self):
        failing = self.root / "tools/failing-ffmpeg"
        failing.write_text("#!/bin/sh\n[ \"$1\" = -version ] && { echo 'ffmpeg version fail'; exit 0; }; exit 1\n")
        failing.chmod(failing.stat().st_mode | stat.S_IXUSR)
        resolution = FFmpegResolution(True, failing, "ffmpeg version fail", "environment")
        with mock.patch.object(self.service, "_resolution", return_value=resolution):
            prepared = self.service.prepare(self._input())
            with self.assertRaisesRegex(ChapterAssemblyError, "не смог"):
                self.service.assemble(self._input())
        output_dir = Path(prepared["input"]["book_slug"])
        self.assertFalse(any((self.root / "chapters").rglob("MANIFEST.json")))

    def test_changed_manifest_marks_prior_assembly_stale_and_billing_is_untouched(self):
        ledger = self.root / "billing/ledger.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_bytes(b'{"events":[]}\n')
        billing_before = ledger.read_bytes()
        with mock.patch.object(self.service, "_resolution", return_value=self._available()):
            first = self.service.assemble(self._input())
            self.manifest.write_text('{"status":"DONE","revision":2}', encoding="utf-8")
            status = self.service.status(self._input())
        self.assertNotEqual(first["assembly_identity"], status["assembly_identity"])
        self.assertEqual(status["state"], "STALE")
        self.assertEqual(status["decision"], "READY_TO_ASSEMBLE")
        self.assertEqual(ledger.read_bytes(), billing_before)

    def test_symlink_in_input_or_output_ancestor_fails_closed(self):
        input_alias = self.root / "renders/input-alias"
        input_alias.symlink_to(self.source_dir, target_is_directory=True)
        authority = dict(
            self.authority,
            audio_path=str(input_alias / self.source.name),
            manifest_path=str(input_alias / self.manifest.name),
        )
        record = copy.deepcopy(self.record)
        record["audio_path"] = authority["audio_path"]
        record["identity"]["path_identity"] = path_identity(Path(authority["audio_path"]))
        with self.assertRaisesRegex(ChapterAssemblyError, "символическую ссылку"):
            self.service.prepare(assembly_input_from_qa(authority, record))

        real_output = self.root / "real-output"
        real_output.mkdir()
        output_alias = self.root / "output-alias"
        output_alias.symlink_to(real_output, target_is_directory=True)
        with self.assertRaisesRegex(ChapterAssemblyError, "символическую ссылку"):
            ChapterAssemblyService(self.root, output_alias / "chapters")


if __name__ == "__main__":
    unittest.main()
