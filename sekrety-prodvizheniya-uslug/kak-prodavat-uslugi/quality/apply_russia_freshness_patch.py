#!/usr/bin/env python3
"""One-time exact Russia freshness correction for Chapter 8.

Fail closed: the old sentence must occur exactly once; after replacement the
permanent BOOK_PROSE gate must pass locally with zero BLOCK/WARN.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CHAPTER = ROOT / "sekrety-prodvizheniya-uslug" / "kak-prodavat-uslugi" / "manuscript" / "08-tsena-obem-i-risk.md"
GATE = ROOT / "sekrety-prodvizheniya-uslug" / "kak-prodavat-uslugi" / "quality" / "book_prose_gate.py"

OLD = "Самозанятый после получения оплаты формирует и передаёт заказчику чек по правилам НПД."
NEW = (
    "Плательщик НПД при расчётах обязан сформировать чек и обеспечить его передачу "
    "покупателю (заказчику) в срок, установленный статьёй 14 Закона № 422-ФЗ; "
    "конкретный срок зависит от формы расчёта."
)


def main() -> int:
    text = CHAPTER.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise RuntimeError(f"Expected exactly one NPD sentence, found {count}")
    CHAPTER.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    subprocess.run(["python", str(GATE)], cwd=ROOT, check=True)
    print("Russia freshness patch applied; BOOK_PROSE remains clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
