# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-23  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Accepted code baseline:** `1414ebdbea358a8aa264651f2756a21d7edca8c9`
**Repository authority baseline before this edit:** `1414ebdbea358a8aa264651f2756a21d7edca8c9`

---

## 1. Назначение и приоритет authority

Этот документ хранит фактическую текущую точку Audiobook Studio и используется вместе с:

1. `docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md` — стабильная архитектура и производственный регламент;
2. `docs/OPENAI-TTS-BACKEND-CONTRACT.md` — provider-specific contract OpenAI;
3. `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md` — актуальный status ledger, acceptance, active checkpoint и launch readiness.

Правила:

- GitHub `main` является source of truth кода и authority;
- chat не является source of truth;
- перед каждым новым task сначала определять actual `origin/main`;
- сохранённые SHA — checkpoint evidence, а не вечный HEAD;
- старый status в стабильном документе уступает актуальному status здесь;
- стабильные архитектурные принципы этим ledger не отменяются;
- historical manifests, billing events и paid plans не переписываются задним числом;
- не создавать параллельные handoff/task docs, если факт может быть зафиксирован здесь.

---

## 2. Что строим

Audiobook Studio — одно local-first macOS приложение:

```text
Audiobook Studio
├── Qwen / MLX Local
├── Yandex SpeechKit v3
└── OpenAI TTS
```

Общий pipeline:

```text
book/source
→ immutable source
→ TTS working copy / preprocessing
→ literary segmentation
→ Voice Library
→ provider adapter
→ fingerprint/cache
→ manifest/Resume
→ QA/review
→ chapter assembly
→ mastering
→ Dilon Voices audio identity
→ export
→ LitRes profile
```

Не создавать provider-specific дубликаты book library, Voice Library, billing, manifest/Resume, QA, mastering, export или native app.

Собственный server/backend/cloud database/localhost daemon текущему продукту не нужен. Yandex и OpenAI — внешние cloud TTS providers; книги и production state остаются локальными.

---

## 3. Canonical local workspace

```text
Workspace:
/Users/elenadymova/Documents/New project/Audiobook-Studio

Repository checkout:
/Users/elenadymova/Documents/New project/books-for-litres

Production Desktop app:
/Users/elenadymova/Desktop/Audiobook Studio.app

Staging artifact:
/Users/elenadymova/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app

Convenience staging symlink:
/Users/elenadymova/Desktop/Audiobook Studio — STAGING.app
→ /Users/elenadymova/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app
```

Staging symlink не является production deployment.

---

## 4. Git policy

Никогда без отдельного bounded решения:

- `git reset`;
- force push;
- blind merge/rebase;
- `git add .`;
- `git add -A`;
- `git add --all`.

Stage только exact paths. Перед push всегда `git fetch origin` и divergence check. Если `origin/main` ушёл вперёд — не делать автоматический merge/rebase.

Local `?? .DS_Store` не является частью Audiobook Studio и не должен stage-иться ради проекта.

---

## 5. Repository state

Принятые OpenAI safety commits:

```text
ccd15f0ac21ab92850218749ffe47b8eb9eba303
Fix explicit OpenAI prepare user gate

4fda7281c3e65195bf4b0fe8d0d0a12d359219e3
Persist OpenAI paid request execution fact
```

Проверенная code parent chain:

```text
c251818566318ed52821835fe2824edc27e5a03e
→ ccd15f0ac21ab92850218749ffe47b8eb9eba303
→ 4fda7281c3e65195bf4b0fe8d0d0a12d359219e3
```

Canonical authority commits после code acceptance:

```text
e82c3c190c26f7737e875d16d345ad53a4f2caad
Record current Audiobook Studio authority state

c62d0cb30be401875aa07d9fe4701f3cb64af1c9
Link Audiobook Studio current-state authority

8d105bd3f36a6675d1ab427259de0c669adbc8fd
Update accepted OpenAI native paid workflow contract

a96b5e3472a110fd0ee6a4f9be8ac1f1f53ddde1
Document accepted native OpenAI paid workflow
```

