# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-29  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Accepted production-code baseline:** `685dee54c82c3d24a8d7d82a4305b9e9193678d5`  
**Accepted feature HEAD for MASTERING_EXPORT_V1:** `c74b92039d970b2b337c19836645eb4f54b85bca`

---

## 1. Authority и правила продолжения

GitHub `main` — source of truth кода и project authority. Этот файл — текущий status ledger; стабильные архитектурные правила находятся в `docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md` и provider-specific contracts.

Перед каждым новым этапом сначала проверять фактический `main`, открытые launch issues/PR и exact evidence. Сохранённые SHA — checkpoints, а не вечный HEAD. Исторические manifests, billing events, paid plans и forensic evidence не переписываются задним числом.

Нельзя без отдельного bounded owner decision:
- provider/network TTS execution;
- paid execution;
- production Desktop deployment;
- system-package installation;
- force push / reset / destructive Git;
- предположение прав на сторонние audio/music assets.

Global OpenAI safety остается:

```text
paid_execution_enabled = false
```

Нет explicit user action → нет PREPARE → нет paid execution.

---

## 2. Что строим

Audiobook Studio — одно local-first macOS приложение с provider-neutral production pipeline:

```text
book/source
→ immutable source
→ TTS working copy / preprocessing
→ literary segmentation
→ Voice Library
→ provider adapter
→ fingerprint/cache
→ manifest/Resume
→ Audio QA/review
→ chapter assembly
→ clean mastering
→ Dilon Voices identity layer
→ delivery export
→ LitRes profile
```

TTS providers:
- Qwen / MLX Local;
- Yandex SpeechKit v3;
- OpenAI TTS.

Не создавать provider-specific дубликаты Book Library, QA, assembly, mastering, export, billing или native app.

---

## 3. Canonical local topology

```text
Repository checkout:
/Users/elenadymova/Documents/New project/books-for-litres

Studio home:
/Users/elenadymova/Documents/New project/Audiobook-Studio

Runtime workspace:
/Users/elenadymova/Documents/New project/Audiobook-Studio/runtime/studio-workspace

Staging build:
/Users/elenadymova/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app

Current Desktop app:
/Users/elenadymova/Desktop/Audiobook Studio.app
```

Desktop должен содержать ровно один текущий Audiobook Studio app icon. Старый convenience shortcut `Audiobook Studio — STAGING.app` удалён и не является частью текущей topology.

После MASTERING_EXPORT_V1 новый `main` еще НЕ развёрнут в production Desktop. Production deployment остаётся отдельным поздним owner-authorized действием.

---

## 4. Accepted launch gates

На `main` приняты:

1. `BOOK_TEXT_PREPARATION_V1` — ACCEPTED;
2. `CHAPTER_PRODUCTION_V1` — ACCEPTED;
3. `AUDIO_QA_REVIEW_V1` — ACCEPTED;
4. `CHAPTER_ASSEMBLY_V1` — ACCEPTED;
5. `MASTERING_EXPORT_V1` — ACCEPTED.

Ключевые recent checkpoints:

```text
AUDIO_QA_REVIEW_V1 accepted main:
450caf0a8c6ad291a1d96e23b1919f8f92e88341

QA runtime authority fix merged main:
4bd582e170cfe1687492b935aa0062ee9e55aafc

CHAPTER_ASSEMBLY_V1 merged main:
7d4e66a2a4ed6b340555faf29ffb6bf835529e2a

MASTERING_EXPORT_V1 final feature HEAD:
c74b92039d970b2b337c19836645eb4f54b85bca

MASTERING_EXPORT_V1 merge/main:
685dee54c82c3d24a8d7d82a4305b9e9193678d5
```

PR #15 exact-head CI `33248195757` — SUCCESS, включая offline tests и macOS native build / strict codesign. Все известные P1/P2 review threads были resolved. Последний fresh Codex review на exact `c74b920...` не смог стартовать только из-за исчерпанной Codex code-review quota; Central Brain выполнил независимый bounded audit последних fixes перед exact-head merge.

Во время MASTERING_EXPORT_V1:

```text
provider/network requests = 0
paid execution = 0
billing unchanged
production Desktop deployment = 0
```

---

## 5. Первая реальная production-глава — НЕ ПЕРЕСИНТЕЗИРОВАТЬ

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

Canonical Yandex source WAV:

```text
/Users/elenadymova/Documents/New project/Audiobook-Studio/runtime/studio-workspace/renders-yandex/hvatit-sebya-obestsenivat/chapter-ch001/yandex_lera/chapter-ch001__lera-neutral-1.04.wav
```

SHA-256:

```text
2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
```

Facts:

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

Этот real Yandex chapter уже оплачен, прослушан и принят. Его нельзя повторно синтезировать для downstream gates. Mastering, identity и export должны использовать уже принятые artifacts.

---

## 6. CHAPTER_ASSEMBLY_V1 — accepted contract

Accepted assembly формирует provider-neutral exact-current chapter WAV из approved production audio без нового provider execution.

Для реальной Yandex главы acceptance доказал canonical assembled WAV:
- 48 kHz;
- mono;
- PCM16;
- exact-current identity;
- source/provider WAV SHA не изменён;
- provider requests `0`;
- billing unchanged.

Assembly является входной authority для clean mastering.

---

## 7. MASTERING_EXPORT_V1 — accepted contract

### Clean master

Named preset:

```text
spoken_word_master_v1
```

