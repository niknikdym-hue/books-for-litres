#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable offline bridge for Content Quality Lexicon management."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from book_library import BookLibrary, BookLibraryError, sha256_bytes
from book_text_preparation import normalize_working_text
from content_quality_lexicon import (
    DEFAULT_EDITORIAL_PROFILES,
    PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
    PROFILE_AUDIOBOOK_TTS_TECHNICAL,
    PROFILE_BOOK_PROSE,
    ContentQualityError,
    ContentQualityLexicon,
    ContentQualityResolutionStore,
    combined_gate_state,
)
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio offline Content Quality bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--scan-book", action="store_true")
    mode.add_argument("--add-user-rule", action="store_true")
    mode.add_argument("--remove-user-rule", action="store_true")
    mode.add_argument("--resolve-finding", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--include-editorial", action="store_true")
    parser.add_argument("--value", default="")
    parser.add_argument("--rule-id", default="")
    parser.add_argument("--action", choices=("BLOCK", "WARN"), default="BLOCK")
    parser.add_argument("--profiles", default=",".join(DEFAULT_EDITORIAL_PROFILES))
    parser.add_argument(
        "--profile",
        choices=(PROFILE_AUDIOBOOK_PRE_SYNTHESIS, PROFILE_AUDIOBOOK_TTS_TECHNICAL),
        default=PROFILE_AUDIOBOOK_PRE_SYNTHESIS,
    )
    parser.add_argument("--reason", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise ContentQualityError("invalid_request", f"{option} is required")
    return value


def _offline_fields() -> dict[str, Any]:
    return {
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }


def _blocked(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "BLOCKED",
        "decision": "INVALID_OR_UNSAFE_CONTENT_QUALITY_OPERATION",
        "blockers": [getattr(error, "code", "content_quality_error")],
        "message": str(error),
        **_offline_fields(),
    }


def _book_texts(book_name: str) -> tuple[str, str, str, Path, BookLibrary]:
    paths = load_workspace_paths()
    library = BookLibrary(paths.books_root)
    profile = library.resolve_book_profile(book_name)
    book = library.load_book_profile(profile.name)
    tts = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else {}
    working_path = library.resolve_book_asset(profile.name, tts.get("path"))
    if working_path.is_symlink() or not working_path.is_file():
        raise ContentQualityError("working_copy_missing", "TTS working copy is missing or unsafe.")
    try:
        working_text = working_path.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as error:
        raise ContentQualityError("working_copy_invalid", "TTS working copy must be strict UTF-8.") from error
    normalized = normalize_working_text(working_text)
    return profile.stem, working_text, normalized, paths.root, library


def _empty_editorial_scan(text: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile": PROFILE_BOOK_PROSE,
        "state": "PASS",
        "text_sha256": sha256_bytes(text.encode("utf-8")),
        "findings": [],
        "blocking_findings": [],
        "warning_findings": [],
        "resolved_findings": [],
        "manual_scan_enabled": False,
        **_offline_fields(),
    }


def scan_book(
    book_name: str,
    *,
    lexicon: ContentQualityLexicon | None = None,
    include_editorial: bool = False,
) -> dict[str, Any]:
    slug, working_text, normalized, workspace_root, _ = _book_texts(book_name)
    engine = lexicon or ContentQualityLexicon()
    # Owner decision: editorial "junk" search in Audiobook Studio is opt-in.
    # It never rewrites the literary text. The obligatory automatic gate here is
    # only the Audiobook-specific TTS technical profile.
    if include_editorial:
        editorial = engine.scan(working_text, profile=PROFILE_BOOK_PROSE)
        editorial["manual_scan_enabled"] = True
    else:
        editorial = _empty_editorial_scan(working_text)
    technical = engine.scan_for_book(
        normalized,
        profile=PROFILE_AUDIOBOOK_TTS_TECHNICAL,
        workspace_root=workspace_root,
        book_slug=slug,
    )
    working_sha = sha256_bytes(working_text.encode("utf-8"))
    normalized_sha = sha256_bytes(normalized.encode("utf-8"))
    return {
        "schema_version": 1,
        "state": combined_gate_state((editorial, technical)),
        "book_slug": slug,
        "working_copy_sha256": working_sha,
        "normalized_sha256": normalized_sha,
        "gate_fingerprint": engine.gate_fingerprint(
            workspace_root=workspace_root,
            book_slug=slug,
            working_copy_sha256=working_sha,
            normalized_sha256=normalized_sha,
        ),
        "editorial": editorial,
        "technical": technical,
        **_offline_fields(),
    }


def resolve_finding(
    *, book_name: str, rule_id: str, profile: str, reason: str
) -> dict[str, Any]:
    slug, working_text, normalized, workspace_root, _ = _book_texts(book_name)
    engine = ContentQualityLexicon()
    text = working_text if profile == PROFILE_AUDIOBOOK_PRE_SYNTHESIS else normalized
    initial = engine.scan_for_book(
        text,
        profile=profile,
        workspace_root=workspace_root,
        book_slug=slug,
    )
    finding = next(
        (
            item
            for item in initial["blocking_findings"]
            if item.get("rule_id") == rule_id and item.get("action") == "BLOCK"
        ),
        None,
    )
    if finding is None:
        raise ContentQualityError(
            "finding_not_currently_blocking",
            "The requested BLOCK finding is not present on the exact current text identity.",
        )
    result = ContentQualityResolutionStore(workspace_root, slug).add(
        rule_id=rule_id,
        profile=profile,
        text_sha256=initial["text_sha256"],
        reason=_require(reason.strip(), "--reason"),
        actor="OWNER",
    )
    rescanned = engine.scan_for_book(
        text,
        profile=profile,
        workspace_root=workspace_root,
        book_slug=slug,
    )
    return {
        "schema_version": 1,
        "state": rescanned["state"],
        "resolution": result,
        "scan": rescanned,
        **_offline_fields(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = ContentQualityLexicon()
        if args.status:
            result = engine.status()
        elif args.scan_book:
            result = scan_book(
                _require(args.book, "--book"),
                lexicon=engine,
                include_editorial=args.include_editorial,
            )
        elif args.add_user_rule:
            profiles = [value.strip() for value in args.profiles.split(",") if value.strip()]
            mutation = engine.user_store.add(
                _require(args.value, "--value"),
                action=args.action,
                profiles=profiles,
                match_type="PHRASE",
            )
            result = {"schema_version": 1, "mutation": mutation, "lexicon": engine.status(), **_offline_fields()}
        elif args.remove_user_rule:
            mutation = engine.user_store.remove(_require(args.rule_id, "--rule-id"))
            result = {"schema_version": 1, "mutation": mutation, "lexicon": engine.status(), **_offline_fields()}
        else:
            result = resolve_finding(
                book_name=_require(args.book, "--book"),
                rule_id=_require(args.rule_id, "--rule-id"),
                profile=args.profile,
                reason=args.reason,
            )
    except (ContentQualityError, BookLibraryError, RuntimeError) as error:
        print(json.dumps(_blocked(error), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
