# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-09-06  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`

GitHub `main` — единственный source of truth кода и project authority.

Текущий `main` на момент этой фиксации:

```text
fa5e1ed9a3796333246af88b5fddd697720f0055
```

Последняя принятая Audiobook Studio feature-точка — merge PR #52 на этом же SHA. Открытый PR #53 относится к книге №3 и не изменяет канон Audiobook Studio.

---

## 1. Safety и неизменяемые правила

Без отдельного bounded owner action запрещены:

- provider/network TTS execution;
- paid execution;
- silent retry после ambiguous/sent request;
- уничтожение внешнего исходного TXT, уже произведённого audio, billing/provider records при удалении книги из Library;
- предположение прав на сторонние audio assets;
- изменение immutable source книги.

OpenAI global safety остаётся `paid_execution_enabled = false`.

Обычная работа автора должна выполняться через `Audiobook Studio.app`, не через Terminal.

---

## 2. Принятые Studio-изменения 2026-09-03 — 2026-09-06

### PR #45 — author-first Studio / production integration

Merge:

```text
a6377928856481456161a053701c2de79764182c
```

Приняты:

- editable TTS working copy при неизменяемом source;
- manual/opt-in editorial junk scan, advisory only;
- обязательный fail-closed только для реальных TTS/production defects и stale/unsafe identity;
- provider-neutral pronunciation/stress workflow;
- Unicode acute как canonical stress;
- Yandex/OpenAI pronunciation adapters;
- author-first native flow, Help/onboarding/sidebar;
- chapter sound design downstream от TTS/QA;
- approved Yandex Voice Library: Lera, Ermil, Kirill, Anton;
- per-book narrator selection;
- per-book delivery formats;
- TXT UTF-8 import contract;
- local updater without ZIP;
- release/cue identity hardening.

Старое draft-description PR #45 больше не является policy authority.

### PR #46 — Yandex configurable timeout

Merge:

```text
1bbb2265ad65b3a02c2c66e81f422d04abc4cc64
```

```text
production default = 180 s
allowed range = 1…600 s
```

Timeout валидируется до transport. Silent retry после sent/ambiguous request не добавлен.

### PR #47 — Yandex recovery UX

Merge:

```text
f246b787887e664422c7a35e8bc796610a7c7891
```

Continuation PREPARE — одна ожидаемая async-operation; recovery controls блокируются на время выполнения; готовый plan не готовится повторно.

### PR #48 — canonical Yandex QA handoff

Merge:

```text
6ce6b67ce2c9e964db7da908ded43c90f218b03b
```

После успешной записи Studio заново разрешает canonical current Yandex authority перед Audio QA; legacy/symlink execution path не используется как QA authority.

### PR #49 — persistent production steps / text stress selector

Merge:

```text
5278b7734a16bfa66c4c42d18e9887104cbf8541
```

Приняты:

- 7 production steps всегда видимы и кликабельны;
- выбранный step сохраняется;
- на `Ударения` виден текст книги;
- double-click word → stress checking;
- Command-F для длинного текста;
- stale pronunciation selection invalidates safely.

Final acceptance after merge:

```text
full offline suite = 708/708 PASS
Python CI = PASS
macOS ARM64 CI = PASS
render 1060×720 = PASS
render 900×620 = PASS
independent UX = PASS
native build / Info.plist / Mach-O / codesign = PASS
provider/network/paid = 0
```

### PR #51 — Global Pronunciation Dictionary / contextual homographs

Feature HEAD:

```text
2944a56e4844eecb10c445ac6e28de38d682f0fa
```

Merge:

```text
c3b0b301e6f04714f318a0a6d4ab21252011a947
```

GitHub workflow `Audiobook Studio Offline` run #332: SUCCESS.

Принято:

- private global `Словарь ударений`;
- global AUTO rules для однозначных owner corrections;
- priority `OCCURRENCE > BOOK > GLOBAL AUTO > default`;
- small versioned contextual registry для омографов;
- known contextual word никогда не становится AUTO только потому, что пользователь выбрал один вариант;
- unresolved contextual pronunciation блокирует только затронутый Yandex chapter/OpenAI segment;
- exact-place contextual save в native pronunciation UI;
- provider input получает выбранный BOOK/OCCURRENCE вариант без мутации immutable source.

Канонический contextual registry V1 содержит:

