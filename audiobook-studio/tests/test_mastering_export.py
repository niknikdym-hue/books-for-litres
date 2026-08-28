from __future__ import annotations

import copy
import errno
import json
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_qa_review import path_identity, sha256_file
from backends.common import inspect_pcm_wav
from mastering_export import (
    BOUNDARY_POLICY,
    LITRES_PROFILE,
    MASTER_PRESET,
    LitresExportService,
    MasteringExportError,
    MasteringService,
    _boundary_measurements,
    _parse_loudnorm_json,
    _safe_output_name,
    build_book_export_state,
    canonical_book_authority,
    litres_profile_hash,
    master_preset_hash,
    resolve_current_assembly,
    resolve_current_master,
)
from media_tools import FFmpegResolution


class MasteringExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = (Path(self.temporary.name) / "workspace").resolve()
        self.root.mkdir()
        self.book_slug = "demo-книга"
        self.job_id = "chapter-ch001"
        self.assembly_identity = "a" * 64
        self.assembly_dir = self.root / "chapters" / self.book_slug / self.job_id / self.assembly_identity
        self.assembly_dir.mkdir(parents=True)
        self.assembly_wav = self.assembly_dir / "chapter.wav"
        self._write_wav(self.assembly_wav, seconds=0.5, lead=0.1, tail=0.2)
        self.assembly_manifest = self.assembly_dir / "MANIFEST.json"
        assembly = {
            "schema_version": 1,
            "status": "READY",
            "assembly_identity": self.assembly_identity,
            "book_slug": self.book_slug,
            "book_title": "Демо книга",
            "job_id": self.job_id,
            "job_label": "Введение",
            "input_granularity": "chapter",
            "ordered_inputs": [{"position": 1, "segment_id": self.job_id}],
            "input": {"provider": "yandex", "profile_id": "yandex_lera"},
            "output": {
                "path": str(self.assembly_wav),
                "path_identity": path_identity(self.assembly_wav),
                "sha256": sha256_file(self.assembly_wav),
                "wav": inspect_pcm_wav(self.assembly_wav).to_dict(),
            },
            "provider_requests": 0,
        }
        self.assembly_manifest.write_text(json.dumps(assembly), encoding="utf-8")
        (self.assembly_dir.parent / "CURRENT.json").write_text(json.dumps({
            "schema_version": 1,
            "assembly_identity": self.assembly_identity,
            "manifest_path": str(self.assembly_manifest),
        }), encoding="utf-8")
        self.authority = self._resolve_assembly()
        self.ffmpeg = self.root / "tools" / "ffmpeg"
        self.ffmpeg.parent.mkdir()
        self.ffmpeg.write_text("fake", encoding="utf-8")
        self.ffmpeg.chmod(self.ffmpeg.stat().st_mode | stat.S_IXUSR)
        self.resolution = FFmpegResolution(True, self.ffmpeg, "ffmpeg version test-1", "environment")
        self.mastering = MasteringService(self.root, self.root / "masters")
        self.exporting = LitresExportService(self.root, self.root / "exports")
        self.book = {
            "slug": self.book_slug,
            "title": "Демо книга",
            "author": "Автор",
            "language": "Russian",
            "selected_profile_id": "yandex_lera",
            "jobs": {
                "chapter-ch001": {"kind": "chapter", "chapter_id": "ch001", "label": "Введение", "preparation_identity": "p1"},
                "chapter-ch002": {"kind": "chapter", "chapter_id": "ch002", "label": "Глава 2", "preparation_identity": "p1"},
                "short-test": {"kind": "preview", "label": "Проба"},
            },
        }

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _write_wav(path: Path, *, seconds: float, lead: float = 0, tail: float = 0, amplitude: int = 1200) -> None:
        rate = 48_000
        total = int(seconds * rate)
        lead_frames, tail_frames = int(lead * rate), int(tail * rate)
        samples = []
        for index in range(total):
            value = 0 if index < lead_frames or index >= total - tail_frames else amplitude * (1 if index % 2 else -1)
            samples.append(struct.pack("<h", value))
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(b"".join(samples))

    def _resolve_assembly(self):
        return resolve_current_assembly(
            workspace_root=self.root,
            chapters_root=self.root / "chapters",
            book_slug=self.book_slug,
            job_id=self.job_id,
            expected_assembly_identity=self.assembly_identity,
        )

    @staticmethod
    def _loudness(value=-19.0, peak=-4.0):
        return {
            "input_i": value,
            "input_tp": peak,
            "input_lra": 2.0,
            "input_thresh": -29.0,
            "target_offset": 0.0,
        }

    @classmethod
    def _measured(cls, value=-19.0, peak=-4.0):
        return cls._loudness(value, peak), ["<ffmpeg>", "-i", "<input>"]

    @staticmethod
    def _copy_run(arguments, **_kwargs):
        source = Path(arguments[arguments.index("-i") + 1])
        destination = Path(arguments[-1])
        shutil.copyfile(source, destination)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    def _create_master(self):
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.mastering, "_measure_loudness", side_effect=[self._measured(-24), self._measured()]), \
             mock.patch.object(self.mastering, "_run", side_effect=self._copy_run):
            return self.mastering.master(self.authority, revalidate=self._resolve_assembly)

    def _master_authority(self):
        manifest = self._create_master()
        return resolve_current_master(
            workspace_root=self.root,
            masters_root=self.root / "masters",
            book_slug=self.book_slug,
            job_id=self.job_id,
            expected_master_identity=manifest["master_identity"],
        )

    def _export(self, master=None, facts=None):
        master = master or self._master_authority()
        facts = facts or {
            "duration_seconds": master["wav"]["duration_seconds"],
            "sample_rate_hz": 48_000,
            "channels": 2,
            "channel_layout": "stereo",
            "bitrate_bps": 128_000,
            "size_bytes": 4096,
            "decodable": True,
        }

        def encode(arguments, **_kwargs):
            Path(arguments[-1]).write_bytes(b"ID3" + b"x" * 4093)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"), \
             mock.patch.object(self.exporting, "_inspect_mp3", return_value=facts), \
             mock.patch("mastering_export.subprocess.run", side_effect=encode):
            return self.exporting.export(master, self.book)

    def test_exact_current_assembly_resolves_and_provider_source_is_not_input(self):
        self.assertEqual(self.authority["audio_path"], str(self.assembly_wav))
        self.assertEqual(self.authority["audio_sha256"], sha256_file(self.assembly_wav))
        self.assertEqual(self.authority["provider_requests"], 0)

    def test_stale_identity_manifest_sha_audio_sha_and_path_are_blocked(self):
        with self.assertRaises(MasteringExportError):
            resolve_current_assembly(
                workspace_root=self.root, chapters_root=self.root / "chapters",
                book_slug=self.book_slug, job_id=self.job_id,
                expected_assembly_identity="b" * 64,
            )
        for field in ("assembly_manifest_sha256", "audio_sha256", "path_identity"):
            changed = copy.deepcopy(self.authority)
            changed[field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(MasteringExportError):
                self.mastering.prepare(changed)

    def test_corrupt_assembly_wav_is_blocked(self):
        self.assembly_wav.write_bytes(b"broken")
        with self.assertRaises(MasteringExportError):
            self._resolve_assembly()

    def test_symlink_root_ancestor_and_leaf_are_rejected(self):
        real = self.root / "outside.wav"
        self._write_wav(real, seconds=0.1)
        leaf = self.assembly_dir / "leaf.wav"
        leaf.symlink_to(real)
        changed = copy.deepcopy(self.authority)
        changed["audio_path"] = str(leaf)
        changed["audio_sha256"] = sha256_file(leaf)
        changed["path_identity"] = path_identity(leaf)
        with self.assertRaises(MasteringExportError):
            self.mastering.prepare(changed)
        linked_root = self.root.parent / "linked-workspace"
        linked_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(MasteringExportError):
            MasteringService(linked_root, linked_root / "masters")
        external = self.root / "external-masters"
        external.mkdir()
        output_link = self.root / "linked-masters"
        output_link.symlink_to(external, target_is_directory=True)
        with self.assertRaises(MasteringExportError):
            MasteringService(self.root, output_link)

    def test_preset_and_profile_identity_are_deterministic_and_versioned(self):
        self.assertEqual(master_preset_hash(), master_preset_hash())
        self.assertEqual(litres_profile_hash(), litres_profile_hash())
        self.assertEqual(LITRES_PROFILE["cover_art_contract"], "canonical_attached_pic_if_configured_v1")
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution):
            first = self.mastering.prepare(self.authority)["master_identity"]
            second = self.mastering.prepare(self.authority)["master_identity"]
        self.assertEqual(first, second)
        changed = copy.deepcopy(MASTER_PRESET)
        changed["target_integrated_lufs"] = -18.0
        self.assertNotEqual(master_preset_hash(), __import__("mastering_export")._canonical_hash({"preset": changed, "boundary_policy": BOUNDARY_POLICY}))

    def test_loudnorm_json_requires_complete_finite_measurements(self):
        stderr = 'noise {"input_i":"-20.1","input_tp":"-4.2","input_lra":"2.0","input_thresh":"-30","target_offset":"0.1"}'
        self.assertEqual(_parse_loudnorm_json(stderr)["input_i"], -20.1)
        for broken in ("none", '{"input_i":"nan"}'):
            with self.subTest(broken=broken), self.assertRaises(MasteringExportError):
                _parse_loudnorm_json(broken)

    def test_boundary_policy_measures_and_only_adds_minimum_padding(self):
        before = _boundary_measurements(self.assembly_wav)
        destination = self.root / "padded.wav"
        result = self.mastering._apply_boundary_padding(self.assembly_wav, destination)
        after = _boundary_measurements(destination)
        self.assertAlmostEqual(before["leading_silence_seconds"], 0.1, places=3)
        self.assertGreaterEqual(after["leading_silence_seconds"], 0.5)
        self.assertGreaterEqual(after["trailing_silence_seconds"], 1.0)
        self.assertEqual(result["trimmed_frames"], 0)

    def test_exact_master_two_pass_manifest_format_identity_and_idempotence(self):
        first = self._create_master()
        second = self._create_master()
        self.assertEqual(first["master_identity"], second["master_identity"])
        self.assertEqual(first["output"]["sha256"], second["output"]["sha256"])
        self.assertEqual(first["output"]["wav"]["sample_rate_hz"], 48_000)
        self.assertEqual(first["output"]["wav"]["channels"], 1)
        self.assertEqual(first["output"]["wav"]["sample_width_bytes"], 2)
        self.assertEqual(first["analysis_pass"]["measurements"]["input_i"], -24)
        self.assertEqual(first["second_pass"]["measurements_used"]["input_i"], -24)
        self.assertEqual(first["provider_requests"], 0)
        self.assertNotIn("credential", json.dumps(first).lower())

    def test_existing_master_repairs_missing_current_pointer(self):
        manifest = self._create_master()
        pointer = self.root / "masters" / self.book_slug / self.job_id / "CURRENT.json"
        pointer.unlink()
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution):
            repair = self.mastering.status(self.authority)
        self.assertEqual(repair["state"], "RECOVERY_REQUIRED")
        self.assertEqual(repair["decision"], "READY_TO_REPAIR")
        self.assertIsNotNone(repair["master"])
        recovered = self._create_master()
        self.assertEqual(recovered["master_identity"], manifest["master_identity"])
        self.assertTrue(pointer.is_file())
        current = resolve_current_master(
            workspace_root=self.root,
            masters_root=self.root / "masters",
            book_slug=self.book_slug,
            job_id=self.job_id,
        )
        self.assertEqual(current["master_identity"], manifest["master_identity"])

    def test_stale_master_retry_cannot_roll_back_current_pointer(self):
        self._create_master()
        pointer = self.root / "masters" / self.book_slug / self.job_id / "CURRENT.json"
        before = pointer.read_bytes()
        changed = copy.deepcopy(self.authority)
        changed["assembly_identity"] = "b" * 64
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution), \
             self.assertRaises(MasteringExportError) as raised:
            self.mastering.master(self.authority, revalidate=lambda: changed)
        self.assertEqual(raised.exception.code, "stale_assembly")
        self.assertEqual(pointer.read_bytes(), before)

    def test_loudness_true_peak_and_clipping_fail_closed(self):
        cases = ((self._measured(-18.0), "loudness_out_of_tolerance"), (self._measured(-19, -2.0), "true_peak_exceeded"))
        for verification, code in cases:
            with self.subTest(code=code), \
                 mock.patch.object(self.mastering, "_resolution", return_value=self.resolution), \
                 mock.patch.object(self.mastering, "_measure_loudness", side_effect=[self._measured(-24), verification]), \
                 mock.patch.object(self.mastering, "_run", side_effect=self._copy_run), \
                 self.assertRaises(MasteringExportError) as raised:
                self.mastering.master(self.authority)
            self.assertEqual(raised.exception.code, code)

        def clipped_run(arguments, **_kwargs):
            destination = Path(arguments[-1])
            self._write_wav(destination, seconds=1.6, lead=0.5, tail=1.0, amplitude=32767)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.mastering, "_measure_loudness", side_effect=[self._measured(-24), self._measured()]), \
             mock.patch.object(self.mastering, "_run", side_effect=clipped_run), \
             self.assertRaises(MasteringExportError) as raised:
            self.mastering.master(self.authority)
        self.assertEqual(raised.exception.code, "clipping_detected")

    def test_ffmpeg_identity_change_and_atomic_failure_publish_nothing(self):
        changed = FFmpegResolution(True, self.ffmpeg, "ffmpeg version test-2", "environment")
        with mock.patch.object(self.mastering, "_resolution", side_effect=[self.resolution, changed]):
            with self.assertRaisesRegex(MasteringExportError, "FFmpeg identity"):
                self.mastering.master(self.authority)
        self.assertFalse((self.root / "masters" / self.book_slug / self.job_id / "CURRENT.json").exists())

    def test_changed_source_during_mastering_blocks_publication(self):
        calls = 0
        def mutate_then_copy(arguments, **kwargs):
            nonlocal calls
            calls += 1
            result = self._copy_run(arguments, **kwargs)
            if calls == 1:
                self.assembly_wav.touch()
            return result
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.mastering, "_measure_loudness", side_effect=[self._measured(-24), self._measured()]), \
             mock.patch.object(self.mastering, "_run", side_effect=mutate_then_copy), \
             self.assertRaises(MasteringExportError):
            self.mastering.master(self.authority)
        self.assertFalse((self.root / "masters" / self.book_slug / self.job_id / "CURRENT.json").exists())

    def test_master_current_resolver_rejects_stale_and_changed_artifacts(self):
        master = self._master_authority()
        self.assertEqual(master["assembly_identity"], self.assembly_identity)
        with self.assertRaises(MasteringExportError):
            resolve_current_master(
                workspace_root=self.root, masters_root=self.root / "masters",
                book_slug=self.book_slug, job_id=self.job_id,
                expected_master_identity="0" * 64,
            )

    def test_master_nonempty_publish_race_returns_valid_winner(self):
        winner = {"status": "READY", "master_identity": "winner"}
        with mock.patch.object(self.mastering, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.mastering, "_measure_loudness", side_effect=[self._measured(-24), self._measured()]), \
             mock.patch.object(self.mastering, "_run", side_effect=self._copy_run), \
             mock.patch.object(self.mastering, "_read_ready", side_effect=[None, winner]), \
             mock.patch("pathlib.Path.rename", side_effect=OSError(errno.ENOTEMPTY, "not empty")):
            result = self.mastering.master(self.authority)
        self.assertIs(result, winner)

    def test_canonical_book_order_ignores_preview_and_preserves_insertion(self):
        authority = canonical_book_authority(self.book)
        self.assertEqual([item["job_id"] for item in authority["chapters"]], ["chapter-ch001", "chapter-ch002"])
        self.assertEqual(authority["chapters"][1]["title"], "Глава 2")

    def test_unicode_output_filename_is_bounded_by_utf8_bytes(self):
        filename = _safe_output_name(1, "界" * 120)
        self.assertLessEqual(len(filename.encode("utf-8")), 255)
        self.assertTrue(filename.startswith("001 — "))
        self.assertTrue(filename.endswith(".mp3"))
        self.assertEqual(filename, _safe_output_name(1, unicodedata.normalize("NFD", "界" * 120)))
        output = self.root / filename
        output.write_bytes(b"mp3")
        self.assertEqual(output.read_bytes(), b"mp3")

    def test_book_state_missing_duplicate_unknown_cover_and_rights_block(self):
        book = canonical_book_authority(self.book)
        one = {"job_id": "chapter-ch001", "candidate_identity": "1"}
        state = build_book_export_state(book, [one])
        self.assertEqual(state["progress"], "1/2")
        self.assertIn("missing_chapters", state["blockers"])
        self.assertIn("missing_cover", state["blockers"])
        duplicate = build_book_export_state(book, [one, one])
        self.assertIn("duplicate_chapters", duplicate["blockers"])
        extra = build_book_export_state(book, [one, {"job_id": "unknown"}])
        self.assertIn("unknown_extra_chapters", extra["blockers"])
        with_rights = copy.deepcopy(book)
        with_rights["rights_provenance"] = {"third_party_assets": ["music"], "verified": False}
        self.assertIn("unproven_third_party_assets", build_book_export_state(with_rights, [one])["blockers"])

    def test_too_many_book_files_fail_closed(self):
        book = copy.deepcopy(self.book)
        book["jobs"] = {
            f"chapter-{index}": {"kind": "chapter", "chapter_id": f"c{index}", "label": str(index)}
            for index in range(501)
        }
        with self.assertRaises(MasteringExportError):
            canonical_book_authority(book)

    def test_exact_master_exports_stereo_128k_unicode_mp3_and_is_idempotent(self):
        first = self._export()
        master = resolve_current_master(
            workspace_root=self.root, masters_root=self.root / "masters",
            book_slug=self.book_slug, job_id=self.job_id,
        )
        second = self._export(master)
        chapter = first["chapter_export"]
        self.assertEqual(first["decision"], "ALREADY_EXPORTED")
        self.assertEqual(second["candidate_identity"], first["candidate_identity"])
        self.assertEqual(chapter["facts"]["channels"], 2)
        self.assertEqual(chapter["facts"]["bitrate_bps"], 128_000)
        self.assertIn("Введение", chapter["filename"])
        self.assertEqual(first["book_export"]["progress"], "1/2")
        self.assertFalse(first["book_export"]["ready"])
        self.assertEqual(first["export_manifest"]["provider_requests"], 0)

    def test_existing_export_repairs_missing_chapter_and_book_pointers(self):
        master = self._master_authority()
        first = self._export(master)
        profile_root = self.root / "exports" / self.book_slug / "litres_author_v1"
        chapter_pointer = profile_root / f"CURRENT-{self.job_id}.json"
        book_pointer = profile_root / "CURRENT.json"
        chapter_pointer.unlink()
        book_pointer.unlink()
        recovered = self._export(master)
        self.assertEqual(recovered["candidate_identity"], first["candidate_identity"])
        self.assertTrue(chapter_pointer.is_file())
        self.assertTrue(book_pointer.is_file())

        book_pointer.unlink()
        recovered_again = self._export(master)
        self.assertEqual(recovered_again["candidate_identity"], first["candidate_identity"])
        self.assertTrue(book_pointer.is_file())

        book_pointer.write_text(json.dumps({
            "schema_version": 1,
            "export_identity": "0" * 64,
            "manifest_path": "/stale/package/MANIFEST.json",
        }), encoding="utf-8")
        recovered_stale = self._export(master)
        repaired = json.loads(book_pointer.read_text(encoding="utf-8"))
        self.assertEqual(recovered_stale["candidate_identity"], first["candidate_identity"])
        self.assertEqual(repaired["export_identity"], first["export_manifest"]["export_identity"])
        self.assertEqual(repaired["manifest_path"], first["manifest_path"])

    def test_export_recovery_revalidates_and_never_rewinds_other_chapter_pointers(self):
        master = self._master_authority()
        self._export(master)
        profile_root = self.root / "exports" / self.book_slug / "litres_author_v1"
        chapter_pointer = profile_root / f"CURRENT-{self.job_id}.json"
        book_pointer = profile_root / "CURRENT.json"
        before_chapter = chapter_pointer.read_bytes()
        before_book = book_pointer.read_bytes()
        changed = copy.deepcopy(self.book)
        changed["author"] = "Новый автор"
        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"), \
             self.assertRaises(MasteringExportError) as raised:
            self.exporting.export(
                master,
                self.book,
                revalidate_master=lambda: master,
                revalidate_book=lambda: changed,
            )
        self.assertEqual(raised.exception.code, "book_authority_changed")
        self.assertEqual(chapter_pointer.read_bytes(), before_chapter)
        self.assertEqual(book_pointer.read_bytes(), before_book)

        book_pointer.unlink()
        other_pointer = profile_root / "CURRENT-chapter-ch002.json"
        other_pointer.write_text(json.dumps({"manifest_path": "/newer/package/MANIFEST.json"}), encoding="utf-8")
        other_before = other_pointer.read_bytes()
        self._export(master)
        self.assertEqual(other_pointer.read_bytes(), other_before)
        self.assertFalse(book_pointer.exists())

    def test_export_recovery_revalidates_manifest_masters_before_book_pointer(self):
        master = self._master_authority()
        first = self._export(master)
        profile_root = self.root / "exports" / self.book_slug / "litres_author_v1"
        book_pointer = profile_root / "CURRENT.json"
        book_pointer.unlink()
        with mock.patch.object(
            self.exporting,
            "_revalidate_candidate_masters",
            side_effect=MasteringExportError("stale_master", "changed"),
        ) as revalidate, self.assertRaises(MasteringExportError) as raised:
            self._export(master)
        self.assertEqual(raised.exception.code, "stale_master")
        self.assertFalse(book_pointer.exists())
        self.assertEqual(
            revalidate.call_args.args[1],
            first["export_manifest"]["chapters"],
        )

    def test_historical_master_change_before_publication_fails_closed(self):
        master = self._master_authority()
        first = self._export(master)
        changed_book = copy.deepcopy(self.book)
        changed_book["author"] = "Автор нового package"
        historical = copy.deepcopy(first["chapter_export"])
        historical_master = copy.deepcopy(master)
        historical_master.update({
            "job_id": "chapter-ch002",
            "master_identity": "b" * 64,
            "audio_sha256": "c" * 64,
            "master_manifest_sha256": "d" * 64,
        })
        authority = canonical_book_authority(changed_book)
        chapter = authority["chapters"][1]
        historical.update({
            "job_id": "chapter-ch002",
            "chapter_id": "ch002",
            "chapter_title": "Глава 2",
            "position": 2,
            "master_identity": historical_master["master_identity"],
            "master_sha256": historical_master["audio_sha256"],
            "master_manifest_sha256": historical_master["master_manifest_sha256"],
        })
        historical["candidate_identity"] = self.exporting._candidate_identity_from_tool(
            historical_master, authority, chapter, historical["tool"], historical["encoder"]
        )
        changed_historical_master = {**historical_master, "audio_sha256": "e" * 64}

        def current_master(**kwargs):
            return master if kwargs["job_id"] == self.job_id else changed_historical_master

        def encode(arguments, **_kwargs):
            Path(arguments[-1]).write_bytes(b"ID3" + b"x" * 4093)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

        profile_root = self.root / "exports" / self.book_slug / "litres_author_v1"
        before_directories = {path.name for path in profile_root.iterdir() if path.is_dir()}
        with mock.patch.object(self.exporting, "_load_current_candidates", return_value=[historical]), \
             mock.patch("mastering_export.resolve_current_master", side_effect=current_master), \
             mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"), \
             mock.patch.object(self.exporting, "_inspect_mp3", return_value={
                 "duration_seconds": master["wav"]["duration_seconds"],
                 "sample_rate_hz": 48_000, "channels": 2, "channel_layout": "stereo",
                 "bitrate_bps": 128_000, "size_bytes": 4096, "decodable": True,
             }), \
             mock.patch("mastering_export.subprocess.run", side_effect=encode), \
             self.assertRaises(MasteringExportError) as raised:
            self.exporting.export(master, changed_book)
        self.assertEqual(raised.exception.code, "stale_master")
        self.assertEqual(
            {path.name for path in profile_root.iterdir() if path.is_dir()},
            before_directories,
        )

    def test_historical_mp3_change_during_copy_fails_closed(self):
        master = self._master_authority()
        first = self._export(master)
        changed_book = copy.deepcopy(self.book)
        changed_book["author"] = "Автор нового package"
        historical = copy.deepcopy(first["chapter_export"])
        historical.update({
            "job_id": "chapter-ch002",
            "chapter_id": "ch002",
            "chapter_title": "Глава 2",
            "position": 2,
        })
        historical_path = Path(historical["path"])
        real_copy = shutil.copyfile

        def copy_with_change(source, destination, **kwargs):
            result = real_copy(source, destination, **kwargs)
            if Path(source) == historical_path:
                Path(destination).write_bytes(b"changed-after-validation")
            return result

        def encode(arguments, **_kwargs):
            Path(arguments[-1]).write_bytes(b"ID3" + b"x" * 4093)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

        profile_root = self.root / "exports" / self.book_slug / "litres_author_v1"
        before_directories = {path.name for path in profile_root.iterdir() if path.is_dir()}
        with mock.patch.object(self.exporting, "_load_current_candidates", return_value=[historical]), \
             mock.patch.object(self.exporting, "_revalidate_candidate_masters"), \
             mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"), \
             mock.patch.object(self.exporting, "_inspect_mp3", return_value={
                 "duration_seconds": master["wav"]["duration_seconds"],
                 "sample_rate_hz": 48_000, "channels": 2, "channel_layout": "stereo",
                 "bitrate_bps": 128_000, "size_bytes": 4096, "decodable": True,
             }), \
             mock.patch("mastering_export.subprocess.run", side_effect=encode), \
             mock.patch("mastering_export.shutil.copyfile", side_effect=copy_with_change), \
             self.assertRaises(MasteringExportError) as raised:
            self.exporting.export(master, changed_book)
        self.assertEqual(raised.exception.code, "historical_export_changed")
        self.assertEqual(
            {path.name for path in profile_root.iterdir() if path.is_dir()},
            before_directories,
        )

    def test_mastering_and_export_use_bounded_book_wide_locks(self):
        calls = []
        active = 0
        maximum_active = 0

        @contextmanager
        def bounded_lock(_workspace_root, **kwargs):
            nonlocal active, maximum_active
            calls.append(kwargs)
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                yield
            finally:
                active -= 1

        with mock.patch("mastering_export.production_authority_lock", side_effect=bounded_lock), \
             mock.patch.object(self.mastering, "_master_locked", return_value={"status": "READY"}):
            self.mastering.master({**self.authority, "job_id": "book"})
        self.assertIn({
            "provider": "master-book", "book_slug": self.book_slug,
            "job_id": "book", "profile_id": "spoken_word_master_v1", "exclusive": True,
        }, calls)
        self.assertIn({
            "provider": "master", "book_slug": self.book_slug,
            "job_id": "book", "profile_id": "spoken_word_master_v1", "exclusive": True,
        }, calls)
        self.assertEqual(len({
            (call["provider"], call["job_id"], call["profile_id"])
            for call in calls
        }), len(calls))
        self.assertLessEqual(maximum_active, 3)

        calls.clear()
        active = 0
        maximum_active = 0
        large_book = copy.deepcopy(self.book)
        large_book["jobs"] = {
            f"chapter-{index:03d}": {
                "kind": "chapter", "chapter_id": f"ch{index:03d}",
                "label": f"Глава {index}", "preparation_identity": "p1",
            }
            for index in range(1, 501)
        }
        with mock.patch("mastering_export.production_authority_lock", side_effect=bounded_lock), \
             mock.patch.object(self.exporting, "_export_locked", return_value={"status": "READY"}):
            self.exporting.export(
                {"book_slug": self.book_slug, "job_id": "chapter-001"},
                large_book,
            )
        self.assertEqual(maximum_active, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], {
            "provider": "book-authority", "book_slug": self.book_slug,
            "job_id": "profile", "profile_id": "canonical-v1", "exclusive": False,
        })
        self.assertEqual(calls[1], {
            "provider": "master-book", "book_slug": self.book_slug,
            "job_id": "book", "profile_id": "spoken_word_master_v1", "exclusive": False,
        })
        self.assertEqual(calls[2], {
            "provider": "export", "book_slug": self.book_slug,
            "job_id": "book", "profile_id": "litres_author_v1", "exclusive": True,
        })

    def test_candidate_preserves_its_own_tool_identity_across_package_changes(self):
        master = self._master_authority()
        exported = self._export(master)
        manifest_path = Path(exported["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidate = manifest["chapters"][0]
        self.assertEqual(candidate["tool"]["version"], self.resolution.version)
        manifest["ffmpeg"] = {**manifest["ffmpeg"], "version": "ffmpeg version later"}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        current = self.exporting._load_current_candidates(canonical_book_authority(self.book))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["tool"]["version"], self.resolution.version)

    def test_export_stale_master_sha_path_and_manifest_are_blocked(self):
        master = self._master_authority()
        for field in ("audio_sha256", "path_identity", "master_manifest_sha256"):
            changed = copy.deepcopy(master)
            changed[field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(MasteringExportError):
                self.exporting.prepare(changed, self.book)

    def test_mp3_stereo_bitrate_duration_size_and_three_hour_limits(self):
        master = self._master_authority()
        base = {
            "duration_seconds": master["wav"]["duration_seconds"], "sample_rate_hz": 48_000,
            "channels": 2, "channel_layout": "stereo", "bitrate_bps": 128_000,
            "size_bytes": 4096, "decodable": True,
        }
        cases = [
            ({**base, "channels": 1}, "invalid_mp3_format"),
            ({**base, "bitrate_bps": 96_000}, "invalid_mp3_bitrate"),
            ({**base, "duration_seconds": base["duration_seconds"] + 1}, "mp3_duration_mismatch"),
            ({**base, "duration_seconds": LITRES_PROFILE["max_duration_seconds"] + 1}, "mp3_too_long"),
            ({**base, "size_bytes": LITRES_PROFILE["max_file_bytes"] + 1}, "mp3_too_large"),
        ]
        for facts, code in cases:
            isolated = LitresExportService(self.root, self.root / f"exports-{code}")
            self.exporting = isolated
            with self.subTest(code=code), self.assertRaises(MasteringExportError) as raised:
                self._export(master, facts)
            self.assertEqual(raised.exception.code, code)

    def test_metadata_and_cover_change_candidate_identity(self):
        master = self._master_authority()
        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"):
            first = self.exporting.prepare(master, self.book)["candidate_identity"]
            changed = copy.deepcopy(self.book)
            changed["author"] = "Другой автор"
            second = self.exporting.prepare(master, changed)["candidate_identity"]
            cover = self.root / "assets" / "cover.jpg"
            cover.parent.mkdir()
            cover.write_bytes(b"cover")
            changed["cover"] = {"path": str(cover), "sha256": sha256_file(cover)}
            third = self.exporting.prepare(master, changed)["candidate_identity"]
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)

    def test_historical_candidate_is_excluded_after_current_metadata_changes(self):
        master = self._master_authority()
        self._export(master)
        changed = copy.deepcopy(self.book)
        changed["author"] = "Другой автор"
        authority = canonical_book_authority(changed)
        self.assertEqual(self.exporting._load_current_candidates(authority), [])

    def test_cover_path_escape_and_sha_mismatch_fail_closed(self):
        master = self._master_authority()
        outside = self.root.parent / "outside-cover.jpg"
        outside.write_bytes(b"cover")
        for cover in (
            {"path": str(outside), "sha256": sha256_file(outside)},
            {"path": str(self.assembly_manifest), "sha256": "0" * 64},
        ):
            book = copy.deepcopy(self.book)
            book["cover"] = cover
            with self.subTest(cover=cover), self.assertRaises(MasteringExportError):
                self.exporting.prepare(master, book)

    def test_canonical_cover_is_embedded_copied_and_validated(self):
        master = self._master_authority()
        cover = self.root / "assets" / "cover.jpg"
        cover.parent.mkdir()
        cover.write_bytes(b"canonical-cover")
        self.book["cover"] = {"path": str(cover), "sha256": sha256_file(cover)}
        facts = {
            "duration_seconds": master["wav"]["duration_seconds"],
            "sample_rate_hz": 48_000,
            "channels": 2,
            "channel_layout": "stereo",
            "bitrate_bps": 128_000,
            "size_bytes": 4096,
            "decodable": True,
            "cover_art_embedded": False,
        }
        with self.assertRaises(MasteringExportError) as raised:
            self._export(master, facts)
        self.assertEqual(raised.exception.code, "missing_cover_art")

        exported = self._export(master, {**facts, "cover_art_embedded": True})
        candidate = exported["chapter_export"]
        self.assertIn("<cover>", candidate["arguments"])
        self.assertIn("attached_pic", candidate["arguments"])
        package_cover = Path(exported["export_manifest"]["cover"]["package_path"])
        self.assertTrue(package_cover.is_file())
        self.assertEqual(sha256_file(package_cover), sha256_file(cover))

        manifest_path = Path(exported["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["chapters"][0]["facts"]["cover_art_embedded"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"), \
             mock.patch.object(self.exporting, "_inspect_mp3", return_value={"cover_art_embedded": True}):
            self.assertEqual(self.exporting._load_current_candidates(canonical_book_authority(self.book)), [])
            prepared = self.exporting.prepare(master, self.book)
        self.assertEqual(prepared["decision"], "READY_TO_EXPORT")
        self.assertIsNone(prepared["chapter_export"])
        manifest["chapters"][0]["facts"]["cover_art_embedded"] = True
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        package_cover.write_bytes(b"changed")
        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"):
            changed = self.exporting.status(master, self.book)
        self.assertEqual(changed["state"], "STALE")
        self.assertEqual(changed["decision"], "READY_TO_EXPORT")
        self.assertIsNone(changed["chapter_export"])

    def test_missing_encoder_blocks_without_installing(self):
        master = self._master_authority()
        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value=None):
            prepared = self.exporting.prepare(master, self.book)
        self.assertEqual(prepared["decision"], "BLOCKED")
        self.assertEqual(prepared["blockers"], ["missing_mp3_encoder"])

    def test_export_atomic_encode_failure_does_not_publish(self):
        master = self._master_authority()
        failure = subprocess.CompletedProcess([], 1, b"", b"failed")
        with mock.patch.object(self.exporting, "_resolution", return_value=self.resolution), \
             mock.patch.object(self.exporting, "_encoder", return_value="libmp3lame"), \
             mock.patch("mastering_export.subprocess.run", return_value=failure), \
             self.assertRaises(MasteringExportError):
            self.exporting.export(master, self.book)
        self.assertFalse((self.root / "exports" / self.book_slug / "litres_author_v1" / "CURRENT.json").exists())

    def test_stale_historical_candidate_is_not_counted_and_symlink_pointer_fails_closed(self):
        master = self._master_authority()
        self._export(master)
        profile_root = self.root / "exports" / self.book_slug / "litres_author_v1"
        master_pointer = self.root / "masters" / self.book_slug / self.job_id / "CURRENT.json"
        master_pointer_original = master_pointer.read_bytes()
        pointer_data = json.loads(master_pointer.read_text(encoding="utf-8"))
        pointer_data["master_identity"] = "0" * 64
        master_pointer.write_text(json.dumps(pointer_data), encoding="utf-8")
        self.assertEqual(self.exporting._load_current_candidates(canonical_book_authority(self.book)), [])
        master_pointer.write_bytes(master_pointer_original)

        chapter_pointer = profile_root / f"CURRENT-{self.job_id}.json"
        saved = chapter_pointer.with_suffix(".saved")
        chapter_pointer.rename(saved)
        chapter_pointer.symlink_to(saved)
        with self.assertRaises(MasteringExportError) as raised:
            self.exporting.status(master, self.book)
        self.assertEqual(raised.exception.code, "symlink_pointer")

    def test_provider_and_billing_contracts_are_always_offline(self):
        master = self._create_master()
        self.assertEqual(master["provider_requests"], 0)
        self.assertFalse(master["billing_changed"])
        exported = self._export(resolve_current_master(
            workspace_root=self.root, masters_root=self.root / "masters",
            book_slug=self.book_slug, job_id=self.job_id,
        ))
        self.assertEqual(exported["export_manifest"]["provider_requests"], 0)
        self.assertFalse(exported["export_manifest"]["billing_changed"])


if __name__ == "__main__":
    unittest.main()
