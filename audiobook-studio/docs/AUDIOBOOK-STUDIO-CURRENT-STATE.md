# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Accepted main after PR #35:** `f3620fb275ff86d98f5030436b0914c53b2f3cde`

---

## 1. Authority и safety

GitHub `main` — source of truth кода и project authority. Перед каждым действием сверять фактический `main`, launch issues/PR и exact-head CI.

Без отдельного bounded owner decision запрещены:
- provider/network TTS execution;
- paid execution;
- production Desktop deployment;
- system-package installation;
- destructive Git / force push / reset;
- предположение прав на сторонние audio/music assets.

Global OpenAI safety: `paid_execution_enabled = false`.

Никогда не выполнять silent retry после неоднозначного или отправленного provider request.

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
20. mounted native Dilon flow in normal Studio form — PR #34;
21. `DILON_IDENTITY_EXTERNAL_READINESS_V1` — PR #35.

### PR #34 native-flow acceptance

- feature HEAD `950f8b4526adca6761dcef06e54c72227b9d011e`;
- Python full offline suite SUCCESS;
- macOS ARM64 native contract/build/strict codesign SUCCESS;
- review threads 0;
- provider/network requests 0;
- paid execution 0;
- production deployment false.

The normal `StudioView` now contains the accepted Dilon flow. It binds only to the exact selected production book/chapter, invalidates Dilon state/player on selection change, exposes exact review candidates without automatic selection, and permits approval only through exact fully-listened SHA/path/fingerprint binding.

`DILON_IDENTITY_NATIVE_FLOW_V1 = ACCEPTED`.

### PR #35 external-readiness acceptance

- feature HEAD `fb8cf4d4280f0037f8b0184c553195f8c462435d`;
- merge commit `f3620fb275ff86d98f5030436b0914c53b2f3cde`;
- exact-head workflow `Audiobook Studio Offline` run `#193`: SUCCESS;
- Python full offline suite SUCCESS;
- macOS ARM64 native contract SUCCESS;
- native build + strict codesign SUCCESS;
- review threads 0;
- real provider/network requests during implementation/CI: 0;
- paid execution during implementation/CI: 0.

The accepted future one-request executor requires exact persisted `plan_id + plan_digest`, fresh price/voice/route/segmentation/fingerprint revalidation, explicit owner authorization and a hard one-request cap. It reuses completed exact results with zero new requests, blocks AMBIGUOUS/unrecoverable IN_FLIGHT/sent-FAILED retries, validates remote DONE against the billing ledger, preserves provider WAV bytes, normalizes a review copy to PCM16 mono 48 kHz and may hand off only to immutable `PENDING_HUMAN_REVIEW`; it cannot auto-approve.

`DILON_IDENTITY_EXTERNAL_READINESS_V1 = ACCEPTED`.

---

## 3. Canonical real book — accepted first chapter is immutable

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

Accepted provider WAV SHA-256:

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

This chapter must **never be re-synthesized** merely to satisfy later gates.

```text
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

---

## 4. Mastering / LitRes authority

Clean-master preset: `spoken_word_master_v1`.

Contract:
- provider-neutral WAV/LPCM;
- 48 kHz mono PCM16;
- target `-19 LUFS-I`;
- true-peak ceiling `-3.0 dBTP`;
- deterministic two-pass mastering;
- conservative boundaries;
- clean master preserved independently from Dilon/delivery outputs.

LitRes profile: `litres_author_v1`.

Release authority fails closed on stale/corrupt/noncanonical pointers, path/symlink violations and invalid immutable packages.

---

## 5. DILON_IDENTITY_V1 authority

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

Production voice:

```text
Yandex Lera / neutral / 1.04
```

Canonical no-music identity path:

```text
exact reviewed opening credit
→ fixed 0.5 s digital silence
→ exact-current clean master
→ immutable identity.wav + MANIFEST.json
→ independent technical QA
→ exact identity human listening
```

Candidate signature/music `Lounge Vibes 05.7` is **NOT release-approved**. Missing rights never blocks the canonical no-music path.

---

## 6. Current owner/provider gate

Repository-side external readiness is complete. If no exact-current reviewed opening-credit WAV already exists locally, remaining external sequence is now genuinely bounded:

```text
fresh offline PREPARE + exact current plan_id/digest/cost
→ explicit owner authorization
→ maximum 1 Yandex request
→ automatic candidate QA
→ immutable PENDING_HUMAN_REVIEW
→ exact candidate listening in mounted Studio UI
→ explicit exact-listened approval
→ no-music Dilon identity build
→ technical QA
→ exact identity listening
→ DILON_IDENTITY_V1 ACCEPTED
```

Historical PREPARE estimate:

```text
billing units = 1
provider request cap = 1
estimated cost ≈ 0.21146666 RUB
Dilon planning ceiling = 10.00 RUB
```

The historical estimate does **not** authorize execution. Fresh PREPARE is mandatory immediately before the real request.

---

## 7. Parallel final launch work

While the owner/provider gate is pending, Central Brain must prepare the final `REAL_BOOK_E2E_ACCEPTANCE` / production-launch preflight so the short external action is followed immediately by final acceptance rather than another engineering cycle.

The final E2E must prove the exact first-real-chapter chain:

```text
source/prepared authority
→ accepted Yandex chapter identity
→ QA/downstream approval
→ chapter assembly
→ clean master
→ LitRes chapter export
→ exact current Dilon identity + technical QA + human listening
→ production app candidate build/codesign
```

It must continue to report whole-book release-ready false while only 1/16 chapters exist.

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
DILON_IDENTITY_EXTERNAL_READINESS_V1 = ACCEPTED
DILON_IDENTITY_V1 = OWNER_PROVIDER_GATE
REAL_BOOK_E2E_ACCEPTANCE = PREPARE_IN_PARALLEL
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_PR35_OFFLINE_WORK = 0
PAID_EXECUTION_DURING_PR35_OFFLINE_WORK = 0
PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

Главный принцип: каждый следующий action сокращает путь к production launch; принятые gates не переоткрываются без нового конкретного evidence-backed дефекта.