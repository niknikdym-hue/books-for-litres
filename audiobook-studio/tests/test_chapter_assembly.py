from __future__ import annotations

import copy
import errno
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
    assembly_input_from_qa_segments,
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

    def _segment_input(self, rates=(48_000, 48_000, 48_000), order=None) -> dict:
        pairs = []
        segment_ids = [f"s{index:04d}" for index in range(1, len(rates) + 1)]
        for index, (segment_id, rate) in enumerate(zip(segment_ids, rates), start=1):
            audio = self.root / f"renders/openai/segments/{segment_id}.wav"
            manifest = self.root / "renders/openai/MANIFEST.json"
            self._write_wav(audio, rate, seconds=index / 100)
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text('{"state":"SUCCEEDED"}', encoding="utf-8")
            fingerprint = str(index) * 64
            authority = dict(
                self.authority,
                provider="openai",
                profile_id="openai_cedar",
                segment_id=segment_id,
                audio_path=str(audio),
                manifest_path=str(manifest),
                synthesis_fingerprint=fingerprint,
            )
            record = dict(
                self.record,
                provider="openai",
                profile_id="openai_cedar",
                segment_id=segment_id,
                audio_path=str(audio),
                identity={
                    "audio_sha256": sha256_file(audio),
                    "path_identity": path_identity(audio),
                    "synthesis_fingerprint": fingerprint,
                },
                wav=self._facts(audio),
            )
            pairs.append((authority, record))
        actual_order = order or segment_ids
        by_id = {pair[0]["segment_id"]: pair for pair in pairs}
        return assembly_input_from_qa_segments(
            [by_id[item] for item in actual_order],
            expected_segment_ids=segment_ids,
            prepared_text_identity="prepared-text-v1",
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

    def test_source_change_during_ffmpeg_never_publishes_ready(self):
        original_run = __import__("subprocess").run

        def mutate_after_conversion(*args, **kwargs):
            completed = original_run(*args, **kwargs)
            self.source.touch()
            return completed

        with mock.patch.object(self.service, "_resolution", return_value=self._available()), mock.patch(
            "chapter_assembly.subprocess.run", side_effect=mutate_after_conversion
        ), self.assertRaisesRegex(ChapterAssemblyError, "измени.*во время сборки"):
            self.service.assemble(self._input())
        self.assertFalse(any((self.root / "chapters").rglob("MANIFEST.json")))

    def test_conversion_uses_the_resolution_bound_into_assembly_identity(self):
        other = FFmpegResolution(True, Path("/different/ffmpeg"), "ffmpeg version other", "config")
        with mock.patch.object(
            self.service, "_resolution", side_effect=[self._available(), other]
        ) as resolution:
            result = self.service.assemble(self._input())
        self.assertEqual(resolution.call_count, 1)
        self.assertEqual(result["normalization"]["ffmpeg_version"], "ffmpeg version deterministic-test")

    def test_three_approved_segments_preserve_order_duration_and_idempotence(self):
        value = self._segment_input()
        with mock.patch.object(self.service, "_resolution", return_value=FFmpegResolution(False, None, None, "unavailable")):
            first = self.service.assemble(value)
            second = self.service.assemble(value)
        self.assertEqual(first["assembly_identity"], second["assembly_identity"])
        self.assertEqual(first["ordered_segment_ids"], ["s0001", "s0002", "s0003"])
        self.assertEqual(first["input_granularity"], "segments")
        self.assertEqual(first["pause_contract"], "no_added_intersegment_silence_v1")
        self.assertEqual(first["concat"]["added_pause_frames"], 0)
        self.assertEqual(first["concat"]["output_frames"], sum(first["concat"]["ordered_input_frames"]))
        self.assertAlmostEqual(
            first["output"]["wav"]["duration_seconds"],
            sum(item["wav"]["duration_seconds"] for item in first["normalization"]["segments"]),
            places=9,
        )
        self.assertFalse(first["normalization"]["performed"])
        self.assertEqual(first["provider_requests"], 0)

    def test_pcm_output_preserves_prepared_segment_order(self):
        value = self._segment_input()
        frame_counts = []
        expected_samples = []
        for index, item in enumerate(value["ordered_inputs"], start=1):
            path = Path(item["source"]["audio_path"])
            frames = index * 20
            frame_counts.append(frames)
            expected_samples.extend([index * 1000] * frames)
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(48_000)
                output.writeframes(b"".join(struct.pack("<h", index * 1000) for _ in range(frames)))
            item["source"]["audio_sha256"] = sha256_file(path)
            item["wav"] = self._facts(path)
        with mock.patch.object(self.service, "_resolution", return_value=FFmpegResolution(False, None, None, "unavailable")):
            result = self.service.assemble(value)
        with wave.open(result["output"]["path"], "rb") as assembled:
            samples = [item[0] for item in struct.iter_unpack("<h", assembled.readframes(assembled.getnframes()))]
        self.assertEqual(samples, expected_samples)
        self.assertEqual(result["concat"]["ordered_input_frames"], frame_counts)

    def test_new_expected_segment_stales_existing_assembly(self):
        original = self._segment_input()
        unavailable = FFmpegResolution(False, None, None, "unavailable")
        with mock.patch.object(self.service, "_resolution", return_value=unavailable):
            first = self.service.assemble(original)
        expanded = self._segment_input(rates=(48_000, 48_000, 48_000, 48_000))
        expanded["prepared_text_identity"] = "prepared-text-v2"
        with mock.patch.object(self.service, "_resolution", return_value=unavailable):
            status = self.service.status(expanded)
        self.assertNotEqual(first["assembly_identity"], status["assembly_identity"])
        self.assertEqual(status["state"], "STALE")
        self.assertEqual(status["decision"], "READY_TO_ASSEMBLE")

    def test_segment_set_rejects_incomplete_duplicate_wrong_order_and_qa(self):
        with self.assertRaisesRegex(ChapterAssemblyError, "одобрены не все"):
            base = self._segment_input()
            pairs = []
            for item in base["ordered_inputs"][:2]:
                authority = dict(self.authority, provider="openai", profile_id="openai_cedar", segment_id=item["segment_id"], **item["source"])
                pairs.append((authority, dict(item["qa"], **{"provider": "openai"})))
            assembly_input_from_qa_segments(pairs, expected_segment_ids=["s0001", "s0002", "s0003"], prepared_text_identity="x")
        with self.assertRaisesRegex(ChapterAssemblyError, "Порядок сегментов"):
            self._segment_input(order=["s0002", "s0001", "s0003"])
        duplicate = self._segment_input()
        duplicate["ordered_inputs"][1]["source"] = copy.deepcopy(duplicate["ordered_inputs"][0]["source"])
        duplicate["ordered_inputs"][1]["wav"] = copy.deepcopy(duplicate["ordered_inputs"][0]["wav"])
        with self.assertRaises(ChapterAssemblyError):
            self.service.prepare(duplicate)
        for field, value in (("manual_state", "UNREVIEWED"), ("manual_state", "STALE"), ("downstream_eligible", False)):
            blocked = self._segment_input()
            blocked["ordered_inputs"][1]["qa"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ChapterAssemblyError):
                self.service.prepare(blocked)

    def test_any_segment_identity_change_changes_identity_or_blocks(self):
        value = self._segment_input()
        with mock.patch.object(self.service, "_resolution", return_value=FFmpegResolution(False, None, None, "unavailable")):
            original = self.service.prepare(value)
            reordered = copy.deepcopy(value)
            reordered["ordered_inputs"] = list(reversed(reordered["ordered_inputs"]))
            for position, item in enumerate(reordered["ordered_inputs"], start=1):
                item["position"] = position
            reordered["ordered_segment_ids"] = [item["segment_id"] for item in reordered["ordered_inputs"]]
            changed_order = self.service.prepare(reordered)
        self.assertNotEqual(original["assembly_identity"], changed_order["assembly_identity"])
        for field, replacement in (("audio_sha256", "0" * 64), ("path_identity", "0" * 64)):
            changed = copy.deepcopy(value)
            changed["ordered_inputs"][1]["source"][field] = replacement
            with self.subTest(field=field), self.assertRaises(ChapterAssemblyError):
                self.service.prepare(changed)
        changed = copy.deepcopy(value)
        changed["ordered_inputs"][1]["source"]["synthesis_fingerprint"] = "9" * 64
        with mock.patch.object(self.service, "_resolution", return_value=FFmpegResolution(False, None, None, "unavailable")):
            self.assertNotEqual(original["assembly_identity"], self.service.prepare(changed)["assembly_identity"])

    def test_mixed_rates_normalize_per_segment_with_one_prepared_ffmpeg(self):
        value = self._segment_input(rates=(48_000, 22_050, 44_100))
        other = FFmpegResolution(True, Path("/wrong/ffmpeg"), "wrong", "config")
        with mock.patch.object(self.service, "_resolution", side_effect=[self._available(), other]) as resolution:
            result = self.service.assemble(value)
        self.assertEqual(resolution.call_count, 1)
        self.assertEqual([item["performed"] for item in result["normalization"]["segments"]], [False, True, True])
        self.assertEqual(result["output"]["wav"]["sample_rate_hz"], 48_000)

    def test_revalidation_and_partial_normalization_failure_never_publish(self):
        value = self._segment_input(rates=(48_000, 22_050, 48_000))
        stale = copy.deepcopy(value)
        stale["ordered_inputs"][2]["qa"]["manual_state"] = "STALE"
        with mock.patch.object(self.service, "_resolution", return_value=self._available()), self.assertRaises(ChapterAssemblyError):
            self.service.assemble(value, revalidate=lambda: stale)
        self.assertFalse(any((self.root / "chapters").rglob("MANIFEST.json")))

        original = self.service._normalize_source
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ChapterAssemblyError("simulated_failure", "simulated")
            return original(*args, **kwargs)
        with mock.patch.object(self.service, "_resolution", return_value=self._available()), mock.patch.object(
            self.service, "_normalize_source", side_effect=fail_second
        ), self.assertRaisesRegex(ChapterAssemblyError, "simulated"):
            self.service.assemble(value)
        self.assertFalse(any((self.root / "chapters").rglob("MANIFEST.json")))

    def test_nonempty_directory_publish_race_returns_winner_idempotently(self):
        winner = {"status": "READY", "assembly_identity": "winner"}
        unavailable = FFmpegResolution(False, None, None, "unavailable")
        with mock.patch.object(self.service, "_resolution", return_value=unavailable), mock.patch.object(
            self.service, "_read_ready", side_effect=[None, winner]
        ), mock.patch("pathlib.Path.rename", side_effect=OSError(errno.ENOTEMPTY, "not empty")):
            result = self.service.assemble(self._segment_input())
        self.assertIs(result, winner)


if __name__ == "__main__":
    unittest.main()