Feature branch `fix/audiobook-openai-explicit-prepare-gate` больше не является authority contour. Accepted code и deployment authority находятся в `main`.

---

## 6. Runtime provisioning contract

Native app исполняет Python bridge из local runtime copy:

```text
/Users/elenadymova/Documents/New project/Audiobook-Studio/runtime/studio-workspace
```

Repository остаётся source of truth production code/config.

Во время OAI acceptance был доказан provisioning gap: сборка `.app` сама по себе не синхронизирует repository execution contour в runtime workspace.

Bounded current-main → runtime sync применяется только к production execution contour, включая Python runners, provider config/pricing JSON и `backends/` code-only contour.

Нельзя таким sync перезаписывать пользовательские books, settings, billing, cache, jobs, manifests, audio, exports или engines.

Tracked safe demo profile:

```text
audiobook-studio/books/demo-book.json
slug = demo-book
job = short-test
segment = t01
segments = 1
text length = 93
```

Post-merge DEPLOY-0 подтвердил bounded runtime provisioning current-main → production workspace по SHA без замены пользовательских данных.

Будущий production installation/update flow должен сохранять этот fail-safe provisioning contract и не зависеть от ручного копирования файлов.

---

## 7. Backends и Voice Library

### Qwen / MLX

Active local backend, API cost = 0.

9 runtime voices:

- Vivian;
- Serena;
- Uncle_Fu;
- Dylan;
- Eric;
- Ryan;
- Aiden;
- Ono_Anna;
- Sohee.

### Yandex SpeechKit v3

Active production cloud backend. Подтверждены segmentation, streaming transport, WAV validation, fingerprint/cache, manifest/Resume, AMBIGUOUS safety, pricing/hard limit и Cloud Billing.

Approved profiles:

- `yandex_lera`;
- `yandex_ermil`;
- `yandex_kirill`;
- `yandex_anton`.

Frozen/default LitRes production profile:

```text
Lera / neutral / 1.04
```

### OpenAI

Approved built-in profiles:

- `openai_onyx`;
- `openai_cedar`.

Они равноправны. Synthetic `openai_female/openai_male` не используются. `gender` не является обязательным identity dimension. Custom Voice = `DEFERRED`.

---

## 8. OpenAI transport acceptance

Canonical model:

```text
gpt-4o-mini-tts
response_format = wav
credential = macOS Keychain / AudiobookStudio-OpenAI
```

Historical smoke 1:

```text
AMBIGUOUS / INCONCLUSIVE
request_id = req_76fa9bd109ec440ebaf50506d675c309
```

Root cause: старый validator неверно трактовал legal streaming RIFF sentinel `0xFFFFFFFF`. Historical manifest не переписывается.

Historical Cedar validation PASS:

```text
profile = openai_cedar
HTTP = 200
request_id = req_84ebe20c7c7842b79306c098fd69050e
WAV = 24 kHz / 16-bit PCM / mono / 6.85 sec
RIFF sentinel = 0xFFFFFFFF
data sentinel = 0xFFFFFFFF
```

Подтверждены WAV validation, atomic final, cache, manifest `SUCCEEDED`, Resume replay без второго network request и idempotent ledger.

---

## 9. Safe native OpenAI paid execution v1 — ACCEPTED AND DEPLOYED

Global config остаётся:

```text
paid_execution_enabled = false
```

Permanent/global unlock запрещён.

Canonical native flow:

```text
explicit primary user action
→ LOCAL PREPARE confirmation
→ memory-only one-shot intent consume
→ network-free immutable PREPARE
→ separate paid confirmation
→ revalidate same plan/digest
→ PREPARED → CONSUMING
→ maximum one new provider request
→ CONSUMED
```

One-shot intent:

