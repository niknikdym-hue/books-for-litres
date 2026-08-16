# NEW CHAT HANDOFF — аудиокнига «Хватит себя обесценивать»

## ПРОЕКТ

Автор: Елена Дилон
Серия: «Право на себя»
Книга №1: «Хватит себя обесценивать»
Репозиторий: `niknikdym-hue/books-for-litres`
Рабочая папка:
`pravo-na-sebya/hvatit-sebya-obestsenivat-audioversiya-tts/`

Актуальная точка продолжения после пересмотра Qwen 16 августа 2026 года.

---

## 1. MASTER — НЕ ТРОГАТЬ

Единственный мастер-текст:
`hvatit-sebya-obestsenivat-audioversiya-tts.txt`

Утверждённая редакция:
- blob SHA: `e9b053954bd217d978aeea2950a5821a8a105e57`
- размер: `149308 bytes`

Мастер не менять ради TTS:
- никаких `+`;
- никаких acute marks;
- никакого SSML;
- никакой служебной разметки.

Во время подготовки нового Qwen CustomVoice test master не изменялся.

---

## 2. ГЛАВНАЯ ПОПРАВКА ПО QWEN

Прежний FAIL относился к конкретной схеме:

`Qwen3-TTS 0.6B + MLX + voice cloning`.

Клонированный звук был плохим («звуковая каша»), а pipeline слишком тяжёлым.

**Нельзя переносить этот FAIL на Qwen3-TTS CustomVoice.**

Новый активный путь:

`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`

Это отдельная модель/режим с 9 готовыми встроенными speaker. Voice cloning не нужен.

Русский официально поддерживается.

---

## 3. АКТИВНЫЙ КАНДИДАТ

`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`

Почему выбран первым:
- 0.6B — разумный размер для M1 / 8 GB;
- готовые голоса, без клонирования;
- русский входит в официальные языки;
- Apache-2.0;
- локально, без API/биллинга;
- в официальном Qwen PR #345 есть Apple-Silicon/MPS support и автор PR сообщает успешный CustomVoice test на Apple Silicon.

Pinned PR head:
`26a5dacbc1644772df13f34966838e601a59c03c`

PR:
`https://github.com/QwenLM/Qwen3-TTS/pull/345`

Статус PR на 2026-08-16: OPEN / not merged.

Поэтому тест только изолированный и pinned.

---

## 4. ВАЖНО: 0.6B НЕ ПОЛУЧАЕТ STYLE INSTRUCT

В текущем официальном коде `generate_custom_voice()` есть явное условие:

`if self.model.tts_model_size in "0b6": instruct = None`

То есть `0.6B CustomVoice` сейчас игнорирует style instruction.

Следствие:
- не писать для 0.6B промпты «читай тепло/иронично/по-книжному»;
- не кормить модель нашими режиссёрскими пояснениями;
- оценивать её собственную естественную просодию;
- если тембр/русский хороши, но не хватает управляемой режиссуры — потом отдельно решить, нужен ли `1.7B-CustomVoice`;
- 1.7B сейчас НЕ устанавливать.

---

## 5. 9 ГОТОВЫХ ГОЛОСОВ

Все должны прочитать один и тот же фрагмент книги:

- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

Нативного русского speaker в штатной девятке нет.

Поэтому выбор только по реальному русскому WAV, а не по английскому/китайскому описанию голоса.

---

## 6. ЭТО НЕ «ТЕСТ РОБОТА», А AUDITION АУДИОКНИГИ

Пользователь отдельно потребовал не делать лабораторные скороговорки и искусственные TTS-tests.

Правильная схема:

### Stage A — все 9 голосов

Каждый читает один и тот же настоящий фрагмент вступления книги.

Фрагмент содержит:
- обычную повествовательную фразу;
- длинное естественное предложение;
- внутреннюю реплику;
- иронию;
- короткую смысловую фразу;
- ритмический список;
- смену длины и рисунка предложений.

Цель — выбрать голоса, которые уже без костылей хочется слушать как книгу.

### Stage B — только 1–2 финалиста

После пользовательского выбора финалисты читают весь подготовленный кусок вступления, включая титул, примерно на несколько минут.

Это реальный HUMAN READING GATE.

Stage B не запускать автоматически.

---

## 7. МАШИНОЧИТАЕМАЯ TTS-СХЕМА

Главный файл:

`15-QWEN3-TTS-BOOK-AUDITION-SCRIPT.json`

Принцип:
- поле `text` = только русский текст, который должен произнести Qwen;
- `pause_after_ms` = техническая пауза, которую добавляет runner ПОСЛЕ синтеза;
- Qwen не видит названий полей, комментариев и pause values;
- Qwen не получает SSML / `+` / acute marks / служебные слова.

Текст разбит на смысловые сегменты не ради рубленого чтения, а чтобы:
- задавать настоящие паузы цифровой тишиной;
- не зависеть от неподдерживаемого SSML;
- не заставлять модель дрейфовать на длинном монолите;
- при production пересинтезировать только конкретный неудачный кусок.

