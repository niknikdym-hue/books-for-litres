"""Provider-neutral local media tool discovery for GUI and CLI runtimes."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


FFMPEG_ENV = "AUDIOBOOK_STUDIO_FFMPEG"


@dataclass(frozen=True)
class FFmpegResolution:
    available: bool
    path: Path | None
    version: str | None
    source: str

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "available": self.available,
            "path": str(self.path) if self.path is not None else None,
            "version": self.version,
            "source": self.source,
        }


def _configured_path(config_path: Path) -> Path | None:
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError):
        return None
    value = payload.get("ffmpeg_path") if isinstance(payload, dict) else None
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def _version(executable: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    first_line = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
    return first_line or None


def resolve_ffmpeg(
    workspace_root: Path,
    *,
    env: Mapping[str, str] | None = None,
    known_locations: Sequence[Path] | None = None,
) -> FFmpegResolution:
    """Resolve FFmpeg without depending on a Finder app's inherited PATH."""
    values = os.environ if env is None else env
    root = Path(workspace_root).expanduser().resolve(strict=False)
    candidates: list[tuple[str, Path]] = []
    override = values.get(FFMPEG_ENV, "").strip()
    if override:
        candidates.append(("environment", Path(override).expanduser()))
    configured = _configured_path(root / "settings" / "media-tools.json")
    if configured is not None:
        candidates.append(("config", configured))
    candidates.extend([
        ("workspace_managed", root / "tools" / "ffmpeg"),
        ("runtime_managed", root / "runtime" / "tools" / "ffmpeg"),
    ])
    locations = known_locations if known_locations is not None else (
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/usr/bin/ffmpeg"),
    )
    candidates.extend(("known_macos_location", Path(item)) for item in locations)

    seen: set[str] = set()
    for source, candidate in candidates:
        absolute = candidate if candidate.is_absolute() else root / candidate
        key = str(absolute)
        if key in seen:
            continue
        seen.add(key)
        if not absolute.is_file() or not os.access(absolute, os.X_OK):
            continue
        version = _version(absolute)
        if version is not None:
            return FFmpegResolution(True, absolute.resolve(), version, source)
    return FFmpegResolution(False, None, None, "unavailable")
