# Audiobook Studio — OpenAI TTS backend contract

**Статус:** **PRODUCTION BACKEND + SAFE NATIVE OPENAI PAID EXECUTION v1 ACCEPTED AND DEPLOYED**
**Дата актуализации:** 2026-08-23  
**Проект:** `audiobook-studio/`  
**Система:** единая `Audiobook Studio`  
**Current-state authority:** `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`

---

## 1. Главный принцип

OpenAI TTS не является отдельной студией, отдельной библиотекой книг или параллельным производственным контуром.

Целевая схема одна:

```text
Audiobook Studio
├── Qwen / MLX Local
├── Yandex SpeechKit v3
│   └── Lera / neutral / 1.04   [FROZEN / APPROVED]
└── OpenAI TTS
    ├── Onyx                    [BUILTIN / APPROVED]
    ├── Cedar                   [BUILTIN / APPROVED]
    └── Custom Voice            [DEFERRED]
```

OpenAI переиспользует общие слои Studio:

```text
book/source text
→ immutable source / TTS working copy
→ common literary segmentation
→ engine adapter
→ segment WAV
→ fingerprint/cache
→ manifest/Resume
→ QA/review
→ chapter/book assembly
→ mastering/export
```

Не создавать для OpenAI параллельные:

- book library;
- chapter model;
- manifest system;
- Resume system;
- QA queue;
- billing layer;
- output/mastering pipeline;
- отдельное пользовательское приложение.

---

## 2. Неприкосновенные решения

### Yandex

Утверждённый Yandex-диктор не пересматривается из-за OpenAI:

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
status: APPROVED / FROZEN
```

### Qwen

Существующий Qwen/MLX тракт не переписывать ради OpenAI.

### Global paid switch

Canonical config остаётся:

```text
paid_execution_enabled = false
```

Успешный smoke или пользовательское подтверждение одного plan не превращаются в permanent/global paid unlock.

---

## 3. Production model / endpoint

Canonical Speech endpoint:

```text
POST https://api.openai.com/v1/audio/speech
```

Canonical model:

```text
gpt-4o-mini-tts
```

Production response format:

```text
wav
```

Официальные references проверяются перед изменением API/pricing:

```text
https://developers.openai.com/api/docs/guides/text-to-speech
https://developers.openai.com/api/docs/models/gpt-4o-mini-tts
```

---

## 4. Approved built-in profiles

Общая Voice Library содержит два равноправных OpenAI profile:

```text
openai_onyx
voice: onyx
status: APPROVED

