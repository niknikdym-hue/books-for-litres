# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-09-06  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`

GitHub `main` — единственный source of truth. Exact repository HEAD всегда проверяется live и не фиксируется здесь как вечный указатель, потому что `main` движется также из-за книжных и authority-коммитов.

Последний принятый **Audiobook Studio runtime feature merge**:

```text
PR #52
fa5e1ed9a3796333246af88b5fddd697720f0055
```

Открытый PR #53 относится к книге №3 и не меняет runtime authority Audiobook Studio.

---

## 1. Safety

Без отдельного bounded owner action запрещены:

- provider/network TTS execution;
- paid execution;
- silent retry после ambiguous/sent request;
- изменение immutable source книги;
- уничтожение внешнего исходного TXT, уже произведённого audio, billing/provider records при удалении книги из Library;
- предположение прав на сторонние audio assets.

OpenAI global safety: `paid_execution_enabled = false`.

Обычная работа автора — через `Audiobook Studio.app`, не Terminal.

---

## 2. Accepted Studio changes

### PR #45 — author-first Studio / production integration

```text
merge = a6377928856481456161a053701c2de79764182c
```

Приняты editable TTS working copy, manual/advisory editorial scan, provider-neutral pronunciation, Yandex/OpenAI adapters, author-first native flow, Help/onboarding, chapter sound design, Voice Library, per-book narrator, delivery formats, TXT import, updater without ZIP и production identity guards.

### PR #46 — configurable Yandex timeout

```text
merge = 1bbb2265ad65b3a02c2c66e81f422d04abc4cc64
production default = 180 s
allowed = 1…600 s
```

Silent retry после sent/ambiguous request не добавлен.

### PR #47 — Yandex recovery UX

```text
merge = f246b787887e664422c7a35e8bc796610a7c7891
```

Continuation PREPARE — одна awaited async-operation; повторный PREPARE готового plan не допускается.

### PR #48 — canonical Yandex QA handoff

```text
merge = 6ce6b67ce2c9e964db7da908ded43c90f218b03b
```

После успешной записи Audio QA получает re-resolved canonical current Yandex authority, а не legacy/symlink execution path.

### PR #49 — persistent production navigation / text stress selector

```text
merge = 5278b7734a16bfa66c4c42d18e9887104cbf8541
```

Приняты 7 постоянно видимых шагов, persistent step selection, текст книги на `Ударения`, double-click word и Command-F.

Final acceptance:

```text
full offline = 708/708 PASS
Python CI = PASS
macOS ARM64 CI = PASS
1060×720 = PASS
900×620 = PASS
independent UX = PASS
build / Info.plist / Mach-O / codesign = PASS
provider/network/paid = 0
```

### PR #51 — global pronunciation dictionary + contextual homographs

```text
feature HEAD = 2944a56e4844eecb10c445ac6e28de38d682f0fa
merge = c3b0b301e6f04714f318a0a6d4ab21252011a947
GitHub Audiobook Studio Offline run #332 = SUCCESS
```

Принято:

- private global `Словарь ударений`;
- safe AUTO rules для однозначных owner corrections;
- priority `OCCURRENCE > BOOK > GLOBAL AUTO > default`;
- small versioned contextual registry;
- known contextual word не становится AUTO после первого выбора;
- contextual choice сохраняется для exact place/book;
- unresolved contextual pronunciation блокирует только affected Yandex chapter/OpenAI segment;
- provider input получает выбранный pronunciation без мутации immutable source.

Canonical contextual V1:

```text
замок
→ за́мок = строение, дворец или крепость
→ замо́к = запирающее устройство
```

Реальная owner-test migration:

```text
revision 10 → 11
legacy global = замок → замо́к / AUTO
new global = замок → за́мок / замо́к / REVIEW_REQUIRED
preferred = null
repeat migration = revision 11, no duplicate change
existing BOOK choice замо́к = preserved
source / working text / profile evidence = preserved
provider/network/model/paid = 0
billing mutation = false
```

Acceptance:

```text
full offline = 750/750 PASS
1060×720 = PASS
900×620 = PASS
independent UX = PASS
Mach-O / Info.plist / strict codesign = PASS
GitHub CI = PASS
```

```text
PRONUNCIATION_DICTIONARY_V1 = ACCEPTED
KNOWN_HOMOGRAPH_ZAMOK_REPAIR = ACCEPTED
```

### PR #50 — simple permanent book deletion

```text
merge = 34017fdaed0d13f99e74bab2abb71d1ca9a8248d
```

Приняты:

- visible trash action для user-added production books;
- permanent archive-free removal или recoverable archive;
- permanent removal очищает canonical Studio book profile/imported Studio assets;
- внешний TXT, rendered audio, billing и provider records сохраняются;
- demo/legacy/traversal/symlink targets fail closed;
- deletion блокируется во время recording/production/library mutation.

Acceptance:

```text
full offline = 715/715 PASS
native build / Info.plist / Mach-O / codesign = PASS
independent safety + UX = PASS after P2 fixes
provider/network/paid = 0
real books removed during tests = 0
```