Canonical contract:
- provider-neutral clean master;
- WAV/LPCM;
- 48 kHz;
- mono;
- PCM16;
- target integrated loudness `-19 LUFS-I`;
- true-peak ceiling `-3.0 dBTP`;
- deterministic two-pass loudnorm;
- conservative boundary policy;
- no aggressive trim;
- clean master отдельно от delivery MP3;
- no Dilon music/signature mixed into clean master.

Master artifacts сохраняются вне Git в provider-neutral `masters/` root и имеют immutable manifest/identity, input assembly identity/SHA, tool/version/arguments, output SHA и independent recovery validation.

### LitRes delivery profile

Named profile:

```text
litres_author_v1
```

Accepted first-upload contract:
- one MP3 per chapter/part;
- stereo dual-mono;
- target/recommended bitrate 128 kbps;
- each file <= 3 hours;
- each file <= 170 MB;
- whole book <= 500 files;
- canonical chapter order;
- decodable output;
- duration agreement with master;
- metadata / title / author / chapter identity recorded;
- cover copied/embedded only from canonical validated asset;
- release package fails closed on stale/corrupt/noncanonical package authority;
- rights blockers prevent `RELEASE_READY`.

M4B остается non-blocking для первого LitRes launch path.

MASTERING_EXPORT_V1 отдельно защищает canonical release authority от stale pointers, malformed manifests, cross-package/cross-root aliases, symlink traversal, invalid/missing cover, bad recovery envelope и cached native release state после fail-closed sweep.

---

## 8. Реальный статус книги: 1 / 16

Текущая production readiness книги:

```text
expected book sections = 16
real production chapters completed = 1
progress = 1/16
```

Поэтому Audiobook Studio pipeline значительно продвинут, но **вся аудиокнига НЕ RELEASE_READY**. Нельзя публиковать whole-book `RELEASE_READY`, пока отсутствуют обязательные главы/части.

Оставшиеся production главы потребуют новых Yandex provider requests и отдельного explicit owner authorization перед paid execution.

---

## 9. Следующий launch gate — DILON_IDENTITY_V1

Current launch gate after accepted MASTERING_EXPORT_V1:

```text
DILON_IDENTITY_V1
issue #12
```

Canonical public brand:

```text
Dilon Voices
```

Approved description:

```text
Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.
```

Current LitRes production voice attribution:

```text
Yandex Lera / neutral / 1.04
```

Opening credit contract:

```text
Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.
```

Dilon identity — отдельный downstream derived layer. Он не имеет права изменять source, TTS, QA, assembly или clean master.

Identity output должен быть отдельным immutable derived artifact/manifest; clean master всегда сохраняется отдельно.

### Signature/music

Candidate signature asset:

```text
Lounge Vibes 05.7
```

Он **НЕ release-approved**, пока rights/provenance не доказаны. Отсутствие прав не должно блокировать no-music identity path.

Нельзя автоматически добавлять музыку/подпись и нельзя утверждать права по предположению.

### Opening credit synthesis

Если точного текущего уже принятого credit audio нет и требуется новый synthesis, это отдельное provider/paid действие:

```text
PREPARE
→ exact cost/evidence
→ explicit owner authorization
→ provider execution
→ QA/manual review
```

До explicit owner authorization provider request запрещён.

---

## 10. После DILON_IDENTITY_V1

Следующий gate:

```text
REAL_BOOK_E2E_ACCEPTANCE
```

Он должен доказать end-to-end provider-neutral путь на реальном accepted material без повторного синтеза первой Yandex главы:

```text
accepted source/provider audio
→ QA
→ assembly
→ clean master
→ optional approved Dilon identity layer
→ LitRes delivery export
→ release blockers/readiness
```

Полный real-book release closeout возможен только после готовности всех обязательных sections.

---

## 11. Provider / billing safety

Canonical rules:
- Yandex и OpenAI — внешние TTS providers;
- Qwen local — zero-API-cost local backend;
- no automatic paid execution;
- no hidden retry after ambiguous paid request;
- provider requests и billing facts всегда evidence-backed;
- unknown balance/cost не превращается в `0`;
- historical billing/paid-run evidence не редактируется задним числом.

Yandex production voice frozen for this book:

```text
yandex_lera = lera / neutral / 1.04
```

Yandex hard-limit guard остается отдельным от фактического balance.

---

## 12. Current launch checkpoint

```text
MAIN_CODE_BASELINE = 685dee54c82c3d24a8d7d82a4305b9e9193678d5
BOOK_TEXT_PREPARATION_V1 = ACCEPTED
CHAPTER_PRODUCTION_V1 = ACCEPTED
AUDIO_QA_REVIEW_V1 = ACCEPTED
CHAPTER_ASSEMBLY_V1 = ACCEPTED
MASTERING_EXPORT_V1 = ACCEPTED
DILON_IDENTITY_V1 = NEXT
REAL_BOOK_E2E_ACCEPTANCE = AFTER_DILON
REAL_BOOK_PROGRESS = 1/16
WHOLE_BOOK_RELEASE_READY = FALSE
PROVIDER_REQUESTS_DURING_LAST_GATE = 0
PAID_EXECUTION_DURING_LAST_GATE = 0
BILLING_CHANGED_DURING_LAST_GATE = FALSE
POST_PR15_PRODUCTION_DESKTOP_DEPLOYED = FALSE
```

Главный принцип продолжения: следующий action должен сокращать путь к launch и сохранять exact authority, а не возвращаться к уже принятым gates без нового конкретного дефекта.
