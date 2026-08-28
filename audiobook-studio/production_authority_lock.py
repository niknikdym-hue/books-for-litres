"""Cross-process readers/writer lock for one production audio authority."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from book_library import BookLibraryError, normalize_slug


class ProductionAuthorityLockError(RuntimeError):
    pass


def _safe_id(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ProductionAuthorityLockError(f"Invalid {label} for production authority lock.")
    return value


@contextmanager
def production_authority_lock(
    workspace_root: Path,
    *,
    provider: str,
    book_slug: str,
    job_id: str,
    profile_id: str,
    exclusive: bool,
) -> Iterator[None]:
    """Hold one exact production identity stable across processes."""
    root = Path(workspace_root).expanduser().resolve(strict=True)
    try:
        canonical_book = normalize_slug(book_slug)
    except BookLibraryError as error:
        raise ProductionAuthorityLockError("Invalid book slug for production authority lock.") from error
    lock_path = (
        root / "runtime" / "production-authority-locks" /
        _safe_id(provider, "provider") / canonical_book /
        _safe_id(job_id, "job_id") / f"{_safe_id(profile_id, 'profile_id')}.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
