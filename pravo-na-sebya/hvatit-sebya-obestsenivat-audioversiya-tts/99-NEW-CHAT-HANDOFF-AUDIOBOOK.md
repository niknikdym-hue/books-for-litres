# NEW CHAT HANDOFF — аудиокнига «Хватит себя обесценивать»

## ПРОЕКТ

Автор: Елена Дилон
Серия: «Право на себя»
Книга №1: «Хватит себя обесценивать»
Репозиторий: `niknikdym-hue/books-for-litres`
Рабочая папка:
`pravo-na-sebya/hvatit-sebya-obestsenivat-audioversiya-tts/`

Актуальная точка немедленного продолжения после фактического PyTorch/MPS-теста Qwen3-TTS 0.6B CustomVoice 16 августа 2026 года.

---

## 1. MASTER — НЕ ТРОГАТЬ

Единственный мастер:
`hvatit-sebya-obestsenivat-audioversiya-tts.txt`

Утверждённая редакция:
- blob SHA: `e9b053954bd217d978aeea2950a5821a8a105e57`
- размер: `149308 bytes`

Master неприкосновенен:
- никаких `+`;
- никаких acute stress marks;
- никакого SSML;
- никакой служебной TTS-разметки.

---

## 2. ЦЕЛЬ

Нужна не технически работающая читалка, а полноценная русская аудиокнига:
- человеческая фразовая интонация;
- естественная русская речь;
- живая смысловая динамика;
- умеренный книжный темп;
- без «авточтеца»;
- без newsreader/рекламной подачи;
- без переигрывания.

Полную книгу не генерировать до SHORT/HUMAN PASS и LONG TEST PASS.

---

## 3. QWEN — ЧТО ИМЕННО ЗАКРЫТО

### Qwen voice cloning — FAIL / CLOSED

Прежний путь:
`Qwen3-TTS 0.6B + MLX + voice cloning`.

Клонированный результат был плохим («звуковая каша»). К cloning не возвращаться.

### Qwen PyTorch/MPS PR #345 — TECHNICAL FAIL / CLOSED

Pinned head:
`26a5dacbc1644772df13f34966838e601a59c03c`

Фактический локальный запуск:
- MacBook Air M1 / 8 GB;
- модель `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`;
- `mps / float16`;
- MPS доступен;
- model load `282.01 s`;
- Serena упала до первого WAV:
  `torch.AcceleratorError: probability tensor contains either inf, nan or element < 0`;
- WAV: `0`;
- остальные 8 speaker не запускались;
- swap примерно `1211.69 -> 2431.75 MB`;
- OOM/kill не было;
- STOP выполнен правильно, никаких ремонтов не делалось.

Подробно:
`18-QWEN3-TTS-MPS-TECHNICAL-FAIL-2026-08-16.md`

Не чинить этот backend, не тюнить sampling, не уходить в CPU/float32 ради demo.

---

## 4. QWEN 0.6B CUSTOMVOICE КАК МОДЕЛЬ НЕ ЗАКРЫТ

Активен другой runtime path:

`Qwen3-TTS 0.6B CustomVoice + MLX-Audio`

Причина: MPS-падение произошло до любого WAV и не говорит ничего о художественном качестве Qwen CustomVoice.

Русский Qwen официально поддерживает.
Есть 9 preset speaker:
- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

Voice cloning не требуется.

---

## 5. НОВЫЙ АКТИВНЫЙ RUNTIME — MLX-AUDIO

Проект:
`https://github.com/Blaizzy/mlx-audio`

Использовать только pinned release:
- tag `v0.4.5`
- commit `04151c6abb74b886f879a4457ccdc96761f10102`

Runtime license: MIT.

Модель только:
`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`

Model repo примерно `2.5 GB`, основной safetensors примерно `1.81 GB`, license Apache-2.0.

Почему этот путь допустим:
- MLX-Audio создан для Apple Silicon;
- Qwen3-TTS поддерживается штатно;
- merged PR #444 специально исправлял 0.6B CustomVoice (`Fix some Custom Voices producing silence with 0.6B`);
- MLX implementation использует собственный native sampling path;
- все 9 нужных speaker доступны;
- WAV не требует установки ffmpeg.

---

## 6. ВАЖНОЕ РАЗЛИЧИЕ ПО `instruct`

Официальный PyTorch Qwen-код для 0.6B зануляет `instruct`.

Но pinned MLX-Audio после PR #444 имеет другое runtime-specific поведение: для `0.6B custom_voice` instruction path сохраняется.

Поэтому новый MLX audition использует **один фиксированный audiobook instruct**.

Он передаётся как отдельный control argument и НЕ является произносимым текстом.

Книжная инструкция требует:
- native-sounding Russian pronunciation;
- тёплую, умную, камерную подачу одному слушателю;
- естественную русскую фразировку и смысловые акценты;
- разнообразный ритм;
- умеренный неторопливый conversational pace;
- тонкую сухую иронию только там, где она есть в тексте;
- не звучать как newsreader/commercial/announcer/voice assistant/synthetic reader;
- не переигрывать, не шептать, не петь и не добавлять слов.

---

## 7. НОВЫЙ КНИЖНЫЙ СЦЕНАРИЙ

