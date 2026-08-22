# Audiobook Studio — текущее каноническое состояние

**Статус:** canonical current-state authority  
**Дата фиксации:** 2026-08-23  
**Проект:** `audiobook-studio/`  
**Repository:** `niknikdym-hue/books-for-litres`  
**Code acceptance baseline:** `4fda7281c3e65195bf4b0fe8d0d0a12d359219e3`

---

## 1. Назначение и приоритет authority

Этот документ хранит **фактическую текущую точку проекта** и должен использоваться вместе с двумя стабильными authority-документами:

1. `docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md` — архитектура и производственный регламент;
2. `docs/OPENAI-TTS-BACKEND-CONTRACT.md` — provider-specific contract OpenAI;
3. `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md` — текущий статус, принятые acceptance-факты, активные checkpoints и исторические forensic-факты.

Правило приоритета:

- стабильные архитектурные принципы не переопределяются этим status ledger;
- если старый документ содержит устаревший **статус этапа** (`IMPLEMENTED OFFLINE`, `NOT PERFORMED`, старый HEAD и т. п.), текущий status в этом файле имеет приоритет;
- historical manifests/plans не переписываются задним числом;
- GitHub `main` является source of truth кода и authority-документов;
- chat не является source of truth проекта.

Не создавать параллельные handoff/task-документы для фактов, которые могут быть зафиксированы здесь или в существующих authority-файлах.

---

## 2. Что строим

Audiobook Studio — **одно local-first macOS приложение** с тремя сменными TTS backend:

```text
Audiobook Studio
├── Qwen / MLX Local
├── Yandex SpeechKit v3
└── OpenAI TTS
```

Не существуют и не должны создаваться три отдельные Studio.

Общие слои:

```text
books/source
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
→ export
→ native UI
```

Нельзя создавать параллельные provider-specific:

- book libraries;
- Voice Libraries;
- billing layers;
- manifest/Resume systems;
- QA/mastering/export contours;
- native apps.

---

## 3. Local-first architecture

Audiobook Studio является local-first macOS application.

Собственный server/backend/cloud database/localhost daemon текущему продукту не нужен.

Yandex и OpenAI — внешние cloud TTS providers. Книги, production state, cache, manifests, Resume, QA и exports остаются локальными.

Canonical workspace на основном Mac:

```text
/Users/elenadymova/Documents/New project/Audiobook-Studio
```

Repository checkout:

```text
/Users/elenadymova/Documents/New project/books-for-litres
```

Production Desktop bundle:

```text
/Users/elenadymova/Desktop/Audiobook Studio.app
```

Staging artifact:

```text
/Users/elenadymova/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app
```

Convenience staging symlink создан локально:

```text
/Users/elenadymova/Desktop/Audiobook Studio — STAGING.app
→ /Users/elenadymova/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app
```

Staging symlink не является production deployment.

---

## 4. Git policy

Никогда без отдельного bounded решения:

- `git reset`;
- force push;
- blind merge;
- blind rebase;
- `git add .`;
- `git add -A`;
- `git add --all`.

Stage только exact paths.

Перед push:

```text
git fetch origin
→ проверить divergence
→ если origin/main ушёл вперёд, не делать автоматический merge/rebase
```

Существующий local `?? .DS_Store` не является частью проекта и не должен stage-иться ради Audiobook Studio tasks.

---

## 5. Текущая repository точка

На момент этой authority-фиксации GitHub показал:

```text
main == fix/audiobook-openai-explicit-prepare-gate
code baseline = 4fda7281c3e65195bf4b0fe8d0d0a12d359219e3
```

То есть два принятых OpenAI safety fix уже находятся в `main`.

Принятые commits:

```text
ccd15f0ac21ab92850218749ffe47b8eb9eba303
Fix explicit OpenAI prepare user gate

4fda7281c3e65195bf4b0fe8d0d0a12d359219e3
Persist OpenAI paid request execution fact
```

Parent chain была проверена:

```text
c251818566318ed52821835fe2824edc27e5a03e
→ ccd15f0ac21ab92850218749ffe47b8eb9eba303
→ 4fda7281c3e65195bf4b0fe8d0d0a12d359219e3
```

Feature branch после попадания тех же commits в `main` больше не является отдельным authority contour.

---

## 6. Runtime provisioning contract

