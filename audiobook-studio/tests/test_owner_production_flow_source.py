from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"


class OwnerProductionFlowSourceTests(unittest.TestCase):
    def test_main_flow_is_author_first_and_costs_are_moved_out(self) -> None:
        app = (NATIVE / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        panel = (NATIVE / "OwnerProductionFlowPanel.swift").read_text(encoding="utf-8")
        main_part, settings_part = app.split("struct SettingsView: View", maxsplit=1)
        self.assertIn("OwnerProductionFlowPanel(", main_part)
        self.assertIn("activeStep: $activeOwnerStep", main_part)
        self.assertIn("selectedBookSlug: book.slug ?? book.id", main_part)
        self.assertIn("let selectedBookSlug: String", panel)
        self.assertIn("soundController.reload(bookID: selectedBookSlug)", panel)
        self.assertNotIn("ContentQualitySettingsPanel(selectedBookID: book.id)", main_part)
        self.assertNotIn('Section("Расходы и лимиты")', main_part)
        self.assertNotIn('Section("Подготовка текста")', main_part)
        self.assertIn('Section("Расходы и лимиты")', settings_part)
        self.assertNotIn("ContentQualitySettingsPanel(selectedBookID: model.selectedBookID)", settings_part)
        self.assertIn('Section("4. Выберите диктора")', app)
        self.assertIn('Section("5. Выберите главу")', app)
        self.assertIn('Section("6. Прослушивание и приёмка")', app)
        self.assertIn('Section("7. Соберите готовую аудиокнигу")', app)
        self.assertIn('Section("Текущий шаг")', panel)
        self.assertIn('"Шаг \\(activeStep.rawValue) из 7 · \\(activeStep.title)"', panel)
        self.assertIn('enum OwnerProductionStep', panel)
        self.assertIn('var systemImage: String', panel)
        self.assertIn('activeOwnerStep == .review', app)
        self.assertIn('activeOwnerStep == .release', app)
        self.assertIn('model.audioQA?.record.manualState == "REGENERATE_REQUESTED"', app)
        self.assertIn('AudioQAReviewSection(model: model, activeStep: $activeOwnerStep)', app)
        self.assertIn('openHelp(.regeneration)', app)
        self.assertIn('Звук добавится после записи голоса', panel)
        for label in (
            "1. Подготовьте текст и главы",
            "Найденные главы",
            "Ничего выделять и отмечать не нужно",
            "Сохранить текст и обновить главы",
            "2. Проверьте ударения",
            "3. Заставка перед главами — необязательно",
            "Как поставить ударение в слове из книги",
            "Текст книги — выделите нужное слово",
            "Выделите его двойным щелчком",
            "Копировать или запоминать его не нужно",
            "PronunciationTextSelector",
            "selectedWord: $textController.stressWord",
            "textView.usesFindBar = true",
            "Для быстрого поиска нажмите ⌘F",
            "Показать варианты ударения",
            "Сохранить ударение для всей книги",
            "Ударение в имени автора — уже заполнено",
            "Это отдельная настройка имени автора",
            "Вернуться к тексту книги",
            "Добавлять короткий звук перед каждой главой",
            "Выбор хранится отдельно для каждой книги",
            "Без заставки",
            "Добавить свой звук…",
            "Предыдущий",
            "Следующий",
            "Слушать",
            "Пауза",
            "Продолжить",
            "Стоп",
            "APPLE_GARAGEBAND_DIGITAL_MATERIAL",
            "Разрешён внутри аудиокниги",
            "исходный аудиофрагмент",
            "Подтвердите право на использование",
            "Подтверждаю права и добавляю",
            "публиковать и распространять её, в том числе коммерчески",
            "Вы подтвердили право использовать этот звук",
            "Выбрать фрагмент заново",
            "Чтобы убрать заставку совсем, выберите «Без заставки» выше",
        ):
            self.assertIn(label, panel)
        self.assertNotIn("Елена Ди́лон. Хватит себя обесценивать", panel)
        self.assertIn("func restartExcerptSelection()", panel)

    def test_sidebar_help_onboarding_and_contextual_next_actions_are_native(self) -> None:
        app = (NATIVE / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        panel = (NATIVE / "OwnerProductionFlowPanel.swift").read_text(encoding="utf-8")
        interface = app + panel
        for label in (
            "ШАГИ РАБОТЫ", "Текст", "Ударения", "Заставка", "Диктор", "Глава", "Запись", "Выпуск",
            "Помощь", "Настройки",
            "Добро пожаловать в Audiobook Studio", "Показать введение снова",
            "Быстрый старт", "Помощь по разделам",
        ):
            self.assertIn(label, interface)
        self.assertIn('ForEach(OwnerProductionStep.allCases)', app)
        self.assertIn('"\\(step.rawValue). \\(step.title)"', app)
        self.assertIn('Button("Подробнее")', panel)
        self.assertNotIn('Section("Путь к готовой аудиокниге")', panel)
        self.assertIn('Дальше: проверить ударения', panel)
        self.assertIn('Дальше: выбрать диктора', panel)
        self.assertIn("applyDiagnosticInitialSectionIfRequested()", app)
        self.assertIn('NSApplication.shared.windows.first(where: { $0.title == "Audiobook Studio" })', app)
        self.assertIn('case "minimum": return CGSize(width: 900, height: 620)', app)
        self.assertIn('case "standard": return CGSize(width: 1060, height: 720)', app)
        self.assertIn('window.setContentSize(diagnosticWindowSize)', app)
        self.assertIn('ProcessInfo.processInfo.environment["AUDIOBOOK_STUDIO_INITIAL_SECTION"] == nil', panel)
        self.assertNotIn('ContentQualitySettingsPanel(selectedBookID: model.selectedBookID)', app)

    def test_chapter_assembly_binds_selected_cue_into_identity_and_output(self) -> None:
        assembly = (ROOT / "chapter_assembly.py").read_text(encoding="utf-8")
        self.assertIn("from book_sound_design import chapter_cue_for_book", assembly)
        self.assertIn('"chapter_cue": chapter_cue', assembly)
        self.assertIn('segment_id": "__chapter_cue__"', assembly)
        self.assertIn("chapter_cue_then_250ms_pause_then_speech_v2", assembly)
        self.assertIn("CHAPTER_CUE_PAUSE_FRAMES = 12_000", assembly)
        self.assertIn("chapter_cue_changed_during_assembly", assembly)
        self.assertIn('if chapter_cue is not None:\n            contract["chapter_cue"] = chapter_cue', assembly)

    def test_genre_and_favorites_remain_selected_and_custom_audio_has_no_dead_heart(self) -> None:
        panel = (NATIVE / "OwnerProductionFlowPanel.swift").read_text(encoding="utf-8")
        self.assertIn('if !availableGenres.contains(selectedGenre) {\n            selectedGenre = "Все"\n        }', panel)
        self.assertNotIn("let selectedGenres = loaded.options.first", panel)
        self.assertIn('if option.origin == "APPLE_GARAGEBAND_DIGITAL_MATERIAL" {', panel)
        self.assertIn('Image(systemName: (option.isFavorite ?? false) ? "heart.fill" : "heart")', panel)
        self.assertIn('if selectedGenre == "Избранное" { return status.options.filter', panel)

    def test_opening_credit_has_first_syllable_stress(self) -> None:
        identity = (ROOT / "dilon_identity.py").read_text(encoding="utf-8")
        self.assertIn('OPENING_CREDIT_TEXT = "Елена Ди́лон.', identity)


if __name__ == "__main__":
    unittest.main()