- initially unarmed;
- consume один раз;
- second consume forbidden;
- cancel/reload/error инвалидируют;
- изменение engine/book/job/profile инвалидирует;
- новый arm заменяет предыдущий.

CACHE_ONLY также требует explicit local user action, но provider network = 0 и paid confirmation не нужен.

### Zero-user-action invariant

После fix instrumented staging и затем production Desktop startup доказали:

```text
PREPARE without explicit user action = 0
--execute-paid-plan = 0
provider requests = 0
```

Canonical invariant:

```text
NO EXPLICIT USER ACTION
→ NO PREPARE
→ NO PAID EXECUTION
```

### Plan semantics

Local-only plans:

```text
runtime/paid-run-plans/<plan-id>.json
TTL default = 10 minutes
max_network_requests = 1
automatic retry = 0
```

`AMBIGUOUS` автоматически не retry. Каждый следующий new MISS/segment требует нового plan и отдельного confirmation.

---

## 10. Live native one-request acceptance — PASS

Во время native acceptance был выполнен ровно один фактический paid OpenAI request.

Фактическая process selection была Onyx default:

```text
profile = openai_onyx
book = demo-book
job = short-test
segment = s0001
characters = 93
```

Это не признано backend profile-substitution defect: новый process был запущен без deterministic Cedar launch env, а historical Cedar transport PASS уже существует.

Live evidence:

```text
HTTP = 200
request_id = req_ec29b6810200449791be47c8aabf201f
content_type = audio/wav
response bytes = 376844
24 kHz
16-bit PCM
mono
7.85 sec
attempt_count = 1
automatic_retry_count = 0
```

PASS:

- exactly one OpenAI request;
- WAV validation;
- atomic final;
- cache STORED;
- manifest `SUCCEEDED`;
- plan `PREPARED → CONSUMING → CONSUMED`;
- second execute blocked before network;
- billing one event;
- exact actual cost не сфабрикован.

Billing event:

```text
actual_cost = null
cost_source = unavailable
remaining = null
remaining_source = unavailable
```

Unknown никогда не трактуется как `$0`.

---

## 11. Persisted execution fact — FIXED + TESTED

Live forensic выявил pre-fix inconsistency: request был доказан, но historical plan сохранял `remote_request_sent=false`.

Historical plan не переписывался.

Fix `4fda728…` задаёт новые canonical semantics:

```text
NETWORK 1:
state = CONSUMED
network_requests = 1
remote_request_sent = true

CACHE_ONLY / NETWORK 0:
state = CONSUMED
network_requests = 0
remote_request_sent = false

AMBIGUOUS after network started:
state = CONSUMED
network_requests = 1
remote_request_sent = true
automatic retry = 0
```

Tests:

```text
Paid-run targeted = 11 / 11 PASS
Full offline suite = 214 / 214 PASS
Native contract = PASS
Native staging build = PASS
Strict codesign = PASS
```

Provider requests during fix = 0.

---

## 12. Forensic preservation

Не переписывать задним числом:

- historical AMBIGUOUS manifest;
- historical paid-run plans;
- pre-fix `remote_request_sent=false` historical plan;
- historical billing events.

Forensic evidence хранит правду о старом поведении; новые contracts действуют на новые executions.

---

## 13. Cloud Billing

Один provider-neutral layer для Yandex и OpenAI.

```text
Money = Decimal only
Yandex = RUB
OpenAI = USD
```

Provenance:

```text
provider_reported
local_actual
local_estimate
user_confirmed
unavailable
```

Правила:

- unknown balance не превращается в 0;
- estimate не становится actual;
- exact OpenAI prepaid balance не фабрикуется;
- future audio cost не фабрикуется как exact;
- ledger idempotent;
- hard limit не является balance;
- OpenAI acceptance hard limit = 1.00 USD.

Unknown money в UI = `Недоступно`, а не `$0/₽0`.

---

## 14. Production Desktop deployment — PASS

Post-merge closeout завершён:

