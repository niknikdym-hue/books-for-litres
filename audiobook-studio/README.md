# Audiobook Studio

Audiobook Studio — единое local-first macOS приложение для подготовки и производства аудиокниг с подключаемыми TTS backend:

- Qwen / MLX Local;
- Yandex SpeechKit v3;
- OpenAI TTS.

Book Library, preprocessing, Voice Library, provider adapters, cache/fingerprint, paid-run safety, Audio QA, chapter assembly, mastering, Dilon Voices identity и LitRes export образуют один provider-neutral production pipeline.

## Canonical authority

Использовать документы в таком порядке:

1. [`docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`](docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md) — стабильная архитектура и production invariants;
2. provider-specific contracts;
3. [`docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`](docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md) — фактическая текущая launch-точка, accepted gates, paid/provider blockers и real-book progress.

GitHub `main` — source of truth. Chat не является project authority. Перед продолжением всегда проверять фактический `main`, current-state и открытые launch PR/issues.

## Текущий launch status

Приняты:

```text
BOOK_TEXT_PREPARATION_V1             ACCEPTED
CHAPTER_PRODUCTION_V1               ACCEPTED
AUDIO_QA_REVIEW_V1                  ACCEPTED
CHAPTER_ASSEMBLY_V1                 ACCEPTED
MASTERING_EXPORT_V1                 ACCEPTED
DILON_IDENTITY_V1_OFFLINE_PREFLIGHT ACCEPTED
DILON_IDENTITY_V1_NO_MUSIC_BUILD    ACCEPTED
DILON_OPENING_CREDIT_PREPARE_V1     ACCEPTED
DILON_IDENTITY_TECHNICAL_QA_V1      ACCEPTED
DILON_OPENING_CREDIT_PLAN_STORE_V1  ACCEPTED
```

Активный gate:

```text
DILON_IDENTITY_V1 = IN_PROGRESS
```

Следующий production-engineering контур — Dilon identity bridge/native status + exact-output preview/QA integration. После полного Dilon gate — `REAL_BOOK_E2E_ACCEPTANCE`.

Первая реальная книга пока не whole-book ready:

```text
book = hvatit-sebya-obestsenivat
production progress = 1 / 16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Первую принятую Yandex-главу не пересинтезировать.

## Dilon Voices

Canonical brand:

```text
Dilon Voices
```

Canonical opening credit:

```text
Елена Дилон. Хватит себя обесценивать. Читает Dilon Voices.
```

Frozen production voice:

```text
yandex_lera = lera / neutral / 1.04
```

Canonical no-music path:

```text
reviewed opening-credit WAV
→ exact 0.5 s digital silence
→ exact-current clean master
→ immutable Dilon identity WAV + MANIFEST + CURRENT
→ independent offline technical QA
```

No-music path не блокируется optional signature/music. Candidate `Lounge Vibes 05.7` не использовать без доказанных commercial audiobook rights/provenance.

Opening-credit PREPARE и immutable plan store полностью offline. Они фиксируют exact `plan_id`, `plan_digest`, frozen voice, request cap и local price estimate, но не дают права на provider execution. Цена обязана быть повторно проверена непосредственно перед любой будущей платной операцией.

## Локальный workspace

По умолчанию:

```text
~/Documents/New project/Audiobook-Studio
```

Единственный path resolver — `workspace_paths.py`. Корень можно переопределить через `AUDIOBOOK_STUDIO_HOME` или `AUDIOBOOK_STUDIO_PATH_CONTRACT`.

Production data находятся вне Git: реальные книги, renders, cache, QA state, chapters, masters, identities, exports, paid-run plans и billing runtime.

## Voice Library

`voice-library.json` / `voice_library.py` — единая authority для cloud voice profiles.

Утверждены:
- Yandex: Lera, Ermil, Kirill, Anton;
- OpenAI: Onyx, Cedar;
- Qwen profiles нормализуются из local runtime catalog.

Для текущей production-книги Yandex Lera frozen: `lera / neutral / 1.04`.

## Безопасность платных операций

Никакой provider execution без explicit owner action.

OpenAI global safety:

```text
paid_execution_enabled=false
```

Общий paid flow:

```text
explicit user action
→ offline PREPARE + current pricing
→ immutable plan/request/cost cap
→ separate explicit authorization
→ authority and price revalidation
→ bounded provider execution
→ automatic QA
→ human review bound to exact output identity
```

Automatic retry ambiguous paid action = 0.

Текущие Dilon preflight/build/PREPARE/plan-store/technical-QA/bridge-status работы не имеют права выполнять provider requests или менять billing.

## Тесты

Из корня репозитория:

```bash
python3 -m unittest discover -s audiobook-studio/tests -v
```

Offline CI также проверяет macOS native contract/build/strict codesign. Тестовая команда не должна выполнять TTS synthesis/provider requests.

## Native staging app

Source: `audiobook-studio/native/`.

Build:

```bash
audiobook-studio/native/build_native_app.sh
```

Default staging output:

```text
~/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app
```

Staging build не заменяет production Desktop app автоматически. Production deployment — отдельный owner-controlled fail-safe gate.

Точную актуальную launch точку всегда брать из `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md` и фактического GitHub `main`.
