"""Cross-process readers/writer lock for one production audio authority."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from book_library import BookLibrary, BookLibraryError, normalize_slug


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


def _pre_synthesis_quality_guard(
    *, workspace_root: Path, provider: str, book_slug: str, exclusive: bool
) -> None:
    """Last local fail-closed check before a cloud-provider execution lock yields.

    Only actual cloud synthesis writers are guarded here. Read-only QA/mastering
    authorities and historical audio remain usable even if the lexicon changes.
    """
    if not exclusive or provider not in {"yandex", "openai"}:
        return
    try:
        from content_quality_gate import (
            ContentQualityGateError,
            validate_prepared_content_quality,
        )

        validate_prepared_content_quality(
            library=BookLibrary(Path(workspace_root) / "books"),
            workspace_root=workspace_root,
            book_name=f"{normalize_slug(book_slug)}.json",
        )
    except (BookLibraryError, ContentQualityGateError) as error:
        code = getattr(error, "code", "content_quality_blocked")
        raise ProductionAuthorityLockError(
            f"Pre-synthesis Content Quality gate blocked provider execution: {code}."
        ) from error


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
            _pre_synthesis_quality_guard(
                workspace_root=root,
                provider=provider,
                book_slug=canonical_book,
                exclusive=exclusive,
            )
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