```text
full offline suite = 214 / 214 PASS
fresh native staging build = PASS
strict codesign = PASS
bounded runtime provisioning = PASS
production Desktop deployment = PASS
zero-action production startup = PASS
```

Production bundle:

```text
/Users/elenadymova/Desktop/Audiobook Studio.app
```

Он установлен fail-safe replacement из accepted staging artifact и прошёл strict codesign.

Production startup вызвал только offline snapshot; доказано:

```text
automatic PREPARE = 0
execute = 0
provider requests = 0
```

Forensic plans, billing ledger, cache и jobs deployment-ом не изменялись.

`DEPLOY-0 = PASS`.

Book Library post-merge deployment также завершён:

```text
accepted code = 97298f0dc84dac6126bf9f283176b50552f7af3c
full offline suite = 233 / 233 PASS
runtime provisioning including book_library.py = PASS / SHA equal
fresh native build + strict codesign = PASS
production Desktop deployment = PASS
automatic PREPARE / execute / provider requests = 0
```

Canonical production registry находится только в `<AUDIOBOOK_STUDIO_HOME>/books/*.json`. `runtime/studio-workspace/books` и repository fixtures не являются параллельной production authority.

---

## 15. Что означает «проект запущен»

Не смешивать три уровня готовности.

### LEVEL A — техническое ядро

**PASS.** Уже работают Qwen, Yandex, OpenAI, Voice Library, Cloud Billing, cache/fingerprint, manifest/Resume, safe paid workflow, native app и regression suite.

### LEVEL B — установленная рабочая Studio

**PASS.** DEPLOY-0 закрыт: актуальная production Desktop app установлена и проходит zero-action safety acceptance.

На этом уровне Studio уже можно запускать как установленное приложение.

### LEVEL C — полноценный production launch для изготовления реальной книги end-to-end

**PENDING.** Осталось построить пользовательский production book workflow:

```text
BOOK LIBRARY / ADD BOOK
→ immutable source
→ TTS working copy
→ chapter/segment production
→ automatic QA + manual review
→ chapter assembly
→ mastering
→ Dilon Voices audio identity
→ export
→ LitRes profile
→ MP3 / M4B
→ end-to-end real-book acceptance
```

Только после end-to-end acceptance на реальной книге Audiobook Studio считается полностью запущенной производственной системой, а не только работающим TTS application core.

---

## 16. BOOK_LIBRARY_ADD_BOOK_V1 — ACCEPTED_AND_DEPLOYED

Accepted product checkpoint:

```text
BOOK_LIBRARY_ADD_BOOK_V1 = ACCEPTED_AND_DEPLOYED
```

Цель: пользователь должен через native Studio добавить реальную книгу в local workspace без Terminal и получить канонический book project с immutable source и отдельной TTS working copy.

Обязательные инварианты:

- production books хранятся только в local workspace;
- repository `books/` не является production user library;
- source после импорта immutable/read-only для pipeline;
- TTS working copy создаётся отдельно и может эволюционировать без изменения source;
- одна canonical local book registry/library;
- существующие Voice Library/backend/cache/manifest/Resume/QA/billing layers переиспользуются;
- разные книги могут иметь разные backend/voice profiles;
- никакого второго native app или provider-specific book registry;
- import/add book не выполняет TTS provider request;
- пользователь не обязан пользоваться Terminal.

### Definition of Done V1

`BOOK_LIBRARY_ADD_BOOK_V1 = PASS`, если через native UI можно:

1. открыть Books/library view;
2. нажать `Добавить книгу`;
3. выбрать UTF-8 TXT source;
4. ввести/подтвердить минимум title + author + slug/ID;
5. импортировать source атомарно в canonical local book project;
6. доказать immutable source hash;
7. создать отдельную TTS working copy;
8. увидеть новую книгу в library после restart приложения;
9. открыть книгу и увидеть source metadata + selected backend/voice fields без provider request;
10. удалить/повредить source через обычный TTS editing flow невозможно;
11. existing demo profile и existing runtime data не повреждены;
12. offline tests + native build/codesign PASS.

