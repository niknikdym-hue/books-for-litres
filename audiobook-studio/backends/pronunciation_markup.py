"""Deterministic provider adapters for canonical Unicode stress marks."""

from __future__ import annotations

import re
from typing import Any


_COMBINING_ACUTE = "\u0301"
_RUSSIAN_VOWEL = "АЕЁИОУЫЭЮЯаеёиоуыэюя"
_ACCENTED_TOKEN = re.compile(r"[А-Яа-яЁё\u0301]+", re.UNICODE)


def yandex_text_markup(text: str) -> str:
    """Translate human-readable ``а́`` into SpeechKit ``+а`` markup."""
    if _COMBINING_ACUTE not in text:
        return text
    invalid = re.search(rf"(?<![{_RUSSIAN_VOWEL}]){_COMBINING_ACUTE}", text)
    if invalid:
        raise ValueError("Combining acute must follow a supported Russian vowel.")
    return re.sub(
        rf"([{_RUSSIAN_VOWEL}]){_COMBINING_ACUTE}",
        lambda match: "+" + match.group(1),
        text,
    )


def accented_words(text: str) -> list[dict[str, Any]]:
    """Return unique accented Russian words in first-occurrence order."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _ACCENTED_TOKEN.finditer(text):
        token = match.group(0)
        if _COMBINING_ACUTE not in token:
            continue
        plain = token.replace(_COMBINING_ACUTE, "")
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append({"word": plain, "display": token})
    return output


def openai_instruction_suffix(text: str) -> str:
    words = accented_words(text)
    if not words:
        return ""
    lines = [
        "Соблюдай следующие точные ударения в словах; не меняй остальной текст:"
    ]
    lines.extend(
        f"- «{item['word']}» произноси как «{item['display']}»."
        for item in words
    )
    return "\n".join(lines)
