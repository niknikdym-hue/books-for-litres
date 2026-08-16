# CODEX TASK — Qwen3-TTS 0.6B CustomVoice через MLX-Audio на MacBook Air M1 / 8 GB

Дата: 2026-08-16

## Цель

Получить реальный книжный audition Qwen3-TTS 0.6B CustomVoice через **нативный Apple-Silicon MLX runtime**, не повторяя уже закрытый PyTorch/MPS PR #345 path.

Это НЕ voice cloning и НЕ лабораторный TTS-test. Генерируется настоящий фрагмент аудиокниги с отдельной control-инструкцией книжной подачи.

## Сначала обязательно прочитать

1. `99-NEW-CHAT-HANDOFF-AUDIOBOOK.md`
2. `18-QWEN3-TTS-MPS-TECHNICAL-FAIL-2026-08-16.md`
3. `20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`
4. `21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py`
5. `17-QWEN3-TTS-PRONUNCIATION-GATE.json`

## Жёсткая граница

PyTorch/MPS PR #345 больше НЕ чинить и НЕ запускать.

Нельзя:
- менять старую Qwen/MLX voice-cloning среду;
- удалять старые TTS;
- использовать старый Qwen model cache;
- делать общую чистку Mac;
- ставить новый системный Python;
- делать Homebrew update/upgrade;
- ставить ffmpeg: для WAV он не нужен;
- использовать voice cloning;
- менять мастер книги;
- добавлять SSML / `+` / acute stress marks в произносимый текст;
- менять текст, паузы или audiobook instruct из подготовленного script;
- автоматически переходить на 8-bit/6-bit/1.7B при любой ошибке;
- делать monkey patches MLX-Audio;
- запускать Stage B или полную книгу.

## Новый изолированный каталог

Создать только:

`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

Если каталог уже существует — STOP, ничего не перезаписывать.

Использовать сохранённый Python 3.11.16:

`/opt/homebrew/Cellar/python@3.11/3.11.16/bin/python3.11`

Внутри test dir создать новый `.venv`.

## Изолировать Hugging Face cache

До скачивания модели задать cache только внутри нового test dir, например:

- `HF_HOME=$TEST_DIR/hf-cache`
- `HUGGINGFACE_HUB_CACHE=$TEST_DIR/hf-cache/hub`

Не использовать и не модифицировать старые Qwen/HF cache directories.

## Runtime — только pinned MLX-Audio

Репозиторий:
`https://github.com/Blaizzy/mlx-audio`

Release/tag:
`v0.4.5`

Точный commit:
`04151c6abb74b886f879a4457ccdc96761f10102`

Установить только внутрь нового venv из checkout этого commit.

После checkout обязательно записать в отчёт:
- `git rev-parse HEAD`;
- `python --version`;
- `pip show mlx-audio`;
- версии `mlx`, `mlx-lm`, `numpy`.

Не использовать текущий `main` и не обновлять зависимости после успешной установки pinned release.

## Модель — только эта

`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`

Не использовать PyTorch checkpoint `Qwen/...` в этом запуске.
Не использовать 8-bit/6-bit fallback автоматически.

Ожидаемый размер HF repo примерно 2.5 GB.

## Входные файлы

Скопировать из репозитория проекта в test dir без редактирования:

- `20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`
- `21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py`

Зафиксировать SHA256 обоих файлов до запуска.

## Что получает модель

Qwen получает:
- только `text` конкретного сегмента как произносимый текст;
- `language = Russian`;
- выбранный preset speaker;
- отдельный `audiobook_instruct` как control argument.

`audiobook_instruct` НЕ является частью текста и не должен звучать в WAV.

Паузы `pause_after_ms` вставляет runner после синтеза как цифровую тишину.

## Generation settings

Использовать ровно script/runner:
- temperature `0.9`
- top_k `50`
- top_p `1.0`
- repetition_penalty `1.05`
- max_tokens `4096`
- stream `false`

Ничего не тюнить до пользовательского прослушивания.

## Порядок запуска

### 1. До модели

Снять:
- свободное место;
- `vm_stat`;
- `sysctl vm.swapusage`;
- текущий memory pressure snapshot.

Сохранить в `logs/`.

### 2. SMOKE — Serena, только первый книжный сегмент

Запустить `21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py` с:
- `--smoke`
- отдельным новым `output-smoke`.

Ожидаемый результат:
- один `a01.wav`;
- один joined `BOOK-AUDITION-MLX-Serena.wav`;
- `RUN-REPORT.json`.

Проверить машинно:
- WAV существует и ненулевой;
- mono PCM16;
- sample rate > 0;
- длительность > 0;
- нет NaN/Inf до записи;
- audiobook instruct не оказался произнесённым текстом (по логике runner он не входит в `text`).

Если SMOKE падает до WAV:
**STOP.**
Не патчить код, не менять sampling, не менять модель, не пробовать другой speaker.
Сохранить полный stdout/stderr и memory snapshots.

### 3. Если SMOKE PASS — Stage A всех 9 speaker

Запустить новый отдельный `output-stage-a` без `--smoke`.

Должны быть получены joined WAV:
- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

Все читают один и тот же книжный фрагмент с одним audiobook instruct и одинаковыми generation settings.

Не выбирать победителя за пользователя.

## STOP по памяти

Во время smoke и Stage A наблюдать memory pressure / swap.

STOP без ремонта, если до первого полноценного WAV:
- процесс killed / OOM;
- memory pressure стабильно уходит в критическую красную зону;
- swap начинает быстро расти и система явно теряет отзывчивость;
- MLX/runtime требует патча исходников.

Обычный умеренный swap сам по себе не считать FAIL, но точные значения записать.

## Что сохранить на выходе

В test dir:
- `logs/`
- `input-sha256.log`
- `output-smoke/`
- при PASS smoke: `output-stage-a/`
- `QWEN-MLX-BOOK-AUDITION-TECHNICAL-RESULT.md`

В итоговом markdown указать:
- pinned mlx-audio commit;
- MLX/model id;
- Python/package versions;
- model load time;
- время каждого сегмента / speaker;
- peak memory, которое сообщает MLX runner;
- swap до/после;
- список фактически созданных WAV и абсолютные пути;
- любые warnings/errors дословно;
- был ли получен smoke WAV;
- сколько из 9 Stage A WAV получено.

## Финальная граница

Если 9 WAV получены — STOP.

Не запускать Stage B.
Не исправлять ударения.
Не менять audiobook instruct.
Не генерировать главу или книгу.

Следующий шаг после 9 WAV — пользовательское прослушивание и выбор максимум 1–2 голосов.
