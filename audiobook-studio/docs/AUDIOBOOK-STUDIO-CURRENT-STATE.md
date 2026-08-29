# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Accepted feature baseline after PR #34:** `184f884274706fe1fc4e89e2b719ca9a8c474d99`

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
18. fail-closed native Swift Dilon card — PR #32;
19. native Dilon flow orchestration / exact-listened approval controller — PR #33;
20. mounted native Dilon flow in the normal Studio form — PR #34.

PR #34 acceptance evidence:
- final feature HEAD `950f8b4526adca6761dcef06e54c72227b9d011e`;
- merge/main baseline `184f884274706fe1fc4e89e2b719ca9a8c474d99`;
- exact-head workflow `Audiobook Studio Offline` run `#187`: SUCCESS;
- Python full offline suite: SUCCESS;
- macOS ARM64 native contract/build/strict codesign: SUCCESS;
- review threads: 0;
- open P1/P2: 0;
- provider/network requests: 0;
- paid execution: 0;
- billing mutation: false;
- production deployment: false.

The mounted native flow now lives in the normal `StudioView`. It owns one `DilonNativeFlowController`, binds only to the exact selected production book/chapter, clears Dilon snapshot/candidate/shared-player state when that selection changes, mounts the accepted `DilonNativeCard`, and wires approval only through the accepted exact-listened controller path. Canonical Unicode Book Library identity remains delegated to the accepted snapshot bridge; no ASCII-only slug transformation was introduced.

`DILON_IDENTITY_NATIVE_FLOW_V1 = ACCEPTED`.

`DILON_IDENTITY_V1` as a whole is **NOT ACCEPTED YET**. The remaining path must now be audited only for real opening-credit external readiness and human-listening acceptance; no accepted upstream gate is to be reopened without a new evidence-backed defect.

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

Accepted safeguards include exact clean-master/current-pointer binding, exact reviewed opening-credit SHA/path/fingerprint authority, deterministic preflight/build identities, PCM16 mono 48 kHz output, no-clipping/frame-count/component-order checks, immutable canonical output containment, crash-safe CURRENT recovery, Unicode canonical Book Library slugs, exact-listened native approval and no false whole-book release-ready state.

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
DILON_IDENTITY_EXTERNAL_READINESS_V1
```

The native/offline status, preview, review, exact-listened approval and mounted UI contour is accepted. The next safe work is a bounded audit of whether all repository-side preparation for the single future opening-credit provider action already exists. Central Brain must not treat owner authorization as the sole blocker until the code path can prove, without executing it, exact persisted plan identity, current price/voice/authority revalidation, one-request cap, unambiguous provider-result handling, automatic candidate QA and handoff into immutable `PENDING_HUMAN_REVIEW` without auto-approval.

If any of that executor/readiness contour is missing, implement and test it offline with fakes only; real provider requests remain forbidden. If the contour is already complete, stop at the exact owner-only gate and request explicit authorization for the bounded Yandex request plus subsequent human listening.

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
DILON_NATIVE_FLOW_ORCHESTRATION_V1 = ACCEPTED
DILON_NATIVE_MOUNTED_UI_V1 = ACCEPTED
DILON_IDENTITY_NATIVE_FLOW_V1 = ACCEPTED
DILON_IDENTITY_EXTERNAL_READINESS_V1 = IN_PROGRESS
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
