"""Shared filesystem lock for writers to the global Yandex audio cache."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .yandex_types import ENGINE_ID


@contextmanager
def shared_cache_execution_lock(output_root: Path) -> Iterator[None]:
    """Serialize every writer that shares the Yandex fingerprint cache."""
    lock_path = Path(output_root) / "_cache" / ENGINE_ID / ".chapter-production.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
