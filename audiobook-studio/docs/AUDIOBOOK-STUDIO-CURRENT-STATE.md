# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Current accepted main after DILON preflight:** `53c1f5b836d25c1802a435392950dc22a8314e39`

---

## 1. Authority и правила продолжения

GitHub `main` — source of truth кода и project authority. Этот файл — текущий status ledger. Стабильные архитектурные правила находятся в `docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md` и provider-specific contracts.

Перед каждым новым этапом сначала проверять фактический `main`, открытые launch issues/PR и exact evidence. Сохранённые SHA — checkpoints, а не вечный HEAD. Исторические manifests, billing events, paid plans и forensic evidence не переписываются задним числом.

Без отдельного bounded owner decision запрещены:
- provider/network TTS execution;
- paid execution;
- production Desktop deployment;
- system-package installation;
- force push / reset / destructive Git;
- предположение прав на сторонние audio/music assets.

Global OpenAI safety:

```text
paid_execution_enabled = false
```

Нет explicit owner action → нет provider execution.

---

## 2. Что строим

Audiobook Studio — local-first macOS production pipeline:

```text
book/source
→ immutable source
→ TTS working copy / preprocessing
→ provider adapter
→ exact fingerprint/cache
→ Audio QA/manual review
→ chapter assembly
→ clean mastering
→ Dilon Voices identity layer
→ LitRes delivery export
```

Providers: Qwen/MLX Local, Yandex SpeechKit v3, OpenAI TTS. Shared Book Library, QA, assembly, mastering, identity, export, billing и native app остаются provider-neutral.

---

## 3. Accepted launch gates

На `main` приняты:

1. `BOOK_TEXT_PREPARATION_V1` — ACCEPTED;
2. `CHAPTER_PRODUCTION_V1` — ACCEPTED;
3. `AUDIO_QA_REVIEW_V1` — ACCEPTED;
4. `CHAPTER_ASSEMBLY_V1` — ACCEPTED;
5. `MASTERING_EXPORT_V1` — ACCEPTED;
6. `DILON_IDENTITY_V1_OFFLINE_PREFLIGHT` — ACCEPTED.

Recent checkpoints:

```text
CHAPTER_ASSEMBLY_V1 merge/main:
7d4e66a2a4ed6b340555faf29ffb6bf835529e2a

MASTERING_EXPORT_V1 final feature HEAD:
c74b92039d970b2b337c19836645eb4f54b85bca

MASTERING_EXPORT_V1 accepted merge/main checkpoint:
685dee54c82c3d24a8d7d82a4305b9e9193678d5

DILON_IDENTITY_V1 offline-preflight accepted feature HEAD:
8a75cfa798f13f09d371e63e286772838df847f6

DILON_IDENTITY_V1 offline-preflight merge/main:
53c1f5b836d25c1802a435392950dc22a8314e39
```

PR #16 exact-head CI `33249190362` — SUCCESS. Independent Central Brain audit found no evidence-backed launch blocker in the bounded offline preflight slice.

For PR #16 / preflight acceptance:

```text
provider/network requests = 0
paid execution = 0
billing changed = false
production Desktop deployment = 0
opening-credit synthesis = 0
signature/music use = 0
```

`DILON_IDENTITY_V1` as a whole is **NOT ACCEPTED YET**. Only its offline authority/preflight slice is accepted.

---

## 4. Первая реальная production-глава — НЕ ПЕРЕСИНТЕЗИРОВАТЬ

Canonical real book:

```text
book = hvatit-sebya-obestsenivat
job = chapter-ch001
section = Введение
provider/profile = yandex_lera
voice = lera
emotion = neutral
speed = 1.04
segments = 35
```

Canonical Yandex source WAV SHA-256:

