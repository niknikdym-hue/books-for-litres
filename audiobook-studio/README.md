# Audiobook Studio

Audiobook Studio — единое local-first macOS приложение для подготовки и производства аудиокниг с подключаемыми TTS backend:

- Qwen / MLX Local;
- Yandex SpeechKit v3;
- OpenAI TTS.

Книги, preprocessing, Voice Library, provider adapters, cache/fingerprint, billing safety, Audio QA, chapter assembly, mastering, Dilon Voices identity и LitRes export образуют один общий provider-neutral production pipeline.

## Canonical authority

Использовать документы в таком порядке:

1. [`docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`](docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md) — стабильная архитектура;
2. provider-specific contracts;
3. [`docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`](docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md) — фактическая текущая точка, принятые gates и launch checkpoint.

GitHub `main` — source of truth. Chat не является project authority.

## Текущий launch status

Приняты и находятся в `main`:

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
```

Активный production gate:

```text
DILON_IDENTITY_V1 = IN_PROGRESS
```

Следующий offline slice — native/bridge Dilon status + exact-output preview/QA integration. После Dilon — `REAL_BOOK_E2E_ACCEPTANCE`.

Первая реальная книга пока не whole-book ready:

```text
hvatit-sebya-obestsenivat
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

Canonical safe identity path:

```text
reviewed opening-credit WAV
→ 0.5 s exact digital silence
→ exact-current clean master
→ immutable Dilon identity WAV + MANIFEST + CURRENT
→ offline technical QA
```

No-music path является каноническим. Candidate `Lounge Vibes 05.7` не использовать без доказанных commercial audiobook rights/provenance.

Если reviewed opening-credit WAV отсутствует, provider action остаётся отдельным owner-gated шагом. Принятый offline PREPARE сейчас оценивает canonical credit максимум в один Yandex request; цена должна быть revalidated непосредственно перед execution.

## Локальный workspace

Канонический workspace по умолчанию:

```text
~/Documents/New project/Audiobook-Studio
```

Единственный resolver находится в `workspace_paths.py`. Корень можно переопределить через `AUDIOBOOK_STUDIO_HOME` или `AUDIOBOOK_STUDIO_PATH_CONTRACT`.

Production data находятся вне Git:

```text
books/
renders/
cache/
qa-review/
chapters/
masters/
identities/
exports/
billing/runtime state
```

Repository хранит production code/config/tests и безопасные fixtures, но не реальные credentials, paid plans, runtime audio или secrets.

## Voice Library

`voice-library.json` / `voice_library.py` — единая authority для cloud voice profiles.

Утверждены:
- Yandex: Lera, Ermil, Kirill, Anton;
- OpenAI: Onyx, Cedar;
- Qwen profiles нормализуются из local runtime catalog.

Yandex Lera для текущей книги frozen: `lera / neutral / 1.04`.

## Безопасность платных операций

Никакой provider execution без explicit owner action.

OpenAI global safety:

```text
paid_execution_enabled=false
```

Общий принцип paid flow:

```text
explicit user action
→ local PREPARE / current pricing
→ immutable plan + request/cost cap
→ separate explicit authorization
→ authority revalidation
→ bounded provider execution
→ QA/manual review
```

Automatic retry ambiguous paid action = 0.

Dilon offline preflight/build/PREPARE/technical QA не выполняют provider requests и не меняют billing.

## Тесты

Из корня репозитория:

```bash
python3 -m unittest discover -s audiobook-studio/tests -v
```

Offline CI также строит macOS native app и проверяет strict codesign. Тестовая команда не должна выполнять TTS synthesis/provider requests.

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

Staging build не заменяет production Desktop app автоматически. Production deployment всегда отдельный fail-safe gate.

Точную актуальную launch точку всегда брать из `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md` и фактического GitHub `main`.
