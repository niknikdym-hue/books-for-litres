from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"


class ContentQualityNativeContractTests(unittest.TestCase):
    def test_native_panel_is_compiled_and_mounted_in_main_production_flow(self) -> None:
        build = (NATIVE / "build_native_app.sh").read_text(encoding="utf-8")
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        app = (NATIVE / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/ContentQualityPanel.swift"', build)
        self.assertIn("ContentQualitySettingsPanel(selectedBookID: book.id)", app)
        self.assertIn('Section("Словарь мусора")', panel)
        self.assertIn('Section("Контроль текста")', panel)
        self.assertIn("BOOK OS + Audiobook Studio", panel)
        self.assertIn("BOOK_PROSE,AUDIOBOOK_PRE_SYNTHESIS", panel)

    def test_panel_exposes_user_rule_and_exact_sha_human_resolution_only(self) -> None:
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        self.assertIn('"--add-user-rule"', panel)
        self.assertIn('"--remove-user-rule"', panel)
        self.assertIn('"--resolve-finding"', panel)
        self.assertIn("Разрешить для этого SHA", panel)
        self.assertIn("Любое изменение текста автоматически делает его неприменимым", panel)
        self.assertIn("Пользовательский REGEX в v1 запрещён", panel)
        self.assertNotIn("--execute-yandex-chapter-plan", panel)
        self.assertNotIn("--execute-paid-plan", panel)
        self.assertNotIn("--run-openai", panel)
        self.assertNotIn("--run-yandex", panel)

    def test_panel_surfaces_rule_fragment_location_block_warn_and_profile_separation(self) -> None:
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        for token in (
            "finding.ruleID",
            "finding.matchedText",
            "finding.line",
            "finding.column",
            "finding.start",
            "finding.end",
            'title: "Общие редакционные"',
            'title: "TTS-технические"',
            'finding.action == "BLOCK"',
        ):
            self.assertIn(token, panel)
        self.assertIn("Литературный текст автоматически не изменяется", panel)


if __name__ == "__main__":
    unittest.main()
