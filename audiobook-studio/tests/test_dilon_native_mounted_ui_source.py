from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "native" / "AudiobookStudioApp.swift"
CARD = ROOT / "native" / "DilonNativeCard.swift"
CONTROLLER = ROOT / "native" / "DilonNativeFlowController.swift"


class DilonNativeMountedUISourceTests(unittest.TestCase):
    def test_studio_view_owns_and_mounts_dilon_flow(self) -> None:
        source = APP.read_text(encoding="utf-8")

        self.assertIn("@StateObject private var dilonFlow = DilonNativeFlowController()", source)
        self.assertIn("DilonNativeCard(", source)
        self.assertIn("snapshot: snapshot", source)
        self.assertIn("player: model.audioPlayer", source)
        self.assertIn("selectedCandidateID: $dilonFlow.selectedCandidateID", source)
        self.assertIn("dilonFlow.approveListenedCandidate(candidate, player: model.audioPlayer)", source)

    def test_mounted_flow_tracks_exact_book_job_selection(self) -> None:
        source = APP.read_text(encoding="utf-8")

        self.assertIn("private var dilonSelectionKey: String", source)
        self.assertIn(".task(id: dilonSelectionKey)", source)
        self.assertIn("book.kind == \"production\"", source)
        self.assertIn("job.kind == \"chapter\"", source)
        self.assertIn("bookName: book.id", source)
        self.assertIn("jobID: job.id", source)
        self.assertIn("bookName: \"\"", source)
        self.assertIn("jobID: \"\"", source)

    def test_mounted_ui_exposes_no_new_provider_or_paid_dilon_action(self) -> None:
        app_source = APP.read_text(encoding="utf-8")
        card_source = CARD.read_text(encoding="utf-8")
        controller_source = CONTROLLER.read_text(encoding="utf-8")

        mounted_start = app_source.index("DilonNativeCard(")
        mounted_end = app_source.index("if model.engine == .qwen", mounted_start)
        mounted = app_source[mounted_start:mounted_end]

        for token in (
            "execute-yandex",
            "execute-paid",
            "synthesize",
            "credential",
            "signature",
            "music",
        ):
            self.assertNotIn(token, mounted.lower())

        self.assertNotIn("--execute-yandex-chapter-plan", controller_source)
        self.assertNotIn("--execute-paid-plan", controller_source)
        self.assertIn("wholeBookReleaseReady", card_source)
        self.assertIn("Whole-book release остаётся заблокирован", card_source)


if __name__ == "__main__":
    unittest.main()
