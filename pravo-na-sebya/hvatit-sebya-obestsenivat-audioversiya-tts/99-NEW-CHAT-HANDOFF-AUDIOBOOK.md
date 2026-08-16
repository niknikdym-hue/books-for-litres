# NEW CHAT HANDOFF — аудиокнига «Хватит себя обесценивать»

Дата актуализации: 2026-08-17

## ПРОЕКТ

Автор: Елена Дилон
Серия: «Право на себя»
Книга №1: «Хватит себя обесценивать»
Репозиторий: `niknikdym-hue/books-for-litres`
Рабочая папка:
`pravo-na-sebya/hvatit-sebya-obestsenivat-audioversiya-tts/`

## 1. MASTER — НЕ ТРОГАТЬ

Единственный мастер:
`hvatit-sebya-obestsenivat-audioversiya-tts.txt`

Утверждённая редакция:
- blob SHA: `e9b053954bd217d978aeea2950a5821a8a105e57`
- размер: `149308 bytes`

Master неприкосновенен. Не добавлять SSML, `+`, acute marks или служебную TTS-разметку.

## 2. ЦЕЛЬ

Нужна полноценная русская аудиокнига, а не технически работающая читалка:
- человеческая фразовая интонация;
- естественная русская речь;
- живая смысловая динамика;
- умеренный книжный темп;
- без «авточтеца»;
- без newsreader/рекламной подачи;
- без переигрывания.

Полную книгу не генерировать до HUMAN/LONG PASS.

## 3. ЗАКРЫТЫЕ ПУТИ

- Silero — FAIL / CLOSED: авточтец.
- Piper — FAIL / CLOSED: качество не принято.
- Qwen voice cloning — FAIL / CLOSED: плохое клонирование, к нему не возвращаться.
- Chatterbox V3 — FAIL / CLOSED: Perth crash, не чинить.
- ZONOS2 — SUPERSEDED / NOT ACTIVE.
- Qwen PyTorch/MPS PR #345 — TECHNICAL FAIL / CLOSED.

PyTorch/MPS test был pinned к `26a5dacbc1644772df13f34966838e601a59c03c`, загрузил 0.6B на MPS/float16, но Serena упала до первого WAV с `torch.AcceleratorError: probability tensor contains either inf, nan or element < 0`. WAV 0. Этот backend больше не чинить.

Неудачный сегодняшний PyTorch/MPS каталог позже удалён целиком. По `du` он занимал 3.8G; фактически свободного места прибавилось примерно 1.32 GiB. Рабочий MLX-Qwen каталог не затронут.

Подробный архивный файл:
`18-QWEN3-TTS-MPS-TECHNICAL-FAIL-2026-08-16.md`

## 4. РАБОЧИЙ PRODUCTION-КАНДИДАТ

Runtime:
- MLX-Audio `v0.4.5`
- commit `04151c6abb74b886f879a4457ccdc96761f10102`

Модель:
`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`

Рабочий локальный каталог:
`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

Этот каталог НЕ удалять и НЕ переустанавливать. Это действующая локальная TTS-студия.

## 5. STAGE A — PASS 9/9

Stage A через MLX успешно завершён.

Факты:
- Serena smoke: PASS;
- все 9 joined WAV созданы и машинно проверены;
- mono PCM16;
- 24 kHz;
- полный Stage A: `1323.22 s`;
- max reported MLX peak: `8.244 GB`;
- OOM/process kill/fatal errors: нет.

Все 9 preset speaker остаются доступными для будущих книг:
- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

Выбор одного диктора для текущей книги НЕ удаляет и не отключает остальные голоса.

## 6. ВЫБОР ПОЛЬЗОВАТЕЛЯ

Финалист для «Хватит себя обесценивать»:

`Vivian`

Только Vivian идёт в Stage B этой книги.

Остальные восемь голосов сохранить для будущих книг.

## 7. SCRIPT / RUNNER

Книжный сценарий:
`20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`

Runner:
`21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py`

Сценарий содержит:
- Stage A короткий реальный фрагмент;
- Stage B длинный реальный фрагмент из 19 сегментов;
- отдельный `audiobook_instruct` как control argument;
- цифровые паузы `pause_after_ms` вне модели;
- фиксированные generation settings.

Stage B уже подготовлен и не требует нового текста или нового runner.

## 8. INSTRUCT

В MLX-Audio path используется отдельная книжная control-инструкция. Она не является произносимым текстом.

Цель инструкции:
- native-sounding Russian;
- тёплая, умная, камерная подача одному слушателю;
- естественная русская фразировка;
- смысловые акценты;
- разнообразный ритм;
- умеренный неторопливый conversational pace;
- тонкая ирония только там, где её допускает текст;
- без newsreader/commercial/announcer/voice-assistant/synthetic-reader подачи;
- без переигрывания и добавления слов.

На первом Vivian Stage B instruct НЕ менять: сначала получить стабильный длинный эталон. Корректировать режиссуру только после пользовательского прослушивания.

## 9. УДАРЕНИЯ / ИМЯ АВТОРА

Файл:
`17-QWEN3-TTS-PRONUNCIATION-GATE.json`

Правильное ожидаемое произношение:
**Елена ДИлон**.

Stage B начинается с титула `Елена Дилон.`

Не добавлять знаки ударения и фонетические хаки заранее. Сначала пользователь слушает естественную Vivian. Если фамилия реально произнесена неправильно — делать отдельный короткий pronunciation correction test только для TTS working copy. Master и основной script не менять без подтверждённого решения.

## 10. ТОЧНОЕ СЛЕДУЮЩЕЕ ЗАДАНИЕ CODEX

Файл:
`22-QWEN3-TTS-VIVIAN-STAGE-B-CODEX-TASK.md`

Выполнить буквально.

Главное:
- использовать существующую рабочую MLX-студию;
- ничего не переустанавливать и не скачивать повторно;
- `--stage stage_b_finalists`;
- `--speakers Vivian`;
- новый output `output-stage-b-vivian`;
- все 19 сегментов;
- после joined Vivian WAV — STOP;
- не запускать полную книгу;
- не тюнить параметры/инструкцию до прослушивания.

## 11. ЧТО НЕЛЬЗЯ ДЕЛАТЬ

- Не удалять рабочий MLX-Qwen каталог.
- Не удалять остальные preset speaker.
- Не возвращаться к PyTorch/MPS PR #345.
- Не возвращаться к voice cloning.
- Не переустанавливать MLX-Audio без отдельной причины.
- Не скачивать модель заново для каждой книги.
- Не делать общую чистку Mac.
- Не менять master.
- Не использовать SSML/`+`/acute marks без подтверждённого pronunciation test.
- Не запускать 8 других speaker в Stage B текущей книги.
- Не запускать полную книгу до Vivian Stage B HUMAN PASS.

## STATUS

`MASTER SOURCE: LOCKED / UNCHANGED`
`QWEN PYTORCH/MPS: TECHNICAL FAIL / CLOSED / TEST DIR CLEANED`
`ACTIVE RUNTIME: MLX-AUDIO v0.4.5 @ 04151c6abb74b886f879a4457ccdc96761f10102`
`ACTIVE MODEL: mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`
`STAGE A: PASS 9/9`
`ALL 9 PRESET SPEAKERS: PRESERVED`
`CURRENT BOOK FINALIST: VIVIAN`
`VIVIAN STAGE B SCRIPT: READY / 19 SEGMENTS`
`NEXT ACTION: EXECUTE 22-QWEN3-TTS-VIVIAN-STAGE-B-CODEX-TASK.md`
`FULL BOOK: HOLD UNTIL VIVIAN STAGE B HUMAN PASS`
