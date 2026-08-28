#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Offline-first bridge for the universal Audiobook Studio launcher."""

from __future__ import annotations

import argparse
from dataclasses import replace
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from voice_library import load_voice_library, normalize_qwen_profiles
from workspace_paths import load_workspace_paths
from cloud_billing import CloudBillingService, decimal_text, decimal_value, save_settings
from book_library import BookLibrary, BookLibraryError, normalize_slug
from book_text_preparation import BookTextPreparationService
from chapter_production import YandexChapterProductionService
from chapter_assembly import (
    ChapterAssemblyService,
    assembly_input_from_qa,
    assembly_input_from_qa_segments,
)
from mastering_export import (
    LitresExportService,
    MasteringExportError,
    MasteringService,
    canonical_book_authority,
    resolve_current_assembly,
    resolve_current_master,
)
from paid_run import PaidRunService
from audio_qa_authority import (
    AudioQAAuthority,
    AudioQAAuthorityError,
    list_openai_qa_targets,
    resolve_openai_authority,
    resolve_openai_segment_set,
    resolve_qwen_authority,
    resolve_yandex_authority,
)
from audio_qa_review import AudioQAReviewService

STUDIO_DIR = Path(__file__).resolve().parent
QWEN_RUNNER = STUDIO_DIR / "studio_app_runner.py"
YANDEX_RUNNER = STUDIO_DIR / "yandex_backend_runner.py"
OPENAI_RUNNER = STUDIO_DIR / "openai_backend_runner.py"
YANDEX_CONFIG = STUDIO_DIR / "yandex-config.json"
YANDEX_PRICING_CONFIG = STUDIO_DIR / "yandex-pricing.json"
USER_PRICING_CONFIG = Path.home() / "Library/Application Support/Audiobook Studio/yandex-pricing.local.json"
WORKSPACE_PATHS = load_workspace_paths()
BOOK_LIBRARY = BookLibrary(WORKSPACE_PATHS.books_root)
BOOK_TEXT_PREPARATION = BookTextPreparationService(
    BOOK_LIBRARY,
    workspace_root=WORKSPACE_PATHS.root,
)

