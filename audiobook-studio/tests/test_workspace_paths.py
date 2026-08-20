from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workspace_paths import load_workspace_paths


class WorkspacePathContractTests(unittest.TestCase):
    def test_default_is_provider_neutral_workspace_under_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            paths = load_workspace_paths(env={}, home=home)
            expected = (home / "Documents/New project/Audiobook-Studio").resolve()
            self.assertEqual(paths.root, expected)

    def test_environment_override_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Studio Override"
            paths = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": str(root)})
            self.assertEqual(paths.root, root.resolve())

    def test_shared_json_contract_supplies_single_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "Audiobook-Studio"
            contract = base / "workspace-paths.json"
            contract.write_text(json.dumps({"workspace_root": str(root)}), encoding="utf-8")
            paths = load_workspace_paths(env={"AUDIOBOOK_STUDIO_PATH_CONTRACT": str(contract)})
            self.assertEqual(paths.root, root.resolve())
            self.assertEqual(paths.runtime_root, root.resolve() / "runtime/studio-workspace")
            self.assertEqual(paths.qwen_python, root.resolve() / "engines/qwen-mlx/.venv/bin/python")

    def test_relative_config_paths_resolve_under_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": directory})
            self.assertEqual(paths.resolve("renders/yandex", "unused"), Path(directory).resolve() / "renders/yandex")

    def test_absolute_test_paths_remain_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = load_workspace_paths(env={"AUDIOBOOK_STUDIO_HOME": "/unused"})
            absolute = Path(directory) / "output"
            self.assertEqual(paths.resolve(absolute, "unused"), absolute)


if __name__ == "__main__":
    unittest.main()