Файл:
`20-QWEN3-TTS-MLX-BOOK-AUDITION-SCRIPT.json`

Там:
- `text` = только то, что должно быть произнесено;
- `audiobook_instruct` = отдельная control-инструкция;
- `pause_after_ms` = цифровая тишина, которую вставляет runner после синтеза;
- generation settings зафиксированы и одинаковы для всех speaker.

Stage A использует настоящий фрагмент вступления книги с:
- повествованием;
- внутренней репликой;
- иронией;
- длинной фразой;
- короткой фразой;
- ритмическим перечислением.

Это audition аудиокниги, а не тест скороговорки.

---

## 8. MLX RUNNER

Файл:
`21-QWEN3-TTS-MLX-AUDIOBOOK-RUNNER.py`

Он:
- работает через `mlx_audio.tts.utils.load_model`;
- требует Apple Silicon arm64;
- использует только подготовленный MLX model id;
- передаёт модели clean `text` + separate `instruct`;
- не использует cloning/SSML/stress markup;
- одинаково seed-ит соответствующие сегменты;
- сохраняет каждый сегмент;
- делает минимальный edge fade;
- вставляет `pause_after_ms` как цифровую тишину;
- собирает `BOOK-AUDITION-MLX-<speaker>.wav`;
- пишет `RUN-REPORT.json`;
- фиксирует reported MLX peak memory и времена.

---

## 9. ТОЧНОЕ СЛЕДУЮЩЕЕ ЗАДАНИЕ CODEX

Файл:
`19-QWEN3-TTS-MLX-AUDIO-M1-CODEX-TASK.md`

Выполнить буквально.

Новый test dir:
`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

Если существует — STOP, не перезаписывать.

Использовать существующий Python 3.11.16, отдельный venv и отдельный HF cache внутри test dir.

### Порядок

1. pinned MLX-Audio v0.4.5;
2. только bf16 0.6B CustomVoice;
3. smoke: Serena + первый книжный сегмент;
4. если smoke WAV есть — Stage A всех 9 speaker;
5. после 9 WAV STOP;
6. пользователь слушает и выбирает максимум 1–2 финалиста.

Stage B автоматически НЕ запускать.

---

## 10. УДАРЕНИЯ

Файл:
`17-QWEN3-TTS-PRONUNCIATION-GATE.json`

Не добавлять stress syntax заранее.
Сначала услышать реальный русский WAV.
Потом фиксировать только фактически неправильные слова отдельными TTS-overrides, не в master.

Известное правильное произношение:
**Елена ДИлон**.

---

## 11. ЧТО НЕЛЬЗЯ ДЕЛАТЬ

- Не возвращаться к Qwen voice cloning.
- Не возвращаться к PyTorch/MPS PR #345.
- Не менять старые Qwen/MLX окружения.
- Не использовать старый HF cache для нового теста.
- Не делать общую чистку Mac.
- Не ставить новый системный Python.
- Не делать Homebrew update/upgrade.
- Не ставить ffmpeg ради WAV.
- Не делать автоматический fallback на 8bit/6bit/1.7B.
- Не monkey-patch MLX-Audio.
- Не менять audiobook instruct до первого прослушивания.
- Не менять текст/паузы сценария.
- Не использовать SSML и выдуманные stress marks.
- Не менять master.
- Не запускать Stage B, главу или книгу до пользовательского выбора.
- Не выбирать победителя вместо пользователя.
- Не возвращаться к Silero/Piper/Chatterbox.
- ZONOS2 не активен.

---

## 12. ЗАКРЫТЫЕ ДВИЖКИ / ПУТИ

- Silero — FAIL / CLOSED: авточтец.
- Piper — FAIL / CLOSED: качество не принято.
- Qwen voice cloning — FAIL / CLOSED.
- Qwen PyTorch/MPS PR #345 — TECHNICAL FAIL / CLOSED.
- Chatterbox V3 — FAIL / CLOSED, не чинить Perth.
- ZONOS2 — SUPERSEDED / NOT ACTIVE.

---

## STATUS

`MASTER SOURCE: LOCKED / UNCHANGED`
`SILERO: FAIL / CLOSED`
`PIPER: FAIL / CLOSED`
`QWEN VOICE CLONING: FAIL / CLOSED`
`QWEN PYTORCH/MPS PR #345: TECHNICAL FAIL / CLOSED`
`CHATTERBOX: FAIL / CLOSED`
`ZONOS2: SUPERSEDED / NOT ACTIVE`
`QWEN 0.6B CUSTOMVOICE MODEL: ACTIVE`
`ACTIVE RUNTIME: MLX-AUDIO v0.4.5 @ 04151c6abb74b886f879a4457ccdc96761f10102`
`ACTIVE MODEL: mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`
`RUSSIAN: SUPPORTED`
`PRESET SPEAKERS: 9`
`VOICE CLONING: NO`
`AUDIOBOOK INSTRUCT: ENABLED IN THIS MLX PATH`
`MLX SCRIPT: READY`
`MLX RUNNER: READY`
`NEXT ACTION: EXECUTE 19-QWEN3-TTS-MLX-AUDIO-M1-CODEX-TASK.md`
`FULL BOOK: HOLD UNTIL HUMAN PASS + LONG TEST`
