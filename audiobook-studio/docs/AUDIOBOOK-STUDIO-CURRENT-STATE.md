# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Accepted feature baseline after PR #32:** `2c3fc2a046d592379ee5e33f4a83c7575e24028f`

---

## 1. Authority и safety

GitHub `main` — source of truth кода и project authority. Перед каждым действием сверять фактический `main`, открытые launch issues/PR и exact-head CI.

Без отдельного bounded owner decision запрещены:
- provider/network TTS execution;
- paid execution;
- production Desktop deployment;
- system-package installation;
- destructive Git / force push / reset;
- предположение прав на сторонние audio/music assets.

Global OpenAI safety: `paid_execution_enabled = false`.

---

## 2. Accepted launch gates

Приняты:

1. `BOOK_TEXT_PREPARATION_V1`;
2. `CHAPTER_PRODUCTION_V1`;
3. `AUDIO_QA_REVIEW_V1`;
4. `CHAPTER_ASSEMBLY_V1`;
5. `MASTERING_EXPORT_V1`;
6. `DILON_IDENTITY_V1_OFFLINE_PREFLIGHT` — PR #16;
7. `DILON_IDENTITY_V1_NO_MUSIC_BUILD` — PR #17;
8. `DILON_OPENING_CREDIT_OFFLINE_PREPARE` — PR #18;
9. `DILON_IDENTITY_V1_TECHNICAL_QA` — PR #19;
10. opening-credit immutable owner-plan store — PR #21;
11. offline Dilon identity bridge service — PR #22;
12. standalone Dilon current-status bridge — PR #24 + provenance correction PR #26;
13. opening-credit PREPARE CLI / exact plan lookup — PR #25;
14. `DILON_OPENING_CREDIT_REVIEW_AUTHORITY` — PR #27;
15. `DILON_OPENING_CREDIT_REVIEW_BRIDGE_V1` — PR #29;
16. `DILON_NATIVE_OFFLINE_SNAPSHOT_V1` — PR #30;
17. exact-current Dilon native preview backend binding — PR #31;
18. fail-closed native Swift Dilon card — PR #32.

PR #32 acceptance evidence:
- final feature HEAD `4b41fd1738065a444eedf539949d7cc15d7ac549`;
- merge/main baseline `2c3fc2a046d592379ee5e33f4a83c7575e24028f`;
- Python full offline CI: SUCCESS;
- macOS native contract/build/strict codesign: SUCCESS;
- review threads: 0;
- provider/network requests: 0;
- paid execution: 0;
- billing mutation: false;
- production deployment: false.

The compiled Swift card decodes exact Dilon status/review candidates/preview, requires explicit candidate selection, reuses `EmbeddedAudioPlayer`, binds playback to exact SHA/path/synthesis fingerprint, and keeps approval disabled until that exact candidate reaches full playback (`finished`). It exposes no provider/paid action and keeps whole-book release blocked.

`DILON_IDENTITY_V1` as a whole is **NOT ACCEPTED YET**. Remaining software work is native flow orchestration/mounting around the accepted card and bridges, followed by the real opening-credit external production + human-listening gate if no reviewed artifact already exists.

---

## 3. Canonical real book — do not re-synthesize accepted chapter

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

Accepted Yandex source WAV SHA-256:

```text
2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
```

Known facts:

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

This accepted chapter must not be re-synthesized merely to satisfy later gates.

