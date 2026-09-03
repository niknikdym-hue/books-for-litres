# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Accepted main through PR #38:** `b6dcd7927d3a6df447ae6e4fc85177ddd642f5f0`

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
21. `DILON_IDENTITY_EXTERNAL_READINESS_V1` — PR #35;
22. final exact-listened Dilon identity human-review authority + mounted native acceptance — PR #37;
23. read-only executable `REAL_BOOK_E2E_ACCEPTANCE` preflight — PR #38.

### PR #35 external-readiness acceptance

- feature HEAD `fb8cf4d4280f0037f8b0184c553195f8c462435d`;
- merge commit `f3620fb275ff86d98f5030436b0914c53b2f3cde`;
- exact-head workflow `Audiobook Studio Offline` run `#193`: SUCCESS;
- Python full offline suite SUCCESS;
- macOS ARM64 native contract/build/strict codesign SUCCESS;
- review threads 0;
- real provider/network requests during implementation/CI: 0;
- paid execution during implementation/CI: 0.

The future one-request opening-credit executor requires exact persisted `plan_id + plan_digest`, fresh price/voice/route/segmentation/fingerprint revalidation, explicit owner authorization and a hard one-request cap. It reuses completed exact results with zero new requests, blocks AMBIGUOUS/unrecoverable IN_FLIGHT/sent-FAILED retries, validates remote DONE against the billing ledger, preserves provider WAV bytes, normalizes a review copy to PCM16 mono 48 kHz and may hand off only to immutable `PENDING_HUMAN_REVIEW`; it cannot auto-approve.

`DILON_IDENTITY_EXTERNAL_READINESS_V1 = ACCEPTED`.

### PR #37 final Dilon human-review acceptance primitive

- feature HEAD `b8a69e066b16f29e7cb804195bcd884851847b3c`;
- merge commit `7d354a5100c6ae7c5b6740f1a0dd098b5680e8c9`;
- exact-head workflow run `#196`: SUCCESS;
- Python full offline suite SUCCESS;
- macOS native contract/build/strict codesign SUCCESS;
- review threads 0.

Final `identity.wav` now has a persisted exact-listened authority. Approval is possible only after full playback of the exact current Dilon identity and an independent rehash of live player binding (`build_identity + audio_sha256 + path_identity`). A changed/stale output returns to `PENDING_HUMAN_REVIEW`; no provider/paid action exists in this review path.

`DILON_FINAL_IDENTITY_HUMAN_REVIEW_PRIMITIVE = ACCEPTED`.

### PR #38 executable REAL_BOOK_E2E preflight

- feature HEAD `19f652ccd963298ddc422f6fdebeb551268176cc`;
- merge commit `b6dcd7927d3a6df447ae6e4fc85177ddd642f5f0`;
- exact-head workflow run `#198`: SUCCESS;
- Python full offline suite SUCCESS;
- macOS native contract/build/strict codesign SUCCESS;
- review threads 0.

`real_book_e2e.py` / `real_book_e2e_runner.py` provide a read-only fail-closed verdict for the exact first-real-chapter chain. The preflight deliberately does not rescan/decide QA, assemble, master, export, reconcile release pointers, approve human review, call providers or mutate billing. It independently requires the accepted first Yandex SHA and explicitly rejects whole-book `ready=true` while progress is 1/16. Before real Dilon completion it reports the remaining Dilon blocker; after completion it can turn green without another code change.

`REAL_BOOK_E2E_PREFLIGHT_V1 = ACCEPTED`.

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

Release authority fails closed on stale/corrupt/noncanonical pointers, path/symlink violations and invalid immutable packages. One chapter export may be valid while whole-book release remains correctly blocked by missing chapters.

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
Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.
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
→ full exact identity listening
→ persisted exact-listened final identity approval
```

Candidate signature/music `Lounge Vibes 05.7` is **NOT release-approved**. Missing rights never blocks the canonical no-music path.

---

## 6. Current owner/provider gate — the active production blocker

Repository-side engineering and final read-only acceptance tooling are prepared. If no exact-current reviewed opening-credit WAV already exists locally, the next action must happen on the actual Mac/runtime:

```text
fresh offline PREPARE
→ report exact current plan_id + plan_digest + provider request cap + current cost/price verification
→ STOP with provider requests = 0
→ explicit owner authorization
→ maximum 1 Yandex request
→ automatic candidate QA
→ immutable PENDING_HUMAN_REVIEW
→ exact candidate listening in mounted Studio UI
→ explicit exact-listened opening-credit approval
→ no-music Dilon identity build
→ independent technical QA
→ full exact identity listening
→ persisted final identity approval
→ rerun read-only REAL_BOOK_E2E preflight
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

