"""Local-only Qwen chapter execution over the persistent manifest contract."""

from __future__ import annotations

import hashlib
import os
import wave
from pathlib import Path
from typing import Any, Callable, Mapping

from backends.common import inspect_pcm_wav
from book_library import BookLibrary
from qwen_chapter_manifest import QwenChapterManifestError, QwenChapterManifestService


class QwenChapterExecutionError(RuntimeError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_join_wavs(inputs: list[dict[str, Any]], destination: Path) -> Path:
    if not inputs:
        raise QwenChapterExecutionError("No Qwen chapter WAV inputs are available for assembly.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    expected: tuple[int, int, int] | None = None
    try:
        with wave.open(str(temporary), "wb") as output:
            for item in inputs:
                source_path = Path(item["wav_path"])
                metadata = inspect_pcm_wav(source_path)
                current = (metadata.channels, metadata.sample_width_bytes, metadata.sample_rate_hz)
                if expected is None:
                    expected = current
                    output.setnchannels(metadata.channels)
                    output.setsampwidth(metadata.sample_width_bytes)
                    output.setframerate(metadata.sample_rate_hz)
                elif current != expected:
                    raise QwenChapterExecutionError("Qwen chapter segment WAV formats do not match.")
                with wave.open(str(source_path), "rb") as source:
                    while True:
                        frames = source.readframes(8192)
                        if not frames:
                            break
                        output.writeframesraw(frames)
                pause_ms = int(item.get("pause_after_ms") or 0)
                if pause_ms > 0:
                    silence_frames = round(metadata.sample_rate_hz * pause_ms / 1000)
                    frame = b"\x00" * metadata.block_align
                    chunk = frame * min(silence_frames, 8192)
                    remaining = silence_frames
                    while remaining > 0:
                        count = min(remaining, 8192)
                        output.writeframesraw(chunk[: count * metadata.block_align])
                        remaining -= count
        inspect_pcm_wav(temporary)
        os.replace(temporary, destination)
        inspect_pcm_wav(destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


class QwenChapterExecutionService:
    def __init__(
        self,
        *,
        library: BookLibrary,
        manifest: QwenChapterManifestService,
        synthesize_segment: Callable[..., None],
    ) -> None:
        self.library = library
        self.manifest = manifest
        self.synthesize_segment = synthesize_segment

    def _segment_texts(self, book_id: str, job_id: str) -> dict[str, str]:
        book = self.library.load_book_for_execution(book_id)
        job = (book.get("jobs") or {}).get(job_id)
        if not isinstance(job, dict) or job.get("kind") != "chapter":
            raise QwenChapterExecutionError("Prepared Qwen chapter job is missing.")
        result: dict[str, str] = {}
        for entry in job.get("segments") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
                raise QwenChapterExecutionError("Prepared Qwen chapter contains invalid segment text.")
            result[str(entry["id"])] = entry["text"]
        return result

    def run(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
        chapter_output: Path,
    ) -> dict[str, Any]:
        self.manifest.prepare(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        status = self.manifest.recover_after_restart(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        if status["counts"]["FAILED"]:
            raise QwenChapterExecutionError("FAILED Qwen segments require explicit retry before resume.")
        texts = self._segment_texts(book_id, job_id)
        generated = 0
        while True:
            claim = self.manifest.claim_next(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            if claim is None:
                break
            segment_id = str(claim["id"])
            text = texts.get(segment_id)
            if text is None or _sha256_text(text) != claim["text_sha256"]:
                self.manifest.fail(
                    book_id=book_id,
                    job_id=job_id,
                    profile_id=profile_id,
                    synthesis_identity=synthesis_identity,
                    segment_id=segment_id,
                    error="prepared_text_hash_mismatch",
                )
                raise QwenChapterExecutionError("Prepared Qwen segment text changed after claim.")
            output_path = Path(claim["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.synthesize_segment(
                    text=text,
                    output_path=output_path,
                    seed=int(claim["seed"]),
                    segment_id=segment_id,
                )
                inspect_pcm_wav(output_path)
                self.manifest.complete(
                    book_id=book_id,
                    job_id=job_id,
                    profile_id=profile_id,
                    synthesis_identity=synthesis_identity,
                    segment_id=segment_id,
                )
                generated += 1
            except Exception as error:
                try:
                    self.manifest.fail(
                        book_id=book_id,
                        job_id=job_id,
                        profile_id=profile_id,
                        synthesis_identity=synthesis_identity,
                        segment_id=segment_id,
                        error=f"{type(error).__name__}: {error}",
                    )
                except QwenChapterManifestError:
                    pass
                raise
        final_status = self.manifest.status(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        if not final_status["complete"]:
            raise QwenChapterExecutionError("Qwen chapter is not complete after local execution.")
        inputs = self.manifest.assembly_inputs(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        final_path = _atomic_join_wavs(inputs, Path(chapter_output))
        return {
            **final_status,
            "generated_segments": generated,
            "output_path": str(final_path),
            "remote_request_sent": False,
        }
