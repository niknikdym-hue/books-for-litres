"""Exact pre-synthesis technical Content Quality gate for Audiobook Studio.

Shared editorial anti-junk rules are an owner-invoked advisory review in Studio.
They must not silently become a provider blocker just because the shared BOOK OS
user lexicon changed. The mandatory execution gate therefore revalidates only
exact prepared text identity, the vendored TTS-technical contract, and any exact
technical human resolutions that were relied upon during preparation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from content_quality_lexicon import (
    PROFILE_AUDIOBOOK_TTS_TECHNICAL,
    ContentQualityError,
    ContentQualityLexicon,
    ContentQualityResolutionStore,
    sha256_file,
)
from preparation_contract import CONTENT_QUALITY_GATE_VERSION


class ContentQualityGateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _blocked(code: str, message: str) -> ContentQualityGateError:
    return ContentQualityGateError(code, message)


def _technical_evidence(evidence: Mapping[str, Any], normalized_sha: str) -> Mapping[str, Any]:
    technical = evidence.get("technical")
    if not isinstance(technical, Mapping):
        raise _blocked("content_quality_technical_evidence_missing", "Prepared TTS technical evidence is missing.")
    if (
        technical.get("profile") != PROFILE_AUDIOBOOK_TTS_TECHNICAL
        or technical.get("text_sha256") != normalized_sha
        or technical.get("state") not in {"PASS", "WARN"}
    ):
        raise _blocked(
            "content_quality_technical_evidence_invalid",
            "Prepared TTS technical evidence is not safe for provider execution.",
        )
    return technical


def _revalidate_technical_contract(
    *,
    engine: ContentQualityLexicon,
    technical: Mapping[str, Any],
    workspace_root: Path,
    book_slug: str,
    normalized_sha: str,
) -> None:
    embedded = technical.get("evidence")
    if not isinstance(embedded, Mapping):
        raise _blocked("content_quality_technical_evidence_invalid", "TTS technical contract evidence is missing.")
    expected_schema = embedded.get("schema_sha256")
    expected_pack = embedded.get("technical_pack_sha256")
    if not isinstance(expected_schema, str) or not isinstance(expected_pack, str):
        raise _blocked("content_quality_technical_evidence_invalid", "TTS technical contract hashes are missing.")
    if sha256_file(engine.schema_path) != expected_schema or sha256_file(engine.technical_path) != expected_pack:
        raise _blocked(
            "content_quality_technical_contract_changed",
            "TTS technical rules changed after preparation; prepare the text again.",
        )

    resolved = technical.get("resolved_findings")
    if not isinstance(resolved, list):
        raise _blocked("content_quality_technical_evidence_invalid", "TTS technical resolution evidence is malformed.")
    if not resolved:
        return
    try:
        current = ContentQualityResolutionStore(workspace_root, book_slug).applicable(
            profile=PROFILE_AUDIOBOOK_TTS_TECHNICAL,
            text_sha256=normalized_sha,
        )
    except ContentQualityError as error:
        raise _blocked(error.code, error.message) from error
    for finding in resolved:
        if not isinstance(finding, Mapping):
            raise _blocked("content_quality_technical_evidence_invalid", "Resolved TTS finding is malformed.")
        rule_id = finding.get("rule_id")
        resolution_id = finding.get("resolution_id")
        current_resolution = current.get(str(rule_id)) if isinstance(rule_id, str) else None
        if (
            not isinstance(current_resolution, Mapping)
            or current_resolution.get("resolution_id") != resolution_id
            or current_resolution.get("text_sha256") != normalized_sha
            or current_resolution.get("actor") != "OWNER"
        ):
            raise _blocked(
                "content_quality_technical_resolution_stale",
                "A TTS technical exception used during preparation is no longer current.",
            )


def validate_prepared_content_quality(
    *,
    library: Any,
    workspace_root: Path,
    book_name: str,
    lexicon: ContentQualityLexicon | None = None,
) -> dict[str, Any]:
    """Fail closed on exact text/TTS technical drift, never on editorial lexicon drift.

    The function performs no provider/model/billing operation. Existing historical
    audio remains untouched; this gate controls only eligibility for a new
    provider/model execution or plan.
    """
    engine = lexicon or ContentQualityLexicon()
    try:
        profile_path = library.resolve_book_profile(book_name)
        book = library.load_book_profile(profile_path.name)
    except Exception as error:
        raise _blocked("content_quality_book_invalid", "Book profile cannot be validated for Content Quality.") from error

    preparation = book.get("preparation") if isinstance(book.get("preparation"), dict) else None
    if not isinstance(preparation, dict) or preparation.get("status") != "READY":
        raise _blocked("content_quality_preparation_missing", "READY text preparation is required before synthesis.")
    if preparation.get("content_quality_gate_version") != CONTENT_QUALITY_GATE_VERSION:
        raise _blocked(
            "content_quality_gate_missing_or_stale",
            "Text preparation predates the current Content Quality gate; prepare the text again.",
        )
    expected_path = preparation.get("content_quality_evidence_path")
    expected_sha = preparation.get("content_quality_evidence_sha256")
    expected_fingerprint = preparation.get("content_quality_gate_fingerprint")
    normalized_sha = preparation.get("normalized_sha256")
    working_sha = preparation.get("working_copy_sha256")
    if not all(isinstance(value, str) and value for value in (
        expected_path, expected_sha, expected_fingerprint, normalized_sha, working_sha
    )):
        raise _blocked("content_quality_evidence_missing", "Prepared Content Quality evidence is incomplete.")

    try:
        evidence_path = library.resolve_book_asset(profile_path.name, expected_path)
        working = book.get("tts_working_copy") if isinstance(book.get("tts_working_copy"), dict) else {}
        working_path = library.resolve_book_asset(profile_path.name, working.get("path"))
        normalized_path = library.resolve_book_asset(profile_path.name, preparation.get("normalized_path"))
    except Exception as error:
        raise _blocked("content_quality_evidence_path_invalid", "Content Quality evidence paths are invalid.") from error
    if (
        evidence_path.is_symlink()
        or working_path.is_symlink()
        or normalized_path.is_symlink()
        or not evidence_path.is_file()
        or not working_path.is_file()
        or not normalized_path.is_file()
    ):
        raise _blocked("content_quality_evidence_missing", "Content Quality evidence or exact text identity is missing.")
    if sha256_file(evidence_path) != expected_sha:
        raise _blocked("content_quality_evidence_tampered", "Content Quality evidence hash no longer matches.")
    if sha256_file(working_path) != working_sha or sha256_file(normalized_path) != normalized_sha:
        raise _blocked("content_quality_text_identity_stale", "Prepared text identity changed after Content Quality review.")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _blocked("content_quality_evidence_invalid", "Content Quality evidence is unreadable.") from error
    if not isinstance(evidence, Mapping):
        raise _blocked("content_quality_evidence_invalid", "Content Quality evidence has an invalid shape.")
    if (
        evidence.get("schema_version") != 1
        or evidence.get("gate_version") != CONTENT_QUALITY_GATE_VERSION
        or evidence.get("book_slug") != profile_path.stem
        or evidence.get("working_copy_sha256") != working_sha
        or evidence.get("normalized_sha256") != normalized_sha
        or evidence.get("gate_fingerprint") != expected_fingerprint
        or evidence.get("state") not in {"PASS", "WARN"}
    ):
        raise _blocked("content_quality_evidence_invalid", "Prepared Content Quality evidence is not current/canonical.")

    technical = _technical_evidence(evidence, normalized_sha)
    _revalidate_technical_contract(
        engine=engine,
        technical=technical,
        workspace_root=Path(workspace_root),
        book_slug=profile_path.stem,
        normalized_sha=normalized_sha,
    )

    return {
        "schema_version": 1,
        "state": str(technical["state"]),
        "book_slug": profile_path.stem,
        "working_copy_sha256": working_sha,
        "normalized_sha256": normalized_sha,
        "gate_version": CONTENT_QUALITY_GATE_VERSION,
        # Keep the preparation-bound identity stable; editorial user-store changes
        # are intentionally not re-bound into the mandatory provider gate.
        "gate_fingerprint": expected_fingerprint,
        "evidence_path": str(evidence_path),
        "evidence_sha256": expected_sha,
        "editorial_policy": "MANUAL_ADVISORY",
        "provider_requests": 0,
        "remote_request_sent": False,
        "model_calls": 0,
        "paid_execution": False,
        "billing_changed": False,
    }
