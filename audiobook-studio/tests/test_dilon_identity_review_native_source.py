from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "native" / "DilonNativeCard.swift"
CONTROLLER = ROOT / "native" / "DilonIdentityReviewController.swift"
BUILD = ROOT / "native" / "build_native_app.sh"


class DilonIdentityReviewNativeSourceTests(unittest.TestCase):
    def test_controller_requires_finished_rehashed_exact_identity_binding(self) -> None:
        source = CONTROLLER.read_text(encoding="utf-8")
        for token in (
            "player.state == .finished",
            "player.validateLoadedIdentity(rehash: true)",
            'binding.role == "dilon-identity-preview"',
            "binding.bookSlug == snapshot.bookSlug",
            "binding.jobID == snapshot.jobID",
            'binding.segmentID == "identity-preview"',
            "binding.audioSHA256 == preview.audioSHA256",
            "binding.pathIdentity == preview.pathIdentity",
            "binding.synthesisFingerprint == preview.buildIdentity",
            '"--listened-build-identity", binding.synthesisFingerprint',
            '"--listened-audio-sha256", binding.audioSHA256',
            '"--listened-path-identity", binding.pathIdentity',
        ):
            self.assertIn(token, source)

    def test_card_unlocks_final_approval_only_after_full_exact_playback(self) -> None:
        source = CARD.read_text(encoding="utf-8")
        for token in (
            "private func fullyListenedIdentity",
            "player.completedExactPlayback",
            'binding.role == "dilon-identity-preview"',
            "binding.audioSHA256 == preview.audioSHA256",
            "binding.pathIdentity == preview.pathIdentity",
            "binding.synthesisFingerprint == preview.buildIdentity",
            'Button("Подтвердить финальную версию")',
            "snapshot.dilonStatus.technicalReady != true",
            "!fullyListenedIdentity(preview)",
            "identityReview.approveListenedIdentity",
        ):
            self.assertIn(token, source)
        self.assertNotIn("automaticReviewApproval = true", source)

    def test_selection_change_reloads_review_for_exact_current_build(self) -> None:
        source = CARD.read_text(encoding="utf-8")
        self.assertIn("identityReviewKey", source)
        self.assertIn("snapshot.identityPreview?.buildIdentity", source)
        self.assertIn("identityReview.selectionDidChange", source)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("selectionGeneration &+= 1", controller)
        self.assertIn("guard selectionGeneration == expectedGeneration", controller)

    def test_native_build_compiles_identity_review_controller(self) -> None:
        source = BUILD.read_text(encoding="utf-8")
        self.assertIn('"$script_dir/DilonIdentityReviewController.swift"', source)

    def test_final_review_surface_has_no_provider_or_paid_execution_command(self) -> None:
        controller = CONTROLLER.read_text(encoding="utf-8")
        forbidden = (
            "--execute-authorized",
            "--run-yandex",
            "--execute-yandex",
            "--run-openai",
            "--execute-paid-plan",
            "owner-authorized",
        )
        for token in forbidden:
            self.assertNotIn(token, controller)


if __name__ == "__main__":
    unittest.main()