```text
замок
→ за́мок = строение, дворец или крепость
→ замо́к = запирающее устройство
```

Реальная owner-test migration доказана:

```text
dictionary revision: 10 → 11
legacy global: замок → замо́к / AUTO
new global: замок → за́мок / замо́к / REVIEW_REQUIRED
preferred = null
repeat migration: revision remains 11
existing BOOK choice замо́к = preserved
source bytes = preserved
working text bytes = preserved
provider/network/model/paid = 0
billing mutation = false
```

Acceptance:

```text
full offline suite = 750/750 PASS
render 1060×720 = PASS
render 900×620 = PASS
independent UX = PASS
Mach-O / Info.plist / strict codesign = PASS
GitHub CI = PASS
```

```text
PRONUNCIATION_DICTIONARY_V1 = ACCEPTED
```

### PR #50 — simple permanent book deletion

Merge:

```text
34017fdaed0d13f99e74bab2abb71d1ca9a8248d
```

Принято:

- visible trash action для user-added production books;
- confirmation позволяет выбрать permanent archive-free removal либо recoverable archive;
- permanent removal удаляет canonical Studio book profile/imported Studio assets;
- внешний исходный TXT, rendered audio, billing и provider records сохраняются;
- demo/legacy/traversal/symlink targets fail closed;
- destructive action блокируется во время recording/production/library mutation;
- UI сохраняет согласованное состояние при post-commit cleanup warning.

Acceptance PR #50:

```text
full offline suite = 715/715 PASS
native build / Info.plist / Mach-O / strict codesign = PASS
independent safety + UX review = PASS after P2 fixes
provider/network/paid = 0
real books removed during tests = 0
```

```text
BOOK_LIBRARY_PERMANENT_DELETE = ACCEPTED
```

### PR #52 — chapter cue crash + explicit trimming UX

Feature HEAD:

```text
7660fe3c610643960bc3d9cd76778eef2c250cfb
```

Merge/current main:

```text
fa5e1ed9a3796333246af88b5fddd697720f0055
```

GitHub workflow `Audiobook Studio Offline` run #335: SUCCESS.

Исправлен доказанный native SwiftUI crash: zero-width chapter-cue slider ranges падали в `Normalizing.init`.

Новый owner-facing контракт:

- выбор cue по умолчанию использует весь звук, который пользователь только что прослушал;
- trimming не происходит скрыто;
- trimming — отдельное явное optional действие;
- после сохранения фрагмента можно прослушать exact saved selection;
- есть one-click `вернуть весь звук`;
- overlapping selection saves защищены.

Acceptance:

```text
targeted sound/UI regressions = PASS
full offline suite = 757/757 PASS
fresh native build = PASS
strict codesign = PASS
GitHub CI = PASS
provider/remote/paid = 0
```

```text
CHAPTER_CUE_SELECTION_UX = ACCEPTED
```

---

## 3. Текущий native author flow

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

Основной экран — author-facing. Billing, SHA/fingerprint, advanced Content Quality и diagnostics не должны доминировать в production flow.

Help/onboarding является частью `.app`.

---

## 4. Импорт и Book Library

MVP import:

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

Оригинал книги не изменяется при подготовке, ударениях или синтезе.

Book Library поддерживает recoverable archive и, после PR #50, owner-confirmed permanent archive-free removal с сохранением внешнего source и downstream production records.

---

## 5. Словарь ударений

Authority:

```text
docs/PRONUNCIATION-DICTIONARY-V1.md
contracts/pronunciation-dictionary-v1.schema.json
```

Private runtime store:

```text
<AUDIOBOOK_STUDIO_HOME>/settings/pronunciation/user-dictionary-v1.json
```

Rule:

```text
исправить ударение один раз
→ применить к текущему context/book
→ сохранить owner evidence
→ upsert в global dictionary
→ AUTO применять в следующих книгах только если слово безопасно однозначно
```

Priority:

```text
OCCURRENCE > BOOK > GLOBAL AUTO > default pronunciation
```

Known homograph:

```text
замок → за́мок / замо́к · зависит от контекста
mode = REVIEW_REQUIRED
preferred = null
```

Никакой silent contextual guessing в V1.

Canonical storage — provider-neutral Unicode acute. Yandex/OpenAI adapters рендерят provider-specific форму позднее.

---

## 6. Voice Library

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