openai_cedar
voice: cedar
status: APPROVED
```

Они не маркируются как primary/backup и не создают synthetic gender slots.

`gender` не является обязательным identity dimension.

OpenAI Custom Voice остаётся `DEFERRED`.

Запрещено до отдельного этапа:

- создавать voice consent;
- загружать пользовательский voice sample;
- создавать custom voice;
- добавлять voice cloning UI.

---

## 5. Speech instructions

`gpt-4o-mini-tts` поддерживает speech instructions. В Studio они являются engine-specific metadata утверждённого voice profile, а не свободным prompt-полем для каждого запуска.

Пример:

```json
{
  "profile_id": "openai_cedar",
  "model": "gpt-4o-mini-tts",
  "voice": "cedar",
  "instructions": "...",
  "response_format": "wav",
  "language": "ru"
}
```

Изменение instructions входит в fingerprint и требует нового synthesis только для затронутых сегментов.

---

## 6. WAV / streaming RIFF contract

Studio валидирует фактический WAV общим provider-neutral validator.

Для finalized WAV RIFF/chunk sizes проверяются строго.

Для streaming WAV `0xFFFFFFFF` в RIFF и/или `data` size является legal sentinel «размер неизвестен до EOF», но не bypass проверки.

Sentinel принимается только при полном structural PCM contract:

- валидные `fmt` / `data` chunks;
- PCM encoding;
- корректные channels;
- sample rate;
- sample width;
- block alignment;
- непустое целое число frames;
- фактический payload корректно заканчивается на container/EOF boundary.

HTTP Content-Length является отдельной transport-проверкой и может отсутствовать.

Historical первый smoke, отвергнутый старым validator из-за sentinel semantics, не переоценивается задним числом.

---

## 7. Segmentation

Не копировать Yandex segment limit как универсальную истину.

OpenAI adapter использует общий literary segmentation contract и собственные backend limits.

Production safe paid execution работает только с заранее выбранным сегментом из canonical prepared job.

Source segment ID и provider execution segment ID могут различаться. Например:

```text
source job: t01
execution:  s0001
```

Это не является дефектом identity само по себе.

---

## 8. Authentication

OpenAI production credential:

```text
macOS Keychain
service = AudiobookStudio-OpenAI
```

API key:

- не хранится в GitHub;
- не хранится в book JSON;
- не печатается в logs;
- не передаётся в Swift source;
- не помещается в WAV metadata.

Credential availability может проверяться как boolean fact без раскрытия secret.

Optional Organization/Admin credential является отдельным contour и не считается production TTS key.

---

## 9. Pricing / cost truth

Pricing хранится metadata-driven:

- model;
- currency;
- input unit price;
- output audio unit price;
- `verified_at`;
- source;
- freshness/staleness;
- local hard limit.

Canonical tracked pricing на acceptance был проверен как non-stale (`verified_at=2026-08-20`).

Нельзя применять Yandex billing-unit formula к OpenAI.

Критические правила:

- exact future audio cost не фабрикуется;
- provider exact prepaid balance не фабрикуется;
- unknown не превращается в `$0`;
- estimate не превращается в actual;
- hard limit не является balance.

Acceptance local OpenAI hard limit:

```text
1.00 USD
```

---

## 10. Cache / Resume / AMBIGUOUS

Fingerprint включает как минимум:

```text
text
+ engine
+ model
+ voice
+ instructions
+ audio format
+ relevant parameters
```

При неизменном fingerprint валидный WAV не синтезируется повторно.

Cache hit не считается новым paid request.

Если после начала/получения network response результат становится `AMBIGUOUS`, automatic retry запрещён.

Forensic response может сохраняться только как local-only artifact `diagnostics/*.ambiguous`. Он не становится final WAV/cache HIT.

Allow-listed diagnostics могут включать:

- request ID;
- HTTP status;
- Content-Type;
- Content-Length;
- received bytes;
- RIFF/data markers.

Credentials и raw authorization headers запрещены.

---

## 11. Provider-neutral Cloud Billing

OpenAI использует общий `cloud_billing.py`.

Money: `Decimal` only.

OpenAI currency:

```text
USD
```

Provenance:

```text
provider_reported
local_actual
local_estimate
user_confirmed
unavailable
```

Unknown completed request cost записывается:

```text
actual_cost = null
cost_source = unavailable
```

а не `0` и не estimate.

Ledger должен оставаться idempotent по transaction/request identity.

---

## 12. Safe native paid execution — accepted architecture

Safe native OpenAI paid execution v1 принят.

Canonical flow:

```text
PRIMARY USER ACTION
→ LOCAL PREPARE CONFIRMATION
→ ONE-SHOT INTENT CONSUME
→ PREPARE (NETWORK-FREE)
→ IMMUTABLE PLAN
→ SEPARATE PAID CONFIRMATION
→ REVALIDATE SAME DIGEST / EXECUTION FACTS
→ PREPARED → CONSUMING
→ MAXIMUM ONE NEW NETWORK REQUEST
→ CONSUMED
```

### 12.1. Explicit PREPARE gate

Первый OpenAI primary action **не имеет права** непосредственно вызывать `--prepare-paid-run`.

Он только:

1. валидирует current selection;
2. arms memory-only one-shot intent;
3. показывает local PREPARE confirmation.

Только explicit local confirmation может consume intent и вызвать PREPARE.

### 12.2. One-shot intent

Intent:

- живёт только в native process memory;
- initially unarmed;
- consume succeeds ровно один раз;
- повторный consume = false;
- cancel инвалидирует;
- reload/error инвалидируют;
- смена engine/book/job/profile инвалидирует;
- новый arm заменяет старый.

One-shot intent не является credential и не передаётся как security secret в Python.

### 12.3. Zero-user-action invariant

Canonical invariant:

```text
NO EXPLICIT USER ACTION
→ PREPARE = 0
→ NEW PLAN = 0
→ EXECUTE = 0
→ PROVIDER REQUEST = 0
```

После fix instrumented staging наблюдался более 6 минут:

```text
startup --ui-snapshot = 1
prepare_paid_run_calls_without_user_action = 0
--execute-paid-plan = 0
new plans = 0
provider requests = 0
```

---

## 13. PREPARE contract

Bridge:

```text
--prepare-paid-run --provider openai --book <book> --job <job> --profile-id <profile>
```

PREPARE:

- не вызывает TTS network;
- не списывает средства;
- строит production segmentation/fingerprints;
- проверяет manifest/cache/Resume;
- блокирует matching `AMBIGUOUS` / unresolved `FAILED`;
- проверяет pricing freshness;
- проверяет shared hard limit;
- проверяет credential availability;
- выбирает максимум первый eligible `PENDING + MISS`.

Plans хранятся local-only:

```text
Audiobook-Studio/runtime/paid-run-plans/<plan-id>.json
```

Default TTL:

```text
10 minutes
```

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

Каждый отдельный PREPARE намеренно создаёт новый UUID plan. Поэтому два PREPARE invocation могут создать два plan даже при одинаковом digest/execution facts.

---

## 14. Immutable plan / digest

Digest покрывает execution-critical facts, включая:

- provider;
- book/source identity;
- job/text identity;
- selected segment text/fingerprint;
- approved profile;
- model;
- voice;
- instructions hash;
- WAV format;
- hard limit;
- pricing identity;
- `max_network_requests = 1`.

Execute не принимает заново text/model/voice/instructions как альтернативную authority.

Перед atomic consumption он заново валидирует source/profile/pricing/hard-limit/credential/fingerprint/manifest/Resume/segment eligibility и тот же digest.

---

## 15. Execute contract

Bridge:

```text
--execute-paid-plan --plan-id <id> --plan-digest <sha256>
```

Paid execution допускается только после отдельного paid confirmation.

Invariant:

```text
one paid confirmation
→ max_network_requests = 1
→ automatic retry = 0
```

Plan перед network переводится:

```text
PREPARED → CONSUMING
```

Crash/повторный вызов не возвращают его в `PREPARED`.

После завершения:

```text
→ CONSUMED
```

Повторное execute consumed plan блокируется до provider network.

Multi-segment job не может продолжить платный batch после одного confirmation. Каждый новый MISS требует нового PREPARE + нового confirmation.

---

## 16. Persisted network fact

До fix final plan сохранял `network_requests`, но мог оставлять подготовительное `remote_request_sent=false`.

Historical plans не переписываются.

Новая canonical semantics:

### Network 1

```text
state = CONSUMED
network_requests = 1
remote_request_sent = true
```

### Network 0 / CACHE_ONLY

```text
state = CONSUMED
network_requests = 0
remote_request_sent = false
```

### AMBIGUOUS after network start

```text
state = CONSUMED
network_requests = 1
remote_request_sent = true
automatic_retry_count = 0
```

Regression baseline:

```text
paid-run targeted = 11 / 11 PASS
full offline suite = 214 / 214 PASS
```

---

## 17. CACHE_ONLY

CACHE_ONLY требует explicit user-initiated local action, но provider network не выполняет.

Canonical acceptance:

```text
network_requests = 0
remote_request_sent = false
provider calls = 0
new ledger events = 0
```

CACHE_ONLY не требует paid confirmation, поскольку нового billable provider request нет.

---

## 18. Native UI

Единый native Studio engine selector:

```text
Qwen
Yandex
OpenAI
```

При OpenAI показывать только approved Onyx/Cedar.

Paid path имеет два независимых dialog:

### Local PREPARE dialog

Смысл:

> Подготовка plan не отправляет TTS request и не списывает средства.

### Paid dialog

Смысл:

> Подтвердить максимум один новый OpenAI TTS request для exact prepared plan.

Не добавлять:

- Always allow;
- Don't ask again;
- persistent paid consent;
- hidden override;
- automatic batch;
- automatic retry ambiguous request.

Unknown price/balance отображать как `Недоступно`.

---

## 19. Acceptance history

### OAI-1 — Voice Casting

**PASS.** Approved profiles:

```text
openai_onyx
openai_cedar
```

### OAI-2 — Production backend

**PASS.** Реализованы adapter, secure credential, pricing, WAV validator, cache, manifest/Resume, AMBIGUOUS forensic contract, tests и Cloud Billing integration.

### Historical smoke 1

```text
status = AMBIGUOUS / INCONCLUSIVE
request_id = req_76fa9bd109ec440ebaf50506d675c309
```

Причина validator mismatch по streaming sentinel. Historical evidence не переписывается.

### Historical Cedar smoke

```text
status = PASS
profile = openai_cedar
HTTP = 200
request_id = req_84ebe20c7c7842b79306c098fd69050e
24 kHz / 16-bit PCM / mono / 6.85 sec
```

PASS:

- sentinel-aware WAV validation;
- atomic final;
- cache;
- manifest;
- Resume without second request;
- idempotent billing ledger.

### OAI-3 — Native Studio integration

**PASS.** OpenAI присутствует в общем native UI, использует Voice Library и Cloud Billing, unknown money не фабрикуется.

### OAI-4 — Safe native paid execution v1

**ACCEPTED.**

Принято:

- explicit local PREPARE gate;
- one-shot intent;
- zero autonomous PREPARE;
- separate paid confirmation;
- max one provider request;
- retry 0;
- persisted execution fact;
- consumed plan replay blocked before network.

### Live native one-request acceptance

Фактический smoke:

```text
profile = openai_onyx
model = gpt-4o-mini-tts
book = demo-book
job = short-test
segment = s0001
characters = 93
HTTP = 200
request_id = req_ec29b6810200449791be47c8aabf201f
content_type = audio/wav
response bytes = 376844
audio data bytes = 376800
24 kHz
16-bit PCM
mono
7.85 sec
```

Результат:

```text
network requests = 1
automatic retry = 0
WAV validation = PASS
atomic final = PASS
cache = STORED
manifest = SUCCEEDED
plan = CONSUMED
billing events = 1
```

Onyx в этом конкретном smoke отражал фактическое process/default selection и не признан доказательством backend profile substitution. Historical Cedar smoke уже доказал Cedar transport, поэтому второй платный Cedar request не требуется.

---

## 20. Forensic integrity

Никогда не переписывать задним числом:

- первый AMBIGUOUS manifest;
- historical plans;
- historical pre-fix `remote_request_sent=false` plan;
- billing events.

Forensic evidence сохраняет фактическую историю системы.

---

## 21. Repository / runtime boundary

Repository хранит:

- production source;
- schemas/config templates;
- approved Voice Library;
- tests;
- authority docs.

Local workspace хранит:

- production books;
- runtime code copy;
- credentials/settings;
- paid-run plans;
- billing ledger/cache;
- WAV/cache;
- manifests/jobs;
- exports/builds.

Native staging build не синхронизирует runtime автоматически. Deployment/update flow должен делать bounded runtime provisioning current-main → runtime без перезаписи пользовательских data contours.

---

## 22. Disclosure

Конечному пользователю должен быть корректно раскрыт факт AI-generated narration в соответствии с product/export policy.

Не вставлять автоматически речевую disclosure-фразу в каждую книгу без отдельного product decision.

---

## 23. Acceptance principle

OpenAI считается частью Audiobook Studio только как сменный backend общего pipeline.

Наличие отдельного скрипта, который отправляет произвольный текст в OpenAI и кладёт WAV в случайную папку, не является интеграцией Studio.

Accepted OpenAI contract должен сохранять одновременно:

```text
shared books
shared Voice Library
shared cache/manifest/Resume
shared Cloud Billing
explicit local PREPARE
separate paid confirmation
max 1 new request
retry 0
forensic honesty
no global paid unlock
```

Production Desktop deployment и zero-action acceptance завершены. Следующий продуктовый слой — `BOOK LIBRARY / ADD BOOK + IMMUTABLE SOURCE / TTS WORKING COPY`, а не расширение paid OpenAI batch semantics.
