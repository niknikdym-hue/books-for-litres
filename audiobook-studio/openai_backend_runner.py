#!/usr/bin/env python3
"""Provider CLI for the production OpenAI TTS backend."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backends.openai_tts import (
    OpenAITTSBackend,
    OpenAITTSError,
    PaidExecutionBlocked,
    load_backend_config,
    load_pricing_config,
)
from cloud_billing import BillingLedger
from book_library import BookLibrary, BookLibraryError
from workspace_paths import load_workspace_paths
from production_authority_lock import production_authority_lock
from content_quality_execution import hold_current_content_quality


STUDIO_DIR = Path(__file__).resolve().parent
CONFIG_PATH = STUDIO_DIR / "openai-config.json"
PRICING_PATH = STUDIO_DIR / "openai-pricing.json"
def load_book_job(book_name: str, job_id: str, *, library: BookLibrary | None = None) -> tuple[dict[str, Any], str]:
    selected_library = library or BookLibrary(load_workspace_paths().books_root)
    try:
        book = selected_library.load_book_for_execution(book_name)
    except BookLibraryError as error:
        raise OpenAITTSError(f"Book profile not found: {book_name}.", category="book") from error
    job = dict((book.get("jobs") or {}).get(job_id) or {})
    segments = job.get("segments")
    if not isinstance(segments, list) or not segments:
        raise OpenAITTSError(f"Book job not found or empty: {job_id}.", category="book")
    texts = []
    for segment in segments:
        value = segment.get("text") if isinstance(segment, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise OpenAITTSError("Book job contains an invalid segment.", category="book")
        texts.append(value.strip())
    return book, "\n\n".join(texts)


def job_directory(
    backend: OpenAITTSBackend,
    book: dict[str, Any],
    job_id: str,
    profile_id: str,
    *,
    canonical_book_slug: str | None = None,
) -> Path:
    slug = canonical_book_slug or str(book.get("slug") or "book")
    return backend.config.jobs_root / slug / job_id / "openai" / profile_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio — production OpenAI TTS backend")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--credential-status", action="store_true")
    mode.add_argument("--pricing-status", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--profile-id", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise OpenAITTSError(f"{option} is required.", category="arguments")
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        workspace = load_workspace_paths()
        backend = OpenAITTSBackend(
            load_backend_config(CONFIG_PATH),
            billing_ledger=BillingLedger(workspace.billing_ledger),
        )
        pricing = load_pricing_config(PRICING_PATH)
        if args.status:
            print(json.dumps(backend.status(check_credentials=False), ensure_ascii=False, indent=2))
            return 0
        if args.credential_status:
            print(json.dumps({
                "credential_available": backend.credential_available(),
                "source_type": "macos_keychain",
                "credential_value_exposed": False,
                "remote_request_sent": False,
            }))
            return 0
        if args.pricing_status:
            print(json.dumps({
                "engine": "openai_tts",
                "model": pricing.model,
                "currency": pricing.currency,
                "verified_at": pricing.verified_at.isoformat(),
                "source": pricing.source_url,
                "stale": pricing.is_stale(),
                "remote_request_sent": False,
            }, indent=2))
            return 0

        book_name = _require(args.book, "--book")
        library = BookLibrary(workspace.books_root)
        book, text = load_book_job(
            book_name,
            _require(args.job, "--job"),
            library=library,
        )
        profile_id = _require(args.profile_id, "--profile-id")
        canonical_slug = library.resolve_book_profile(book_name).stem
        job_dir = job_directory(
            backend,
            book,
            args.job,
            profile_id,
            canonical_book_slug=canonical_slug,
        )
        if args.preflight:
            print(json.dumps(
                backend.preflight(text, profile_id=profile_id, pricing=pricing, job_dir=job_dir),
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        if args.run:
            # Preserve the established machine-readable paid gate before any
            # Content Quality lock or provider credential/network path.
            if not backend.config.paid_execution_enabled:
                raise PaidExecutionBlocked()
            with production_authority_lock(
                workspace.root,
                provider="openai",
                book_slug=canonical_slug,
                job_id=args.job,
                profile_id=profile_id,
                exclusive=True,
            ):
                # Canonical execution lock order is production authority first,
                # then shared/user Content Quality locks. The exact prepared
                # evidence is revalidated while both remain held, immediately
                # before the backend can perform provider execution.
                with hold_current_content_quality(
                    library=library,
                    workspace_root=workspace.root,
                    book_name=book_name,
                ):
                    manifest = backend.run_text_job(
                        text,
                        job_dir,
                        job_id=args.job,
                        profile_id=profile_id,
                        pricing=pricing,
                    )
            print(json.dumps({"manifest": str(manifest), "remote_request_sent": True}))
            return 0
        return 0
    except OpenAITTSError as error:
        print(json.dumps({
            "error": error.category,
            "state": error.state,
            "message": str(error),
            "remote_request_sent": False,
        }), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