Narrator/profile сохраняется per book.

---

## 7. Звуковое оформление

Chapter cue остаётся optional downstream layer:

```text
clean TTS
→ Audio QA
→ approved narration
→ chapter cue
→ assembly
→ mastering
```

Смена cue или его trimming не запускает TTS заново.

Поддерживаются:

- `Без звука`;
- preview/playback;
- per-book selection;
- favorites/genre selection;
- user WAV import с owner rights attestation;
- локальные GarageBand assets при подтверждённой local provenance;
- explicit optional trimming;
- exact saved-selection preview;
- restore full sound.

Выбор cue использует весь прослушанный asset, пока владелец явно не включает trimming.

Исторический exact asset `Lounge Vibes 05.7` не найден. На Mac найден реальный `Lounge Vibes 05.caf`; он показывается под честным именем как любимый вариант владельца. Raw Apple asset отдельно не экспортируется.

---

## 8. Форматы выпуска

Per-book, без default:

```text
По главам
M4B
MP3
Архив высокого качества
```

Whole-book output заблокирован до готовности полного required chapter set.

---

## 9. Первая реальная книга

```text
book = hvatit-sebya-obestsenivat
accepted first job = chapter-ch001 / Введение
accepted provider/profile = yandex_lera
voice = lera / neutral / 1.04
accepted provider WAV SHA-256 = 2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
```

Known accepted facts:

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

Исторический gate denominator:

```text
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Позднейшие pronunciation/preparation changes не дают права пересинтезировать уже хороший WAV без реального изменения затронутого speech identity.

---

## 10. Dilon Voices

```text
Brand = Dilon Voices
Opening credit = Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.
Production voice = Yandex Lera / neutral / 1.04
```

No-music identity path остаётся безопасным default. Optional music/cue не должен блокировать clean speech path.

---

## 11. Private application-level Yandex acceptance — 2026-09-03

Normal Studio bridge + existing macOS Keychain credential прошли bounded live path:

```text
Keychain → Yandex SpeechKit → valid WAV → provider-neutral Audio QA
```

Exact smoke facts:

```text
book = private-yandex-live-smoke-20260903
job = chapter-ch001
profile = yandex_lera
text chars = 46
max provider requests = 1
actual provider requests = 1
retry = 0
actual local cost = 0.21146666 RUB
joined WAV SHA-256 = 24271d1807cac78e5a1a23b1ff31b02d766db8099482a78fa26e4ba5945b64d6
automatic Audio QA = PASS
manual review = UNREVIEWED
secret disclosure = 0
```

```text
APPLICATION_KEYCHAIN_TO_YANDEX_TO_AUDIO_QA = PASS
```

PR #46–#48 усилили этот путь без дополнительных provider calls при разработке.

---

## 12. Current checkpoint

```text
BOOK_LIBRARY_V1 = ACCEPTED
BOOK_LIBRARY_PERMANENT_DELETE = ACCEPTED
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
AUTHOR_FIRST_NATIVE_FLOW = ACCEPTED
HELP_ONBOARDING_NATIVE = ACCEPTED
PER_BOOK_YANDEX_NARRATOR_SELECTION = ACCEPTED
CHAPTER_SOUND_DESIGN = ACCEPTED
CHAPTER_CUE_SELECTION_UX = ACCEPTED
PER_BOOK_DELIVERY_FORMATS = ACCEPTED
YANDEX_CONFIGURABLE_TIMEOUT = ACCEPTED
YANDEX_RECOVERY_UI = ACCEPTED
YANDEX_CANONICAL_QA_HANDOFF = ACCEPTED
PERSISTENT_PRODUCTION_STEPS = ACCEPTED
BOOK_TEXT_STRESS_SELECTION = ACCEPTED
PRONUNCIATION_DICTIONARY_V1 = ACCEPTED
KNOWN_HOMOGRAPH_ZAMOK_REPAIR = ACCEPTED
CURRENT_STUDIO_FEATURE_MAIN = fa5e1ed9a3796333246af88b5fddd697720f0055
WHOLE_BOOK_RELEASE_READY = FALSE
```

Следующие Studio slices обязаны сохранять global pronunciation dictionary, contextual-homograph safety, book-delete preservation boundaries и explicit chapter-cue trimming UX. Уже принятые gates не переоткрывать без нового concrete evidence-backed defect.
