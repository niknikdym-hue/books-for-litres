"""Persistent, resumable Qwen chapter manifest for production jobs.

This layer owns local execution state only. It never loads MLX, never synthesizes audio,
and never contacts a provider. A later runner claims one segment at a time and completes
it only after the provider-neutral PCM WAV integrity check succeeds.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from backends.common import atomic_write_json, inspect_pcm_wav
from book_library import BookLibrary
from chapter_production import ChapterProductionService


SCHEMA_VERSION = 1
STATES = {"PENDING", "RUNNING", "DONE", "FAILED"}


class QwenChapterManifestError(RuntimeError):
    pass


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid_wav(path: Path) -> bool:
    try:
        inspect_pcm_wav(path)
        return True
    except Exception:
        return False


class QwenChapterManifestService:
    def __init__(self, *, library: BookLibrary, output_root: Path) -> None:
        self.library = library
        self.output_root = Path(output_root)
        self.chapter = ChapterProductionService(library)

    def _job_dir(self, book_id: str, job_id: str, profile_id: str) -> Path:
        book = self.library.load_book_for_execution(book_id)
        slug = str(book.get("slug") or Path(book_id).stem)
        return self.output_root / slug / job_id / "qwen" / profile_id

    @contextmanager
    def _locked(self, job_dir: Path) -> Iterator[None]:
        job_dir.mkdir(parents=True, exist_ok=True)
        lock_path = job_dir / ".manifest.lock"
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _expected(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        plan = self.chapter.plan(
            book_id=book_id,
            job_id=job_id,
            engine="qwen",
            profile_id=profile_id,
        )
        base_seed = int(synthesis_identity.get("base_seed", 20260816))
        segments: list[dict[str, Any]] = []
        for position, item in enumerate(plan["segments"]):
            critical = {
                "chapter_production_identity": plan["chapter_production_identity"],
                "profile_id": profile_id,
                "synthesis_identity": dict(synthesis_identity),
                "segment": item,
                "seed": base_seed + position,
            }
            fingerprint = _canonical_hash(critical)
            segments.append({
                "id": item["id"],
                "fingerprint": fingerprint,
                "text_sha256": item["text_sha256"],
                "pause_after_ms": item["pause_after_ms"],
                "seed": base_seed + position,
                "wav": f"segments/{item['id']}__{fingerprint[:12]}.wav",
            })
        production_identity = _canonical_hash({
            "chapter_production_identity": plan["chapter_production_identity"],
            "profile_id": profile_id,
            "synthesis_identity": dict(synthesis_identity),
            "segments": segments,
        })
        return plan, segments, production_identity

    def _archive_manifest(self, job_dir: Path, manifest: Mapping[str, Any]) -> None:
        history = job_dir / "history"
        history.mkdir(parents=True, exist_ok=True)
        old_identity = str(manifest.get("production_identity") or "unknown")
        manifest_hash = _canonical_hash(dict(manifest))
        destination = history / f"MANIFEST__{old_identity}__{manifest_hash[:12]}.json"
        if not destination.exists():
            shutil.copy2(job_dir / "MANIFEST.json", destination)

    def prepare(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        plan, segments, identity = self._expected(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        job_dir = self._job_dir(book_id, job_id, profile_id)
        path = job_dir / "MANIFEST.json"
        with self._locked(job_dir):
            if path.exists():
                try:
                    old = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise QwenChapterManifestError("Existing Qwen chapter manifest is unreadable.") from error
                if not isinstance(old, dict):
                    raise QwenChapterManifestError("Existing Qwen chapter manifest is invalid.")
                if old.get("production_identity") == identity:
                    return self.status(
                        book_id=book_id,
                        job_id=job_id,
                        profile_id=profile_id,
                        synthesis_identity=synthesis_identity,
                    )
                self._archive_manifest(job_dir, old)

            entries = {
                item["id"]: {**item, "state": "PENDING", "updated_at": _utc_now()}
                for item in segments
            }
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "engine": "qwen",
                "book_id": plan["book_id"],
                "job_id": job_id,
                "profile_id": profile_id,
                "chapter_production_identity": plan["chapter_production_identity"],
                "production_identity": identity,
                "synthesis_identity": dict(synthesis_identity),
                "created_at": _utc_now(),
                "segments": entries,
            }
            atomic_write_json(path, manifest)
        return self.status(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )

    def _load_current(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        _, expected, identity = self._expected(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        job_dir = self._job_dir(book_id, job_id, profile_id)
        path = job_dir / "MANIFEST.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise QwenChapterManifestError("Qwen chapter manifest is missing or unreadable.") from error
        if not isinstance(manifest, dict):
            raise QwenChapterManifestError("Qwen chapter manifest is invalid.")
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("production_identity") != identity:
            raise QwenChapterManifestError("Qwen chapter manifest is invalidated by current execution facts.")
        expected_map = {item["id"]: item for item in expected}
        entries = manifest.get("segments")
        if not isinstance(entries, dict) or set(entries) != set(expected_map):
            raise QwenChapterManifestError("Qwen chapter manifest segment catalog mismatch.")
        for segment_id, expected_entry in expected_map.items():
            entry = entries[segment_id]
            if not isinstance(entry, dict) or any(
                entry.get(key) != expected_entry[key]
                for key in ("fingerprint", "text_sha256", "pause_after_ms", "seed", "wav")
            ):
                raise QwenChapterManifestError("Qwen chapter manifest fingerprint mismatch.")
            if entry.get("state") not in STATES:
                raise QwenChapterManifestError("Qwen chapter manifest contains invalid state.")
        return job_dir, manifest

    def _reconcile_done_integrity(self, job_dir: Path, manifest: dict[str, Any]) -> bool:
        changed = False
        for entry in manifest["segments"].values():
            if entry["state"] == "DONE" and not _valid_wav(job_dir / entry["wav"]):
                entry["state"] = "PENDING"
                entry["integrity_recovery"] = True
                entry["updated_at"] = _utc_now()
                changed = True
        if changed:
            atomic_write_json(job_dir / "MANIFEST.json", manifest)
        return changed

    def recover_after_restart(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        job_dir = self._job_dir(book_id, job_id, profile_id)
        with self._locked(job_dir):
            _, manifest = self._load_current(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            changed = False
            for entry in manifest["segments"].values():
                if entry["state"] == "RUNNING":
                    entry["state"] = "DONE" if _valid_wav(job_dir / entry["wav"]) else "PENDING"
                    entry["recovered_after_restart"] = True
                    entry["updated_at"] = _utc_now()
                    changed = True
            if changed:
                atomic_write_json(job_dir / "MANIFEST.json", manifest)
            self._reconcile_done_integrity(job_dir, manifest)
        return self.status(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )

    def status(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        job_dir, manifest = self._load_current(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        self._reconcile_done_integrity(job_dir, manifest)
        counts = {state: 0 for state in STATES}
        for entry in manifest["segments"].values():
            counts[entry["state"]] += 1
        return {
            "schema_version": SCHEMA_VERSION,
            "book_id": manifest["book_id"],
            "job_id": job_id,
            "profile_id": profile_id,
            "production_identity": manifest["production_identity"],
            "job_dir": str(job_dir),
            "segment_count": len(manifest["segments"]),
            "counts": counts,
            "complete": counts["DONE"] == len(manifest["segments"]),
            "remote_request_sent": False,
        }

    def claim_next(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        job_dir = self._job_dir(book_id, job_id, profile_id)
        with self._locked(job_dir):
            _, manifest = self._load_current(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            self._reconcile_done_integrity(job_dir, manifest)
            for entry in manifest["segments"].values():
                if entry["state"] == "PENDING":
                    entry["state"] = "RUNNING"
                    entry["updated_at"] = _utc_now()
                    atomic_write_json(job_dir / "MANIFEST.json", manifest)
                    return {
                        **entry,
                        "output_path": str(job_dir / entry["wav"]),
                        "remote_request_sent": False,
                    }
        return None

    def complete(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
        segment_id: str,
    ) -> dict[str, Any]:
        job_dir = self._job_dir(book_id, job_id, profile_id)
        with self._locked(job_dir):
            _, manifest = self._load_current(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            entry = manifest["segments"].get(segment_id)
            if not isinstance(entry, dict) or entry.get("state") != "RUNNING":
                raise QwenChapterManifestError("Only RUNNING segment can be completed.")
            metadata = inspect_pcm_wav(job_dir / entry["wav"])
            entry["state"] = "DONE"
            entry["wav_metadata"] = {
                "duration_seconds": metadata.duration_seconds,
                "sample_rate_hz": metadata.sample_rate_hz,
                "channels": metadata.channels,
                "sample_width_bytes": metadata.sample_width_bytes,
            }
            entry["updated_at"] = _utc_now()
            atomic_write_json(job_dir / "MANIFEST.json", manifest)
        return self.status(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )

    def fail(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
        segment_id: str,
        error: str,
    ) -> dict[str, Any]:
        job_dir = self._job_dir(book_id, job_id, profile_id)
        with self._locked(job_dir):
            _, manifest = self._load_current(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            entry = manifest["segments"].get(segment_id)
            if not isinstance(entry, dict) or entry.get("state") != "RUNNING":
                raise QwenChapterManifestError("Only RUNNING segment can fail.")
            entry["state"] = "FAILED"
            entry["error"] = str(error)
            entry["updated_at"] = _utc_now()
            atomic_write_json(job_dir / "MANIFEST.json", manifest)
        return self.status(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )

    def assembly_inputs(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        job_dir, manifest = self._load_current(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
        result: list[dict[str, Any]] = []
        for entry in manifest["segments"].values():
            if entry.get("state") != "DONE":
                raise QwenChapterManifestError("Qwen chapter is not complete for assembly.")
            wav_path = job_dir / entry["wav"]
            metadata = inspect_pcm_wav(wav_path)
            result.append({
                "id": entry["id"],
                "wav_path": str(wav_path),
                "pause_after_ms": int(entry["pause_after_ms"]),
                "sample_rate_hz": metadata.sample_rate_hz,
                "channels": metadata.channels,
                "sample_width_bytes": metadata.sample_width_bytes,
            })
        return result

    def retry_failed(
        self,
        *,
        book_id: str,
        job_id: str,
        profile_id: str,
        synthesis_identity: Mapping[str, Any],
        segment_id: str,
    ) -> dict[str, Any]:
        job_dir = self._job_dir(book_id, job_id, profile_id)
        with self._locked(job_dir):
            _, manifest = self._load_current(
                book_id=book_id,
                job_id=job_id,
                profile_id=profile_id,
                synthesis_identity=synthesis_identity,
            )
            entry = manifest["segments"].get(segment_id)
            if not isinstance(entry, dict) or entry.get("state") != "FAILED":
                raise QwenChapterManifestError("Only FAILED segment can be retried explicitly.")
            entry["state"] = "PENDING"
            entry.pop("error", None)
            entry["updated_at"] = _utc_now()
            atomic_write_json(job_dir / "MANIFEST.json", manifest)
        return self.status(
            book_id=book_id,
            job_id=job_id,
            profile_id=profile_id,
            synthesis_identity=synthesis_identity,
        )