Native app исполняет Python bridge из local runtime copy, а repository остаётся source of truth production code/config.

Canonical runtime execution root:

```text
/Users/elenadymova/Documents/New project/Audiobook-Studio/runtime/studio-workspace
```

В ходе OAI acceptance был доказан provisioning gap: staging bundle сам по себе не синхронизирует repository execution contour в runtime workspace.

Был выполнен bounded runtime sync current-main → local runtime для production execution contour, включая:

- `audiobook_studio_app_runner.py`;
- `cloud_billing.py`;
- `openai_backend_runner.py`;
- `paid_run.py`;
- `studio.py`;
- `studio_app_runner.py`;
- `voice_library.py`;
- `workspace_paths.py`;
- `yandex_backend_runner.py`;
- provider config/pricing JSON;
- `backends/` code-only contour.

Пользовательские books/settings/billing/cache/jobs/audio/manifests/exports/engines не должны заменяться repository sync.

Tracked safe demo profile:

```text
audiobook-studio/books/demo-book.json
slug = demo-book
job = short-test
segment = t01
segments = 1
text length = 93
```

Local runtime demo copy используется только для безопасных acceptance tests и не заменяет будущую Book Library.

**Следствие для будущего deployment:** production installation/update flow должен иметь явный fail-safe runtime provisioning contract, чтобы Desktop app не зависела от ручного копирования execution files.

---

## 7. Qwen / MLX

Qwen остаётся локальным backend без API-расходов.

Canonical runtime voice set: 9 profiles:

- Vivian;
- Serena;
- Uncle_Fu;
- Dylan;
- Eric;
- Ryan;
- Aiden;
- Ono_Anna;
- Sohee.

Qwen не переписывается ради Yandex/OpenAI и продолжает использовать общие books/manifest/QA/export semantics по мере развития общего pipeline.

---

## 8. Yandex SpeechKit

Yandex SpeechKit v3 остаётся production cloud backend общей Studio.

Подтверждённые слои:

- segmentation;
- streaming transport;
- WAV validation;
- fingerprint/cache;
- manifest/Resume;
- AMBIGUOUS safety;
- pricing/hard limit;
- Cloud Billing integration.

Approved profiles:

- `yandex_lera`;
- `yandex_ermil`;
- `yandex_kirill`;
- `yandex_anton`.

Текущий production-default:

```text
Lera
neutral
1.04
```

Не менять frozen/approved Yandex profile из-за работ по OpenAI.

---

## 9. Voice Library

Одна provider-neutral Voice Library.

Approved cloud profiles:

```text
Yandex:
- yandex_lera
- yandex_ermil
- yandex_kirill
- yandex_anton

OpenAI:
- openai_onyx
- openai_cedar
```

OpenAI Onyx и Cedar являются равноправными approved built-in profiles.

Synthetic slots `openai_female` / `openai_male` не используются. `gender` не является обязательным identity dimension.

OpenAI Custom Voice: `DEFERRED` до отдельного этапа.

---

## 10. OpenAI production backend — validated transport

Canonical model:

```text
gpt-4o-mini-tts
```

Canonical output:

```text
WAV
```

Credential:

```text
macOS Keychain
service = AudiobookStudio-OpenAI
```

### 10.1. Historical smoke 1

Первый controlled OpenAI smoke завершился:

```text
AMBIGUOUS / INCONCLUSIVE
request_id = req_76fa9bd109ec440ebaf50506d675c309
```

Причина: старый validator ошибочно интерпретировал legal streaming RIFF sentinel `0xFFFFFFFF` как конечный размер файла.

Historical manifest не переписывается.

После этого provider-neutral RIFF parser был исправлен и offline протестирован для finalized WAV, true truncation, RIFF/data sentinels, PCM validation, block alignment и forensic preservation.

### 10.2. Historical Cedar production validation

Второй controlled smoke завершился PASS:

```text
profile = openai_cedar
model = gpt-4o-mini-tts
HTTP = 200
request_id = req_84ebe20c7c7842b79306c098fd69050e
content_type = audio/wav
response bytes = 328844
Content-Length = absent
RIFF sentinel = 0xFFFFFFFF
data sentinel = 0xFFFFFFFF
24 kHz
16-bit PCM
mono
6.85 sec
```