```text
BOOK_LIBRARY_PERMANENT_DELETE = ACCEPTED
```

### PR #52 — chapter cue crash + explicit trimming

```text
feature HEAD = 7660fe3c610643960bc3d9cd76778eef2c250cfb
merge = fa5e1ed9a3796333246af88b5fddd697720f0055
GitHub Audiobook Studio Offline run #335 = SUCCESS
```

Исправлен доказанный native crash из zero-width chapter-cue SwiftUI `Slider` range.

Owner-facing contract:

- выбор cue использует весь звук, который только что прослушан;
- hidden trimming запрещён;
- trimming — explicit optional action;
- saved fragment можно прослушать exact;
- есть one-click restore full sound;
- overlapping selection saves защищены.

Acceptance:

```text
targeted sound/UI = PASS
full offline = 757/757 PASS
fresh native build = PASS
strict codesign = PASS
GitHub CI = PASS
provider/remote/paid = 0
```

```text
CHAPTER_CUE_SELECTION_UX = ACCEPTED
```

---

## 3. Current native author flow

```text
1. Текст
2. Ударения
3. Звук глав
4. Диктор
5. Глава
6. Запись / прослушивание
7. Выпуск
```

Help/onboarding — внутри `.app`. Engineering diagnostics и billing не доминируют в основном flow.

---

## 4. Book Library / import

```text
TXT
UTF-8
<= 20 MiB
вся книга одним файлом
```

```text
immutable source = <book>/source/original.txt
editable TTS copy = <book>/tts/working.txt
```

Book Library поддерживает recoverable archive и accepted permanent removal с preservation boundaries PR #50.

---

## 5. Словарь ударений

Authority:

```text
docs/PRONUNCIATION-DICTIONARY-V1.md
contracts/pronunciation-dictionary-v1.schema.json
```

Private store:

```text
<AUDIOBOOK_STUDIO_HOME>/settings/pronunciation/user-dictionary-v1.json
```

```text
исправить ударение
→ применить к current context/book
→ сохранить evidence
→ upsert global dictionary
→ AUTO reuse only if safe and unambiguous
```

```text
OCCURRENCE > BOOK > GLOBAL AUTO > default
```

Known homograph `замок` всегда contextual:

```text
за́мок / замо́к
mode = REVIEW_REQUIRED
preferred = null
```

V1 не делает silent contextual guessing.

Canonical storage — Unicode acute; provider syntax создаётся adapter-слоем.

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

```text
clean TTS → Audio QA → approved narration → chapter cue → assembly → mastering
```

Смена cue/trimming не запускает TTS.

Поддерживаются `Без звука`, preview, per-book selection, favorites, user WAV с rights attestation, local GarageBand assets, explicit trimming, exact saved-fragment preview и restore full sound.

По умолчанию выбирается весь прослушанный cue; trimming включается только явно.

На Mac найден `Lounge Vibes 05.caf`, он показывается под честным именем как любимый owner option. Exact historical `Lounge Vibes 05.7` не найден.

---

## 8. Delivery

Per-book без default:

```text
По главам
M4B
MP3
Архив высокого качества
```

Whole-book output закрыт до полного required chapter set.

---

## 9. Первая реальная книга

```text
book = hvatit-sebya-obestsenivat
accepted chapter = chapter-ch001 / Введение
profile = yandex_lera
accepted WAV SHA-256 = 2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
```

```text
PCM16 mono 22050 Hz
duration = 347.001768707483 s
cost = 7.40133310 RUB
provider requests = 35
retries = 0
automatic QA = PASS
manual QA = APPROVED
WHOLE_BOOK_RELEASE_READY = FALSE
```

Accepted good WAV не пересинтезируется без реального изменения affected speech identity.

---

## 10. Dilon Voices

```text
Brand = Dilon Voices
Opening credit = Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.
Production voice = Yandex Lera / neutral / 1.04
```

No-music path — safe default; optional cue/music не блокирует clean speech path.

---

## 11. Private Yandex acceptance — 2026-09-03

```text
Keychain → Yandex SpeechKit → valid WAV → provider-neutral Audio QA = PASS
provider requests = 1
retry = 0
actual local cost = 0.21146666 RUB
joined WAV SHA-256 = 24271d1807cac78e5a1a23b1ff31b02d766db8099482a78fa26e4ba5945b64d6
automatic QA = PASS
secret disclosure = 0
```

PR #46–#48 усилили этот path без дополнительных provider calls при разработке.

---

## 12. Checkpoint

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
LATEST_ACCEPTED_STUDIO_RUNTIME_MERGE = fa5e1ed9a3796333246af88b5fddd697720f0055
WHOLE_BOOK_RELEASE_READY = FALSE
```

Следующие Studio changes обязаны сохранять contextual-homograph safety, pronunciation dictionary, PR #50 deletion preservation boundaries и explicit chapter-cue trimming UX. Принятые gates не переоткрывать без concrete evidence-backed defect.