## 7. Final launch sequence after fresh PREPARE

After the owner/provider/human-listening sequence completes, run `REAL_BOOK_E2E_PREFLIGHT_V1` against the actual Mac runtime. It must verify:

```text
source/prepared authority
→ accepted Yandex chapter SHA unchanged
→ persisted APPROVED QA
→ exact chapter assembly
→ exact clean master
→ exact LitRes chapter export
→ exact current Dilon identity + technical QA
→ persisted exact-listened final identity approval
```

Expected whole-book state remains:

```text
1 / 16
WHOLE_BOOK_RELEASE_READY = FALSE
```

If and only if this first-real-chapter E2E verdict is green, the remaining Studio launch action is production native candidate verification and **explicit owner authorization for production Desktop deployment**.

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
DILON_FINAL_IDENTITY_HUMAN_REVIEW_PRIMITIVE = ACCEPTED
REAL_BOOK_E2E_PREFLIGHT_V1 = ACCEPTED
DILON_IDENTITY_V1 = OWNER_PROVIDER_GATE
REAL_BOOK_E2E_ACCEPTANCE = WAITING_FOR_REAL_DILON_OUTPUT
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_PR35_PR37_PR38_OFFLINE_WORK = 0
PAID_EXECUTION_DURING_PR35_PR37_PR38_OFFLINE_WORK = 0
PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

---

## 9. Private application-level Yandex SpeechKit acceptance — 2026-09-03

This bounded live acceptance used the normal Audiobook Studio bridge and the
existing macOS Keychain credential.  The credential value was never exported,
printed, copied into configuration, or persisted in repository artifacts.

```text
repository branch = brain/content-quality-lexicon-v1
repository HEAD before evidence-only update = a3e61abd026228cbf1214e3fca23c5a88f7f9756
authoritative origin/main = e1a7e1c2c0440476189fd7ba6945547da75ebb97
Keychain service = AudiobookStudio-YandexSpeechKit
Keychain account = elenadymova
local health credentials_present = true
local health remote_request_sent = false
```

The private production smoke contained one Russian execution segment only:

```text
book = private-yandex-live-smoke-20260903
job = chapter-ch001
profile = yandex_lera
voice / role / speed = lera / neutral / 1.04
text characters = 46
plan_id = 1767a2f93ce24df6be7030aa2de7ae25
plan_digest = 9ae893dd7fad02e550d566862368d4a99295a229605d1627974a67b885310a71
PREPARE decision = READY_FOR_CONFIRMATION
credential_available = true
max_network_requests = 1
estimated_remaining_cost = 0.21146666 RUB
hard_limit = 20.00 RUB
PREPARE remote_request_sent = false
```

The exact plan was executed once.  No retry was performed:

```text
plan final state = CONSUMED
provider = yandex / yandex_speechkit_v3
network_requests = 1 / 1
segment = s0001
provider request id = dae0adc4-8474-4adb-82d4-b097a4c6a9fd
segment synthesis fingerprint = 84c1730e6ea378271e25f481ea71e72c97c12bf390678a800f9e9b179e3a50a0
joined WAV SHA-256 = 24271d1807cac78e5a1a23b1ff31b02d766db8099482a78fa26e4ba5945b64d6
joined WAV = PCM Int16 mono / 22050 Hz / 3.524943 s / 155494 bytes
billing transaction id = 1d19495a0e5d7ee7805be6ea3d71138c534a15eaf7adbf0c523c0683d4809bfd
billing actual_cost = 0.21146666 RUB
billing cost_source = local_actual
```

The same output then entered the normal provider-neutral Audio QA authority
resolver and scanner without any provider access:

```text
Audio QA synthesis fingerprint = f87705df3aa42aba7b284c5cdb1b25feb083593125bd15c2e9518e5dc9d3b05d
Audio QA audio SHA-256 = 24271d1807cac78e5a1a23b1ff31b02d766db8099482a78fa26e4ba5945b64d6
automatic_status = PASS
manual_state = UNREVIEWED
downstream_eligible = false
Audio QA remote_request_sent = false
```

Acceptance verdict:

```text
APPLICATION_KEYCHAIN_TO_YANDEX_TO_AUDIO_QA = PASS
TOTAL_PROVIDER_REQUESTS = 1
AUTOMATIC_RETRIES = 0
SECRET_DISCLOSURE = 0
```

Главный принцип: каждый следующий action сокращает путь к production launch; принятые gates не переоткрываются без нового конкретного evidence-backed дефекта.