Runner соединяет сегменты в один WAV.

---

## 8. RUNNER

Файл:

`16-QWEN3-TTS-AUDIOBOOK-RUNNER.py`

Он:
- требует MPS и не падает молча на CPU;
- загружает только `0.6B-CustomVoice`;
- передаёт Qwen только `text`;
- `language="Russian"`;
- `instruct=None`;
- не использует cloning;
- не использует SSML;
- не добавляет неподдерживаемые stress marks;
- использует официальные generation defaults модели без ручного temperature/top-k/top-p tuning;
- одинаково seed-ит соответствующие сегменты для сравнимости speaker;
- генерирует сегменты отдельно;
- делает минимальный 8 ms edge fade против цифрового щелчка;
- добавляет `pause_after_ms` как цифровую тишину;
- сохраняет сегменты и joined `BOOK-AUDITION-<speaker>.wav`;
- пишет `RUN-REPORT.json`.

Stage A начинает с Serena как технического smoke. Если Serena не запускается штатно — не тратить время на остальные 8.

---

## 9. ПРОИЗНОШЕНИЕ И УДАРЕНИЯ

Отдельный файл:

`17-QWEN3-TTS-PRONUNCIATION-GATE.json`

Правило:
- не придумывать Qwen-синтаксис ударений, которого нет;
- сначала услышать натуральный русский WAV;
- фиксировать только реально ошибочно произнесённые слова;
- corrections делать только в отдельной TTS working copy / override;
- master книги не менять.

Известное ожидание:

**Елена ДИлон**.

Фамилия проверяется в Stage B.

Если Qwen поставит ударение неправильно — сначала короткий отдельный pronunciation test и только потом подтверждённая TTS-safe замена.

---

## 10. ТОЧНОЕ ЗАДАНИЕ CODEX

Файл:

`14-QWEN3-TTS-0.6B-CUSTOMVOICE-M1-CODEX-TASK.md`

Следующий исполнитель должен выполнить его буквально.

Разрешён новый каталог:

`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-book-audition-2026-08-16`

Если уже существует — STOP, не перезаписывать.

Использовать существующий Python 3.11.16:

`/opt/homebrew/Cellar/python@3.11/3.11.16/bin/python3.11`

Создать новый venv только внутри нового test dir.

Старую Qwen-среду не трогать.

---

## 11. ЧТО НЕЛЬЗЯ ДЕЛАТЬ

- Не возвращаться к Qwen voice cloning.
- Не трогать старые Qwen установки/модели.
- Не ставить новый системный Python.
- Не делать Homebrew update/upgrade.
- Не ставить CUDA/FlashAttention.
- Не ставить 1.7B до отдельного решения.
- Не возвращаться к Silero/Piper/Chatterbox.
- Не возвращать ZONOS2 как активный путь: подготовленные ранее ZONOS2 test files удалены как superseded.
- Не кормить 0.6B style prompts: они игнорируются.
- Не использовать SSML и выдуманные stress marks.
- Не менять master.
- Не генерировать всю главу/книгу до HUMAN PASS.
- Не выбирать speaker за пользователя.

---

## 12. ЗАКРЫТЫЕ / НЕАКТИВНЫЕ ПУТИ

### Silero
FAIL / CLOSED — ощущение авточтеца.

### Piper
FAIL / CLOSED — качество не принято.

### Qwen voice cloning
FAIL / CLOSED — плохое клонирование; этот статус не относится к CustomVoice.

### Chatterbox V3
FAIL / CLOSED — техническая карусель до WAV; очищен сегодняшний install мусор.

### ZONOS2
Не тестировался на Mac. Был временно выбран в research, но после обнаружения правильного Qwen CustomVoice path снят с активного маршрута. Созданные ZONOS2 selection/task/test files удалены из рабочей папки.

---

## STATUS

`MASTER SOURCE: LOCKED / UNCHANGED`
`SILERO: FAIL / CLOSED`
`PIPER: FAIL / CLOSED`
`QWEN VOICE CLONING: FAIL / CLOSED`
`CHATTERBOX: FAIL / CLOSED`
`ZONOS2: SUPERSEDED / NOT ACTIVE`
`ACTIVE CANDIDATE: QWEN3-TTS 0.6B CUSTOMVOICE`
`RUSSIAN: OFFICIALLY SUPPORTED`
`PRESET SPEAKERS: 9`
`VOICE CLONING REQUIRED: NO`
`0.6B STYLE INSTRUCT: DISABLED BY CURRENT OFFICIAL CODE`
`APPLE SILICON PATH: OFFICIAL PR #345 PINNED`
`MAC INSTALL FOR THIS PATH: NOT STARTED`
`AUDITION SCRIPT: READY`
`AUDIOBOOK RUNNER: READY`
`PRONUNCIATION GATE: READY`
`NEXT ACTION: EXECUTE 14-QWEN3-TTS-0.6B-CUSTOMVOICE-M1-CODEX-TASK.md / STAGE A ONLY`
`FULL BOOK: HOLD UNTIL HUMAN PASS + LONG TEST`
