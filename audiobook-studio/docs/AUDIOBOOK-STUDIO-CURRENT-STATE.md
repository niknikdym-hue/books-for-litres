# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Current accepted main:** `219423deb464c9e0cb402a8b1bf5b6a981a0a396`

---

## 1. Authority и правила продолжения

GitHub `main` — source of truth кода и project authority. Этот файл — текущий status ledger. Стабильные архитектурные правила находятся в `docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md` и provider-specific contracts.

Перед каждым действием сначала проверять фактический `main`, открытые launch PR/issues и exact evidence. Сохранённые SHA — checkpoints, а не вечный HEAD.

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

## 2. Accepted launch gates

На `main` приняты:

1. `BOOK_TEXT_PREPARATION_V1` — ACCEPTED;
2. `CHAPTER_PRODUCTION_V1` — ACCEPTED;
3. `AUDIO_QA_REVIEW_V1` — ACCEPTED;
4. `CHAPTER_ASSEMBLY_V1` — ACCEPTED;
5. `MASTERING_EXPORT_V1` — ACCEPTED;
6. `DILON_IDENTITY_V1_OFFLINE_PREFLIGHT` — ACCEPTED;
7. `DILON_IDENTITY_V1_NO_MUSIC_BUILD` — ACCEPTED;
8. `DILON_OPENING_CREDIT_PREPARE_V1` — ACCEPTED;
9. `DILON_IDENTITY_TECHNICAL_QA_V1` — ACCEPTED.

Recent accepted checkpoints:

```text
CHAPTER_ASSEMBLY_V1 merge/main:
7d4e66a2a4ed6b340555faf29ffb6bf835529e2a

MASTERING_EXPORT_V1 final feature HEAD:
c74b92039d970b2b337c19836645eb4f54b85bca

MASTERING_EXPORT_V1 accepted merge/main checkpoint:
685dee54c82c3d24a8d7d82a4305b9e9193678d5

DILON offline preflight merge/main:
53c1f5b836d25c1802a435392950dc22a8314e39

DILON no-music immutable build merge/main:
a8c53e00feba8593d5e7b3088574b3ade460f4ca

DILON opening-credit offline PREPARE merge/main:
171dede3bd2f9a7de926ee71ae111b160b29764a

DILON technical QA merge/main:
219423deb464c9e0cb402a8b1bf5b6a981a0a396
```

`DILON_IDENTITY_V1` как весь production gate **ещё IN_PROGRESS**: offline architecture/build/QA уже приняты, но native status/preview integration и реальная reviewed opening-credit authority ещё не закрыты.

---

## 3. Первая реальная production-глава — НЕ ПЕРЕСИНТЕЗИРОВАТЬ

```text
book = hvatit-sebya-obestsenivat
job = chapter-ch001
section = Введение
provider/profile = yandex_lera
voice = lera
role = neutral
speed = 1.04
segments = 35
```

Canonical Yandex source WAV SHA-256:

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

Эта глава уже оплачена, прослушана и принята. Downstream gates используют существующие accepted artifacts; повторный synthesis запрещён.

---

## 4. Assembly / clean master / LitRes export

`CHAPTER_ASSEMBLY_V1` формирует provider-neutral exact-current chapter WAV из approved production audio без provider execution.

Clean-master preset:

```text
spoken_word_master_v1
48 kHz mono PCM16
-19 LUFS-I target
-3.0 dBTP ceiling
```

LitRes delivery profile:

```text
litres_author_v1
```

MASTERING/EXPORT защищены от stale/corrupt/noncanonical authority, cross-package aliases, symlink traversal, invalid cover/recovery envelope и stale cached native state. Whole-book `RELEASE_READY` запрещён до наличия всех обязательных глав.

---

## 5. Реальный статус книги: 1 / 16