Подтверждено:

- WAV validation PASS;
- atomic final PASS;
- cache PASS;
- manifest `SUCCEEDED`;
- Resume replay PASS;
- second network request = 0;
- billing ledger idempotent PASS.

Это остаётся canonical evidence, что Cedar transport path работает.

---

## 11. Safe native OpenAI paid execution v1 — ACCEPTED

Состояние `IMPLEMENTED OFFLINE / LIVE NOT PERFORMED` больше не актуально.

Safe native paid execution прошёл offline, instrumented и live acceptance.

Global config остаётся:

```text
paid_execution_enabled = false
```

Никакого permanent/global paid unlock нет.

### 11.1. Принятый native flow

```text
primary OpenAI action
→ LOCAL PREPARE confirmation
→ one-shot intent consume
→ network-free immutable PREPARE
→ separate paid confirmation
→ revalidate same plan/digest
→ PREPARED → CONSUMING
→ maximum one new provider request
→ CONSUMED
```

Первый OpenAI action больше не имеет права непосредственно вызывать `--prepare-paid-run`.

One-shot intent:

- memory-only;
- initially unarmed;
- consume работает ровно один раз;
- повторный consume запрещён;
- cancel инвалидирует intent;
- reload/error инвалидируют intent;
- изменение engine/book/job/profile инвалидирует intent;
- новый arm заменяет предыдущий intent.

CACHE_ONLY также требует явного user-initiated local action, но не требует paid confirmation и не выполняет provider network.

### 11.2. Zero-user-action invariant

После safety fix instrumented staging наблюдался более 6 минут после startup snapshot.

Доказано:

```text
startup --ui-snapshot = 1
prepare_paid_run_calls_without_user_action = 0
--execute-paid-plan = 0
new plans = 0
provider requests = 0
billing changes = 0
```

Canonical invariant:

```text
NO EXPLICIT USER ACTION
→ NO PAID PLAN PREPARE
→ NO PAID EXECUTION
```

### 11.3. PREPARE plan semantics

Immutable plans хранятся local-only:

```text
Audiobook-Studio/runtime/paid-run-plans/<plan-id>.json
```

Default TTL: 10 minutes.

States:

```text
PREPARED
CONSUMING
CONSUMED
EXPIRED
BLOCKED
```

Decisions:

```text
READY_FOR_CONFIRMATION
CACHE_ONLY
BLOCKED
```

Один confirmation допускает максимум один новый provider request.

Automatic retry для safe paid run = 0.

`AMBIGUOUS` никогда автоматически не retry.

Каждый следующий новый MISS/segment требует нового plan и нового confirmation.

---

## 12. Live native one-request acceptance — PASS

Во время native acceptance пользователь случайно подтвердил paid action раньше отдельного Brain gate. Действие было принято как фактический controlled one-request smoke и исследовано forensic-only; повторный request не выполнялся.

Фактический execution использовал текущий process selection:

```text
profile = openai_onyx
voice = onyx
model = gpt-4o-mini-tts
book = demo-book
job = short-test
execution segment = s0001
characters = 93
```

Этот Onyx result **не является доказательством backend profile substitution**. Новый process был запущен без deterministic Cedar launch env; Onyx является штатным OpenAI default. Historical Cedar transport validation уже существует, поэтому второй платный Cedar smoke не требуется.

Live native transport evidence:

```text
HTTP = 200
request_id = req_ec29b6810200449791be47c8aabf201f
content_type = audio/wav
response bytes = 376844
audio data bytes = 376800
Content-Length = absent
24 kHz
16-bit PCM
mono
7.85 sec
frames = 188400
```

Принятые факты:

- new OpenAI network requests = 1;
- automatic retry count = 0;
- attempt count = 1;
- WAV validation PASS;
- final WAV atomic PASS;
- cache STORED;
- manifest `SUCCEEDED`;
- plan `PREPARED → CONSUMING → CONSUMED`;
- повторное execution того же consumed plan блокируется до сети;
- billing получил ровно один новый event;
- exact actual cost не был известен и не был сфабрикован.

Billing event:

```text
actual_cost = null
cost_source = unavailable
known_local_actual_spend: 0 → 0
unknown_cost_events: 1 → 2
remaining = null
remaining_source = unavailable
```

Unknown никогда не трактуется как `$0`.

