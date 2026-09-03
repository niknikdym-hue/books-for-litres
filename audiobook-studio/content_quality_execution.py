"""Exact pre-provider barrier for Audiobook Studio production execution.

Provider execution freezes the mutable TTS working copy/pronunciation overlay and
any exact TTS-technical human resolutions for the complete execution context.
The shared editorial anti-junk store is intentionally not part of this mandatory
barrier because Studio editorial review is owner-invoked and advisory.
"""

from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from content_quality_gate import validate_prepared_content_quality
from content_quality_lexicon import ContentQualityLexicon, ContentQualityResolutionStore
from tts_text_review import assert_manual_review_ready, working_copy_lock


def _delegated_openai_child_owns_gate() -> bool:
    """Keep the legacy universal CLI's paid-gate precedence and lock order.

    ``audiobook_studio_app_runner.py --run-openai`` is only a subprocess
    delegator. The actual provider runner owns this barrier so the established
    order remains ``production authority -> working text -> technical quality``.
    """
    return bool(
        Path(sys.argv[0]).name == "audiobook_studio_app_runner.py"
        and "--run-openai" in sys.argv[1:]
    )


@contextmanager
def _exclusive_advisory_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe Content Quality lock path: {path}")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def hold_current_content_quality(
    *,
    library: Any,
    workspace_root: Path,
    book_name: str,
    lexicon: ContentQualityLexicon | None = None,
) -> Iterator[Mapping[str, Any]]:
    """Freeze exact text/pronunciation/technical state through provider execution."""
    if _delegated_openai_child_owns_gate():
        yield {
            "schema_version": 1,
            "state": "DEFERRED_TO_OPENAI_PROVIDER_RUNNER",
            "provider_requests": 0,
            "remote_request_sent": False,
            "model_calls": 0,
            "paid_execution": False,
            "billing_changed": False,
        }
        return

    engine = lexicon or ContentQualityLexicon()
    profile_path = library.resolve_book_profile(book_name)
    resolution_store = ContentQualityResolutionStore(
        Path(workspace_root), profile_path.stem
    )
    # The caller's production-authority lock is outermost. Owner text/stress
    # mutations acquire only working_copy_lock, while technical resolutions
    # acquire only their resolution lock, so this order is deadlock-safe.
    with working_copy_lock(library, profile_path.name):
        with _exclusive_advisory_lock(resolution_store.lock_path):
            manual_review = assert_manual_review_ready(library, profile_path.name)
            evidence = dict(validate_prepared_content_quality(
                library=library,
                workspace_root=Path(workspace_root),
                book_name=profile_path.name,
                lexicon=engine,
            ))
            evidence["manual_text_review"] = manual_review["manual_review"]
            yield evidence