```text
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

---

## 4. Mastering / export authority

Accepted clean-master preset: `spoken_word_master_v1`.

Clean-master contract:
- provider-neutral WAV/LPCM;
- 48 kHz mono PCM16;
- target `-19 LUFS-I`;
- true-peak ceiling `-3.0 dBTP`;
- deterministic two-pass mastering;
- conservative boundaries;
- clean master preserved independently from identity/delivery exports.

LitRes profile: `litres_author_v1`.

Release authority fails closed on stale/corrupt/noncanonical pointers, path/symlink violations and invalid immutable packages.

---

## 5. DILON_IDENTITY_V1 canonical authority

Brand:

```text
Dilon Voices
```

Description:

```text
Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.
```

Opening credit:

```text
Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.
```

Current production voice:

```text
Yandex Lera / neutral / 1.04
```

Canonical no-music path:

```text
exact reviewed opening credit
→ fixed 0.5 s digital silence
→ exact-current clean master
→ immutable identity.wav + MANIFEST.json
→ independent technical QA
→ human listening required
```

Accepted safeguards include exact clean-master/current-pointer binding, exact reviewed opening-credit SHA/path/fingerprint authority, deterministic preflight/build identities, PCM16 mono 48 kHz output, no-clipping/frame-count/component-order checks, immutable canonical output containment, crash-safe CURRENT recovery, Unicode canonical Book Library slugs and no false whole-book release-ready state.

Candidate signature/music `Lounge Vibes 05.7` is **NOT release-approved**. Missing rights never blocks the canonical no-music path.

---

## 6. Opening-credit external gate

Accepted offline PREPARE facts for canonical phrase:

```text
billing units = 1
provider request cap = 1
estimated cost ≈ 0.21146666 RUB
Dilon planning ceiling = 10.00 RUB
```

Price/route/authority must be revalidated immediately before any provider execution.

If no exact-current reviewed opening-credit artifact exists, external sequence remains:

```text
revalidate PREPARE
→ explicit owner paid authorization
→ one bounded Yandex request
→ automatic candidate QA
→ immutable review candidate
→ exact-identity human listening
→ explicit approval
→ no-music Dilon build
→ technical QA
```

No provider execution is authorized by this document.

---

## 7. Current active launch work

```text
DILON_IDENTITY_NATIVE_FLOW_V1
```

Accepted backend/native primitives now include: current status, PREPARE/plan lookup, review candidates, exact-listened approval bridge, aggregate native snapshot, exact-current identity preview binding, and a compiled fail-closed Dilon Swift card.

Immediate next safe slice is native flow orchestration around that card:
- load read-only snapshot for the selected canonical book/job;
- clear snapshot/candidate/playback on selection change;
- execute only the accepted offline exact-listened review approval;
- refresh snapshot after approval;
- keep provider/network/paid actions absent;
- preserve Unicode canonical Book Library slug identity;
- mount the card into normal Studio Form only after orchestration contract is green.

After native flow acceptance, complete remaining offline/pre-execution checks. Only if the reviewed opening-credit artifact is still absent may Central Brain request explicit owner authorization for the one bounded Yandex opening-credit call and subsequent human listening.

---

## 8. Current checkpoint

```text
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
DILON_IDENTITY_V1_OFFLINE_PREFLIGHT = ACCEPTED
DILON_IDENTITY_V1_NO_MUSIC_BUILD = ACCEPTED
DILON_OPENING_CREDIT_OFFLINE_PREPARE = ACCEPTED
DILON_IDENTITY_V1_TECHNICAL_QA = ACCEPTED
DILON_OPENING_CREDIT_REVIEW_AUTHORITY = ACCEPTED
DILON_OPENING_CREDIT_REVIEW_BRIDGE_V1 = ACCEPTED
DILON_NATIVE_OFFLINE_SNAPSHOT_V1 = ACCEPTED
DILON_NATIVE_IDENTITY_PREVIEW_BINDING_V1 = ACCEPTED
DILON_NATIVE_CARD_V1 = ACCEPTED
DILON_IDENTITY_NATIVE_FLOW_V1 = IN_PROGRESS
DILON_IDENTITY_V1 = IN_PROGRESS
REAL_BOOK_E2E_ACCEPTANCE = AFTER_DILON
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_CURRENT_DILON_OFFLINE_WORK = 0
PAID_EXECUTION_DURING_CURRENT_DILON_OFFLINE_WORK = 0
BILLING_CHANGED_DURING_CURRENT_DILON_OFFLINE_WORK = FALSE
PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

Главный принцип: каждый следующий action сокращает путь к launch, сохраняет exact authority и не возвращается к принятым gates без нового конкретного дефекта.