ENGINES = (
    ("qwen", "Qwen — локально"),
    ("yandex", "Yandex SpeechKit — облако"),
    ("openai", "OpenAI TTS — облако"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio universal app bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-engines", action="store_true")
    mode.add_argument("--list-books", action="store_true")
    mode.add_argument("--add-book", action="store_true")
    mode.add_argument("--book-details", action="store_true")
    mode.add_argument("--prepare-book-text", action="store_true")
    mode.add_argument("--book-preparation-status", action="store_true")
    mode.add_argument("--list-jobs", action="store_true")
    mode.add_argument("--list-voices", action="store_true")
    mode.add_argument("--default-speaker", action="store_true")
    mode.add_argument("--yandex-check", action="store_true")
    mode.add_argument("--yandex-estimate-demo", action="store_true")
    mode.add_argument("--ui-snapshot", action="store_true")
    mode.add_argument("--yandex-local-health", action="store_true")
    mode.add_argument("--set-yandex-hard-limit", action="store_true")
    mode.add_argument("--run-qwen", action="store_true")
    mode.add_argument("--run-yandex-demo", action="store_true")
    mode.add_argument("--prepare-yandex-chapter-run", action="store_true")
    mode.add_argument("--execute-yandex-chapter-plan", action="store_true")
    mode.add_argument("--openai-status", action="store_true")
    mode.add_argument("--openai-credential-status", action="store_true")
    mode.add_argument("--openai-pricing-status", action="store_true")
    mode.add_argument("--openai-preflight", action="store_true")
    mode.add_argument("--run-openai", action="store_true")
    mode.add_argument("--prepare-paid-run", action="store_true")
    mode.add_argument("--execute-paid-plan", action="store_true")
    mode.add_argument("--billing-status", action="store_true")
    mode.add_argument("--billing-preflight", action="store_true")
    mode.add_argument("--set-billing-setting", action="store_true")
    mode.add_argument("--audio-qa-current", action="store_true")
    mode.add_argument("--audio-qa-openai-targets", action="store_true")
    mode.add_argument("--audio-qa-decide", action="store_true")
    mode.add_argument("--audio-qa-downstream", action="store_true")
    mode.add_argument("--chapter-assembly-status", action="store_true")
    mode.add_argument("--prepare-chapter-assembly", action="store_true")
    mode.add_argument("--assemble-chapter", action="store_true")
    mode.add_argument("--mastering-status", action="store_true")
    mode.add_argument("--prepare-master", action="store_true")
    mode.add_argument("--create-master", action="store_true")
    mode.add_argument("--litres-export-status", action="store_true")
    mode.add_argument("--create-litres-export", action="store_true")
    mode.add_argument("--reconcile-litres-release-authority", action="store_true")
    mode.add_argument("--reconcile-all-litres-release-authorities", action="store_true")
    parser.add_argument("--engine", choices=("qwen", "yandex", "openai"), default="")
    parser.add_argument("--book", default="")
    parser.add_argument("--source-file", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--slug", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--profile-id", default="")
    parser.add_argument("--provider", choices=("qwen", "yandex", "openai"), default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--setting", choices=("hard_limit",), default="")
    parser.add_argument("--value", default="")
    parser.add_argument("--hard-limit-rub", default="")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--plan-digest", default="")
    parser.add_argument("--audio-path", default="")
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--reviewed-audio-sha256", default="")
    parser.add_argument("--reviewed-path-identity", default="")
    parser.add_argument("--reviewed-fingerprint", default="")
    parser.add_argument(
        "--decision",
        choices=("APPROVED", "REJECTED", "REGENERATE_REQUESTED"),
        default="",
    )
    parser.add_argument("--format", dest="output_format", choices=("json", "tsv"), default="json")
    return parser


def _delegate(script: Path, *arguments: str) -> int:
    """Run an existing engine runner without copying its implementation."""
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
    )
    return completed.returncode


def _require(value: str, option: str) -> str:
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _billing_service() -> CloudBillingService:
    return CloudBillingService(
        settings_path=WORKSPACE_PATHS.cloud_billing_settings,
        ledger_path=WORKSPACE_PATHS.billing_ledger,
        cache_path=WORKSPACE_PATHS.billing_provider_cache,
    )


def _paid_run_service() -> PaidRunService:
    from backends.openai_tts import OpenAITTSBackend, load_backend_config, load_pricing_config
    from openai_backend_runner import CONFIG_PATH as OPENAI_CONFIG_PATH
    from openai_backend_runner import PRICING_PATH as OPENAI_PRICING_PATH

    billing = _billing_service()
    backend = OpenAITTSBackend(
        load_backend_config(OPENAI_CONFIG_PATH),
        billing_ledger=billing.ledger,
    )
    return PaidRunService(
        backend=backend,
        pricing=load_pricing_config(OPENAI_PRICING_PATH),
        billing=billing,
        books_dir=WORKSPACE_PATHS.books_root,
        plans_dir=WORKSPACE_PATHS.paid_run_plans,
    )


def _yandex_chapter_service() -> YandexChapterProductionService:
    from backends.yandex_speechkit import YandexSpeechKitBackend

    billing = _billing_service()
    offline_backend, pricing, _ = _load_yandex_offline()
    backend = YandexSpeechKitBackend(
        offline_backend.config,
        billing_ledger=billing.ledger,
    )
    return YandexChapterProductionService(
        backend=backend,
        pricing=pricing,
        billing=billing,
        books_dir=WORKSPACE_PATHS.books_root,
        plans_dir=WORKSPACE_PATHS.paid_run_plans,
    )


def _audio_qa_service() -> AudioQAReviewService:
    return AudioQAReviewService(WORKSPACE_PATHS.qa_review_root)


def _chapter_assembly_service() -> ChapterAssemblyService:
    return ChapterAssemblyService(
        workspace_root=WORKSPACE_PATHS.root,
        chapters_root=WORKSPACE_PATHS.chapters_root,
    )


def _mastering_service() -> MasteringService:
    return MasteringService(
        workspace_root=WORKSPACE_PATHS.root,
        masters_root=WORKSPACE_PATHS.masters_root,
    )


def _litres_export_service() -> LitresExportService:
    return LitresExportService(
        workspace_root=WORKSPACE_PATHS.root,
        exports_root=WORKSPACE_PATHS.exports_root,
    )


def reconcile_litres_release_authority(*, book_name: str) -> dict[str, Any]:
    """Apply current book rights to the release pointer without media tools."""
    profile_path = BOOK_LIBRARY.resolve_book_profile(book_name)

    def load_profile_authority() -> dict[str, Any]:
        book = BOOK_LIBRARY.load_book_profile(
            profile_path.name, allow_disabled=True,
        )
        book["slug"] = profile_path.stem
        return book

    book = load_profile_authority()
    return _litres_export_service().reconcile_release_authority(
        book,
        revalidate_book=load_profile_authority,
    )


def _profile_requires_release_quarantine(
    profile_name: str, book_slug: str,
) -> bool:
    """Revalidate whether a profile must not retain book release authority."""
    return _profile_release_authority(profile_name, book_slug) is None


def _profile_release_authority(
    profile_name: str, book_slug: str,
) -> dict[str, Any] | None:
    """Return the current canonical profile only when it authorizes release."""
    canonical_name = f"{normalize_slug(book_slug)}.json"
    try:
        book = BOOK_LIBRARY.load_book_profile(
            canonical_name, allow_disabled=True,
        )
    except BookLibraryError:
        # If no recovered canonical profile exists, preserve the original
        # enumerated-name check.  This keeps case-variant malformed profiles
        # quarantinable on case-sensitive filesystems.
        if profile_name == canonical_name:
            return None
        try:
            book = BOOK_LIBRARY.load_book_profile(
                profile_name, allow_disabled=True,
            )
        except BookLibraryError:
            # The case-variant path may have disappeared because it was
            # atomically restored under its canonical name between lookups.
            # Retry that canonical authority before authorizing quarantine.
            try:
                book = BOOK_LIBRARY.load_book_profile(
                    canonical_name, allow_disabled=True,
                )
            except BookLibraryError:
                return None
    if book.get("enabled", True) is False:
        return None
    rights = book.get("rights_provenance")
    if bool(
        isinstance(rights, Mapping)
        and rights.get("third_party_assets")
        and rights.get("verified") is not True
    ):
        return None
    book["slug"] = normalize_slug(book_slug)
    return book


def reconcile_all_litres_release_authorities() -> dict[str, Any]:
    """Reconcile every readable profile before fallible UI snapshot services."""
    results: list[dict[str, Any]] = []
    failed_book_ids: list[str] = []
    quarantined_book_ids: list[str] = []
    quarantine_failed_book_ids: list[str] = []
    for profile_path in BOOK_LIBRARY.list_book_profiles():
        try:
            results.append(reconcile_litres_release_authority(book_name=profile_path.name))
        except (BookLibraryError, MasteringExportError, OSError, ValueError):
            # Continue so one malformed profile cannot prevent release cleanup
            # for every other canonical book.  No exception text is exposed.
            failed_book_ids.append(profile_path.name)
            try:
                book_slug = normalize_slug(profile_path.stem)
                quarantine = _litres_export_service().quarantine_release_authority(
                    book_slug,
                    revalidate_quarantine=lambda name=profile_path.name, slug=book_slug: (
                        _profile_requires_release_quarantine(name, slug)
                    ),
                    revalidate_recovered_book=lambda name=profile_path.name, slug=book_slug: (
                        _profile_release_authority(name, slug)
                    ),
                )
                if quarantine["release_authority_revoked"]:
                    quarantined_book_ids.append(profile_path.name)
            except (BookLibraryError, MasteringExportError, OSError, ValueError):
                quarantine_failed_book_ids.append(profile_path.name)
    return {
        "schema_version": 1,
        "processed_books": len(results),
        "failed_book_ids": failed_book_ids,
        "quarantined_book_ids": quarantined_book_ids,
        "quarantine_failed_book_ids": quarantine_failed_book_ids,
        "results": results,
        "provider_requests": 0,
        "remote_request_sent": False,
        "billing_changed": False,
    }


def _stable_symlink_identity(path: Path) -> tuple[tuple[int | str, ...], Path]:
    """Return a race-checked identity and the direct lexical symlink target."""
    before = path.lstat()
    raw_target = os.readlink(path)
    after = path.lstat()
    identity: tuple[int | str, ...] = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        raw_target,
    )
    if identity[:-1] != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise AudioQAAuthorityError(
            "Yandex compatibility alias changed during identity verification."
        )
    raw_path = Path(raw_target)
    direct_target = raw_path if raw_path.is_absolute() else path.parent / raw_path
    return identity, Path(os.path.abspath(str(direct_target)))


def _nonsymlink_path_identity(
    path: Path,
    *,
    anchor: Path,
) -> tuple[tuple[int | str, ...], ...]:
    """Snapshot a lexical path below anchor while rejecting symlink components."""
    lexical_path = Path(os.path.abspath(str(path)))
    lexical_anchor = Path(os.path.abspath(str(anchor)))
    try:
        relative = lexical_path.relative_to(lexical_anchor)
    except ValueError as error:
        raise AudioQAAuthorityError(
            "Yandex compatibility alias must remain inside the workspace root."
        ) from error

    identities: list[tuple[int | str, ...]] = []
    current = lexical_anchor
    for component in (None, *relative.parts):
        if component is not None:
            current /= component
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise AudioQAAuthorityError(
                "Yandex compatibility alias parent cannot contain symlink components."
            )
        identities.append((
            str(current),
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        ))
    return tuple(identities)


def _audio_qa_authority(
    *,
    provider: str,
    book_name: str,
    job_id: str,
    profile_id: str,
    audio_path: str = "",
    manifest_path: str = "",
) -> AudioQAAuthority:
    selected_audio = Path(audio_path) if audio_path else None
    selected_manifest = Path(manifest_path) if manifest_path else None
    # Output directories are keyed by the canonical registry identity.  The
    # optional raw `slug` field may be absent or merely NFKC/case-equivalent.
    slug = BOOK_LIBRARY.resolve_book_profile(book_name).stem
    if provider == "qwen":
        candidates = [selected_manifest] if selected_manifest is not None else list(
            (WORKSPACE_PATHS.qwen_output_root / slug).glob("*/RUN-REPORT.json")
        )
        return resolve_qwen_authority(
            library=BOOK_LIBRARY,
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            report_candidates=candidates,
            allowed_output_roots=[(
                WORKSPACE_PATHS.qwen_output_root,
                WORKSPACE_PATHS.root,
            )],
            config_path=STUDIO_DIR / "studio-config.json",
            audio_path=selected_audio,
            fail_on_invalid_report=selected_manifest is not None,
        )
    if provider == "yandex":
        backend, _, _ = _load_yandex_offline()
        relative = Path(slug) / job_id / profile_id / "MANIFEST.json"
        configured_root = Path(backend.config.output_root).expanduser().absolute()
        workspace_alias = WORKSPACE_PATHS.yandex_output_root.expanduser().absolute()
        historical_root = (
            WORKSPACE_PATHS.runtime_root / "renders-yandex"
        ).expanduser().absolute()
        expected_alias_targets = {
            str(historical_root),
            os.path.relpath(historical_root, workspace_alias.parent),
        }
        compatibility_alias_identity: tuple[
            tuple[tuple[int | str, ...], ...],
            tuple[int | str, ...],
        ] | None = None
        if selected_manifest is not None:
            # An explicit authority must remain fail-closed, including every
            # symlink/path-component guard applied by resolve_yandex_authority.
            candidates = [selected_manifest]
        else:
            known_historical_alias = False
            if configured_root == workspace_alias and workspace_alias.is_symlink():
                try:
                    parent_identity = _nonsymlink_path_identity(
                        workspace_alias.parent,
                        anchor=WORKSPACE_PATHS.root,
                    )
                    alias_identity, direct_target = _stable_symlink_identity(
                        workspace_alias
                    )
                    known_historical_alias = (
                        alias_identity[-1] in expected_alias_targets
                        and direct_target == historical_root
                    )
                    if known_historical_alias:
                        compatibility_alias_identity = (
                            parent_identity,
                            alias_identity,
                        )
                except OSError:
                    known_historical_alias = False
            if known_historical_alias:
                # This exact workspace alias predates the canonical path guard.
                # Never authorize through it; inspect only its known real root.
                candidates = [
                    historical_root / relative,
                    STUDIO_DIR / "renders-yandex" / relative,
                ]
            else:
                # A real configured root is the sole current authority. Missing
                # output or any other symlink/path defect must fail closed rather
                # than silently resurrecting a historical artifact.
                candidates = [configured_root / relative]
        allowed_output_roots = [
            (configured_root, WORKSPACE_PATHS.root),
            (historical_root, WORKSPACE_PATHS.root),
            (STUDIO_DIR / "renders-yandex", STUDIO_DIR),
        ]
        authority = resolve_yandex_authority(
            library=BOOK_LIBRARY,
            backend=backend,
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            manifest_candidates=candidates,
            allowed_output_roots=allowed_output_roots,
            audio_path=selected_audio,
        )
        if compatibility_alias_identity is not None:
            try:
                current_parent_identity = _nonsymlink_path_identity(
                    workspace_alias.parent,
                    anchor=WORKSPACE_PATHS.root,
                )
                current_identity, direct_target = _stable_symlink_identity(workspace_alias)
            except OSError as error:
                raise AudioQAAuthorityError(
                    "Yandex compatibility alias changed during authority resolution."
                ) from error
            if (
                (current_parent_identity, current_identity)
                != compatibility_alias_identity
                or current_identity[-1] not in expected_alias_targets
                or direct_target != historical_root
            ):
                raise AudioQAAuthorityError(
                    "Yandex compatibility alias changed during authority resolution."
                )
        return authority
    if provider == "openai":
        from backends.openai_tts import OpenAITTSBackend, load_backend_config
        from openai_backend_runner import CONFIG_PATH as OPENAI_CONFIG_PATH

        backend = OpenAITTSBackend(load_backend_config(OPENAI_CONFIG_PATH))
        current_manifest = selected_manifest or (
            backend.config.jobs_root / slug / job_id / "openai" / profile_id / "MANIFEST.json"
        )
        return resolve_openai_authority(
            library=BOOK_LIBRARY,
            backend=backend,
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            jobs_root_anchor=WORKSPACE_PATHS.root,
            manifest_path=current_manifest,
            audio_path=selected_audio,
        )
    raise AudioQAAuthorityError("No current production authority is available for this provider.")


def audio_qa_current(
    *,
    provider: str,
    book_name: str,
    job_id: str,
    profile_id: str,
    audio_path: str = "",
    manifest_path: str = "",
    decision: str = "",
    reviewed_identity: Mapping[str, str] | None = None,
    downstream: bool = False,
) -> dict[str, Any]:
    authority = _audio_qa_authority(
        provider=provider,
        book_name=book_name,
        job_id=job_id,
        profile_id=profile_id,
        audio_path=audio_path,
        manifest_path=manifest_path,
    )
    service = _audio_qa_service()
    identity = {
        "provider": authority.provider,
        "profile_id": authority.profile_id,
        "book_slug": authority.book_slug,
        "job_id": authority.job_id,
        "segment_id": authority.segment_id,
    }
    current = {
        "audio_path": authority.audio_path,
        "synthesis_fingerprint": authority.synthesis_fingerprint,
        "expected_sample_rate_hz": authority.expected_sample_rate_hz,
        "text_characters": authority.text_characters,
    }
    if decision:
        record = service.decide(
            **identity,
            **current,
            decision=decision,
            reviewed_identity=reviewed_identity,
        )
        eligible = bool(record["downstream_eligible"])
    elif downstream:
        eligible_record = service.downstream_audio(**identity, **current)
        record = eligible_record or service.status(**identity)
        eligible = eligible_record is not None
    else:
        record = service.scan(**identity, **current)
        eligible = bool(record["downstream_eligible"])
    return {
        "schema_version": 1,
        "authority": authority.to_dict(),
        "record": record,
        "eligible": eligible,
        "remote_request_sent": False,
    }


def openai_qa_targets(*, book_name: str, job_id: str, profile_id: str) -> dict[str, Any]:
    """Return current exact QA choices from the canonical manifest, offline."""
    from backends.openai_tts import OpenAITTSBackend, load_backend_config
    from openai_backend_runner import CONFIG_PATH as OPENAI_CONFIG_PATH

    backend = OpenAITTSBackend(load_backend_config(OPENAI_CONFIG_PATH))
    slug = BOOK_LIBRARY.resolve_book_profile(book_name).stem
    manifest_path = (
        backend.config.jobs_root / slug / job_id / "openai" / profile_id / "MANIFEST.json"
    )
    return {
        "schema_version": 1,
        "qa_targets": list_openai_qa_targets(
            library=BOOK_LIBRARY,
            backend=backend,
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            jobs_root_anchor=WORKSPACE_PATHS.root,
            manifest_path=manifest_path,
        ),
        "remote_request_sent": False,
    }


def chapter_assembly_current(
    *,
    action: str,
    provider: str,
    book_name: str,
    job_id: str,
    profile_id: str,
    audio_path: str = "",
    manifest_path: str = "",
) -> dict[str, Any]:
    """Resolve exact current downstream authority, then operate entirely offline."""
    if provider == "openai":
        from backends.openai_tts import OpenAITTSBackend, load_backend_config
        from openai_backend_runner import CONFIG_PATH as OPENAI_CONFIG_PATH

        backend = OpenAITTSBackend(load_backend_config(OPENAI_CONFIG_PATH))
        slug = BOOK_LIBRARY.resolve_book_profile(book_name).stem
        canonical_manifest = (
            backend.config.jobs_root / slug / job_id / "openai" / profile_id / "MANIFEST.json"
        )
        segment_set = resolve_openai_segment_set(
            library=BOOK_LIBRARY,
            backend=backend,
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            jobs_root_anchor=WORKSPACE_PATHS.root,
            manifest_path=canonical_manifest,
        )
        qa_items = [audio_qa_current(
            provider="openai",
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            audio_path=str(authority.audio_path),
            manifest_path=str(authority.manifest_path),
            downstream=True,
        ) for authority in segment_set.authorities]
        approved = [item for item in qa_items if item.get("eligible")]
        qa_blockers = [{
            "segment_id": str(item.get("authority", {}).get("segment_id") or "unknown"),
            "reason": "qa_not_currently_approved",
        } for item in qa_items if not item.get("eligible")]
        selected_qa = next((
            item for item in qa_items
            if not audio_path or Path(item["authority"]["audio_path"]).resolve() == Path(audio_path).resolve()
        ), qa_items[0] if qa_items else None)
        counts = {
            "expected": len(segment_set.expected_segment_ids),
            "produced": len(segment_set.produced_segment_ids),
            "approved": len(approved),
            "blocked": len(segment_set.expected_segment_ids) - len(approved),
        }
        if not segment_set.complete or len(approved) != len(segment_set.expected_segment_ids):
            resolution = _chapter_assembly_service()._resolution()
            return {
                "schema_version": 1,
                "qa": selected_qa,
                "assembly": {
                    "schema_version": 1,
                    "state": "BLOCKED",
                    "decision": "BLOCKED",
                    "blockers": ["incomplete_approved_segment_set"],
                    "blocker_message": "Для сборки главы одобрены не все готовые сегменты.",
                    "assembly_identity": segment_set.prepared_text_identity,
                    "target": {
                        "container": "WAV", "codec": "LPCM", "sample_rate_hz": 48000,
                        "channels": 1, "sample_width_bytes": 2,
                    },
                    "ffmpeg": resolution.to_dict(),
                    "output_path": None,
                    "manifest_path": None,
                    "assembly": None,
                    "segment_counts": counts,
                    "segment_blockers": list(segment_set.blockers) + qa_blockers,
                    "provider_requests": 0,
                    "remote_request_sent": False,
                },
                "provider_requests": 0,
                "remote_request_sent": False,
            }
        assembly_input = assembly_input_from_qa_segments(
            [(item["authority"], item["record"]) for item in qa_items],
            expected_segment_ids=segment_set.expected_segment_ids,
            prepared_text_identity=segment_set.prepared_text_identity,
        )

        def current_openai_input() -> Mapping[str, Any]:
            current_set = resolve_openai_segment_set(
                library=BOOK_LIBRARY,
                backend=backend,
                book_name=book_name,
                job_id=job_id,
                profile_id=profile_id,
                jobs_root_anchor=WORKSPACE_PATHS.root,
                manifest_path=canonical_manifest,
            )
            if not current_set.complete:
                raise RuntimeError("Полный текущий набор OpenAI-сегментов больше не доступен.")
            current_qa = [audio_qa_current(
                provider="openai", book_name=book_name, job_id=job_id,
                profile_id=profile_id, audio_path=str(authority.audio_path),
                manifest_path=str(authority.manifest_path), downstream=True,
            ) for authority in current_set.authorities]
            if not all(item.get("eligible") for item in current_qa):
                raise RuntimeError("Одобрение одного из OpenAI-сегментов устарело.")
            return assembly_input_from_qa_segments(
                [(item["authority"], item["record"]) for item in current_qa],
                expected_segment_ids=current_set.expected_segment_ids,
                prepared_text_identity=current_set.prepared_text_identity,
            )
        qa = selected_qa
    else:
        qa = audio_qa_current(
            provider=provider,
            book_name=book_name,
            job_id=job_id,
            profile_id=profile_id,
            audio_path=audio_path,
            manifest_path=manifest_path,
            downstream=True,
        )
        if not qa.get("eligible") or not isinstance(qa.get("record"), Mapping):
            raise RuntimeError("Для сборки требуется точное текущее одобренное аудио.")
        assembly_input = assembly_input_from_qa(qa["authority"], qa["record"])

        def current_chapter_input() -> Mapping[str, Any]:
            current = audio_qa_current(
                provider=provider, book_name=book_name, job_id=job_id,
                profile_id=profile_id, audio_path=audio_path,
                manifest_path=manifest_path, downstream=True,
            )
            if not current.get("eligible"):
                raise RuntimeError("Одобрение исходного аудио устарело.")
            return assembly_input_from_qa(current["authority"], current["record"])
    service = _chapter_assembly_service()
    if action == "status":
        assembly = service.status(assembly_input)
    elif action == "prepare":
        assembly = service.prepare(assembly_input)
    elif action == "assemble":
        service.assemble(
            assembly_input,
            revalidate=current_openai_input if provider == "openai" else current_chapter_input,
        )
        assembly = service.status(assembly_input)
    else:
        raise RuntimeError("Unsupported chapter assembly action.")
    return {
        "schema_version": 1,
        "qa": qa,
        "assembly": assembly,
        "provider_requests": 0,
        "remote_request_sent": False,
    }


def _current_assembly_authority(
    *, provider: str, book_name: str, job_id: str, profile_id: str,
    audio_path: str = "", manifest_path: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = chapter_assembly_current(
        action="status", provider=provider, book_name=book_name,
        job_id=job_id, profile_id=profile_id,
        audio_path=audio_path, manifest_path=manifest_path,
    )
    status = envelope["assembly"]
    if status.get("decision") != "ALREADY_ASSEMBLED" or not isinstance(status.get("assembly"), Mapping):
        raise RuntimeError("Для мастеринга требуется точная текущая сборка главы.")
    authority = resolve_current_assembly(
        workspace_root=WORKSPACE_PATHS.root,
        chapters_root=WORKSPACE_PATHS.chapters_root,
        book_slug=BOOK_LIBRARY.resolve_book_profile(book_name).stem,
        job_id=job_id,
        expected_assembly_identity=status["assembly_identity"],
    )
    return envelope, authority


def mastering_current(
    *, action: str, provider: str, book_name: str, job_id: str,
    profile_id: str, audio_path: str = "", manifest_path: str = "",
) -> dict[str, Any]:
    """Prepare or create one clean master from exact-current assembly, offline."""
    assembly_envelope, authority = _current_assembly_authority(
        provider=provider, book_name=book_name, job_id=job_id,
        profile_id=profile_id, audio_path=audio_path, manifest_path=manifest_path,
    )

    def revalidate() -> Mapping[str, Any]:
        _, current = _current_assembly_authority(
            provider=provider, book_name=book_name, job_id=job_id,
            profile_id=profile_id, audio_path=audio_path, manifest_path=manifest_path,
        )
        return current

    service = _mastering_service()
    if action == "status":
        mastering = service.status(authority)
    elif action == "prepare":
        mastering = service.prepare(authority)
    elif action == "master":
        service.master(authority, revalidate=revalidate)
        mastering = service.status(revalidate())
    else:
        raise RuntimeError("Unsupported mastering action.")
    return {
        "schema_version": 1,
        "assembly": assembly_envelope["assembly"],
        "mastering": mastering,
        "provider_requests": 0,
        "remote_request_sent": False,
        "billing_changed": False,
    }


def litres_export_current(
    *, action: str, provider: str, book_name: str, job_id: str,
    profile_id: str, audio_path: str = "", manifest_path: str = "",
) -> dict[str, Any]:
    """Prepare or create one LitRes MP3 candidate from exact-current master."""
    mastering_envelope = mastering_current(
        action="status", provider=provider, book_name=book_name,
        job_id=job_id, profile_id=profile_id,
        audio_path=audio_path, manifest_path=manifest_path,
    )
    mastering = mastering_envelope["mastering"]
    if mastering.get("decision") != "ALREADY_MASTERED" or not isinstance(mastering.get("master"), Mapping):
        raise RuntimeError("Для экспорта требуется точный текущий clean master.")
    slug = BOOK_LIBRARY.resolve_book_profile(book_name).stem
    master = resolve_current_master(
        workspace_root=WORKSPACE_PATHS.root,
        masters_root=WORKSPACE_PATHS.masters_root,
        book_slug=slug,
        job_id=job_id,
        expected_master_identity=mastering["master_identity"],
    )
    book = BOOK_LIBRARY.load_book_for_execution(book_name)

    def revalidate_master() -> Mapping[str, Any]:
        current_mastering = mastering_current(
            action="status", provider=provider, book_name=book_name,
            job_id=job_id, profile_id=profile_id,
            audio_path=audio_path, manifest_path=manifest_path,
        )["mastering"]
        if current_mastering.get("decision") != "ALREADY_MASTERED":
            raise RuntimeError("Clean master больше не является текущим.")
        return resolve_current_master(
            workspace_root=WORKSPACE_PATHS.root,
            masters_root=WORKSPACE_PATHS.masters_root,
            book_slug=slug, job_id=job_id,
            expected_master_identity=current_mastering["master_identity"],
        )

    def revalidate_book() -> Mapping[str, Any]:
        return BOOK_LIBRARY.load_book_for_execution(book_name)

    service = _litres_export_service()
    if action == "status":
        export = service.status(master, book)
    elif action == "export":
        service.export(
            master, book,
            revalidate_master=revalidate_master,
            revalidate_book=revalidate_book,
        )
        export = service.status(revalidate_master(), revalidate_book())
    else:
        raise RuntimeError("Unsupported LitRes export action.")
    return {
        "schema_version": 1,
        "mastering": mastering,
        "export": export,
        "provider_requests": 0,
        "remote_request_sent": False,
        "billing_changed": False,
    }


def _load_book_job_text(book_name: str, job_id: str) -> tuple[dict[str, Any], str]:
    book = BOOK_LIBRARY.load_book_for_execution(book_name)
    job = (book.get("jobs") or {}).get(job_id) if isinstance(book, dict) else None
    segments = job.get("segments") if isinstance(job, dict) else None
    if not isinstance(segments, list) or not segments:
        raise RuntimeError(f"Book job not found or empty: {job_id}")
    texts: list[str] = []
    for segment in segments:
        value = segment.get("text") if isinstance(segment, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("Book job contains an invalid segment")
        texts.append(value.strip())
    return book, "\n\n".join(texts)


def billing_status(
    *,
    provider: str = "",
    refresh: bool = False,
    current_job_estimates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = _billing_service()
    _, yandex_pricing, _ = _load_yandex_offline()
    hard_limits = {
        "yandex": yandex_pricing.hard_limit_rub,
        "openai": service.settings.openai_hard_limit_usd,
    }

    def one(name: str) -> dict[str, Any]:
        value = (current_job_estimates or {}).get(name)
        estimate = decimal_value(value, f"{name}.current_job_estimate") if value is not None else None
        return service.status(
            name,
            refresh=refresh,
            current_job_estimate=estimate,
            current_job_estimate_source="local_estimate" if estimate is not None else "unavailable",
            hard_limit=hard_limits[name],
            paid_execution_enabled=False if name == "openai" else True,
        )

    if provider:
        return one(provider)
    results = {name: one(name) for name in ("yandex", "openai")}
    return {
        "schema_version": 1,
        "providers": results,
        "remote_request_sent": any(result["remote_request_sent"] for result in results.values()),
    }


def set_billing_setting(*, provider: str, setting: str, value: str) -> dict[str, Any]:
    """Atomically update an explicitly supported local-only billing setting."""
    if provider != "openai" or setting != "hard_limit":
        raise RuntimeError("Unsupported Cloud Billing setting.")
    amount = decimal_value(value.strip(), "openai.hard_limit_usd")
    service = _billing_service()
    updated = replace(service.settings, openai_hard_limit_usd=amount)
    save_settings(service.settings_path, updated)
    return {
        "schema_version": 1,
        "provider": provider,
        "setting": setting,
        "value": decimal_text(amount),
        "currency": "USD",
        "remote_request_sent": False,
    }


def billing_preflight(*, provider: str, book_name: str, job_id: str, profile_id: str = "") -> dict[str, Any]:
    book, text = _load_book_job_text(book_name, job_id)
    service = _billing_service()
    if provider == "yandex":
        backend, pricing, _ = _load_yandex_offline()
        estimate = backend.estimate(text, pricing=pricing, scope="book")
        value = estimate.get("estimated_remaining_cost")
        current = decimal_value(value, "yandex.current_job_estimate") if value is not None else None
        return service.preflight(
            "yandex",
            current_job_estimate=current,
            current_job_estimate_source="local_estimate" if current is not None else "unavailable",
            hard_limit=pricing.hard_limit_rub,
            paid_execution_enabled=True,
            job_metadata={"book": book.get("slug"), "job_id": job_id, "provider_preflight": estimate},
        )

    from backends.openai_tts import OpenAITTSBackend, load_backend_config, load_pricing_config
    from openai_backend_runner import CONFIG_PATH as OPENAI_CONFIG_PATH
    from openai_backend_runner import PRICING_PATH as OPENAI_PRICING_PATH

    selected_profile = _require(profile_id, "--profile-id")
    backend = OpenAITTSBackend(load_backend_config(OPENAI_CONFIG_PATH))
    estimate = backend.preflight(
        text,
        profile_id=selected_profile,
        pricing=load_pricing_config(OPENAI_PRICING_PATH),
    )
    # The exact output audio charge is unavailable before synthesis, so the
    # full current-job cost remains unavailable rather than becoming a false total.
    return service.preflight(
        "openai",
        current_job_estimate=None,
        current_job_estimate_source="unavailable",
        hard_limit=service.settings.openai_hard_limit_usd,
        paid_execution_enabled=False,
        job_metadata={"book": book.get("slug"), "job_id": job_id, "provider_preflight": estimate},
    )


def _load_yandex_offline() -> tuple[Any, Any, str]:
    # Imports stay inside the Yandex branch so a failure in one engine cannot
    # prevent the other engine's catalog commands from starting.
    from backends.yandex_speechkit import (
        YandexSpeechKitBackend,
        load_backend_config,
        YandexPricingConfig,
        load_pricing_config,
    )
    from yandex_backend_runner import DEMO_TEXT

    config = load_backend_config(YANDEX_CONFIG)
    base = json.loads(YANDEX_PRICING_CONFIG.read_text(encoding="utf-8"))
    if USER_PRICING_CONFIG.exists():
        try:
            override = json.loads(USER_PRICING_CONFIG.read_text(encoding="utf-8"))
            if isinstance(override, dict):
                base["hard_limit_rub"] = override.get("hard_limit_rub")
        except (OSError, ValueError):
            pass
    # Keep the load helper as the canonical validator for the repository file;
    # constructing the merged mapping avoids copying pricing rules into UI code.
    _ = load_pricing_config(YANDEX_PRICING_CONFIG)
    return YandexSpeechKitBackend(config), YandexPricingConfig.from_mapping(base), DEMO_TEXT


def _load_qwen_runtime_catalog() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    spec = importlib.util.spec_from_file_location("audiobook_studio_qwen_catalog", STUDIO_DIR / "studio.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить каталог книг Qwen.")
    studio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(studio)
    return BOOK_LIBRARY.list_book_summaries(), list(studio.load_voices())


def add_book(*, source_file: str, title: str, author: str, slug: str) -> dict[str, Any]:
    return BOOK_LIBRARY.import_text_book(
        source_file=Path(_require(source_file, "--source-file")),
        title=_require(title, "--title"),
        author=_require(author, "--author"),
        slug=_require(slug, "--slug"),
    )


def book_details(book_name: str) -> dict[str, Any]:
    return BOOK_LIBRARY.book_details(_require(book_name, "--book"))


def prepare_book_text(book_name: str) -> dict[str, Any]:
    return BOOK_TEXT_PREPARATION.prepare(_require(book_name, "--book"))


def book_preparation_status(book_name: str) -> dict[str, Any]:
    return BOOK_TEXT_PREPARATION.status(_require(book_name, "--book"))


def voice_library_listing(engine: str) -> dict[str, Any]:
    if engine == "qwen":
        _, raw_qwen_voices = _load_qwen_runtime_catalog()
        profiles = normalize_qwen_profiles(raw_qwen_voices)
    else:
        profiles = load_voice_library(provider=engine)
    return {
        "engine": engine,
        "voices": profiles,
        "remote_request_sent": False,
    }


def _print_voice_listing(result: dict[str, Any], output_format: str) -> None:
    if output_format == "tsv":
        for profile in result["voices"]:
            print(f"{profile['profile_id']}\t{profile['label']}")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def ui_snapshot() -> dict[str, Any]:
    books, raw_qwen_voices = _load_qwen_runtime_catalog()
    qwen_voices = [{"id": str(voice["id"]), "label": str(voice["id"])} for voice in raw_qwen_voices]
    profiles = load_voice_library(qwen_loader=lambda: raw_qwen_voices)
    estimate = yandex_demo_estimate()
    _, pricing, _ = _load_yandex_offline()
    cloud_billing = billing_status(current_job_estimates={
        "yandex": estimate.get("estimated_remaining_cost"),
    })
    return {
        "workspace_root": str(WORKSPACE_PATHS.root),
        "engines": [
            {"id": engine_id, "label": label, "kind": "local" if engine_id == "qwen" else "cloud"}
            for engine_id, label in ENGINES
        ],
        "books": books,
        "qwen_voices": qwen_voices,
        "voice_library": {
            engine: [profile for profile in profiles if profile["provider"] == engine]
            for engine in ("qwen", "yandex", "openai")
        },
        "yandex_profile": {
            "voice": estimate["voice_display"],
            "role": estimate["role"],
            "speed": estimate["speed"],
        },
        "yandex_estimate": estimate,
        "yandex_settings": {"hard_limit_rub": str(pricing.hard_limit_rub) if pricing.hard_limit_rub is not None else None},
        "cloud_billing": cloud_billing,
        "remote_request_sent": False,
    }


def yandex_local_health() -> dict[str, Any]:
    backend, _, _ = _load_yandex_offline()
    result = backend.healthcheck(remote=False)
    result["remote_request_sent"] = False
    return result


def set_yandex_hard_limit(value: str) -> dict[str, Any]:
    from decimal import Decimal, InvalidOperation

    normalized: str | None
    if not value.strip():
        normalized = None
    else:
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise RuntimeError("Лимит должен быть числом в рублях.") from error
        if amount < 0:
            raise RuntimeError("Лимит не может быть отрицательным.")
        normalized = format(amount, "f")
    USER_PRICING_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_PRICING_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps({"hard_limit_rub": normalized}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, USER_PRICING_CONFIG)
    return {"hard_limit_rub": normalized, "remote_request_sent": False}


def yandex_offline_check() -> dict[str, Any]:
    backend, _, _ = _load_yandex_offline()
    result = backend.validate_config(resolve_credentials=False)
    result["backend_config_ok"] = bool(result.pop("ok", False))
    result["keychain_check"] = "not_attempted_offline"
    result["remote_request_sent"] = False
    return result


def yandex_demo_estimate() -> dict[str, Any]:
    backend, pricing, demo_text = _load_yandex_offline()
    config_status = backend.validate_config(resolve_credentials=False)
    estimate = backend.estimate(demo_text, pricing=pricing, scope="demo")
    return {
        "backend_config_ok": bool(config_status["ok"]),
        "engine": estimate["engine"],
        "engine_display": "Yandex SpeechKit v3",
        "voice": backend.profile.voice,
        "voice_display": backend.profile.voice.capitalize(),
        "role": backend.profile.role,
        "speed": backend.profile.speed,
        "characters": estimate["characters"],
        "segments": estimate["segments"],
        "estimated_billing_units": estimate["estimated_billing_units"],
        "cached_segments": estimate["cached_segments"],
        "total_billing_units": estimate["total_billing_units"],
        "billable_remaining_units": estimate["billable_remaining_units"],
        "currency": estimate["currency"],
        "unit_price": estimate["unit_price"],
        "estimated_total_cost": estimate["estimated_total_cost"],
        "estimated_remaining_cost": estimate["estimated_remaining_cost"],
        "price_verified_at": estimate["price_verified_at"],
        "price_stale": estimate["price_stale"],
        "price_source": estimate["price_source"],
        "hard_limit_rub": estimate["hard_limit_rub"],
        "allowed_to_start": estimate["allowed_to_start"],
        "blocked_reason": estimate["blocked_reason"],
        "keychain_check": "not_attempted_offline",
        "remote_request_sent": False,
    }


def _print_yandex_estimate(result: dict[str, Any], output_format: str) -> None:
    if output_format == "tsv":
        print("\t".join(str(result[key]) for key in (
            "engine_display",
            "voice_display",
            "role",
            "speed",
            "characters",
            "segments",
            "estimated_billing_units",
        )))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_engines:
        for engine_id, label in ENGINES:
            print(f"{engine_id}\t{label}")
        return 0

    if args.list_books:
        for book in BOOK_LIBRARY.list_book_summaries():
            print(f"{book['id']}\t{book['title']} — {book['author']}")
        return 0

    if args.add_book:
        print(json.dumps(add_book(
            source_file=args.source_file,
            title=args.title,
            author=args.author,
            slug=args.slug,
        ), ensure_ascii=False, indent=2))
        return 0

    if args.book_details:
        print(json.dumps(book_details(args.book), ensure_ascii=False, indent=2))
        return 0

    if args.prepare_book_text:
        print(json.dumps(prepare_book_text(args.book), ensure_ascii=False, indent=2))
        return 0

    if args.book_preparation_status:
        print(json.dumps(book_preparation_status(args.book), ensure_ascii=False, indent=2))
        return 0

    if args.list_jobs:
        return _delegate(QWEN_RUNNER, "--list-jobs", "--book", _require(args.book, "--book"))

    if args.list_voices:
        engine = _require(args.engine, "--engine")
        _print_voice_listing(voice_library_listing(engine), args.output_format)
        return 0

    if args.default_speaker:
        return _delegate(QWEN_RUNNER, "--default-speaker", "--book", _require(args.book, "--book"))

    if args.yandex_check:
        print(json.dumps(yandex_offline_check(), ensure_ascii=False, indent=2))
        return 0

    if args.yandex_estimate_demo:
        _print_yandex_estimate(yandex_demo_estimate(), args.output_format)
        return 0

    if args.ui_snapshot:
        print(json.dumps(ui_snapshot(), ensure_ascii=False, indent=2))
        return 0

    if args.yandex_local_health:
        print(json.dumps(yandex_local_health(), ensure_ascii=False, indent=2))
        return 0

    if args.set_yandex_hard_limit:
        print(json.dumps(set_yandex_hard_limit(args.hard_limit_rub), ensure_ascii=False, indent=2))
        return 0

    if args.run_qwen:
        return _delegate(
            QWEN_RUNNER,
            "--run",
            "--book", _require(args.book, "--book"),
            "--job", _require(args.job, "--job"),
            "--speaker", _require(args.speaker, "--speaker"),
        )

    if args.run_yandex_demo:
        # Legacy bounded diagnostic smoke; the production chapter route below
        # requires an immutable plan and a separate execute command.
        return _delegate(YANDEX_RUNNER, "--demo")

    if args.prepare_yandex_chapter_run:
        print(json.dumps(
            _yandex_chapter_service().prepare(
                book_name=_require(args.book, "--book"),
                job_id=_require(args.job, "--job"),
                profile_id=_require(args.profile_id, "--profile-id"),
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.execute_yandex_chapter_plan:
        print(json.dumps(
            _yandex_chapter_service().execute(
                plan_id=_require(args.plan_id, "--plan-id"),
                plan_digest=_require(args.plan_digest, "--plan-digest"),
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.audio_qa_openai_targets:
        print(json.dumps(openai_qa_targets(
            book_name=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            profile_id=_require(args.profile_id, "--profile-id"),
        ), ensure_ascii=False, indent=2))
        return 0

    if args.audio_qa_current or args.audio_qa_decide or args.audio_qa_downstream:
        reviewed_identity = None
        if args.audio_qa_decide:
            reviewed_identity = {
                "audio_sha256": _require(args.reviewed_audio_sha256, "--reviewed-audio-sha256"),
                "path_identity": _require(args.reviewed_path_identity, "--reviewed-path-identity"),
                "synthesis_fingerprint": _require(args.reviewed_fingerprint, "--reviewed-fingerprint"),
            }
        print(json.dumps(audio_qa_current(
            provider=_require(args.provider, "--provider"),
            book_name=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            profile_id=_require(args.profile_id, "--profile-id"),
            audio_path=args.audio_path,
            manifest_path=args.manifest_path,
            decision=_require(args.decision, "--decision") if args.audio_qa_decide else "",
            reviewed_identity=reviewed_identity,
            downstream=args.audio_qa_downstream,
        ), ensure_ascii=False, indent=2))
        return 0

    if (
        args.chapter_assembly_status
        or args.prepare_chapter_assembly
        or args.assemble_chapter
    ):
        action = (
            "status" if args.chapter_assembly_status else
            "prepare" if args.prepare_chapter_assembly else
            "assemble"
        )
        print(json.dumps(chapter_assembly_current(
            action=action,
            provider=_require(args.provider, "--provider"),
            book_name=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            profile_id=_require(args.profile_id, "--profile-id"),
            audio_path=args.audio_path,
            manifest_path=args.manifest_path,
        ), ensure_ascii=False, indent=2))
        return 0

    if args.mastering_status or args.prepare_master or args.create_master:
        action = (
            "status" if args.mastering_status else
            "prepare" if args.prepare_master else
            "master"
        )
        print(json.dumps(mastering_current(
            action=action,
            provider=_require(args.provider, "--provider"),
            book_name=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            profile_id=_require(args.profile_id, "--profile-id"),
            audio_path=args.audio_path,
            manifest_path=args.manifest_path,
        ), ensure_ascii=False, indent=2))
        return 0

    if args.litres_export_status or args.create_litres_export:
        print(json.dumps(litres_export_current(
            action="status" if args.litres_export_status else "export",
            provider=_require(args.provider, "--provider"),
            book_name=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
            profile_id=_require(args.profile_id, "--profile-id"),
            audio_path=args.audio_path,
            manifest_path=args.manifest_path,
        ), ensure_ascii=False, indent=2))
        return 0

    if args.reconcile_litres_release_authority:
        print(json.dumps(reconcile_litres_release_authority(
            book_name=_require(args.book, "--book"),
        ), ensure_ascii=False, indent=2))
        return 0

    if args.reconcile_all_litres_release_authorities:
        print(json.dumps(reconcile_all_litres_release_authorities(), ensure_ascii=False, indent=2))
        return 0

    if args.openai_status:
        return _delegate(OPENAI_RUNNER, "--status")

    if args.openai_credential_status:
        return _delegate(OPENAI_RUNNER, "--credential-status")

    if args.openai_pricing_status:
        return _delegate(OPENAI_RUNNER, "--pricing-status")

    if args.openai_preflight:
        return _delegate(
            OPENAI_RUNNER,
            "--preflight",
            "--book", _require(args.book, "--book"),
            "--job", _require(args.job, "--job"),
            "--profile-id", _require(args.profile_id, "--profile-id"),
        )

    if args.run_openai:
        return _delegate(
            OPENAI_RUNNER,
            "--run",
            "--book", _require(args.book, "--book"),
            "--job", _require(args.job, "--job"),
            "--profile-id", _require(args.profile_id, "--profile-id"),
        )

    if args.prepare_paid_run:
        if _require(args.provider, "--provider") != "openai":
            raise RuntimeError("Safe paid run v1 supports only OpenAI.")
        print(json.dumps(
            _paid_run_service().prepare(
                book_name=_require(args.book, "--book"),
                job_id=_require(args.job, "--job"),
                profile_id=_require(args.profile_id, "--profile-id"),
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.execute_paid_plan:
        print(json.dumps(
            _paid_run_service().execute(
                plan_id=_require(args.plan_id, "--plan-id"),
                plan_digest=_require(args.plan_digest, "--plan-digest"),
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.billing_status:
        print(json.dumps(
            billing_status(provider=args.provider, refresh=args.refresh),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.billing_preflight:
        print(json.dumps(
            billing_preflight(
                provider=_require(args.provider, "--provider"),
                book_name=_require(args.book, "--book"),
                job_id=_require(args.job, "--job"),
                profile_id=args.profile_id,
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.set_billing_setting:
        print(json.dumps(
            set_billing_setting(
                provider=_require(args.provider, "--provider"),
                setting=_require(args.setting, "--setting"),
                value=_require(args.value, "--value"),
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2)
