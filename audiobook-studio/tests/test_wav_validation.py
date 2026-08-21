from __future__ import annotations

import io
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.common import (
    RIFF_SIZE_SENTINEL,
    WavTruncatedError,
    WavValidationError,
    inspect_pcm_wav,
    wav_size_markers,
)


def riff_chunk(chunk_id: bytes, payload: bytes, *, declared_size: int | None = None) -> bytes:
    size = len(payload) if declared_size is None else declared_size
    padding = b"\0" if size != RIFF_SIZE_SENTINEL and len(payload) & 1 else b""
    return chunk_id + struct.pack("<I", size) + payload + padding


def pcm_wav_bytes(
    *,
    payload: bytes = b"\0\0" * 16,
    riff_sentinel: bool = False,
    data_sentinel: bool = False,
    trailing_chunks: bytes = b"",
    include_fmt: bool = True,
    include_data: bool = True,
    audio_format: int = 1,
    block_align: int = 2,
) -> bytes:
    chunks = b""
    if include_fmt:
        fmt = struct.pack("<HHIIHH", audio_format, 1, 24_000, 24_000 * block_align, block_align, 16)
        chunks += riff_chunk(b"fmt ", fmt)
    if include_data:
        chunks += riff_chunk(
            b"data",
            payload,
            declared_size=RIFF_SIZE_SENTINEL if data_sentinel else None,
        )
    chunks += trailing_chunks
    riff_size = RIFF_SIZE_SENTINEL if riff_sentinel else 4 + len(chunks)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + chunks


class ProviderNeutralWavValidationTests(unittest.TestCase):
    def inspect(self, data: bytes):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.wav"
            path.write_bytes(data)
            return inspect_pcm_wav(path)

    def test_normal_finalized_pcm_wav_passes(self):
        metadata = self.inspect(pcm_wav_bytes())
        self.assertEqual(metadata.frame_count, 16)
        self.assertEqual(metadata.data_bytes, 32)
        self.assertFalse(metadata.riff_size_sentinel)
        self.assertFalse(metadata.data_size_sentinel)

    def test_true_truncated_finalized_riff_fails(self):
        data = bytearray(pcm_wav_bytes())
        data[4:8] = struct.pack("<I", int.from_bytes(data[4:8], "little") + 8)
        with self.assertRaises(WavTruncatedError):
            self.inspect(bytes(data))

    def test_streaming_riff_and_data_sentinels_use_payload_to_eof(self):
        metadata = self.inspect(pcm_wav_bytes(riff_sentinel=True, data_sentinel=True))
        self.assertEqual(metadata.frame_count, 16)
        self.assertTrue(metadata.riff_size_sentinel)
        self.assertTrue(metadata.data_size_sentinel)
        self.assertEqual(metadata.riff_declared_size, RIFF_SIZE_SENTINEL)
        self.assertEqual(metadata.data_declared_size, RIFF_SIZE_SENTINEL)

    def test_riff_sentinel_with_finalized_data_and_trailing_chunk_passes(self):
        trailing = riff_chunk(b"JUNK", b"abc")
        metadata = self.inspect(pcm_wav_bytes(riff_sentinel=True, trailing_chunks=trailing))
        self.assertEqual(metadata.frame_count, 16)
        self.assertTrue(metadata.riff_size_sentinel)
        self.assertFalse(metadata.data_size_sentinel)

    def test_finalized_riff_with_data_sentinel_passes(self):
        metadata = self.inspect(pcm_wav_bytes(data_sentinel=True))
        self.assertEqual(metadata.frame_count, 16)
        self.assertFalse(metadata.riff_size_sentinel)
        self.assertTrue(metadata.data_size_sentinel)

    def test_empty_sentinel_payload_fails(self):
        with self.assertRaises(WavValidationError):
            self.inspect(pcm_wav_bytes(payload=b"", riff_sentinel=True, data_sentinel=True))

    def test_sentinel_payload_with_incomplete_pcm_frame_is_truncated(self):
        with self.assertRaises(WavTruncatedError):
            self.inspect(pcm_wav_bytes(payload=b"\0", riff_sentinel=True, data_sentinel=True))

    def test_malformed_fmt_and_data_contracts_fail(self):
        fixtures = {
            "missing_fmt": pcm_wav_bytes(include_fmt=False),
            "missing_data": pcm_wav_bytes(include_data=False),
            "compressed": pcm_wav_bytes(audio_format=3),
            "bad_alignment": pcm_wav_bytes(block_align=4),
        }
        for name, data in fixtures.items():
            with self.subTest(name=name), self.assertRaises(WavValidationError):
                self.inspect(data)

    def test_finalized_data_chunk_larger_than_container_is_truncated(self):
        data = bytearray(pcm_wav_bytes())
        data_offset = data.index(b"data")
        data[data_offset + 4 : data_offset + 8] = struct.pack("<I", 64)
        with self.assertRaises(WavTruncatedError):
            self.inspect(bytes(data))

    def test_finalized_riff_rejects_bytes_outside_declared_container(self):
        with self.assertRaises(WavValidationError):
            self.inspect(pcm_wav_bytes() + b"extra")

    def test_safe_marker_reader_reports_only_size_contract(self):
        data = pcm_wav_bytes(riff_sentinel=True, data_sentinel=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.wav"
            path.write_bytes(data)
            markers = wav_size_markers(path)
        self.assertEqual(markers, {
            "riff_declared_size": RIFF_SIZE_SENTINEL,
            "data_declared_size": RIFF_SIZE_SENTINEL,
            "riff_size_sentinel": True,
            "data_size_sentinel": True,
        })

    def test_python_wave_cannot_authoritatively_validate_data_sentinel(self):
        data = pcm_wav_bytes(riff_sentinel=True, data_sentinel=True)
        with wave.open(io.BytesIO(data), "rb") as audio:
            declared_frames = audio.getnframes()
            actual_bytes = len(audio.readframes(declared_frames))
            block_align = audio.getnchannels() * audio.getsampwidth()
        self.assertEqual(declared_frames, RIFF_SIZE_SENTINEL // block_align)
        self.assertEqual(actual_bytes, 32)
        self.assertNotEqual(declared_frames * block_align, actual_bytes)


if __name__ == "__main__":
    unittest.main()
