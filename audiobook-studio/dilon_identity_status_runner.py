#!/usr/bin/env python3
"""Machine-readable offline bridge for current Dilon Voices identity status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from book_library import BookLibrary
from dilon_identity_status import current_dilon_identity_status
from workspace_paths import load_workspace_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio Dilon identity status bridge")
    parser.add_argument("--status", action="store_true", required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument("--job", required=True)
    return parser


def status_for_selection(*, book_name: str, job_id: str) -> dict[str, object]:
    paths = load_workspace_paths()
    library = BookLibrary(paths.books_root)
    profile_path = library.resolve_book_profile(book_name)
    return current_dilon_identity_status(
        workspace_root=paths.root,
        masters_root=paths.masters_root,
        identities_root=paths.root / "identities",
        book_slug=profile_path.stem,
        job_id=job_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = status_for_selection(book_name=args.book, job_id=args.job)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