Фактическая acceptance закрыла Definition of Done: provider-neutral `BookLibrary`, atomic strict UTF-8 import, immutable hash-protected source, отдельная writable TTS copy, native file picker/form, restart persistence, integrity states, empty-jobs UI, `233/233` tests и production deployment.

Canonical layout:

```text
<AUDIOBOOK_STUDIO_HOME>/books/<slug>.json
<AUDIOBOOK_STUDIO_HOME>/books/<slug>/source/original.txt
<AUDIOBOOK_STUDIO_HOME>/books/<slug>/tts/working.txt
```

Legacy real-book profile `hvatit-sebya-obestsenivat.json` перенесён copy-preserving в canonical registry с одинаковым SHA-256; original old runtime copy сохранён. Demo/template fixtures автоматически не мигрировались.

Следующий после Book Library checkpoint:

```text
BOOK_TEXT_PREPARATION_V1
```

Он подготовил только TTS working copy: conservative normalization → chapter structure → provider-neutral literary segments → prepared jobs. Synthesis и provider requests в checkpoint не входят.

`BOOK_TEXT_PREPARATION_V1 = ACCEPTED_IN_MAIN` на merge commit `1414ebdbea358a8aa264651f2756a21d7edca8c9`. Приняты versioned preparation identity, deterministic artifacts, lightweight job references, fail-closed source/working-copy/artifact integrity и tamper regressions.

---

## 17. Product sequence

```text
BOOK_LIBRARY_ADD_BOOK_V1                  ACCEPTED_AND_DEPLOYED
→ BOOK_TEXT_PREPARATION_V1                ACCEPTED_IN_MAIN
→ CHAPTER_PRODUCTION_V1                   ACTIVE CHECKPOINT
→ QA / Review
→ chapter assembly
→ mastering
→ Dilon Voices audio identity
→ export
→ LitRes profile
→ MP3 / M4B
→ end-to-end real-book acceptance
```

Не начинать mastering/export раньше готовности production book workflow.

### CHAPTER_PRODUCTION_V1 — bounded Definition of Done

Первый production route — одна выбранная prepared chapter job через утверждённый `yandex_lera` profile.

Обязательные инварианты:

- native Studio показывает только prepared jobs с `kind = chapter`;
- PREPARE выполняется локально и имеет `remote_request_sent = false`;
- immutable plan связывает preparation identity, working-copy hash, job text hash, voice/profile, pricing identity, hard limit, cache state и максимум новых provider requests;
- execution требует отдельного явного подтверждения;
- изменившийся выбор или execution facts инвалидируют plan;
- `AMBIGUOUS`, unresolved `FAILED`, stale/missing tariff, missing credential и нарушенный manifest блокируют запуск;
- автоматический retry отсутствует;
- cache-only completion выполняется с provider requests `0`;
- provider requests никогда не превышают зафиксированный plan cap;
- V1 дополнительно блокирует главу, если текущий cache-miss plan требует более 200 provider requests;
- source и prepared text artifacts не изменяются production execution;
- результатом является resumable Yandex manifest, WAV-сегменты и WAV выбранной главы;
- offline tests + native contracts/build должны пройти до acceptance; production Desktop deployment остаётся отдельным checkpoint.

---

## 18. Dilon Voices

Public narrator brand:

```text
Dilon Voices
```

Описание:

> Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.

Текущий основной LitRes production voice:

```text
Yandex Lera / neutral / 1.04
```

Opening credit текущей книги:

> Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.

Audio identity/music — downstream layer после clean TTS, QA и chapter assembly.

Candidate signature asset:

```text
Lounge Vibes 05.7
```

Не вмешивать branding/music в backend tasks раньше отдельного этапа.

---

## 19. Finished audio target

```text
segments
→ QA
→ chapters
→ book master WAV
→ MP3 chapter exports
→ optional full-book MP3
→ M4B
→ LitRes export profile
```

