#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Machine-readable read-only snapshot for the native Dilon Voices UI."""

from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from book_library import BookLibrary
from dilon_native_snapshot import DilonNativeSnapshotError, current_native_snapshot
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio Dilon native offline snapshot bridge"
    )
    parser.add_argument("--snapshot", action="store_true", required=True)
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    return parser


def _require(value: str, option: str) -> str:
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _blocked(code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "BLOCKED",
        "decision": "INVALID_REQUEST",
        "blockers": [code],
        "whole_book_release_ready": False,
        "provider_requests": 0,
        "remote_request_sent": False,
        "paid_execution": False,
        "billing_changed": False,
    }


def snapshot_for_selection(*, book_name: str, job_id: str) -> dict[str, Any]:
    paths = load_workspace_paths()
    library = BookLibrary(paths.books_root)
    profile_path = library.resolve_book_profile(book_name)
    return current_native_snapshot(
        workspace_root=paths.root,
        masters_root=paths.masters_root,
        identities_root=paths.root / "identities",
        book_slug=profile_path.stem,
        job_id=job_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = snapshot_for_selection(
            book_name=_require(args.book, "--book"),
            job_id=_require(args.job, "--job"),
        )
    except (RuntimeError, DilonNativeSnapshotError, OSError, ValueError) as error:
        code = getattr(error, "code", "invalid_request")
        print(json.dumps(_blocked(code), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
