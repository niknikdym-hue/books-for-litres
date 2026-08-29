from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "native" / "DilonNativeFlowController.swift"
BUILD = ROOT / "native" / "build_native_app.sh"


def test_dilon_native_flow_controller_is_exact_identity_offline_only() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")

    assert '"--snapshot"' in source
    assert '"--approve-candidate"' in source
    assert '"--decision", "APPROVE"' in source
    assert '"--listened-audio-sha256"' in source
    assert '"--listened-path-identity"' in source
    assert '"--listened-synthesis-fingerprint"' in source
    assert "player.state == .finished" in source
    assert "player.validateLoadedIdentity(rehash: true)" in source
    assert 'binding.role == "dilon-opening-credit-review"' in source
    assert "binding.audioSHA256 == candidate.audioSHA256" in source
    assert "binding.pathIdentity == candidate.pathIdentity" in source
    assert "binding.synthesisFingerprint == candidate.synthesisFingerprint" in source
    assert "providerRequests == 0" in source
    assert "!remoteRequestSent" in source
    assert "!paidExecution" in source
    assert "!billingChanged" in source

    forbidden = (
        "--execute-yandex-chapter-plan",
        "--execute-paid-plan",
        "--run-yandex-demo",
        "--run-openai",
        "credential",
    )
    for token in forbidden:
        assert token not in source


def test_selection_generation_clears_stale_dilon_playback_and_state() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")

    assert "selectionGeneration &+= 1" in source
    assert "selectedCandidateID = nil" in source
    assert "snapshot = nil" in source
    assert "player.clear()" in source
    assert "selectionGeneration == expectedGeneration" in source
    assert "activeBookName == expectedBookName" in source
    assert "activeJobID == expectedJobID" in source


def test_unicode_book_selection_is_resolved_by_accepted_snapshot_bridge() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")

    # The controller sends the selected Book Library name to the accepted
    # snapshot runner, then uses the canonical book_slug returned by that
    # bridge for approval. It never ASCII-normalizes the native selection.
    assert 'arguments: ["--snapshot", "--book", bookName, "--job", jobID]' in source
    assert "let expectedBookSlug = currentSnapshot.bookSlug" in source
    assert '"--book", expectedBookSlug' in source
    assert "normalize_slug" not in source
    assert "lowercased()" not in source


def test_native_build_compiles_flow_controller_before_card_and_app() -> None:
    source = BUILD.read_text(encoding="utf-8")
    controller = source.index('"$script_dir/DilonNativeFlowController.swift"')
    card = source.index('"$script_dir/DilonNativeCard.swift"')
    app = source.index('"$script_dir/AudiobookStudioApp.swift"')

    assert controller < card < app
