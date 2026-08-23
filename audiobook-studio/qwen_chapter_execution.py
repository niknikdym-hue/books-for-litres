"""Local-only Qwen chapter segment production over the persistent manifest contract.

This service stops at integrity-checked WAV segments. Chapter assembly is intentionally a
later gate after automatic QA and manual review acceptance.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from backends.common import inspect_pcm_wav
from book_library import BookLibrary
from qwen_chapter_manifest import QwenChapterManifestError, QwenChapterManifestService


# Only one local Qwen chapter execution may own recovery/claim/synthesis state at a
# time in this process. The file lock below extends the same exclusion across app
# processes and is released automatically if an owning process terminates.
_QWEN_PROCESS_EXECUTION_LOCK = threading.Lock()


class QwenChapterExecutionError(RuntimeError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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

    @contextmanager
    def _execution_locked(self, *, book_id: str, job_id: str, profile_id: str) -> Iterator[None]:
        # Use a lock distinct from the short-lived manifest mutation lock. The
        # execution lock covers prepare -> restart recovery -> all claims and
        # synthesis -> final status, preventing a second live runner from
        # mistaking the first runner's RUNNING segment for interrupted work.
        job_dir = self.manifest._job_dir(book_id, job_id, profile_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        lock_path = job_dir / ".execution.lock"
        with _QWEN_PROCESS_EXECUTION_LOCK:
            with lock_path.open("a+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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
    ) -> dict[str, Any]:
        with self._execution_locked(book_id=book_id, job_id=job_id, profile_id=profile_id):
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
                temporary_path = output_path.with_suffix(output_path.suffix + ".part")
                if temporary_path.exists():
                    temporary_path.unlink()
                try:
                    self.synthesize_segment(
                        text=text,
                        output_path=temporary_path,
                        seed=int(claim["seed"]),
                        segment_id=segment_id,
                    )
                    inspect_pcm_wav(temporary_path)
                    os.replace(temporary_path, output_path)
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
                finally:
                    if temporary_path.exists():
                        temporary_path.unlink()
            final_status = self.manifest.status(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            if not final_status["complete"]:
                raise QwenChapterExecutionError("Qwen segment production is not complete after local execution.")
            return {
                **final_status,
                "generated_segments": generated,
                "segment_job_dir": final_status["job_dir"],
                "chapter_assembly_performed": False,
                "next_gate": "AUTOMATIC_QA",
                "remote_request_sent": False,
            }
