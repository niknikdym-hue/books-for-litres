# CODEX TASK — Vivian Stage B / Qwen3-TTS MLX audiobook

Дата: 2026-08-17

## Решение пользователя

Финалист для книги «Хватит себя обесценивать»:

`Vivian`

Остальные 8 preset speaker НЕ удалять и НЕ изменять: они сохраняются для будущих книг.

## Цель этого запуска

Получить длинный Stage B только для Vivian на реальном вступлении книги и проверить, выдерживает ли голос несколько минут цельного книжного чтения.

Это уже HUMAN BOOK GATE, а не новый технический кастинг.

## Рабочая среда — использовать существующую

Рабочий каталог успешной MLX-студии:

`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

НЕ создавать новое окружение.
НЕ переустанавливать `mlx-audio`.
НЕ скачивать модель повторно.
НЕ менять Hugging Face cache.
НЕ трогать старые TTS.
НЕ чистить рабочий каталог.

Подтверждённый runtime:
- MLX-Audio `v0.4.5`
- commit `04151c6abb74b886f879a4457ccdc96761f10102`
- model `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`
- Stage A: PASS 9/9

## Входные файлы

Использовать из репозитория проекта без редактирования:

- `20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`
- `21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py`
- `17-QWEN3-TTS-PRONUNCIATION-GATE.json`

Перед запуском сравнить их SHA256 с копиями, которые реально будут запускаться. Если локальные копии отличаются от репозитория — STOP и показать diff; не исправлять молча.

## Stage B

Создать только новый output dir внутри рабочей MLX-студии:

`output-stage-b-vivian`

Если такой каталог уже существует — STOP, не перезаписывать.

Запускать runner:

- `--stage stage_b_finalists`
- `--speakers Vivian`
- `--output-dir .../output-stage-b-vivian`
- без `--smoke`

Использовать ровно тот `audiobook_instruct`, generation settings, сегментацию и паузы, которые уже лежат в `20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`.

Ничего не тюнить на этом запуске.

## Важное по имени автора

Первый сегмент Stage B содержит:

`Елена Дилон.`

Ожидаемое произношение фамилии:

`Елена ДИлон`

На этом запуске НЕ добавлять знаки ударения, `+`, SSML или фонетические хаки заранее.

Сначала получить естественный вариант Vivian и дать пользователю услышать его.

Если фамилия реально произнесена неправильно, зафиксировать это отдельно в отчёте как:

`AUTHOR_NAME_PRONUNCIATION: FAIL / needs isolated correction test`

Но НЕ перегенерировать b01 автоматически и НЕ менять master/script.

## Что не делать

- не запускать другие 8 speaker;
- не запускать полную главу/книгу;
- не менять тембр Vivian;
- не менять instruct;
- не менять temperature/top_k/top_p/repetition_penalty;
- не менять длину пауз;
- не добавлять аудиообработку, EQ, compression, denoise;
- не исправлять ударения автоматически;
- не удалять Stage A WAV;
- не удалять модель/окружение после выполнения.

## Контроль памяти

До запуска сохранить в `logs/`:
- `vm_stat`;
- `sysctl vm.swapusage`;
- memory pressure snapshot.

После Stage B повторить.

Обычный swap допустим, если система остаётся стабильной. STOP при OOM/process kill/критической потере отзывчивости.

## Что должно получиться

В `output-stage-b-vivian/`:
- отдельные WAV `b01.wav` ... `b19.wav` внутри папки Vivian;
- объединённый `BOOK-AUDITION-MLX-Vivian.wav`;
- `RUN-REPORT.json`.

Машинно проверить joined WAV:
- mono;
- PCM16;
- 24 kHz (если runtime сохранил подтверждённый Stage A sample rate);
- ненулевая длительность;
- без NaN/Inf до PCM conversion;
- все 19 сегментов присутствуют;
- файл открывается стандартным WAV parser.

## Отчёт

Создать:

`QWEN-VIVIAN-STAGE-B-TECHNICAL-RESULT.md`

Указать:
- runtime/model без повторной установки;
- точную команду;
- model load time;
- длительность каждого сегмента;
- total wall time;
- joined duration;
- max reported MLX peak;
- swap before/after;
- warnings/errors;
- абсолютный путь к joined WAV;
- `SEGMENTS: 19/19` либо фактическое значение;
- `AUTHOR_NAME_PRONUNCIATION: HUMAN CHECK REQUIRED` (не пытаться определять слухом автоматически).

## Финальная граница

После получения полноценного Vivian Stage B — STOP.

Не запускать полную книгу.
Не делать варианты режиссуры.
Не исправлять имя автоматически.

Следующий шаг — пользователь слушает длинный WAV и решает:
1. Vivian PASS как диктор книги;
2. нужны точечные изменения режиссуры;
3. нужны точечные pronunciation fixes;
4. Vivian не подходит на длинной дистанции.
