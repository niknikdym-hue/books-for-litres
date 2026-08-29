from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DilonNativeCardSourceTests(unittest.TestCase):
    def test_native_card_enforces_exact_full_listening_before_approval(self) -> None:
        source = (ROOT / "native" / "DilonNativeCard.swift").read_text(encoding="utf-8")
        self.assertIn('player.state == .finished', source)
        self.assertIn('binding.role == "dilon-opening-credit-review"', source)
        self.assertIn('binding.audioSHA256 == candidate.audioSHA256', source)
        self.assertIn('binding.pathIdentity == candidate.pathIdentity', source)
        self.assertIn('binding.synthesisFingerprint == candidate.synthesisFingerprint', source)
        self.assertIn('.disabled(!fullyListened(candidate) || candidate.automaticStatus == "FAIL")', source)
        self.assertIn('onApproveListenedCandidate(candidate)', source)

    def test_identity_preview_is_exact_read_only_local_playback(self) -> None:
        source = (ROOT / "native" / "DilonNativeCard.swift").read_text(encoding="utf-8")
        self.assertIn('if let preview = snapshot.identityPreview, preview.readOnly', source)
        self.assertIn('audioSHA256: preview.audioSHA256', source)
        self.assertIn('pathIdentity: preview.pathIdentity', source)
        self.assertIn('synthesisFingerprint: preview.buildIdentity', source)
        self.assertIn('role: "dilon-identity-preview"', source)
        self.assertIn('player.loadAndPlay(identityBinding(preview))', source)

    def test_card_exposes_no_provider_or_paid_execution_action(self) -> None:
        source = (ROOT / "native" / "DilonNativeCard.swift").read_text(encoding="utf-8")
        self.assertNotIn('runBridgeJSON(', source)
        self.assertNotIn('Process(', source)
        self.assertNotIn('executePaid', source)
        self.assertNotIn('run-yandex', source)
        self.assertIn('!capabilities.providerExecutionAvailable', source)
        self.assertIn('!capabilities.paidExecutionAvailable', source)
        self.assertIn('!capabilities.automaticReviewApproval', source)
        self.assertIn('!wholeBookReleaseReady', source)

    def test_native_build_compiles_dilon_card(self) -> None:
        build = (ROOT / "native" / "build_native_app.sh").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/DilonNativeCard.swift"', build)
        self.assertLess(
            build.index('"$script_dir/DilonNativeCard.swift"'),
            build.index('"$script_dir/AudiobookStudioApp.swift"'),
        )


if __name__ == "__main__":
    unittest.main()