```text
expected book sections = 16
real production chapters completed = 1
progress = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Оставшиеся production главы потребуют новых provider requests и отдельного explicit owner authorization перед paid execution.

---

## 6. Current launch gate — DILON_IDENTITY_V1

Canonical brand:

```text
Dilon Voices
```

Description:

```text
Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.
```

Production voice:

```text
yandex_lera = lera / neutral / 1.04
```

Canonical opening credit:

```text
Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.
```

Dilon identity — отдельный downstream derived layer; source/TTS/QA/assembly/clean master не изменяются.

### 6.1 Accepted preflight

Принятый `dilon_voices_identity_v1` требует:
- exact-current canonical clean master package;
- exact 48 kHz mono PCM16 authority;
- canonical opening-credit text;
- automatic QA evidence;
- `manual_state=APPROVED`;
- reviewed audio SHA/path/synthesis fingerprint;
- optional signature только с доказанными commercial audiobook rights/provenance;
- deterministic identity plan;
- provider/network requests `0`, paid execution `false`, billing unchanged.

### 6.2 Accepted no-music immutable build

Canonical safe path:

```text
reviewed opening-credit WAV
→ exact 0.5 s digital silence
→ exact clean master PCM
→ immutable Dilon identity WAV + MANIFEST + CURRENT
```

No-music path является каноническим. Music/signature не требуется для запуска identity layer.

### 6.3 Accepted opening-credit PREPARE

Offline PREPARE привязывает canonical credit к frozen `yandex_lera / lera / neutral / 1.04`.

Текущая локальная pricing authority даёт:

```text
maximum provider requests = 1
billing units = 1
estimated cost = 0.21146666 RUB
hard limit = 10.00 RUB
```

Цена должна быть повторно проверена непосредственно перед возможным execution.

PREPARE module физически не содержит execute/synthesize функции:

```text
provider requests = 0
remote request sent = false
paid execution = false
billing changed = false
```

Если reviewed opening-credit WAV отсутствует, будущая цепочка остаётся:

```text
fresh PREPARE / price revalidation
→ explicit owner authorization
→ maximum one Yandex request
→ automatic QA
→ human listening bound to exact identity
```

До explicit authorization никакого provider execution.

### 6.4 Accepted technical identity QA

Offline QA требует:
- exact-current immutable Dilon identity output;
- exact canonical credit text;
- current reviewed credit SHA/path/synthesis fingerprint;
- exact-current clean-master `CURRENT.json` authority;
- component order `opening_credit → gap → clean_master`;
- byte-for-byte opening-credit PCM equality;
- exact 24,000-frame / 0.5 s digital-silence gap;
- byte-for-byte clean-master PCM equality;
- exact total frame count, no trailing audio;
- no clipped PCM samples;
- no workspace-root symlink alias;
- provider/network/paid/billing = 0.

---

## 7. Signature/music

Candidate:

```text
Lounge Vibes 05.7
```

Asset **НЕ release-approved**. Не использовать без explicit proven rights/provenance. Отсутствие прав не блокирует canonical no-music path.

---

## 8. Следующие launch действия

Текущий безопасный путь:

```text
DILON_NATIVE_BRIDGE_STATUS_PREVIEW
→ real reviewed opening-credit authority if absent
→ DILON_IDENTITY_V1 final acceptance
→ REAL_BOOK_E2E_ACCEPTANCE
```

До Codex/owner-only действий Central Brain должен самостоятельно закрывать всё, что возможно offline:
- native/bridge Dilon status + exact-output preview/QA integration;
- Unicode slug contract alignment между Book Library и Dilon build, если ещё открыт;
- current-state/launch authority sync;
- tests/CI/native build/codesign.

Owner/Codex привлекать только когда реально нужен:
- paid opening-credit synthesis;
- human listening/approval;
- production Desktop deployment;
- доказательства прав на optional music/signature;
- новый launch blocker, который не может быть безопасно закрыт текущим контуром.

---

## 9. Current launch checkpoint

```text
MAIN_CODE_BASELINE = 219423deb464c9e0cb402a8b1bf5b6a981a0a396
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
DILON_IDENTITY_V1_OFFLINE_PREFLIGHT = ACCEPTED
DILON_IDENTITY_V1_NO_MUSIC_BUILD = ACCEPTED
DILON_OPENING_CREDIT_PREPARE_V1 = ACCEPTED
DILON_IDENTITY_TECHNICAL_QA_V1 = ACCEPTED
DILON_IDENTITY_V1 = IN_PROGRESS
NEXT_OFFLINE_SLICE = DILON_NATIVE_BRIDGE_STATUS_PREVIEW
REAL_BOOK_E2E_ACCEPTANCE = AFTER_DILON
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_DILON_OFFLINE_WORK = 0
PAID_EXECUTION_DURING_DILON_OFFLINE_WORK = 0
BILLING_CHANGED_DURING_DILON_OFFLINE_WORK = FALSE
PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

Главный принцип: каждый следующий action сокращает путь к launch, сохраняет exact authority и не возвращается к принятым gates без нового конкретного дефекта.