---

## 13. Persisted execution fact — accepted fix

Live forensic выявил consistency defect: historical consumed plan имел фактический `network_requests=1`, но сохранял подготовительное `remote_request_sent=false`.

Historical plan не переписывался задним числом.

Fix `4fda7281c3e65195bf4b0fe8d0d0a12d359219e3` устанавливает canonical final semantics:

### Network request был отправлен

```text
state = CONSUMED
network_requests = 1
remote_request_sent = true
```

### CACHE_ONLY / network 0

```text
state = CONSUMED
network_requests = 0
remote_request_sent = false
```

### AMBIGUOUS после начала network request

```text
state = CONSUMED
network_requests = 1
remote_request_sent = true
automatic retry = 0
```

Targeted paid-run suite после fix:

```text
11 / 11 PASS
```

Full offline suite:

```text
214 / 214 PASS
```

Provider requests во время fix task: 0.

Historical forensic plan bytes/SHA/mtime были сохранены неизменными.

---

## 14. Forensic preservation

Нельзя переписывать задним числом:

- historical AMBIGUOUS manifest первого OpenAI smoke;
- historical paid-run plans;
- historical plan, в котором pre-fix `remote_request_sent=false` при доказанном request;
- historical billing events.

Forensic evidence хранит историю поведения системы, а новые contracts действуют только на новые executions.

---

## 15. Cloud Billing

Один provider-neutral Cloud Billing layer для Yandex и OpenAI.

Money arithmetic: `Decimal` only.

Currencies:

```text
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

- unknown balance никогда не превращается в 0;
- estimate никогда не становится actual;
- OpenAI exact prepaid balance не фабрикуется;
- OpenAI future audio cost заранее точно не фабрикуется;
- ledger idempotent;
- hard limit не является balance;
- OpenAI default local hard limit на acceptance: `1.00 USD`.

OpenAI Admin metadata и TTS credential являются разными credential contours.

---

## 16. Native UI

Native macOS Studio имеет единый engine selector:

```text
Qwen
Yandex
OpenAI
```

OpenAI approved selections:

```text
Onyx
Cedar
```

Cloud Billing интегрирован.

Unknown money отображается как:

```text
Недоступно
```

а не `$0` / `₽0`.

Production OpenAI paid UX после accepted fix имеет **два раздельных подтверждения**:

1. локальное подтверждение подготовки plan — network-free;
2. отдельное подтверждение максимум одного платного provider request.

Нельзя добавлять:

- `Always allow`;
- `Don't ask again`;
- persistent paid consent;
- whole-book/chapter batch после одного confirmation;
- automatic retry `AMBIGUOUS`.

---

## 17. Tests и build baseline

После explicit prepare gate + persistence fix:

```text
Native contract tests = PASS
Paid-run targeted = 11 / 11 PASS
Full offline suite = 214 / 214 PASS
Native staging build = PASS
Strict codesign = PASS
```

Offline tests не должны отправлять provider TTS requests.

---

## 18. Desktop deployment status

Важно различать:

```text
accepted code in main
≠ staging build
≠ production Desktop deployment
```

Post-merge closeout после `4fda728…` завершён: full offline suite `214/214 PASS`, fresh native staging build и strict codesign прошли, bounded runtime contour синхронизирован с current `main`, offline UI snapshot прошёл без provider request.

Поэтому текущий статус:

```text
OPENAI SAFE NATIVE PAID WORKFLOW = ACCEPTED_AND_DEPLOYED
PRODUCTION DESKTOP DEPLOYMENT = PASS
ZERO-ACTION PRODUCTION ACCEPTANCE = PASS
```

Production bundle `/Users/elenadymova/Desktop/Audiobook Studio.app` установлен fail-safe replacement из accepted staging artifact и прошёл strict codesign. Production startup вызвал только `--ui-snapshot`: automatic PREPARE `0`, execute `0`, provider requests `0`; forensic plans, billing ledger, cache и jobs не изменились.

Staging build не заменяет Desktop app автоматически.

---

## 19. Dilon Voices

Публичный narrator brand:

```text
Dilon Voices
```

Описание:

> Dilon Voices — проект аудиокниг с профессионально подготовленной синтезированной озвучкой и авторской аудиообработкой.

Текущий основной LitRes production voice:

