#!/usr/bin/env python3
"""One-time exact cleanup of Introduction/Chapter 1 premise overlap.

Fail closed: the reviewed source block must occur exactly once. After replacement,
run the canonical BOOK_PROSE gate before allowing the workflow to commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "sekrety-prodvizheniya-uslug" / "kak-prodavat-uslugi" / "manuscript" / "01-pochemu-horoshuyu-uslugu-trudno-kupit.md"

OLD = """# Глава 1. Почему хорошую услугу трудно купить

У сильного специалиста есть коммерческая проблема, которой почти нет у производителя стула: значительная часть качества его работы ещё не существует в момент покупки.

Клиент выбирает будущий анализ, будущие решения, будущие встречи, будущую реакцию специалиста на неожиданную ситуацию. Даже когда итог услуги материален — договор, сайт, проект, отчёт, рекламная кампания, программный модуль, — заранее можно увидеть лишь часть того, за что предстоит заплатить.

Из-за этого профессиональное качество и продаваемость качества — разные вещи.

Специалист может объективно работать сильнее конкурента и проигрывать ему на этапе выбора. Не потому, что рынок «не понимает ценность». Покупатель просто вынужден принимать решение раньше, чем сможет проверить большую часть будущего результата.

"""

NEW = """# Глава 1. Почему хорошую услугу трудно купить

Разрыв проверяемости превращает профессиональное качество в отдельную коммерческую задачу. До оплаты покупатель видит лишь признаки будущей работы и по ним пытается понять, насколько разумно входить в сделку.

Отсюда возникает парадокс: специалист способен работать сильнее конкурента и продаваться слабее. Профессиональное качество и способность сделать основания для выбора достаточно наблюдаемыми — разные компетенции.

Первый практический вопрос поэтому звучит так: **что именно покупатель пока не способен оценить достаточно уверенно?** Ответ определяет, какую часть продажи имеет смысл улучшать.

"""

text = PATH.read_text(encoding="utf-8")
count = text.count(OLD)
if count != 1:
    raise SystemExit(f"Expected reviewed opening exactly once, found {count}")
PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")

subprocess.run(
    ["python", str(ROOT / "sekrety-prodvizheniya-uslug" / "kak-prodavat-uslugi" / "quality" / "book_prose_gate.py")],
    cwd=ROOT,
    check=True,
)
