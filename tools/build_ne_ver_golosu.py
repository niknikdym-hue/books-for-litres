#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Pt

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "ne-ver-golosu"
MANUSCRIPT = BOOK / "manuscript"
DIST = BOOK / "dist"
DIST.mkdir(parents=True, exist_ok=True)

ORDER = [
    "00-PROLOG.md", "01-VOICE.md", "02-FACE.md", "03-MESSAGES.md",
    "04-EVIDENCE.md", "05-DECISION.md", "06-SECRECY.md", "07-KNOWLEDGE.md",
    "08-EXIT-CHANNEL.md", "09-RISK.md", "10-FAMILY.md", "11-BUSINESS.md",
    "12-DETECTORS-PROVENANCE.md", "13-DIGITAL-DOUBLE.md",
    "14-LIARS-DIVIDEND.md", "15-CONCLUSION.md", "16-APPENDICES.md", "17-SOURCES.md",
]

BANNED = [
    "мы живём в эпоху", "мы живем в эпоху", "важно понимать", "следует отметить",
    "в современном мире", "страшно подумать", "зловещая технология",
    "никому нельзя верить", "искусственный интеллект навсегда изменил всё",
    "искусственный интеллект навсегда изменил все",
]
OPEN_MARKERS = ["TODO", "VERIFY", "SOURCE?", "FIXME", "TBD"]


def strip_md_inline(s: str) -> str:
    # Preserve human-readable wording; remove only Markdown formatting markup.
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r"\1 (\2)", s)
    # The arrow is visually useful in Markdown but unnecessarily exotic in upload DOCX.
    s = s.replace("→", "—")
    return s.strip()


def add_inline_runs(paragraph, text: str):
    # Basic bold / italic support without introducing fields or hyperlinks.
    pattern = re.compile(r"(\*\*.+?\*\*|(?<!\*)\*[^*]+?\*(?!\*))")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        token = m.group(0)
        if token.startswith("**"):
            r = paragraph.add_run(token[2:-2])
            r.bold = True
        else:
            r = paragraph.add_run(token[1:-1])
            r.italic = True
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def parse_blocks(text: str):
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = []
    buf = []

    def flush():
        nonlocal buf
        if buf:
            txt = " ".join(x.strip() for x in buf if x.strip()).strip()
            if txt:
                blocks.append(("p", txt))
            buf = []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush()
            blocks.append((f"h{len(m.group(1))}", m.group(2).strip()))
            continue
        if re.match(r"^---+$", line.strip()):
            flush()
            continue
        if line.startswith("> "):
            flush()
            blocks.append(("quote", line[2:].strip()))
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            flush()
            blocks.append(("bullet", m.group(1).strip()))
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            flush()
            blocks.append(("number", m.group(2).strip()))
            continue
        buf.append(line)
    flush()
    return blocks


def build_docx(texts: list[tuple[str, str]]) -> Path:
    doc = Document()
    sec = doc.sections[0]
    # No headers/footers/page numbers/page breaks: LitRes reflows content itself.
    sec.header.is_linked_to_previous = True
    sec.footer.is_linked_to_previous = True

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    for name in ["Heading 1", "Heading 2", "Heading 3", "Heading 4"]:
        st = styles[name]
        st.font.name = "Times New Roman"
        st._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")

    styles["Heading 1"].font.size = Pt(18)
    styles["Heading 2"].font.size = Pt(15)
    styles["Heading 3"].font.size = Pt(13)
    styles["Heading 4"].font.size = Pt(12)

    for filename, text in texts:
        for kind, raw in parse_blocks(text):
            if kind.startswith("h"):
                level = min(int(kind[1]), 4)
                p = doc.add_paragraph(style=f"Heading {level}")
                add_inline_runs(p, raw)
            elif kind == "quote":
                p = doc.add_paragraph(style="Quote")
                add_inline_runs(p, raw)
            elif kind == "bullet":
                p = doc.add_paragraph(style="List Bullet")
                add_inline_runs(p, raw)
            elif kind == "number":
                p = doc.add_paragraph(style="List Number")
                add_inline_runs(p, raw)
            else:
                p = doc.add_paragraph()
                add_inline_runs(p, raw)

    out = DIST / "ne-ver-golosu-litres.docx"
    doc.core_properties.author = ""
    doc.core_properties.title = ""
    doc.core_properties.subject = ""
    doc.core_properties.keywords = ""
    doc.save(out)
    return out


