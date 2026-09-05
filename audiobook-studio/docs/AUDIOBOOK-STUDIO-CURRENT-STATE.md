# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-09-05  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`

GitHub `main` — единственный source of truth кода и project authority. Последняя принятая Audiobook Studio feature-точка в `main` — merge PR #49 `5278b7734a16bfa66c4c42d18e9887104cbf8541`. После неё в `main` есть литературные/Book 2 коммиты и authority-обновления, не меняющие принятую Studio feature-точку.

---

## 1. Safety и неизменяемые правила

Без отдельного bounded owner action запрещены:

- provider/network TTS execution;
- paid execution;
- silent retry после ambiguous/sent request;
- destructive production-data operations;
- предположение прав на сторонние audio assets;
- изменение immutable source книги.

OpenAI global safety остаётся `paid_execution_enabled = false`.

Обычная работа автора должна выполняться через `Audiobook Studio.app`, не через Terminal.

---

## 2. Что принято за последние 48 часов

### PR #45 — merged 2026-09-03

Merge commit:

```text
a6377928856481456161a053701c2de79764182c
```

Приняты в `main`:

- shared Content Quality lexicon infrastructure;
- editorial junk scan в Studio только manual/opt-in и advisory;
- mandatory auto-block только для реальных TTS/production technical defects, stale/unsafe identity и явно включённого owner text acceptance;
- editable TTS working copy при неизменяемом source;
- provider-neutral pronunciation/stress workflow;
- materialization canonical Unicode stress в working text;
- Yandex/OpenAI pronunciation adapters;
- возможность исправлять уже поставленное ударение после прослушивания;
- author-first native production flow;
- chapter sound design downstream от TTS/QA;
- approved Yandex Voice Library: Lera, Ermil, Kirill, Anton;
- per-book narrator selection;
- Help/onboarding/sidebar UX;
- per-book delivery formats;
- TXT import requirements;
- Yandex application-level live QA path;
- local updater without ZIP delivery;
- stale release/cue identity hardening.

PR #45 закрыт и merged. Его старое draft-description не является актуальной policy authority; актуальная policy находится в этом current-state и owner decision history.

### PR #46 — merged 2026-09-03

Merge commit:

```text
1bbb2265ad65b3a02c2c66e81f422d04abc4cc64
```

Yandex synthesis timeout больше не зашит в 60 s:

```text
production default = 180 s
allowed range = 1…600 s
```

Timeout валидируется до transport. После sent/ambiguous timeout automatic retry не добавлен.

### PR #47 — merged 2026-09-04

Merge commit:

```text
f246b787887e664422c7a35e8bc796610a7c7891
```

Исправлен Yandex continuation/recovery UX:

- PREPARE continuation — одна ожидаемая async operation;
- recovery controls блокируются на время операции;
- после готового continuation plan UI не запускает повторный PREPARE;
- пользователь получает явный переход к подтверждению озвучки.

### PR #48 — merged 2026-09-04

Merge commit:

```text
6ce6b67ce2c9e964db7da908ded43c90f218b03b
```

Исправлен handoff после успешной Yandex-записи:

```text
provider execution complete
→ re-resolve canonical current Yandex authority
→ Audio QA
```

Legacy/symlink execution output path больше не передаётся напрямую как QA authority.

### PR #49 — merged 2026-09-04

Merge commit:

```text
5278b7734a16bfa66c4c42d18e9887104cbf8541
```

Принято:

- все 7 production steps постоянно видимы и кликабельны;
- выбранный production step сохраняется;
- на `Ударения` снова виден текст книги;
- двойной клик по слову отправляет его в проверку ударения;
- Command-F помогает искать слово в длинной книге;
- stale pronunciation selection invalidates safely;
- duplicate horizontal step strip удалён.

Acceptance PR #49:

```text
full offline suite = 707/707 PASS
native build = PASS
Info.plist = PASS
Mach-O arm64 = PASS
strict codesign = PASS
render 1060×720 = PASS
render 900×620 = PASS
independent UX acceptance = PASS
provider/network/paid requests = 0
```

---

## 3. Незавершённая работа

### PR #50 — OPEN, НЕ accepted

```text
title = Add simple permanent book deletion from the sidebar
head = 1a021f164f76121da67e5a6cb236852a141f4e80
base = 5278b7734a16bfa66c4c42d18e9887104cbf8541
```

