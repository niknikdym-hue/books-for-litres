#!/usr/bin/env python3
"""Offline BOOK_PROSE quality gate for «Как продавать услуги».

This gate intentionally uses the repository's canonical Content Quality Lexicon.
It performs no provider/model/network/paid calls.

Policy:
- every expected manuscript chapter must exist and no unexpected .md chapter may appear;
- SYSTEM/USER BLOCK findings fail the gate;
- WARN findings are emitted as GitHub annotations and remain mandatory editorial review;
- the shared mutable USER store is replaced by an empty temporary store in CI so
  repository results are deterministic and do not depend on a runner's home dir.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_ROOT = REPO_ROOT / "audiobook-studio"
BOOK_ROOT = REPO_ROOT / "sekrety-prodvizheniya-uslug" / "kak-prodavat-uslugi"
MANUSCRIPT_ROOT = BOOK_ROOT / "manuscript"

sys.path.insert(0, str(STUDIO_ROOT))

from content_quality_lexicon import (  # noqa: E402
    PROFILE_BOOK_PROSE,
    ContentQualityLexicon,
)


EXPECTED_CHAPTERS = (
    "01-pochemu-horoshuyu-uslugu-trudno-kupit.md",
    "02-chto-klient-dolzhen-reshitsya-kupit.md",
    "03-dokazatelstva-vmesto-uvereniy.md",
    "04-pokazat-rabotu-do-nachala-raboty.md",
    "05-diagnoz-do-predlozheniya.md",
    "06-kogda-horoshaya-prodazha-zakanchivaetsya-otkazom.md",
    "07-kommercheskoe-predlozhenie-kak-dokument-resheniya.md",
    "08-tsena-obem-i-risk.md",
    "09-ya-podumayu-eto-ne-odno-vozrazhenie.md",
    "10-pochemu-vy-proigrali-sdelku.md",
)


def github_annotation(kind: str, path: Path, finding: dict[str, object]) -> None:
    relative = path.relative_to(REPO_ROOT).as_posix()
    line = int(finding.get("line") or 1)
    column = int(finding.get("column") or 1)
    rule_id = str(finding.get("rule_id") or "CONTENT_QUALITY")
    matched = str(finding.get("matched_text") or "").replace("\n", " ").strip()
    rationale = str(finding.get("rationale") or "").replace("\n", " ").strip()
    message = f"{rule_id}: {matched}"
    if rationale:
        message += f" — {rationale}"
    print(f"::{kind} file={relative},line={line},col={column},title={rule_id}::{message}")


def validate_chapter_inventory() -> list[Path]:
    actual = tuple(sorted(path.name for path in MANUSCRIPT_ROOT.glob("*.md")))
    expected = tuple(sorted(EXPECTED_CHAPTERS))
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        print("BOOK_PROSE inventory mismatch", file=sys.stderr)
        if missing:
            print(f"missing={missing}", file=sys.stderr)
        if unexpected:
            print(f"unexpected={unexpected}", file=sys.stderr)
        raise SystemExit(2)
    return [MANUSCRIPT_ROOT / name for name in EXPECTED_CHAPTERS]


def main() -> int:
    chapters = validate_chapter_inventory()

    aggregate: list[dict[str, object]] = []
    blocking_count = 0
    warning_count = 0

    with tempfile.TemporaryDirectory(prefix="book-prose-lexicon-") as temporary:
        lexicon = ContentQualityLexicon(
            user_store_path=Path(temporary) / "empty-user-rules-v1.json"
        )
        status = lexicon.status()
        print(
            "BOOK_PROSE lexicon "
            f"core_sha256={status['core_pack_sha256']} "
            f"fingerprint={status['lexicon_fingerprint']}"
        )

        for path in chapters:
            text = path.read_text(encoding="utf-8")
            scan = lexicon.scan(text, profile=PROFILE_BOOK_PROSE)
            blocks = list(scan["blocking_findings"])
            warnings = list(scan["warning_findings"])
            blocking_count += len(blocks)
            warning_count += len(warnings)

            for finding in blocks:
                github_annotation("error", path, finding)
            for finding in warnings:
                github_annotation("warning", path, finding)

            aggregate.append(
                {
                    "chapter": path.name,
                    "state": scan["state"],
                    "text_sha256": scan["text_sha256"],
                    "blocks": len(blocks),
                    "warnings": len(warnings),
                }
            )

    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    print(
        f"BOOK_PROSE summary chapters={len(chapters)} "
        f"blocks={blocking_count} warnings={warning_count}"
    )

    if blocking_count:
        print("BOOK_PROSE GATE: BLOCKED", file=sys.stderr)
        return 1

    print("BOOK_PROSE GATE: PASS_WITH_WARNINGS" if warning_count else "BOOK_PROSE GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