Canonical master = lossless WAV. MP3 не является единственным master.

---

## 20. Brain / owner governance

Главный Brain:

- самостоятельно закрывает безопасные, логичные и обратимые технические решения;
- не спрашивает owner о каждом рутинном шаге;
- ведёт работу от actual main + canonical authority;
- не гоняет acceptance бесконечными микрошагами;
- объединяет проверки в bounded checkpoints.

Owner нужен только при:

- password/secret;
- macOS security approval;
- фактическом paid confirmation;
- существенном product/business fork;
- необратимом действии вне согласованного scope.

Codex tasks передавать одним цельным copy/paste message.

---

## 21. Current acceptance summary

```text
Qwen / MLX                         ACTIVE LOCAL BACKEND
Yandex SpeechKit v3               ACTIVE PRODUCTION BACKEND
OpenAI backend transport          ACCEPTED
Historical Cedar smoke            PASS
Native explicit PREPARE gate      ACCEPTED
Zero-user-action PREPARE          0 / PASS
One-request native safety         PASS
OpenAI live native transport      PASS
Automatic retry                   0 / PASS
Paid plan one-shot consumption    PASS
Persisted remote_request_sent     FIXED + TESTED
Cloud Billing                     ACTIVE PROVIDER-NEUTRAL LAYER
Book Library deployment suite     233 / 233 PASS
Accepted code baseline            1414ebd…
DEPLOY-0                           PASS
Production Desktop                ACCEPTED_AND_DEPLOYED
Book Library / Add Book           ACCEPTED_AND_DEPLOYED
Level A — technical core          PASS
Level B — installed Studio        PASS
Level C — real-book end-to-end    PENDING
Book Text Preparation             ACCEPTED_IN_MAIN / 1414ebd…
Active checkpoint                 CHAPTER_PRODUCTION_V1
Chapter Production implementation IMPLEMENTED_OFFLINE / PENDING_ACCEPTANCE
```

---

## 22. Change log

### 2026-08-23

- `BOOK_LIBRARY_ADD_BOOK_V1` принят, fast-forward merged в `main` и развёрнут;
- `BOOK_TEXT_PREPARATION_V1` принят merge commit `1414ebd…`; artifacts sealed exact SHA-256 hashes and tamper regressions accepted;
- active checkpoint переведён на `CHAPTER_PRODUCTION_V1`;
- bounded Yandex Lera chapter plan, separate native confirmation, cache-only path, request cap and no-retry regressions реализованы offline; status остаётся `PENDING_ACCEPTANCE`, пока не пройдут native macOS build/codesign и отдельный controlled execution/deployment checkpoint;
- canonical production library зафиксирована как `<AUDIOBOOK_STUDIO_HOME>/books/*.json`;
- immutable source и отдельная TTS working copy реализованы и проверены;
- native `Добавить книгу` работает через offline bridge; provider requests при import = 0;
- legacy real-book profile перенесён byte-identical без удаления original;
- full offline suite после Book Library = `233/233 PASS`;
- OpenAI explicit PREPARE hazard исправлен;
- memory-only one-shot gate принят;
- zero-user-action PREPARE = 0 доказан;
- live native one-request safety = PASS;
- historical Cedar transport = PASS;
- persisted `remote_request_sent` исправлен и regression-tested;
- paid-run targeted `11/11`, full offline baseline `214/214` PASS;
- accepted code находится в `main`;
- bounded runtime provisioning после merge прошёл;
- production Desktop bundle развёрнут fail-safe и прошёл strict codesign + zero-action acceptance;
- `DEPLOY-0 = PASS`;
- feature branch перестал считаться authority после merge;
- формально введены readiness levels A/B/C и определение «проект запущен»;
- предыдущий active checkpoint `BOOK_LIBRARY_ADD_BOOK_V1` закрыт как `ACCEPTED_AND_DEPLOYED`.
