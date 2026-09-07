#!/usr/bin/env python3
"""One-time exact editorial cleanup for Round-1 BOOK_PROSE warnings.

Fail closed:
- every old fragment must occur exactly once in its expected manuscript file;
- after replacement, canonical BOOK_PROSE must report zero BLOCK and zero WARN;
- no network/model/provider calls.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_ROOT = REPO_ROOT / "audiobook-studio"
BOOK_ROOT = REPO_ROOT / "sekrety-prodvizheniya-uslug" / "kak-prodavat-uslugi"
MANUSCRIPT = BOOK_ROOT / "manuscript"

sys.path.insert(0, str(STUDIO_ROOT))

from content_quality_lexicon import PROFILE_BOOK_PROSE, ContentQualityLexicon  # noqa: E402


REPLACEMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "01-pochemu-horoshuyu-uslugu-trudno-kupit.md": (
        (
            "Здесь вопрос уже не в качестве сторон по отдельности, а в качестве конкретной конфигурации обязательств.",
            "Здесь решающей становится конкретная конфигурация обязательств; качества сторон по отдельности для вывода недостаточно.",
        ),
        (
            "## Российские сделки различаются не культурой, а устройством решения",
            "## Российские сделки различаются прежде всего устройством решения",
        ),
    ),
    "02-chto-klient-dolzhen-reshitsya-kupit.md": (
        (
            "рекламный бюджет в стоимость не входил, а некоторые гипотезы требуют времени для проверки.",
            "рекламный бюджет оказался отдельной статьёй; некоторые гипотезы требуют времени для проверки.",
        ),
        (
            "Для нашей практики важно не превращать это в академический термин, а увидеть коммерческое следствие: **понятные действия исполнителя ещё не означают понятную покупку**.",
            "Для нашей практики важнее коммерческое следствие самого явления: **понятные действия исполнителя ещё не означают понятную покупку**.",
        ),
    ),
    "03-dokazatelstva-vmesto-uvereniy.md": (
        (
            "Одна презентация не обязана одинаково отвечать всем четырём.",
            "Разным участникам решения могут понадобиться разные подтверждения.",
        ),
    ),
    "04-pokazat-rabotu-do-nachala-raboty.md": (
        (
            "## Покупателю нужна не производственная кухня, а структура решений",
            "## Покупателю нужна структура будущих решений",
        ),
        (
            "Один процесс не обязан выглядеть одинаково на всех носителях.",
            "Один процесс естественно описывается по-разному на разных носителях.",
        ),
    ),
    "05-diagnoz-do-predlozheniya.md": (
        (
            "Специалист обладает знаниями, которых у клиента может не быть, а клиент знает собственную ситуацию, ограничения и внутренний контекст лучше внешнего исполнителя.",
            "Специалист обладает знаниями, которых у клиента может не быть. Клиент, в свою очередь, лучше внешнего исполнителя знает собственную ситуацию, ограничения и внутренний контекст.",
        ),
        (
            "За четыре месяца число входящих обращений почти не изменилось, а доля обращений, дошедших до коммерческого предложения, снизилась с привычного уровня.",
            "За четыре месяца число входящих обращений осталось примерно прежним. Доля обращений, дошедших до коммерческого предложения, при этом снизилась с привычного уровня.",
        ),
        (
            "Диагностическая встреча не обязана заканчиваться обещанием прислать коммерческое предложение к вечеру.",
            "Коммерческое предложение к вечеру — лишь один из возможных итогов диагностической встречи.",
        ),
    ),
    "06-kogda-horoshaya-prodazha-zakanchivaetsya-otkazom.md": (
        (
            "## Оценивайте не человека, а конфигурацию сделки",
            "## Оценивайте конфигурацию сделки",
        ),
        (
            "Профессиональная продажа не обязана превращать каждую понятую задачу в собственный контракт.",
            "Профессиональное решение иногда состоит в том, чтобы не брать понятую задачу в собственный контракт.",
        ),
    ),
    "07-kommercheskoe-predlozhenie-kak-dokument-resheniya.md": (
        (
            "Возьмите реальное предложение и проверьте его не по числу страниц, а по восьми вопросам.",
            "Возьмите реальное предложение и проверьте его по восьми вопросам, не связывая качество с числом страниц.",
        ),
        (
            "Финал файла должен отвечать не на вопрос «как сильнее подтолкнуть», а на вопрос «что покупателю нужно решить дальше».",
            "Финал файла должен ясно показывать, **что покупателю нужно решить дальше**.",
        ),
        (
            "Стресс-тест проверяет не красоту файла, а его **переносимость**: способен ли документ удержать решение без устных пояснений автора.",
            "Стресс-тест проверяет **переносимость** документа: способен ли он удержать решение без устных пояснений автора.",
        ),
    ),
    "09-ya-podumayu-eto-ne-odno-vozrazhenie.md": (
        (
            "Пока нет различающего факта, продавец имеет не диагноз, а несколько возможных объяснений.",
            "Пока нет различающего факта, у продавца есть только несколько возможных объяснений.",
        ),
        (
            "## Начинайте не со списка причин, а с двух-трёх версий этой сделки",
            "## Сформулируйте две-три версии именно этой сделки",
        ),
    ),
    "10-pochemu-vy-proigrali-sdelku.md": (
        (
            "Для практики важен не список из исследования, а методологический вывод: **исход сделки и объяснение исхода — разные типы данных**.",
            "Для практики важен прежде всего методологический вывод: **исход сделки и объяснение исхода — разные типы данных**.",
        ),
        (
            "Такое число выглядит точным только внешне. Причины могут быть не установлены, а пять неоднородных сделок не превращаются в надёжную статистическую выборку после занесения в таблицу.",
            "Такое число выглядит точным только внешне. Причины могут оставаться неустановленными; пять неоднородных сделок не превращаются в надёжную статистическую выборку после занесения в таблицу.",
        ),
    ),
}


def apply_exact_replacements() -> None:
    for filename, replacements in REPLACEMENTS.items():
        path = MANUSCRIPT / filename
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            count = text.count(old)
            if count != 1:
                raise RuntimeError(
                    f"Expected exactly one match in {filename}: {old!r}; found {count}"
                )
            text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")


def assert_clean_lexicon() -> None:
    with tempfile.TemporaryDirectory(prefix="book-prose-cleanup-") as temporary:
        lexicon = ContentQualityLexicon(
            user_store_path=Path(temporary) / "empty-user-rules-v1.json"
        )
        blocks = 0
        warnings = 0
        for path in sorted(MANUSCRIPT.glob("*.md")):
            scan = lexicon.scan(path.read_text(encoding="utf-8"), profile=PROFILE_BOOK_PROSE)
            blocks += len(scan["blocking_findings"])
            warnings += len(scan["warning_findings"])
            if scan["blocking_findings"] or scan["warning_findings"]:
                print(
                    path.name,
                    [(f["rule_id"], f["matched_text"], f["line"]) for f in scan["findings"]],
                    file=sys.stderr,
                )
        if blocks or warnings:
            raise RuntimeError(f"Cleanup did not reach clean BOOK_PROSE: blocks={blocks} warnings={warnings}")
        print("BOOK_PROSE post-cleanup: blocks=0 warnings=0")


def main() -> int:
    apply_exact_replacements()
    assert_clean_lexicon()
    print(f"Applied {sum(len(items) for items in REPLACEMENTS.values())} exact editorial replacements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
