# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Current accepted production-code baseline after Dilon technical QA:** `219423deb464c9e0cb402a8b1bf5b6a981a0a396`

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
6. `DILON_IDENTITY_V1_OFFLINE_PREFLIGHT` — ACCEPTED;
7. `DILON_IDENTITY_V1_NO_MUSIC_BUILD` — ACCEPTED;
8. `DILON_OPENING_CREDIT_OFFLINE_PREPARE` — ACCEPTED;
9. `DILON_IDENTITY_V1_TECHNICAL_QA` — ACCEPTED.

Recent Dilon checkpoints:

```text
PR #16 offline preflight feature HEAD:
8a75cfa798f13f09d371e63e286772838df847f6
merge/main:
53c1f5b836d25c1802a435392950dc22a8314e39

PR #17 no-music identity build final feature HEAD:
6de551256fad655499a441f32a0e9212391d6c22
merge/main:
a8c53e00feba8593d5e7b3088574b3ade460f4ca

PR #18 opening-credit offline PREPARE final feature HEAD:
75ee0a7f8d178b95cc87dfe55c4801fe1199b1e2
merge/main:
171dede3bd2f9a7de926ee71ae111b160b29764a

PR #19 Dilon identity technical QA final feature HEAD:
99dbd20e5eaf7f21cc1534e8a736283203fa8831
merge/main:
219423deb464c9e0cb402a8b1bf5b6a981a0a396
```

Accepted Dilon slices passed exact-head Python offline CI and macOS native contract/build/strict codesign. No accepted Dilon slice performed provider/network TTS requests, paid execution, signature/music use or production Desktop deployment.

`DILON_IDENTITY_V1` as a whole is **NOT ACCEPTED YET**: normal native/bridge flow and real reviewed opening-credit production authority remain to be closed.

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

## 5. Assembly / mastering / LitRes export

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

LitRes profile:

```text
litres_author_v1
```

Release authority fail-closes on stale/corrupt/noncanonical pointers, path/symlink violations and invalid immutable packages. Whole-book `RELEASE_READY` запрещён до наличия всех обязательных глав.

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

## 7. DILON_IDENTITY_V1 — что уже принято

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

### Offline preflight

Accepted preflight требует exact-current canonical clean master, exact canonical opening-credit text, automatic QA, `manual_state=APPROVED`, exact reviewed SHA/path/synthesis fingerprint и fail-closed rights evidence для любого optional signature/music asset.

### No-music identity build

Accepted provider-neutral builder публикует immutable derived identity package only from canonical READY preflight:

```text
exact reviewed opening credit
→ fixed 0.5 s digital silence
→ exact-current clean master
→ identity.wav + MANIFEST.json + canonical CURRENT.json
```

Build is deterministic, preserves clean-master/opening-credit source bytes, enforces PCM16 mono 48 kHz, zero clipped PCM samples, canonical output containment, immutable manifest envelope and crash-safe pointer recovery.

No-music path является каноническим.

### Technical QA

Accepted technical QA independently verifies the exact-current immutable identity output against:
- exact reviewed opening-credit SHA/path/fingerprint;
- exact current clean-master SHA/path authority;
- exact component order;
- exact 0.5 s digital-silence gap;
- frame count/duration;
- PCM format;
- zero clipping;
- immutable package/current-pointer integrity.

Technical QA does not replace human listening.

### Signature/music

Candidate:

```text
Lounge Vibes 05.7
```

Asset **НЕ release-approved**. Никакого music/signature use без explicit proven rights/provenance. Отсутствие доказанных прав не блокирует canonical no-music path.

---

## 8. Opening credit — paid action подготовлен, но НЕ разрешён

PR #18 принял только offline PREPARE contour. Frozen production route:

```text
profile = yandex_lera
voice = lera
emotion = neutral
speed = 1.04
```

Current recorded local pricing authority for canonical phrase:

```text
billing units = 1
provider request cap = 1
estimated cost = 0.21146666 RUB
hard limit = 10.00 RUB
```

Цена обязана быть revalidated непосредственно перед будущим provider execution.

Если exact-current reviewed opening-credit WAV ещё не существует, следующий реальный production action:

```text
revalidate PREPARE
→ explicit owner paid authorization
→ ONE bounded Yandex request
→ automatic QA
→ exact-identity human listening/review
→ only then Dilon identity build + technical QA on real artifact
```

На текущем этапе provider execution не авторизован.

---

## 9. Current active launch work

Следующий безопасный slice, который необходимо закрыть без денег/Codex:

```text
DILON_IDENTITY_NATIVE_BRIDGE_V1
```

Цель normal macOS flow без Terminal:
- provider-neutral Dilon identity status;
- current clean-master identity/status;
- opening-credit authority/status/blockers;
- exact identity output status;
- exact-output preview/play through existing embedded player;
- technical QA result;
- no-music / signature-rights state;
- downstream readiness without false `RELEASE_READY`;
- exact-selection invalidation and stale-authority fail-closed behavior;
- Unicode canonical book-slug compatibility;
- provider/network/paid actions remain impossible from status/preview path.

После этого offline contour должен быть максимально готов к единственному реальному external step: opening-credit production + human listening, если готового exact reviewed artifact нет.

---

## 10. Provider / billing safety

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

## 11. Current launch checkpoint

```text
ACCEPTED_PRODUCTION_CODE_BASELINE = 219423deb464c9e0cb402a8b1bf5b6a981a0a396
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
DILON_IDENTITY_V1_OFFLINE_PREFLIGHT = ACCEPTED
DILON_IDENTITY_V1_NO_MUSIC_BUILD = ACCEPTED
DILON_OPENING_CREDIT_OFFLINE_PREPARE = ACCEPTED
DILON_IDENTITY_V1_TECHNICAL_QA = ACCEPTED
DILON_IDENTITY_V1_NATIVE_BRIDGE = NEXT
DILON_IDENTITY_V1 = IN_PROGRESS
REAL_BOOK_E2E_ACCEPTANCE = AFTER_DILON
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_CURRENT_DILON_OFFLINE_WORK = 0
PAID_EXECUTION_DURING_CURRENT_DILON_OFFLINE_WORK = 0
BILLING_CHANGED_DURING_CURRENT_DILON_OFFLINE_WORK = FALSE
PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

Главный принцип: каждый следующий action должен сокращать путь к launch, сохранять exact authority и не возвращаться к принятым gates без нового конкретного дефекта.
