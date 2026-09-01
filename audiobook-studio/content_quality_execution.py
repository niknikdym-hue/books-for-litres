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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from content_quality_gate import validate_prepared_content_quality
from content_quality_lexicon import ContentQualityLexicon, ContentQualityResolutionStore


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
    """Freeze shared rules/resolutions and yield validated prepared evidence."""
    engine = lexicon or ContentQualityLexicon()
    profile_path = library.resolve_book_profile(book_name)
    resolution_store = ContentQualityResolutionStore(
        Path(workspace_root), profile_path.stem
    )
    # Fixed lock order prevents Audiobook Studio processes from deadlocking.
    with _exclusive_advisory_lock(engine.user_store.lock_path):
        with _exclusive_advisory_lock(resolution_store.lock_path):
            evidence = validate_prepared_content_quality(
                library=library,
                workspace_root=Path(workspace_root),
                book_name=profile_path.name,
                lexicon=engine,
            )
            yield evidence