def normalized_plain(text: str) -> str:
    text = re.sub(r"^#{1,4}\s+.*$", "", text, flags=re.M)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`>#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def quality_report(texts: list[tuple[str, str]], docx_path: Path) -> str:
    rows = []
    combined = []
    paragraph_locations = defaultdict(list)
    lower_all = ""

    for filename, text in texts:
        plain = normalized_plain(text)
        chars = len(plain)
        chars_ws = len(re.sub(r"\s", "", plain))
        words = len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]+(?:[-’'][A-Za-zА-Яа-яЁё0-9]+)?", plain))
        rows.append((filename, chars, words))
        combined.append(plain)
        lower_all += "\n" + plain.lower()
        for kind, p in parse_blocks(text):
            if kind == "p":
                n = re.sub(r"\s+", " ", strip_md_inline(p).lower()).strip()
                if len(n) >= 100:
                    paragraph_locations[n].append(filename)

    combined_text = "\n".join(combined)
    total_chars = len(combined_text)
    total_words = len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]+(?:[-’'][A-Za-zА-Яа-яЁё0-9]+)?", combined_text))
    author_sheets = total_chars / 40000.0
    duplicates = [(p, locs) for p, locs in paragraph_locations.items() if len(locs) > 1]

    banned_hits = {p: lower_all.count(p) for p in BANNED if lower_all.count(p)}
    marker_hits = {m: combined_text.count(m) for m in OPEN_MARKERS if combined_text.count(m)}

    phrase_watch = [
        "не нужно", "нужно", "важно", "представьте", "главная мысль",
        "в этом и", "это не", "поэтому", "другими словами", "на самом деле",
        "не потому", "именно поэтому", "стоит запомнить",
    ]
    phrase_counts = {p: lower_all.count(p) for p in phrase_watch}

    # Exact repeated sentences of meaningful length.
    sent_map = defaultdict(list)
    for filename, text in texts:
        plain = normalized_plain(text)
        for s in re.split(r"(?<=[.!?])\s+", plain):
            n = re.sub(r"\s+", " ", s.strip().lower())
            if len(n) >= 90:
                sent_map[n].append(filename)
    repeated_sentences = [(s, locs) for s, locs in sent_map.items() if len(set(locs)) > 1]

    report = []
    report.append("# QUALITY REPORT — «НЕ ВЕРЬ ГОЛОСУ»")
    report.append("")
    report.append("Автоматическая проверка дополняет, но не заменяет содержательную редактуру.")
    report.append("")
    report.append(f"- Общий объём текста: **{total_chars:,} знаков с пробелами**".replace(",", " "))
    report.append(f"- Ориентировочный объём: **{author_sheets:.2f} авторского листа**")
    report.append(f"- Слов: **{total_words:,}**".replace(",", " "))
    report.append(f"- DOCX: `{docx_path.relative_to(ROOT)}`")
    report.append("")
    report.append("## Объём по файлам")
    report.append("")
    report.append("| Файл | Знаков | Слов |")
    report.append("|---|---:|---:|")
    for filename, chars, words in rows:
        report.append(f"| {filename} | {chars} | {words} |")

    report.append("")
    report.append("## Gate")
    report.append("")
    report.append(f"- Незакрытые TODO/VERIFY/SOURCE markers: **{marker_hits or 'нет'}**")
    report.append(f"- Запрещённые шаблонные формулы: **{banned_hits or 'нет'}**")
    report.append(f"- Точные дубли длинных абзацев между файлами: **{len(duplicates)}**")
    report.append(f"- Точные дубли длинных предложений между файлами: **{len(repeated_sentences)}**")
    report.append("")
    report.append("## Частотные контрольные обороты")
    report.append("")
    for p, c in phrase_counts.items():
        report.append(f"- `{p}`: {c}")

    if duplicates:
        report.append("")
        report.append("## Дубли абзацев — проверить вручную")
        for p, locs in duplicates[:20]:
            report.append(f"- {locs}: {p[:220]}…")

    if repeated_sentences:
        report.append("")
        report.append("## Дубли предложений — проверить вручную")
        for s, locs in repeated_sentences[:20]:
            report.append(f"- {locs}: {s[:220]}…")

    report.append("")
    report.append("## Автоматический вердикт")
    problems = []
    if marker_hits:
        problems.append("есть незакрытые редакционные маркеры")
    if banned_hits:
        problems.append("есть запрещённые шаблонные обороты")
    if duplicates:
        problems.append("есть точные дубли длинных абзацев")
    if total_chars < 120000:
        problems.append("объём выглядит как короткая книга/лонгрид — требуется редакторская оценка")
    if problems:
        report.append("**REVIEW REQUIRED:** " + "; ".join(problems) + ".")
    else:
        report.append("**AUTOMATED GATE PASS.** Финальный статус всё равно требует ручного фактчека, литературной редактуры и render-QA DOCX.")

    return "\n".join(report) + "\n"


def main():
    texts = []
    missing = []
    for name in ORDER:
        path = MANUSCRIPT / name
        if not path.exists():
            missing.append(str(path))
            continue
        texts.append((name, path.read_text(encoding="utf-8")))
    if missing:
        raise SystemExit("Missing manuscript files:\n" + "\n".join(missing))

    docx = build_docx(texts)
    report = quality_report(texts, docx)
    (DIST / "quality-report.md").write_text(report, encoding="utf-8")

    manifest = {
        "manuscript_files": ORDER,
        "docx": str(docx.relative_to(ROOT)),
        "quality_report": str((DIST / "quality-report.md").relative_to(ROOT)),
    }
    (DIST / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report)

if __name__ == "__main__":
    main()