Заявлено в PR:

- trash action для user-added books;
- выбор permanent removal или recoverable archive;
- внешний TXT, rendered audio, billing/provider records должны сохраняться;
- destructive action блокируется во время production/library operations;
- local full suite 715/715 PASS;
- independent safety/UX review PASS.

До merge PR #50 не считать эту функцию частью canonical `main`.

---

## 4. Текущий native author flow

Семь постоянных шагов:

```text
1. Текст
2. Ударения
3. Звук глав
4. Диктор
5. Глава
6. Запись / прослушивание
7. Выпуск
```

Основной экран — author-facing. Billing, SHA/fingerprint, advanced Content Quality и диагностика не должны доминировать в production flow.

Help/onboarding является частью `.app`.

---

## 5. Импорт книги

MVP contract:

```text
TXT
UTF-8
<= 20 MiB
вся книга одним файлом
```

Immutable source:

```text
<book>/source/original.txt
```

Editable TTS working copy:

```text
<book>/tts/working.txt
```

Оригинал книги не изменяется при подготовке, расстановке ударений или синтезе.

---

## 6. Ударения — текущее состояние и новый канон

### Уже реализовано

Текущая Studio умеет:

- выбрать слово из текста;
- показать варианты ударения;
- записать BOOK/OCCURRENCE pronunciation override;
- материализовать BOOK stress в TTS working text;
- исправить ранее поставленное ударение;
- передать canonical stress provider adapter-у;
- Yandex: Unicode acute → SpeechKit `+` markup;
- OpenAI: Unicode acute → pronunciation instruction;
- изменить working-copy/preparation identity только при реальном изменении текста/произношения.

### Новый обязательный V1 — глобальный «Словарь ударений»

Authority:

```text
docs/PRONUNCIATION-DICTIONARY-V1.md
contracts/pronunciation-dictionary-v1.schema.json
```

Private runtime store:

```text
<AUDIOBOOK_STUDIO_HOME>/settings/pronunciation/user-dictionary-v1.json
```

Главное правило владельца:

```text
исправила ударение один раз
→ Studio применяет его в текущей книге
→ автоматически запоминает в глобальном словаре
→ следующая книга использует правило автоматически
```

Приоритет:

```text
OCCURRENCE > BOOK > GLOBAL AUTO > default pronunciation
```

Омонимы защищены small versioned registry: известный contextual word никогда не
получает `AUTO` даже при первом owner correction. V1 содержит доказанный случай
`замок`: `за́мок` (строение) / `замо́к` (запирающее устройство). В native UI
выбор сохраняется для точного места и SHA текста; unresolved блокирует только
затронутый Yandex chapter или OpenAI segment.

Canonical storage — provider-neutral Unicode acute.

Существующие согласованные BOOK/OCCURRENCE pronunciation rules сохраняют приоритет.
Legacy global `AUTO` для известного омографа мигрируется идемпотентно в
`REVIEW_REQUIRED`, `preferred=null`, с обоими curated variants.

Private owner-test runtime migration доказана production-кодом 2026-09-05:

- normalized `замок`: revision `10 → 11`, `AUTO → REVIEW_REQUIRED`;
- variants после repair: `за́мок / замо́к`, `preferred=null`;
- повторный запуск: revision остаётся `11`, repair/changed entries = `0`;
- сохранённый BOOK override `замо́к`, profile bytes, working text и immutable source
  не изменились;
- provider/network/model/paid = `0`, billing mutation = `false`.

Runtime implementation принят после полного offline suite, native build/codesign и
независимой UX-проверки на окнах 1060×720 и 900×620. Словарь хранится только в
private Studio home, безопасно переживает обновление runtime, а его операции не
вызывают provider/model/network/paid/billing действий.

```text
PRONUNCIATION_DICTIONARY_V1 = ACCEPTED
```

---

## 7. Voice Library

Approved Yandex:

```text
yandex_lera   = lera   / neutral / 1.04
yandex_ermil  = ermil  / neutral / 1.0
yandex_kirill = kirill / neutral / 1.0
yandex_anton  = anton  / neutral / 1.0
```

Approved OpenAI:

```text
openai_onyx
openai_cedar
```

