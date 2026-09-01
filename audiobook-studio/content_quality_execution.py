"""Cross-process Content Quality barrier for exact provider/model execution.

The barrier shares the same advisory user-store lock defined by the BOOK OS
interoperability contract and also freezes Audiobook Studio's exact-SHA human
resolution store while an execution is in progress. Validation happens after
both locks are acquired, so a provider/model cannot begin on a lexicon identity
that changes between the final check and the execution call.
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
from tts_text_review import assert_manual_review_ready


def _delegated_openai_child_owns_gate() -> bool:
    """Keep the legacy universal CLI's paid-gate precedence and lock order.

    ``audiobook_studio_app_runner.py --run-openai`` is only a subprocess
    delegator. The actual provider runner owns the Content Quality barrier so
    it can preserve the established paid-execution gate and acquire locks in
    the canonical order ``production authority -> content quality``. This is
    not a bypass: ``openai_backend_runner.py --run`` revalidates the exact
    prepared Content Quality evidence immediately before backend execution.
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
    """Freeze rules/resolutions and yield exact manual-review + prepared evidence."""
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
    # Fixed lock order prevents Audiobook Studio processes from deadlocking.
    with _exclusive_advisory_lock(engine.user_store.lock_path):
        with _exclusive_advisory_lock(resolution_store.lock_path):
            # Optional owner acceptance is exact-SHA. When the switch is off this
            # returns ready=True and is non-blocking; when on, any working-copy edit
            # invalidates the previous acceptance before a paid/provider call.
            manual_review = assert_manual_review_ready(library, profile_path.name)
            evidence = dict(validate_prepared_content_quality(
                library=library,
                workspace_root=Path(workspace_root),
                book_name=profile_path.name,
                lexicon=engine,
            ))
            evidence["manual_text_review"] = manual_review["manual_review"]
            yield evidence