```text
Yandex Lera / neutral / 1.04
```

Opening credit для текущей книги:

> Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.

Audio branding является отдельным downstream layer:

```text
clean TTS
→ QA
→ chapters
→ audio identity/music
→ mastering
→ export
```

Кандидат signature asset:

```text
Lounge Vibes 05.7
```

Не вмешивать audio branding/music в backend tasks до отдельного этапа.

---

## 20. Finished audio target

Целевая структура:

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

Canonical master: lossless WAV.

MP3 не является единственным master.

---

## 21. Product sequence / active checkpoint

Не превращать разработку в хаос и не перепрыгивать к mastering/export раньше готовности production book workflow.

OpenAI backend/paid execution и `DEPLOY-0` закрыты. Следующий крупный checkpoint:

```text
BOOK LIBRARY / ADD BOOK
+ IMMUTABLE SOURCE
+ TTS WORKING COPY
```

Далее по порядку:

```text
Book Library / Add book
→ immutable source + TTS working copy
→ chapter production
→ QA
→ chapter assembly
→ mastering
→ Dilon Voices audio identity
→ export
→ LitRes profile
→ MP3 / M4B
```

---

## 22. Book Library / Add book — архитектурные границы следующего этапа

Следующий слой должен:

- дать пользователю нормальный native Add book flow;
- хранить immutable source отдельно от TTS working copy;
- не использовать repository `books/` как production user library;
- хранить production books в local workspace;
- переиспользовать существующие Voice Library, backend, cache, manifest, Resume, QA и billing layers;
- не создавать второй book registry;
- сохранить возможность для разных книг иметь разные backend/voice profiles;
- не начинать mastering/export раньше production book workflow.

Детальная реализация этого checkpoint ещё не начата и должна опираться на актуальный `main` после DEPLOY-0.

---

## 23. User/Brain governance

Главный Brain проекта:

- сам закрывает безопасные, логичные и обратимые технические решения;
- не спрашивает пользователя о каждом рутинном шаге;
- ведёт проект по canonical authority и actual `main`;
- не гоняет acceptance бесконечными микрошагами, когда доказательства уже достаточны;
- объединяет технические проверки в bounded checkpoints.

Пользователь нужен только когда реально требуется:

- password/secret;
- macOS security approval;
- фактическое платное подтверждение;
- существенное product/business решение;
- необратимое действие вне согласованного scope.

Для Codex задания должны передаваться **одним цельным сообщением для разового copy/paste**, а не фрагментами.

---

## 24. Current acceptance summary

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
Full offline suite                214 / 214 PASS
Code in main                      YES @ 4fda728… baseline
Post-merge Desktop deployment     PASS
Zero-action production startup    PASS / PREPARE 0 / EXECUTE 0
Next product checkpoint           BOOK_LIBRARY_ADD_BOOK
```

---

## 25. Change log

### 2026-08-23

- признан и исправлен autonomous/native PREPARE hazard;
- добавлен explicit local PREPARE confirmation + memory-only one-shot intent;
- доказано `PREPARE=0` без explicit user action;
- проведён один live native paid OpenAI request: exactly one request, zero retry, WAV/cache/manifest/billing PASS;
- execution использовал фактический Onyx default process selection; это не признано backend profile-substitution defect;
- historical Cedar production transport validation остаётся отдельным PASS;
- исправлена persistence семантика `remote_request_sent` после execution;
- targeted `11/11`, full offline `214/214` PASS;
- commits `ccd15f0…` и `4fda728…` находятся в `main`;
- post-merge full offline suite `214/214`, fresh staging build и strict codesign повторно прошли;
- bounded runtime provisioning current-main → production workspace проверен по SHA; пользовательские books/settings/billing/cache/jobs/audio/manifests не заменялись;
- production Desktop bundle развёрнут fail-safe и прошёл zero-action acceptance: startup snapshot `1`, PREPARE `0`, execute `0`, provider requests `0`;
- OpenAI native paid workflow классифицирован `ACCEPTED_AND_DEPLOYED`; следующий checkpoint — `BOOK_LIBRARY_ADD_BOOK`;
- введён этот canonical current-state ledger, чтобы фактический статус проекта больше не зависел от chat и не требовал переписывания стабильной архитектуры при каждом acceptance checkpoint.
