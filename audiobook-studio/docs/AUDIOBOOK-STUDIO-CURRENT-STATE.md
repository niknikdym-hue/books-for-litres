# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Current accepted main after Dilon opening-credit review bridge:** `5d6b03b35faf2db97336ae1d7c8ee85276fd4ed1`

---

## 1. Authority и правила продолжения

GitHub `main` — source of truth кода и project authority. Этот файл — текущий status ledger. Перед каждым следующим действием сверять фактический `main`, открытые launch issues/PR и exact-head CI.

Без отдельного bounded owner decision запрещены:
- provider/network TTS execution;
- paid execution;
- production Desktop deployment;
- system-package installation;
- destructive Git / force push / reset;
- предположение прав на сторонние audio/music assets.

Global OpenAI safety: `paid_execution_enabled = false`.

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

Shared Book Library, QA, assembly, mastering, identity, export, billing и native app остаются provider-neutral.

---

## 3. Accepted launch gates

На `main` приняты:

1. `BOOK_TEXT_PREPARATION_V1` — ACCEPTED;
2. `CHAPTER_PRODUCTION_V1` — ACCEPTED;
3. `AUDIO_QA_REVIEW_V1` — ACCEPTED;
4. `CHAPTER_ASSEMBLY_V1` — ACCEPTED;
5. `MASTERING_EXPORT_V1` — ACCEPTED;
6. `DILON_IDENTITY_V1_OFFLINE_PREFLIGHT` — ACCEPTED (PR #16);
7. `DILON_IDENTITY_V1_NO_MUSIC_BUILD` — ACCEPTED (PR #17);
8. `DILON_OPENING_CREDIT_OFFLINE_PREPARE` — ACCEPTED (PR #18);
9. `DILON_IDENTITY_V1_TECHNICAL_QA` — ACCEPTED (PR #19);
10. opening-credit immutable owner-plan store — ACCEPTED (PR #21);
11. offline Dilon identity bridge service — ACCEPTED (PR #22);
12. standalone Dilon current-status bridge — ACCEPTED (PR #24 + provenance correction PR #26);
13. opening-credit PREPARE CLI / exact plan lookup — ACCEPTED (PR #25);
14. `DILON_OPENING_CREDIT_REVIEW_AUTHORITY` — ACCEPTED (PR #27);
15. `DILON_OPENING_CREDIT_REVIEW_BRIDGE_V1` — ACCEPTED (PR #29).

PR #29 final accepted feature HEAD:

```text
3bd1438c69b63135788e68e1a2b8481652ad9484
```

Merge/main:

```text
5d6b03b35faf2db97336ae1d7c8ee85276fd4ed1
```

Acceptance evidence for PR #29:
- Python full offline CI: SUCCESS;
- macOS native contract/build/strict codesign: SUCCESS;
- review threads: 0;
- provider/network requests during review-bridge work: 0;
- paid execution: 0;
- billing mutation: false;
- production deployment: false.

The bridge exposes exact pending-candidate status and explicit approval bound to the exact SHA/path/synthesis identity actually listened to. Historical paid/provider provenance remains separate from the current offline review action. Missing/invalid arguments are machine-readable fail-closed JSON. Canonical Unicode book slugs remain supported.

`DILON_IDENTITY_V1` as a whole is **NOT ACCEPTED YET**. Native macOS flow and the real opening-credit external production/human-listening gate remain.

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

Accepted clean-master preset: `spoken_word_master_v1`.

Clean-master contract:
- provider-neutral WAV/LPCM;
- 48 kHz mono PCM16;
- target `-19 LUFS-I`;
- true-peak ceiling `-3.0 dBTP`;
- deterministic two-pass mastering;
- conservative boundaries;
- no destructive trim;
- clean master сохраняется отдельно от identity и delivery export.

LitRes profile: `litres_author_v1`.

Release authority fail-closes on stale/corrupt/noncanonical pointers, path/symlink violations and invalid immutable packages.

Whole-book progress remains:

```text
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
```

---

## 6. DILON_IDENTITY_V1 — accepted offline contour

Canonical public brand:

```text
Dilon Voices
```

Description:

```text
Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.
```

Opening-credit authority:

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

Accepted offline safeguards include:
- exact clean-master SHA/path/current-pointer binding;
- canonical opening-credit text;
- exact opening-credit SHA/path/synthesis fingerprint/manual approval;
- deterministic preflight and build identities;
- PCM16 mono 48 kHz contract;
- independent zero-clipping / frame-count / gap / component-order QA;
- canonical immutable output containment and crash-safe CURRENT recovery;
- Unicode canonical Book Library slug support at status/authority/review-bridge layers;
- no false whole-book release-ready state.

---

## 7. Opening-credit production / review authority

The offline path is ready around the only future provider action.

Accepted PREPARE facts for the canonical phrase:

```text
billing units = 1
provider request cap = 1
estimated cost ≈ 0.21146666 RUB
Dilon-specific planning ceiling = 10.00 RUB
```

Price/route/authority must be revalidated immediately before any provider execution.

The accepted review authority and bridge provide:
- immutable review candidate under `runtime/dilon-opening-credit/<book>/<job>/candidates/<candidate_id>`;
- exact plan_id / plan_digest / synthesis fingerprint / frozen `yandex_lera` / audio SHA / WAV binding;
- 48 kHz mono PCM16 + duration + non-silence + no-clipping automatic gate;
- `PENDING_HUMAN_REVIEW` with no canonical approval publication;
- machine-readable candidate status by exact `candidate_id + candidate_digest`;
- explicit `decision=APPROVE` bound to the exact listened SHA/path/fingerprint;
- revalidation of candidate bytes/manifest before canonical authority publication;
- preservation of historical provider/paid/billing provenance while review/status actions themselves stay offline and billing-neutral;
- structured offline errors instead of argparse/non-JSON failure for missing exact identifiers.

No automatic approval and no listening bypass exist.

If no already-reviewed opening-credit artifact exists, the remaining external sequence is:

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

Provider execution is not authorized by this document.

---

## 8. Signature/music

Candidate: `Lounge Vibes 05.7`.

It is **NOT release-approved**. No signature/music use until exact file identity, provenance and commercial audiobook rights are proven. Missing rights never block the canonical no-music path.

---

## 9. Current active launch work

Next safe launch-critical slice:

```text
DILON_IDENTITY_NATIVE_FLOW_V1
```

Normal macOS app must expose without Terminal:
- current Dilon status;
- exact clean-master identity/status;
- opening-credit status/blockers;
- offline PREPARE and exact plan status;
- pending review candidate status;
- exact candidate playback through the existing embedded player;
- explicit approval bound to the exact audio identity actually played/listened;
- exact identity output preview/playback;
- technical-QA result;
- no-music / optional-signature rights state;
- stale/selection-change fail-closed behavior;
- Unicode canonical book slug compatibility;
- provider/network/paid execution impossible from status/preview/review actions.

After the native flow is accepted, complete all remaining offline/pre-execution checks. Only then, if a reviewed opening-credit artifact is still absent, request explicit owner authorization for the one bounded Yandex opening-credit production call and subsequent human listening.

---

## 10. Current checkpoint

```text
ACCEPTED_MAIN = 5d6b03b35faf2db97336ae1d7c8ee85276fd4ed1
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
DILON_IDENTITY_NATIVE_FLOW_V1 = NEXT
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
