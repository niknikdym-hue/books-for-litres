from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "native" / "DilonNativeFlowController.swift"
BUILD = ROOT / "native" / "build_native_app.sh"


class DilonNativeFlowControllerSourceTests(unittest.TestCase):
    def test_dilon_native_flow_controller_is_exact_identity_offline_only(self) -> None:
        source = CONTROLLER.read_text(encoding="utf-8")

        self.assertIn('"--snapshot"', source)
        self.assertIn('"--approve-candidate"', source)
        self.assertIn('"--decision", "APPROVE"', source)
        self.assertIn('"--listened-audio-sha256"', source)
        self.assertIn('"--listened-path-identity"', source)
        self.assertIn('"--listened-synthesis-fingerprint"', source)
        self.assertIn("player.state == .finished", source)
        self.assertIn("player.validateLoadedIdentity(rehash: true)", source)
        self.assertIn('binding.role == "dilon-opening-credit-review"', source)
        self.assertIn("binding.audioSHA256 == candidate.audioSHA256", source)
        self.assertIn("binding.pathIdentity == candidate.pathIdentity", source)
        self.assertIn("binding.synthesisFingerprint == candidate.synthesisFingerprint", source)
        self.assertIn("providerRequests == 0", source)
        self.assertIn("!remoteRequestSent", source)
        self.assertIn("!paidExecution", source)
        self.assertIn("!billingChanged", source)

        forbidden = (
            "--execute-yandex-chapter-plan",
            "--execute-paid-plan",
            "--run-yandex-demo",
            "--run-openai",
            "credential",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_approval_mutation_cannot_race_native_selection_change(self) -> None:
        source = CONTROLLER.read_text(encoding="utf-8")

        approval = source.index("func approveListenedCandidate")
        sync_bridge = source.index("try runJSONSync", approval)
        refresh_task = source.index("Task {", sync_bridge)

        self.assertLess(sync_bridge, refresh_task)
        self.assertIn("blocking UI selection events during this bounded call", source)
        pre_refresh = source[approval:refresh_task]
        self.assertIn("selectionGeneration == expectedGeneration", pre_refresh)
        self.assertIn("activeBookName == expectedBookName", pre_refresh)
        self.assertIn("activeJobID == expectedJobID", pre_refresh)

    def test_selection_generation_clears_stale_dilon_playback_and_state(self) -> None:
        source = CONTROLLER.read_text(encoding="utf-8")

        self.assertIn("selectionGeneration &+= 1", source)
        self.assertIn("selectedCandidateID = nil", source)
        self.assertIn("snapshot = nil", source)
        self.assertIn("player.clear()", source)
        self.assertIn("selectionGeneration == expectedGeneration", source)
        self.assertIn("activeBookName == expectedBookName", source)
        self.assertIn("activeJobID == expectedJobID", source)

    def test_unicode_book_selection_is_resolved_by_accepted_snapshot_bridge(self) -> None:
        source = CONTROLLER.read_text(encoding="utf-8")

        # The controller sends the selected Book Library name to the accepted
        # snapshot runner, then uses the canonical book_slug returned by that
        # bridge for approval. It never ASCII-normalizes the native selection.
        self.assertIn(
            'arguments: ["--snapshot", "--book", bookName, "--job", jobID]',
            source,
        )
        self.assertIn("let expectedBookSlug = currentSnapshot.bookSlug", source)
        self.assertIn('"--book", expectedBookSlug', source)
        self.assertNotIn("normalize_slug", source)
        self.assertNotIn("lowercased()", source)

    def test_native_build_compiles_flow_controller_before_card_and_app(self) -> None:
        source = BUILD.read_text(encoding="utf-8")
        controller = source.index('"$script_dir/DilonNativeFlowController.swift"')
        card = source.index('"$script_dir/DilonNativeCard.swift"')
        app = source.index('"$script_dir/AudiobookStudioApp.swift"')

        self.assertLess(controller, card)
        self.assertLess(card, app)


if __name__ == "__main__":
    unittest.main()