Выбранный narrator/profile сохраняется per book. Для текущей книги «Хватит себя обесценивать» accepted production narrator остаётся Lera 1.04, пока владелец явно не меняет его для будущей записи.

---

## 8. Звуковое оформление

Chapter cue остаётся optional и downstream:

```text
clean TTS
→ Audio QA
→ approved narration
→ chapter cue
→ assembly
→ mastering
```

Смена cue не запускает TTS заново.

Studio поддерживает:

- `Без звука`;
- preview/playback;
- per-book selection;
- выбор фрагмента;
- favorites/genre selection;
- user WAV import с owner rights attestation;
- локальные GarageBand assets при наличии и подтверждённой local license provenance.

Историческое название `Lounge Vibes 05.7` точным исходным asset не найдено. На Mac найден реальный `Lounge Vibes 05.caf`, он используется под собственным честным именем как любимый вариант владельца; raw Apple asset отдельно не экспортируется.

---

## 9. Форматы выпуска

Per-book selection, без default:

```text
По главам
M4B одним файлом
MP3 одним файлом
Архив высокого качества
```

Whole-book форматы недоступны до готовности полного required chapter set.

---

## 10. Первая реальная книга

```text
book = hvatit-sebya-obestsenivat
job = chapter-ch001
section = Введение
provider/profile = yandex_lera
voice = lera
speed = 1.04
segments = 35
```

Accepted provider WAV SHA-256:

```text
2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
```

Accepted facts:

```text
PCM16 mono 22050 Hz
duration = 347.001768707483 s
cost = 7.40133310 RUB
provider requests = 35
retries = 0
billing duplicates = 0
automatic QA = PASS
manual QA = APPROVED
```

```text
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Эту принятую главу не пересинтезировать без фактического изменения нужного текста/произношения.

---

## 11. Dilon Voices

Brand:

```text
Dilon Voices
```

Canonical opening credit:

```text
Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.
```

Canonical production voice:

```text
Yandex Lera / neutral / 1.04
```

No-music identity path остаётся безопасным default. Optional music/cue никогда не должен блокировать clean speech path.

---

## 12. Private application-level Yandex acceptance — 2026-09-03

Normal Audiobook Studio bridge + existing macOS Keychain credential прошли bounded live path:

```text
Keychain → Yandex SpeechKit → valid WAV → provider-neutral Audio QA
```

Exact live smoke facts:

```text
book = private-yandex-live-smoke-20260903
job = chapter-ch001
profile = yandex_lera
voice = lera / neutral / 1.04
text chars = 46
max provider requests = 1
actual provider requests = 1
retry = 0
estimated/actual local cost = 0.21146666 RUB
joined WAV SHA-256 = 24271d1807cac78e5a1a23b1ff31b02d766db8099482a78fa26e4ba5945b64d6
automatic Audio QA = PASS
manual review = UNREVIEWED
secret disclosure = 0
```

```text
APPLICATION_KEYCHAIN_TO_YANDEX_TO_AUDIO_QA = PASS
```

PR #46–#48 после этого усилили timeout/recovery/canonical QA handoff без новых provider calls при разработке.

---

## 13. Current checkpoint

```text
BOOK_LIBRARY_V1 = ACCEPTED
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
AUTHOR_FIRST_NATIVE_FLOW = ACCEPTED
HELP_ONBOARDING_NATIVE = ACCEPTED
PER_BOOK_YANDEX_NARRATOR_SELECTION = ACCEPTED
CHAPTER_SOUND_DESIGN = ACCEPTED
PER_BOOK_DELIVERY_FORMATS = ACCEPTED
YANDEX_CONFIGURABLE_TIMEOUT = ACCEPTED
YANDEX_RECOVERY_UI = ACCEPTED
YANDEX_CANONICAL_QA_HANDOFF = ACCEPTED
PERSISTENT_PRODUCTION_STEPS = ACCEPTED
BOOK_TEXT_STRESS_SELECTION = ACCEPTED
PRONUNCIATION_DICTIONARY_V1 = ACCEPTED
PR50_BOOK_DELETE = OPEN_NOT_ACCEPTED
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Следующие Studio slices обязаны сохранять контракт global pronunciation dictionary
из `PRONUNCIATION-DICTIONARY-V1.md` и не переоткрывать уже принятые gates.
