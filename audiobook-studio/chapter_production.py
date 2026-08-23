"""Offline chapter-production planning over integrity-checked prepared book jobs.

This module deliberately does not synthesize audio. It establishes the provider-neutral
identity and safety policy that execution adapters must revalidate before any local or
remote synthesis begins.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from book_library import BookLibrary, BookLibraryError


CHAPTER_PRODUCTION_SCHEMA_VERSION = 1
SUPPORTED_ENGINES = {"qwen", "yandex", "openai"}

_ENGINE_POLICIES: dict[str, dict[str, Any]] = {
    "qwen": {
        "execution_mode": "LOCAL_FULL_CHAPTER",
        "confirmation_scope": "chapter",
        "max_network_requests": 0,
        "requires_cost_preflight": False,
        "resume_authority": "chapter_production_manifest",
    },
    "yandex": {
        "execution_mode": "CLOUD_CHAPTER_BATCH",
        "confirmation_scope": "chapter",
        "max_network_requests": None,
        "requires_cost_preflight": True,
        "resume_authority": "provider_manifest",
    },
    "openai": {
        "execution_mode": "CLOUD_ONE_SEGMENT",
        "confirmation_scope": "segment",
        "max_network_requests": 1,
        "requires_cost_preflight": True,
        "resume_authority": "provider_manifest",
    },
}


class ChapterProductionError(RuntimeError):
    pass


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ChapterProductionService:
    """Build immutable, network-free chapter execution identities and policies."""

    def __init__(self, library: BookLibrary) -> None:
        self.library = library

    def chapter_catalog(self, book_id: str | Path) -> dict[str, Any]:
        try:
            book = self.library.load_book_for_execution(book_id)
        except BookLibraryError as error:
            raise ChapterProductionError(str(error)) from error
        preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else None
        if not preparation or preparation.get("status") != "READY":
            raise ChapterProductionError("Book text preparation is not READY.")
        jobs = book.get("jobs") if isinstance(book.get("jobs"), dict) else {}
        chapters = []
        for job_id, raw_job in jobs.items():
            if not isinstance(raw_job, dict) or raw_job.get("kind") != "chapter":
                continue
            chapters.append({
                "job_id": str(job_id),
                "label": str(raw_job.get("label") or job_id),
                "chapter_id": str(raw_job.get("chapter_id") or ""),
                "segment_count": len(raw_job.get("segments") or []),
                "preparation_identity": str(raw_job.get("preparation_identity") or ""),
            })
        chapters.sort(key=lambda item: item["job_id"])
        return {
            "schema_version": CHAPTER_PRODUCTION_SCHEMA_VERSION,
            "book_id": str(book.get("slug") or Path(book_id).stem),
            "preparation_identity": str(preparation.get("identity_sha256") or ""),
            "preparation_revision": int(preparation.get("revision") or 0),
            "chapters": chapters,
            "remote_request_sent": False,
        }

    def plan(
        self,
        *,
        book_id: str | Path,
        job_id: str,
        engine: str,
        profile_id: str,
    ) -> dict[str, Any]:
        engine = str(engine or "").strip().lower()
        if engine not in SUPPORTED_ENGINES:
            raise ChapterProductionError(f"Unsupported chapter-production engine: {engine or '<empty>'}.")
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            raise ChapterProductionError("profile_id is required for chapter production.")

        try:
            profile_path = self.library.resolve_book_profile(book_id)
            book = self.library.load_book_for_execution(profile_path.name)
        except BookLibraryError as error:
            raise ChapterProductionError(str(error)) from error

        preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else None
        if not preparation or preparation.get("status") != "READY":
            raise ChapterProductionError("Book text preparation is not READY.")
        preparation_identity = str(preparation.get("identity_sha256") or "")
        if not preparation_identity:
            raise ChapterProductionError("READY preparation has no identity.")

        jobs = book.get("jobs") if isinstance(book.get("jobs"), dict) else {}
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            raise ChapterProductionError(f"Prepared chapter job not found: {job_id}.")
        if job.get("kind") != "chapter":
            raise ChapterProductionError("Chapter production accepts only prepared chapter jobs.")
        if job.get("preparation_identity") != preparation_identity:
            raise ChapterProductionError("Prepared chapter job identity does not match current preparation.")

        segments = job.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ChapterProductionError("Prepared chapter job contains no executable segments.")

        descriptors: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        characters = 0
        utf8_bytes = 0
        for index, item in enumerate(segments, 1):
            if not isinstance(item, dict):
                raise ChapterProductionError("Prepared chapter contains an invalid segment entry.")
            segment_id = str(item.get("id") or "")
            text = item.get("text")
            if not segment_id or segment_id in seen_ids:
                raise ChapterProductionError("Prepared chapter segment IDs must be unique and non-empty.")
            if not isinstance(text, str) or not text.strip():
                raise ChapterProductionError(f"Prepared segment {segment_id} has invalid text.")
            seen_ids.add(segment_id)
            exact_sha = _text_sha256(text)
            stored_sha = item.get("prepared_text_sha256")
            if stored_sha is not None and stored_sha != exact_sha:
                raise ChapterProductionError(f"Prepared segment {segment_id} hash does not match its text.")
            encoded = text.encode("utf-8")
            characters += len(text)
            utf8_bytes += len(encoded)
            descriptors.append({
                "id": segment_id,
                "index": int(item.get("index") or index),
                "text_sha256": exact_sha,
                "characters": len(text),
                "utf8_bytes": len(encoded),
                "pause_after_ms": int(item.get("pause_after_ms") or 0),
            })

        policy = dict(_ENGINE_POLICIES[engine])
        blockers: list[str] = []
        if engine == "qwen":
            # Current Qwen runner creates a unique new render and cannot resume a
            # canonical chapter manifest after interruption. Do not advertise it
            # as production-ready until that adapter exists.
            blockers.append("qwen_persistent_resume_adapter_pending")
            decision = "ADAPTER_PENDING"
        elif engine == "yandex":
            decision = "READY_FOR_PROVIDER_PREFLIGHT"
        else:
            # Reuse PaidRunService; every MISS continues to require a fresh
            # immutable plan and a separate explicit paid confirmation.
            decision = "READY_FOR_SEGMENT_PLAN"

        critical = {
            "schema_version": CHAPTER_PRODUCTION_SCHEMA_VERSION,
            "book_id": str(book.get("slug") or profile_path.stem),
            "book_file": profile_path.name,
            "preparation_identity": preparation_identity,
            "preparation_revision": int(preparation.get("revision") or 0),
            "job_id": str(job_id),
            "chapter_id": str(job.get("chapter_id") or ""),
            "engine": engine,
            "profile_id": profile_id,
            "segments": descriptors,
            "execution_policy": policy,
        }
        chapter_production_identity = _canonical_hash(critical)
        return {
            **critical,
            "chapter_production_identity": chapter_production_identity,
            "job_label": str(job.get("label") or job_id),
            "segment_count": len(descriptors),
            "characters": characters,
            "utf8_bytes": utf8_bytes,
            "decision": decision,
            "blockers": blockers,
            "remote_request_sent": False,
        }
