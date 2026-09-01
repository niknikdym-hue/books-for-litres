#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable offline bridge for manual TTS text review and stress control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from book_library import BookLibrary, BookLibraryError
from tts_text_review import (
    TTSTextReviewError,
    accept_current_working_copy,
    add_pronunciation_override,
    provider_stress_preview,
    save_working_copy,
    set_manual_review_required,
    stress_candidates,
    working_copy_status,
)
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio offline TTS text review bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--save-working-copy", action="store_true")
    mode.add_argument("--set-manual-review-required", action="store_true")
    mode.add_argument("--accept-current-working-copy", action="store_true")
    mode.add_argument("--stress-candidates", action="store_true")
    mode.add_argument("--stress-preview", action="store_true")
    mode.add_argument("--add-pronunciation-override", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--input-file", default="")
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--required", choices=("true", "false"), default="false")
    parser.add_argument("--word", default="")
    parser.add_argument("--vowel-number", type=int, default=0)
    parser.add_argument("--engine", default="yandex")
    parser.add_argument("--scope", choices=("BOOK", "OCCURRENCE"), default="BOOK")
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise TTSTextReviewError("invalid_request", f"{option} is required")
    return value


def _blocked(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "BLOCKED",
        "blockers": [getattr(error, "code", "tts_text_review_error")],
        "message": str(error),
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }


def _load_input_file(value: str) -> str:
    path = Path(_require(value, "--input-file")).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise TTSTextReviewError("unsafe_input_file", "Input file must be an absolute regular file, not a symlink.")
    try:
        return path.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as error:
        raise TTSTextReviewError("invalid_input_file", "Input file must contain strict UTF-8 text.") from error


def _with_selection_context(library: BookLibrary, book_name: str, result: dict[str, Any]) -> dict[str, Any]:
    profile = library.resolve_book_profile(book_name)
    book = library.load_book_profile(profile.name)
    return {
        **result,
        "selected_backend": str(book.get("selected_backend") or ""),
        "selected_profile_id": str(book.get("selected_profile_id") or ""),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = load_workspace_paths()
    library = BookLibrary(paths.books_root)
    try:
        if args.status:
            book_name = _require(args.book, "--book")
            result = _with_selection_context(
                library,
                book_name,
                working_copy_status(library, book_name),
            )
        elif args.save_working_copy:
            result = save_working_copy(
                library,
                _require(args.book, "--book"),
                text=_load_input_file(args.input_file),
                expected_sha256=_require(args.expected_sha256, "--expected-sha256"),
            )
        elif args.set_manual_review_required:
            result = set_manual_review_required(
                library,
                _require(args.book, "--book"),
                required=args.required == "true",
            )
        elif args.accept_current_working_copy:
            result = accept_current_working_copy(library, _require(args.book, "--book"))
        elif args.stress_candidates:
            result = {
                "schema_version": 1,
                "word": _require(args.word, "--word"),
                "candidates": stress_candidates(args.word),
                "provider_requests": 0,
                "remote_request_sent": False,
                "model_calls": 0,
                "paid_execution": False,
                "billing_changed": False,
            }
        elif args.stress_preview:
            result = provider_stress_preview(
                _require(args.word, "--word"),
                vowel_number=args.vowel_number,
                engine=args.engine,
            )
        else:
            result = add_pronunciation_override(
                library,
                _require(args.book, "--book"),
                word=_require(args.word, "--word"),
                vowel_number=args.vowel_number,
                scope=args.scope,
                start=args.start,
                end=args.end,
            )
    except (TTSTextReviewError, BookLibraryError, RuntimeError) as error:
        print(json.dumps(_blocked(error), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
