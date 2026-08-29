"""Read-only production launch preflight for the first real Audiobook Studio chapter.

This module composes already accepted authorities. It does not scan/decide QA,
produce audio, master/export media, call providers, mutate billing, approve human
review, reconcile release pointers, or deploy the native app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from audio_qa_review import path_identity, sha256_file
from audiobook_studio_app_runner import (
    BOOK_LIBRARY,
    BOOK_TEXT_PREPARATION,
    WORKSPACE_PATHS,
    _audio_qa_authority,
    _audio_qa_service,
    _chapter_assembly_service,
    _litres_export_service,
    _mastering_service,
)
from chapter_assembly import assembly_input_from_qa
from dilon_identity_review import DilonIdentityReviewError, identity_review_status
from dilon_native_snapshot import DilonNativeSnapshotError, current_native_snapshot
from mastering_export import MasteringExportError, resolve_current_assembly, resolve_current_master

SCHEMA_VERSION = 1
CANONICAL_BOOK = "hvatit-sebya-obestsenivat"
CANONICAL_JOB = "chapter-ch001"
CANONICAL_PROFILE = "yandex_lera"
CANONICAL_PROVIDER = "yandex"
ACCEPTED_PROVIDER_WAV_SHA256 = "2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6"
EXPECTED_BOOK_SECTIONS = 16
PRODUCTION_READY_SECTIONS = 1


class RealBookE2EError(RuntimeError):
    pass


def _gate(name: str, *, passed: bool, blocker: str | None = None, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if passed else "BLOCKED",
        "blocker": None if passed else (blocker or "unknown_blocker"),
        "evidence": dict(evidence or {}),
    }


def _all_offline(*values: Mapping[str, Any]) -> bool:
    for value in values:
        if value.get("provider_requests", 0) not in {0, None}:
            return False
        if value.get("remote_request_sent", False) is not False:
            return False
        if value.get("paid_execution", False) is not False:
            return False
        if value.get("billing_changed", False) is not False:
            return False
    return True


def real_book_e2e_preflight(
    *,
    book_name: str = CANONICAL_BOOK,
    job_id: str = CANONICAL_JOB,
    profile_id: str = CANONICAL_PROFILE,
) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    slug = ""
    book: dict[str, Any] | None = None
    authority: Any = None
    qa_record: Mapping[str, Any] | None = None
    assembly_status: Mapping[str, Any] | None = None
    mastering_status: Mapping[str, Any] | None = None
    export_status: Mapping[str, Any] | None = None
    dilon_snapshot: Mapping[str, Any] | None = None
    identity_review: Mapping[str, Any] | None = None

    # 1. Source/prepared authority.
    try:
        profile_path = BOOK_LIBRARY.resolve_book_profile(book_name)
        slug = profile_path.stem
        preparation = BOOK_TEXT_PREPARATION.status(book_name)
        book = BOOK_LIBRARY.load_book_for_execution(book_name)
        job = (book.get("jobs") or {}).get(job_id) if isinstance(book, Mapping) else None
        prepared_ok = bool(
            slug == CANONICAL_BOOK
            and preparation.get("preparation_status") == "READY"
            and preparation.get("source_integrity") == "OK"
            and isinstance(job, Mapping)
            and job.get("kind") == "chapter"
        )
        gates.append(_gate(
            "source_prepared_authority",
            passed=prepared_ok,
            blocker="source_or_prepared_authority_not_ready",
            evidence={
                "book_slug": slug,
                "preparation_status": preparation.get("preparation_status"),
                "source_integrity": preparation.get("source_integrity"),
                "job_id": job_id,
                "job_kind": job.get("kind") if isinstance(job, Mapping) else None,
            },
        ))
    except Exception as error:
        gates.append(_gate(
            "source_prepared_authority",
            passed=False,
            blocker="source_or_prepared_authority_unavailable",
            evidence={"error_type": type(error).__name__},
        ))

    # 2. Exact accepted Yandex authority + persisted manual QA, read-only.
    if gates[-1]["status"] == "PASS":
        try:
            authority = _audio_qa_authority(
                provider=CANONICAL_PROVIDER,
                book_name=book_name,
                job_id=job_id,
                profile_id=profile_id,
                audio_path="",
                manifest_path="",
            )
            audio_path = Path(authority.audio_path)
            current_sha = sha256_file(audio_path)
            current_path_identity = path_identity(audio_path)
            qa_record = _audio_qa_service().status(
                provider=authority.provider,
                profile_id=authority.profile_id,
                book_slug=authority.book_slug,
                job_id=authority.job_id,
                segment_id=authority.segment_id,
            )
            identity = qa_record.get("identity") if isinstance(qa_record, Mapping) else None
            qa_ok = bool(
                authority.provider == CANONICAL_PROVIDER
                and authority.profile_id == CANONICAL_PROFILE
                and authority.book_slug == CANONICAL_BOOK
                and authority.job_id == CANONICAL_JOB
                and current_sha == ACCEPTED_PROVIDER_WAV_SHA256
                and isinstance(identity, Mapping)
                and identity.get("audio_sha256") == current_sha
                and identity.get("path_identity") == current_path_identity
                and identity.get("synthesis_fingerprint") == authority.synthesis_fingerprint
                and qa_record.get("automatic_status") in {"PASS", "WARN"}
                and qa_record.get("manual_state") == "APPROVED"
                and qa_record.get("downstream_eligible") is True
                and qa_record.get("remote_request_sent") is False
            )
            gates.append(_gate(
                "accepted_yandex_qa_authority",
                passed=qa_ok,
                blocker="accepted_yandex_or_manual_qa_not_current",
                evidence={
                    "provider": authority.provider,
                    "profile_id": authority.profile_id,
                    "book_slug": authority.book_slug,
                    "job_id": authority.job_id,
                    "audio_sha256": current_sha,
                    "accepted_audio_sha256": ACCEPTED_PROVIDER_WAV_SHA256,
                    "automatic_status": qa_record.get("automatic_status") if isinstance(qa_record, Mapping) else None,
                    "manual_state": qa_record.get("manual_state") if isinstance(qa_record, Mapping) else None,
                    "downstream_eligible": qa_record.get("downstream_eligible") if isinstance(qa_record, Mapping) else None,
                },
            ))
        except Exception as error:
            gates.append(_gate(
                "accepted_yandex_qa_authority",
                passed=False,
                blocker="accepted_yandex_or_manual_qa_unavailable",
                evidence={"error_type": type(error).__name__},
            ))
    else:
        gates.append(_gate("accepted_yandex_qa_authority", passed=False, blocker="upstream_source_prepared_blocked"))

    # 3. Exact-current chapter assembly without rescanning QA.
    if gates[-1]["status"] == "PASS" and authority is not None and isinstance(qa_record, Mapping):
        try:
            assembly_input = assembly_input_from_qa(authority.to_dict(), qa_record)
            assembly_status = _chapter_assembly_service().status(assembly_input)
            assembly = assembly_status.get("assembly")
            assembly_ok = bool(
                assembly_status.get("decision") == "ALREADY_ASSEMBLED"
                and isinstance(assembly, Mapping)
                and assembly_status.get("provider_requests") == 0
                and assembly_status.get("remote_request_sent") is False
            )
            assembly_authority = None
            if assembly_ok:
                assembly_authority = resolve_current_assembly(
                    workspace_root=WORKSPACE_PATHS.root,
                    chapters_root=WORKSPACE_PATHS.chapters_root,
                    book_slug=CANONICAL_BOOK,
                    job_id=CANONICAL_JOB,
                    expected_assembly_identity=assembly_status.get("assembly_identity"),
                )
            gates.append(_gate(
                "chapter_assembly",
                passed=assembly_ok and isinstance(assembly_authority, Mapping),
                blocker="chapter_assembly_not_exact_current",
                evidence={
                    "decision": assembly_status.get("decision"),
                    "assembly_identity": assembly_status.get("assembly_identity"),
                    "output_sha256": (assembly or {}).get("output", {}).get("sha256") if isinstance(assembly, Mapping) else None,
                },
            ))
        except Exception as error:
            assembly_authority = None
            gates.append(_gate("chapter_assembly", passed=False, blocker="chapter_assembly_unavailable", evidence={"error_type": type(error).__name__}))
    else:
        assembly_authority = None
        gates.append(_gate("chapter_assembly", passed=False, blocker="upstream_yandex_qa_blocked"))

    # 4. Exact-current clean master.
    if gates[-1]["status"] == "PASS" and isinstance(assembly_authority, Mapping):
        try:
            mastering_status = _mastering_service().status(assembly_authority)
            master = mastering_status.get("master")
            mastering_ok = bool(
                mastering_status.get("decision") == "ALREADY_MASTERED"
                and isinstance(master, Mapping)
                and mastering_status.get("provider_requests") == 0
                and mastering_status.get("remote_request_sent") is False
                and mastering_status.get("billing_changed") is False
            )
            master_authority = None
            if mastering_ok:
                master_authority = resolve_current_master(
                    workspace_root=WORKSPACE_PATHS.root,
                    masters_root=WORKSPACE_PATHS.masters_root,
                    book_slug=CANONICAL_BOOK,
                    job_id=CANONICAL_JOB,
                    expected_master_identity=mastering_status.get("master_identity"),
                )
            gates.append(_gate(
                "clean_master",
                passed=mastering_ok and isinstance(master_authority, Mapping),
                blocker="clean_master_not_exact_current",
                evidence={
                    "decision": mastering_status.get("decision"),
                    "master_identity": mastering_status.get("master_identity"),
                    "audio_sha256": master_authority.get("audio_sha256") if isinstance(master_authority, Mapping) else None,
                },
            ))
        except Exception as error:
            master_authority = None
            gates.append(_gate("clean_master", passed=False, blocker="clean_master_unavailable", evidence={"error_type": type(error).__name__}))
    else:
        master_authority = None
        gates.append(_gate("clean_master", passed=False, blocker="upstream_assembly_blocked"))

    # 5. Current LitRes chapter candidate; whole-book incompleteness is expected and required.
    if gates[-1]["status"] == "PASS" and isinstance(master_authority, Mapping) and isinstance(book, Mapping):
        try:
            export_status = _litres_export_service().status(master_authority, book)
            chapter_export = export_status.get("chapter_export")
            book_export = export_status.get("book_export")
            whole_ready = book_export.get("ready") if isinstance(book_export, Mapping) else None
            blockers = list(book_export.get("blockers") or []) if isinstance(book_export, Mapping) else []
            export_ok = bool(
                export_status.get("decision") == "ALREADY_EXPORTED"
                and isinstance(chapter_export, Mapping)
                and whole_ready is False
                and "missing_chapters" in blockers
                and export_status.get("provider_requests") == 0
                and export_status.get("remote_request_sent") is False
                and export_status.get("billing_changed") is False
            )
            gates.append(_gate(
                "litres_chapter_export",
                passed=export_ok,
                blocker="litres_chapter_export_not_current_or_book_state_invalid",
                evidence={
                    "decision": export_status.get("decision"),
                    "candidate_identity": chapter_export.get("candidate_identity") if isinstance(chapter_export, Mapping) else None,
                    "chapter_sha256": chapter_export.get("sha256") if isinstance(chapter_export, Mapping) else None,
                    "whole_book_ready": whole_ready,
                    "whole_book_blockers": blockers,
                },
            ))
        except Exception as error:
            gates.append(_gate("litres_chapter_export", passed=False, blocker="litres_chapter_export_unavailable", evidence={"error_type": type(error).__name__}))
    else:
        gates.append(_gate("litres_chapter_export", passed=False, blocker="upstream_master_blocked"))

    # 6. Current Dilon identity + technical QA. This may correctly stay BLOCKED before owner/provider work.
    try:
        dilon_snapshot = current_native_snapshot(
            workspace_root=WORKSPACE_PATHS.root,
            masters_root=WORKSPACE_PATHS.masters_root,
            identities_root=WORKSPACE_PATHS.root / "identities",
            book_slug=CANONICAL_BOOK,
            job_id=CANONICAL_JOB,
        )
        dilon_status = dilon_snapshot.get("dilon_status") if isinstance(dilon_snapshot, Mapping) else None
        preview = dilon_snapshot.get("identity_preview") if isinstance(dilon_snapshot, Mapping) else None
        dilon_ok = bool(
            isinstance(dilon_status, Mapping)
            and dilon_status.get("state") == "CURRENT_TECHNICAL_QA_PASS"
            and dilon_status.get("technical_ready") is True
            and isinstance(preview, Mapping)
            and preview.get("read_only") is True
            and dilon_snapshot.get("whole_book_release_ready") is False
            and _all_offline(dilon_snapshot, dilon_status)
        )
        gates.append(_gate(
            "dilon_identity_technical",
            passed=dilon_ok,
            blocker="dilon_identity_not_current_technical_qa_pass",
            evidence={
                "state": dilon_status.get("state") if isinstance(dilon_status, Mapping) else None,
                "decision": dilon_status.get("decision") if isinstance(dilon_status, Mapping) else None,
                "build_identity": preview.get("build_identity") if isinstance(preview, Mapping) else None,
                "output_sha256": preview.get("audio_sha256") if isinstance(preview, Mapping) else None,
                "blockers": list(dilon_status.get("blockers") or []) if isinstance(dilon_status, Mapping) else [],
            },
        ))
    except (DilonNativeSnapshotError, Exception) as error:
        gates.append(_gate("dilon_identity_technical", passed=False, blocker="dilon_identity_not_available", evidence={"error_type": type(error).__name__}))

    # 7. Persisted exact-listened final identity human acceptance.
    if gates[-1]["status"] == "PASS":
        try:
            identity_review = identity_review_status(
                workspace_root=WORKSPACE_PATHS.root,
                masters_root=WORKSPACE_PATHS.masters_root,
                identities_root=WORKSPACE_PATHS.root / "identities",
                book_slug=CANONICAL_BOOK,
                job_id=CANONICAL_JOB,
            )
            final_review_ok = bool(
                identity_review.get("state") == "APPROVED"
                and identity_review.get("decision") == "IDENTITY_REVIEW_COMPLETE"
                and identity_review.get("identity_accepted") is True
                and identity_review.get("human_listening_required") is False
                and identity_review.get("whole_book_release_ready") is False
                and _all_offline(identity_review)
            )
            gates.append(_gate(
                "dilon_identity_human_acceptance",
                passed=final_review_ok,
                blocker="dilon_identity_human_listening_required",
                evidence={
                    "state": identity_review.get("state"),
                    "decision": identity_review.get("decision"),
                    "identity_accepted": identity_review.get("identity_accepted"),
                    "review_manifest_path": identity_review.get("review_manifest_path"),
                },
            ))
        except DilonIdentityReviewError as error:
            gates.append(_gate("dilon_identity_human_acceptance", passed=False, blocker=error.code))
        except Exception as error:
            gates.append(_gate("dilon_identity_human_acceptance", passed=False, blocker="dilon_identity_review_unavailable", evidence={"error_type": type(error).__name__}))
    else:
        gates.append(_gate("dilon_identity_human_acceptance", passed=False, blocker="upstream_dilon_identity_blocked"))

    all_pass = all(item["status"] == "PASS" for item in gates)
    blockers = [item["blocker"] for item in gates if item["status"] != "PASS"]
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "READY" if all_pass else "BLOCKED",
        "decision": "READY_FOR_PRODUCTION_APP_ACCEPTANCE" if all_pass else "REMAINING_LAUNCH_GATES",
        "book_slug": CANONICAL_BOOK,
        "job_id": CANONICAL_JOB,
        "profile_id": CANONICAL_PROFILE,
        "accepted_provider_wav_sha256": ACCEPTED_PROVIDER_WAV_SHA256,
        "gates": gates,
        "blockers": blockers,
        "real_book_progress": {
            "production_ready_sections": PRODUCTION_READY_SECTIONS,
            "expected_sections": EXPECTED_BOOK_SECTIONS,
        },
        "whole_book_release_ready": False,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
        "production_desktop_deployed": False,
    }
