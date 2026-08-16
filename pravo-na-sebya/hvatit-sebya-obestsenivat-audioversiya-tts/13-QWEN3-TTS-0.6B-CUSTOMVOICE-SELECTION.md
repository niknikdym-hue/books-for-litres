# Qwen3-TTS 0.6B CustomVoice — текущий выбор и runtime gate

Дата актуализации: 2026-08-16

## Главный вывод

Qwen3-TTS 0.6B CustomVoice **не закрыт как модель для аудиокниги**.

Закрыты два конкретных прежних пути:

1. `Qwen3-TTS 0.6B + MLX + voice cloning` — плохой клонированный звук («звуковая каша»), cloning для книги больше не использовать.
2. `Qwen3-TTS 0.6B CustomVoice + upstream PR #345 + PyTorch MPS/float16` — технический FAIL до первого WAV на MacBook Air M1 / 8 GB.

Активный следующий путь:

`Qwen3-TTS 0.6B CustomVoice + Blaizzy/mlx-audio v0.4.5 + MLX bf16 model`

Точный model id:
`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`

Это по-прежнему **без voice cloning**.

---

## Что подтверждено по Qwen

Оригинальная модель Qwen:
`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`

Подтверждено разработчиком Qwen:
- русский входит в 10 поддерживаемых языков;
- есть 9 preset premium timbres;
- каждый preset speaker может говорить на любом поддерживаемом языке, в том числе по-русски;
- для лучшего качества Qwen рекомендует native language speaker, но Russian не запрещён;
- cloning для CustomVoice не нужен;
- лицензия Apache-2.0.

9 speaker:
- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

Нативного русского speaker среди них нет. Поэтому пригодность определяется только реальным русским книжным WAV.

---

## PyTorch/MPS PR #345 — ПРОВЕРЕН И ЗАКРЫТ

Pinned head:
`26a5dacbc1644772df13f34966838e601a59c03c`

Фактический запуск на MacBook Air M1 / 8 GB:
- model load: `282.01 s`;
- device/dtype: `mps / float16`;
- первый speaker: Serena;
- до первого WAV:
  `torch.AcceleratorError: probability tensor contains either inf, nan or element < 0`;
- WAV: `0`;
- swap вырос примерно с `1211.69 MB` до `2431.75 MB`.

Это технический FAIL runtime, не оценка голоса.

Подробно:
`18-QWEN3-TTS-MPS-TECHNICAL-FAIL-2026-08-16.md`

Решение:
`PYTORCH/MPS PR #345: CLOSED FOR THIS PROJECT`

Не чинить sampling, не уходить в CPU/float32 и не тюнить параметры ради технического WAV.

---

## Новый runtime: MLX-Audio

Проект:
`https://github.com/Blaizzy/mlx-audio`

Pinned release:
`v0.4.5`

Pinned commit:
`04151c6abb74b886f879a4457ccdc96761f10102`

Почему этот runtime выбран:
- специально построен на Apple MLX для Apple Silicon;
- MIT license;
- Qwen3-TTS поддерживается штатно;
- есть прямой `0.6B-CustomVoice-bf16` model path;
- WAV не требует ffmpeg;
- в проект уже merged отдельный PR #444: `[Qwen3-TTS] Fix some Custom Voices producing silence with 0.6B`;
- в коде используется MLX-native categorical sampling;
- model repo `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16` около 2.5 GB, `model.safetensors` около 1.81 GB, license Apache-2.0;
- текущая MLX-Audio реализация перечисляет все 9 нужных CustomVoice speaker.

Это не возврат к прежнему cloning test. Теперь используется только preset CustomVoice.

---

## Важное различие по `instruct`

Официальный PyTorch Qwen-код для 0.6B содержит условие, которое зануляет `instruct`.

Однако MLX-Audio после merged PR #444 имеет отдельную реализацию: для `tts_model_size == "0b6"` instruct отключается только когда model type **не** `custom_voice`. Для `0.6B CustomVoice` instruction path сохраняется.

Поэтому:
- на закрытом PyTorch/MPS пути считать 0.6B instruct недоступным;
- в новом MLX-Audio audition использовать один фиксированный audiobook instruct;
- instruct передаётся отдельным control argument и **не является произносимым текстом**;
- Qwen получает как речь только поле `text`.

Это runtime-specific поведение MLX-Audio; не переносить его автоматически на официальный PyTorch backend.

---

## Книжный, а не лабораторный audition

Новый сценарий:
`20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`

Runner:
`21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py`

Принцип:
- настоящий фрагмент вступления книги;
- все 9 голосов читают один и тот же текст;
- одинаковый audiobook instruct;
- одинаковые generation settings;
- паузы добавляются runner после синтеза цифровой тишиной;
- модель не видит служебные комментарии, названия пауз, SSML или stress markup;
- master книги не меняется.

Audiobook instruct задаёт:
- native-sounding Russian;
- тёплую, умную, камерную подачу одному слушателю;
- естественную русскую фразировку и смысловые акценты;
- умеренный неторопливый темп;
- тонкую сухую иронию только там, где она заложена текстом;
- запрет newsreader/commercial/announcer/voice-assistant/synthetic manner;
- запрет переигрывания, шёпота, пения и добавления слов.

---

## Ударения

Русский stress-control у Qwen остаётся реальным риском.

Не добавлять заранее:
- `+`;
- acute accents;
- апострофы;
- SSML;
- выдуманный pronunciation syntax.

Сначала получить настоящий книжный WAV. Затем фиксировать только реально ошибочные слова в отдельной TTS-copy / pronunciation override.

Известное ожидание:
**Елена ДИлон**.

Файл:
`17-QWEN3-TTS-PRONUNCIATION-GATE.json`

---

## Следующий gate

Точное задание Codex:
`19-QWEN3-TTS-MLX-AUDIO-M1-CODEX-TASK.md`

Порядок:
1. новый изолированный test dir;
2. isolated venv;
3. isolated HF cache;
4. pinned `mlx-audio v0.4.5`;
5. только bf16 0.6B CustomVoice;
6. Serena / первый книжный сегмент — technical smoke;
7. если WAV получен — сразу Stage A для всех 9;
8. после 9 WAV STOP и пользовательское прослушивание.

Автоматические fallback на 8bit/6bit/1.7B запрещены.

---

## STATUS

`QWEN VOICE CLONING: FAIL / CLOSED`
`QWEN PYTORCH/MPS PR #345: TECHNICAL FAIL / CLOSED`
`QWEN 0.6B CUSTOMVOICE MODEL: STILL ACTIVE`
`ACTIVE RUNTIME: MLX-AUDIO v0.4.5`
`ACTIVE MODEL: mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`
`RUSSIAN: SUPPORTED`
`PRESET SPEAKERS: 9`
`VOICE CLONING: NO`
`MLX-AUDIO AUDIOBOOK INSTRUCT: ENABLED FOR THIS TEST`
`MASTER: LOCKED / UNCHANGED`
`NEXT ACTION: EXECUTE 19-QWEN3-TTS-MLX-AUDIO-M1-CODEX-TASK.md`
`FULL BOOK: HOLD UNTIL HUMAN PASS + LONG TEST`
