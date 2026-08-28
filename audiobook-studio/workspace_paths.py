"""Canonical local path contract for Audiobook Studio.

The contract has one root. Every provider-specific runtime/output path is
derived from it, so callers never need to carry their own absolute paths.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


WORKSPACE_ENV = "AUDIOBOOK_STUDIO_HOME"
CONTRACT_ENV = "AUDIOBOOK_STUDIO_PATH_CONTRACT"
DEFAULT_RELATIVE_ROOT = Path("Documents/New project/Audiobook-Studio")


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    contract_file: Path

    @property
    def runtime_root(self) -> Path:
        return self.root / "runtime" / "studio-workspace"

    @property
    def books_root(self) -> Path:
        return self.root / "books"

    @property
    def qwen_engine_root(self) -> Path:
        return self.root / "engines" / "qwen-mlx"

    @property
    def qwen_python(self) -> Path:
        return self.qwen_engine_root / ".venv" / "bin" / "python"

    @property
    def qwen_hf_home(self) -> Path:
        return self.qwen_engine_root / "hf-cache"

    @property
    def qwen_output_root(self) -> Path:
        return self.root / "renders" / "studio"

    @property
    def yandex_output_root(self) -> Path:
        return self.root / "renders" / "yandex"

    @property
    def cache_root(self) -> Path:
        return self.root / "cache"

    @property
    def openai_cache_root(self) -> Path:
        return self.cache_root / "openai"

    @property
    def jobs_root(self) -> Path:
        return self.root / "jobs"

    @property
    def qa_review_root(self) -> Path:
        return self.root / "runtime" / "qa-review"

    @property
    def chapters_root(self) -> Path:
        return self.root / "chapters"

    @property
    def masters_root(self) -> Path:
        return self.root / "masters"

    @property
    def exports_root(self) -> Path:
        return self.root / "exports"

    @property
    def media_tools_config(self) -> Path:
        return self.root / "settings" / "media-tools.json"

    @property
    def cloud_billing_settings(self) -> Path:
        return self.root / "settings" / "cloud-billing.json"

    @property
    def billing_runtime_root(self) -> Path:
        return self.root / "runtime" / "billing"

    @property
    def billing_ledger(self) -> Path:
        return self.billing_runtime_root / "ledger.json"

    @property
    def billing_provider_cache(self) -> Path:
        return self.billing_runtime_root / "provider-cache.json"

    @property
    def paid_run_plans(self) -> Path:
        return self.root / "runtime" / "paid-run-plans"

    @property
    def openai_casting_root(self) -> Path:
        return self.root / "casting" / "openai"

    @property
    def yandex_casting_root(self) -> Path:
        return self.root / "casting" / "yandex"

    @property
    def builds_root(self) -> Path:
        return self.root / "builds"

    def resolve(self, value: str | Path | None, default_relative: str | Path) -> Path:
        candidate = Path(value if value not in (None, "") else default_relative).expanduser()
        return candidate if candidate.is_absolute() else self.root / candidate


def load_workspace_paths(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> WorkspacePaths:
    values = os.environ if env is None else env
    home_dir = Path.home() if home is None else Path(home)
    default_root = home_dir / DEFAULT_RELATIVE_ROOT

    explicit_root = values.get(WORKSPACE_ENV, "").strip()
    contract_value = values.get(CONTRACT_ENV, "").strip()
    contract_file = (
        Path(contract_value).expanduser()
        if contract_value
        else default_root / "settings" / "workspace-paths.json"
    )

    if explicit_root:
        root = Path(explicit_root).expanduser()
    elif contract_file.is_file():
        payload = json.loads(contract_file.read_text(encoding="utf-8"))
        configured = payload.get("workspace_root") if isinstance(payload, dict) else None
        if not isinstance(configured, str) or not configured.strip():
            raise RuntimeError(f"Invalid Audiobook Studio path contract: {contract_file}")
        root = Path(configured).expanduser()
    else:
        root = default_root

    return WorkspacePaths(root=root.resolve(), contract_file=contract_file.resolve())
