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
        self.assertIn('Section("Текст перед озвучкой")', panel)
        self.assertIn('Section("Ударения и произношение")', panel)
        self.assertIn('Section("Словарь мусора")', panel)
        self.assertIn('Section("Контроль текста")', panel)
        self.assertIn("BOOK OS + Audiobook Studio", panel)
        self.assertIn("BOOK_PROSE,AUDIOBOOK_PRE_SYNTHESIS", panel)

    def test_panel_exposes_shared_rule_field_and_manual_junk_toggle_without_auto_rewrite(self) -> None:
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        self.assertIn("Добавить слово/фразу в словарь мусора", panel)
        self.assertIn('"--add-user-rule"', panel)
        self.assertIn('"--remove-user-rule"', panel)
        self.assertIn('"--include-editorial"', panel)
        self.assertIn("Искать мусорные слова и фразы в этой книге", panel)
        self.assertIn("Studio сама литературный текст не правит", panel)
        self.assertIn("Пользовательский REGEX в v1 запрещён", panel)
        self.assertIn("BLOCK здесь — серьёзность находки, а не автоматический запрет синтеза", panel)

    def test_panel_exposes_editable_working_copy_and_optional_exact_sha_acceptance(self) -> None:
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        for token in (
            "TextEditor(text: $controller.workingTextDraft)",
            '"--save-working-copy"',
            '"--set-manual-review-required"',
            '"--accept-current-working-copy"',
            "Требовать ручную приёмку текущего текста перед озвучкой",
            "Текущий SHA принят владельцем",
            "После сохранения старая подготовка станет STALE",
            "Оригинал книги остаётся read-only",
        ):
            self.assertIn(token, panel)

    def test_panel_exposes_provider_aware_stress_choices_without_provider_execution(self) -> None:
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        for token in (
            '"--stress-candidates"',
            '"--stress-preview"',
            '"--add-pronunciation-override"',
            "Текущий диктор",
            "Показать варианты",
            "Запомнить для этой книги",
            "providerValue",
        ):
            self.assertIn(token, panel)
        self.assertIn("этот редактор сам платные запросы не запускает", panel)
        self.assertNotIn("--execute-yandex-chapter-plan", panel)
        self.assertNotIn("--execute-paid-plan", panel)
        self.assertNotIn("--run-openai", panel)
        self.assertNotIn("--run-yandex", panel)

    def test_panel_surfaces_exact_finding_location_and_allows_only_technical_sha_resolution(self) -> None:
        panel = (NATIVE / "ContentQualityPanel.swift").read_text(encoding="utf-8")
        for token in (
            "finding.ruleID",
            "finding.matchedText",
            "finding.line",
            "finding.column",
            "finding.start",
            "finding.end",
            'title: "Мусор — ручная проверка"',
            'title: "TTS-технические"',
            'finding.profile == "AUDIOBOOK_TTS_TECHNICAL"',
            'finding.action == "BLOCK"',
            '"--resolve-finding"',
            "Разрешить для этого SHA",
            "Любое изменение текста автоматически делает его неприменимым",
        ):
            self.assertIn(token, panel)


if __name__ == "__main__":
    unittest.main()