```text
2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
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

Эта глава уже оплачена, прослушана и принята. Downstream gates обязаны использовать существующие accepted artifacts, а не повторно синтезировать её.

---

## 5. CHAPTER_ASSEMBLY_V1 и MASTERING_EXPORT_V1

Accepted assembly формирует provider-neutral exact-current chapter WAV из approved production audio без provider execution. Реальная Yandex глава доказана как assembled 48 kHz mono PCM16 с неизменным source SHA.

Clean-master preset:

```text
spoken_word_master_v1
```

Clean-master contract:
- provider-neutral WAV/LPCM;
- 48 kHz mono PCM16;
- target `-19 LUFS-I`;
- true-peak ceiling `-3.0 dBTP`;
- deterministic two-pass mastering;
- conservative boundaries;
- no destructive trim;
- clean master сохраняется отдельно от identity и delivery export.

LitRes delivery profile:

```text
litres_author_v1
```

Release profile защищён от stale/corrupt/noncanonical authority, cross-package aliases, symlink traversal, invalid cover/recovery envelope и cached native state после fail-closed sweep. Whole-book `RELEASE_READY` запрещён до наличия всех обязательных глав.

---

## 6. Реальный статус книги: 1 / 16

```text
expected book sections = 16
real production chapters completed = 1
progress = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Оставшиеся production главы потребуют новых provider requests и отдельного explicit owner authorization перед paid execution.

---

## 7. Current launch gate — DILON_IDENTITY_V1

Canonical public brand:

```text
Dilon Voices
```

Description:

```text
Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.
```

Current LitRes production voice:

```text
Yandex Lera / neutral / 1.04
```

Opening-credit authority:

```text
Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.
```

Dilon identity — отдельный downstream derived layer. Он не имеет права изменять source, TTS working copy, QA-approved audio, canonical assembly или clean master.

### Accepted offline preflight

`dilon_voices_identity_v1` теперь на `main` и требует:
- exact-current clean master из canonical immutable `masters/<book>/<job>/<master_identity>/` package;
- 48 kHz mono PCM16 clean master, exact SHA/path/manifest identity;
- exact opening-credit text;
- automatic QA evidence;
- `manual_state=APPROVED`;
- exact reviewed audio SHA/path/synthesis fingerprint;
- optional signature asset только с явным `verified=true` и `commercial_audiobook_distribution=true` плюс непустой provenance/right-to-use;
- deterministic `identity_plan_id`;
- provider/network requests `0`;
- paid execution `false`;
- billing unchanged.

No-music path является каноническим и не блокируется отсутствием доказанных прав на signature/music.

### Signature/music

Candidate:

```text
Lounge Vibes 05.7
```

Asset **НЕ release-approved**. Никакого music/signature use без explicit proven rights/provenance.

### Opening credit

Если exact-current reviewed opening-credit WAV отсутствует, его получение — отдельное paid/provider действие:

```text
PREPARE
→ exact cost/request cap
→ explicit owner authorization
→ provider execution
→ automatic QA
→ exact-identity human review
```

До owner authorization никаких provider requests.

---

## 8. Следующий безопасный offline slice

После принятия PR #16 Central Brain начал следующий bounded slice: deterministic provider-neutral **no-music identity build/publish contour**.

Цель:

```text
READY Dilon preflight
→ reviewed opening-credit WAV
→ fixed explicit silence gap
→ exact clean master
→ immutable derived identity WAV + manifest + CURRENT
```

Этот slice должен оставаться полностью offline/billing-neutral и не использовать signature/music. Он не заменяет реальный human review и не разрешает synthesis opening credit.

После offline build contour остаются:
- real reviewed opening-credit authority (если такого artifact ещё нет — owner-authorized paid synthesis + QA/manual listening);
- final identity technical QA;
- native identity status/preview/blocker UX;
- затем `REAL_BOOK_E2E_ACCEPTANCE`.

---

## 9. Provider / billing safety

Canonical rules:
- no automatic paid execution;
- no hidden retry after ambiguous paid request;
- provider requests и billing facts evidence-backed;
- unknown balance/cost не превращается в `0`;
- historical billing/paid-run evidence не редактируется.

Yandex production voice frozen for this book:

```text
yandex_lera = lera / neutral / 1.04
```

---

## 10. Current launch checkpoint

```text
MAIN_CODE_BASELINE = 53c1f5b836d25c1802a435392950dc22a8314e39
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
DILON_IDENTITY_V1_OFFLINE_PREFLIGHT = ACCEPTED
DILON_IDENTITY_V1 = IN_PROGRESS
NEXT_OFFLINE_SLICE = NO_MUSIC_IDENTITY_BUILD_PUBLISH
REAL_BOOK_E2E_ACCEPTANCE = AFTER_DILON
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_PREFLIGHT = 0
PAID_EXECUTION_DURING_PREFLIGHT = 0
BILLING_CHANGED_DURING_PREFLIGHT = FALSE
PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

Главный принцип: каждый следующий action должен сокращать путь к launch, сохранять exact authority и не возвращаться к принятым gates без нового конкретного дефекта.
