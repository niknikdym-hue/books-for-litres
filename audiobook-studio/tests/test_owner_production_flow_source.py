from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"


class OwnerProductionFlowSourceTests(unittest.TestCase):
    def test_main_flow_is_author_first_and_costs_are_moved_out(self) -> None:
        app = (NATIVE / "AudiobookStudioApp.swift").read_text(encoding="utf-8")
        panel = (NATIVE / "OwnerProductionFlowPanel.swift").read_text(encoding="utf-8")
        self.assertIn("OwnerProductionFlowPanel(model: model, selectedBookID: book.id)", app)
        self.assertNotIn('Section("Расходы и лимиты") {\n                            Label("Локальный движок', app)
        self.assertIn('Section("Расходы и лимиты")', app)
        self.assertIn('Section("4. Диктор")', app)
        self.assertIn('Section("5. Глава для записи")', app)
        self.assertIn('Section("6. Прослушивание и приёмка")', app)
        self.assertIn('Section("Путь к готовой аудиокниге")', panel)
        for label in (
            "1. Текст для озвучки",
            "2. Ударения и произношение",
            "3. Звук перед главами — по желанию автора",
            "Елена Ди́лон",
            "ДИлон",
            "Добавлять короткий звук перед каждой главой",
            "Выбор хранится отдельно для каждой книги",
        ):
            self.assertIn(label, panel)

    def test_chapter_assembly_binds_selected_cue_into_identity_and_output(self) -> None:
        assembly = (ROOT / "chapter_assembly.py").read_text(encoding="utf-8")
        self.assertIn("from book_sound_design import chapter_cue_for_book", assembly)
        self.assertIn('"chapter_cue": chapter_cue', assembly)
        self.assertIn('segment_id": "__chapter_cue__"', assembly)
        self.assertIn("chapter_cue_then_speech_v1", assembly)
        self.assertIn("chapter_cue_changed_during_assembly", assembly)

    def test_opening_credit_has_first_syllable_stress(self) -> None:
        identity = (ROOT / "dilon_identity.py").read_text(encoding="utf-8")
        self.assertIn('OPENING_CREDIT_TEXT = "Елена Ди́лон.', identity)


if __name__ == "__main__":
    unittest.main()
