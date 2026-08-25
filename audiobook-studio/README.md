# Audiobook Studio

Audiobook Studio — единое приложение для подготовки и производства аудиокниг с подключаемыми TTS backend:

- Qwen / MLX Local — локальный синтез на Mac;
- Yandex SpeechKit v3 — облачный backend;
- OpenAI TTS — облачный backend.

Qwen, Yandex и OpenAI не являются отдельными Studio. Книги, подготовка текста, сегментация, Voice Library, cache/fingerprint, manifest/Resume, QA, сборка и export образуют один общий контур.

## Canonical authority

Использовать документы в таком порядке:

1. [`docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`](docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md) — стабильная архитектура и производственный регламент;
2. [`docs/OPENAI-TTS-BACKEND-CONTRACT.md`](docs/OPENAI-TTS-BACKEND-CONTRACT.md) — provider-specific contract OpenAI;
3. [`docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`](docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md) — фактическая текущая точка, принятые acceptance-факты, launch readiness, активный checkpoint и changelog.

Если старый authority-документ содержит устаревший **status** этапа, текущий status из `AUDIOBOOK-STUDIO-CURRENT-STATE.md` имеет приоритет. Стабильные архитектурные правила при этом не переопределяются. GitHub `main` является source of truth; chat не является source of truth проекта.

## Текущий статус запуска

Техническое ядро и установленная production Desktop Studio уже приняты:

```text
LEVEL A — technical core       PASS
LEVEL B — installed Studio     PASS
DEPLOY-0                       PASS
```

Safe native OpenAI paid workflow принят, находится в `main` и развёрнут в production Desktop app. Post-merge runtime provisioning, fresh build, strict codesign и zero-action production acceptance завершены.

`BOOK_LIBRARY_ADD_BOOK_V1` принят, находится в `main` и развёрнут в production Desktop app:

```text
BOOK_LIBRARY_ADD_BOOK_V1 = ACCEPTED_AND_DEPLOYED
canonical registry = <AUDIOBOOK_STUDIO_HOME>/books/*.json
immutable source = books/<slug>/source/original.txt
editable TTS copy = books/<slug>/tts/working.txt
```

Add Book работает через native file picker и offline bridge; импорт не выполняет provider request.

`BOOK_TEXT_PREPARATION_V1` принят в `main` на `1414ebdbea358a8aa264651f2756a21d7edca8c9`: conservative normalization, chapter detection, provider-neutral literary segmentation, fail-closed artifact integrity и prepared chapter jobs работают без synthesis/provider requests.

Активный checkpoint — `CHAPTER_PRODUCTION_V1`: безопасное производство одной выбранной подготовленной главы. Первый production route — Yandex Lera с локальным immutable PREPARE-планом, отдельным подтверждением, cache/Resume и жёсткой верхней границей provider-запросов.

Полный production launch для реальной книги end-to-end ещё не завершён. После chapter production по порядку: QA/Review → assembly → mastering → Dilon Voices → export → LitRes profile → MP3/M4B → end-to-end acceptance на реальной книге.

Definition of Done активного checkpoint хранится в `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`.

Не переходить к mastering/export раньше готовности production book workflow.

## Локальный workspace

Канонический workspace по умолчанию:

```text
~/Documents/New project/Audiobook-Studio
```

Единственный resolver находится в `workspace_paths.py`. Корень можно переопределить через `AUDIOBOOK_STUDIO_HOME` или общий JSON contract, указанный в `AUDIOBOOK_STUDIO_PATH_CONTRACT`. Локальный contract по умолчанию: `Audiobook-Studio/settings/workspace-paths.json`.

Production-книги, WAV, manifests, cache, renders, masters и exports хранятся в локальном workspace, а не в Git. В `books/` репозитория остаются только template и безопасный demo profile.

Canonical production book library:

```text
<AUDIOBOOK_STUDIO_HOME>/books/<slug>.json
<AUDIOBOOK_STUDIO_HOME>/books/<slug>/source/original.txt
<AUDIOBOOK_STUDIO_HOME>/books/<slug>/tts/working.txt
```

Единственный resolver/import/integrity authority — `book_library.py`. Старый `runtime/studio-workspace/books` и repository fixtures не являются параллельным production registry.

Native app исполняет Python из local runtime copy. Repository остаётся source of truth для production code/config; installation/update flow должен синхронизировать bounded execution contour без перезаписи пользовательских книг, billing, cache, manifests и audio artifacts.

## Voice Library

`voice-library.json` и `voice_library.py` задают единый schema v1 для cloud-профилей. Утверждены:

- Yandex: Lera, Ermil, Kirill, Anton;
- OpenAI: Onyx и Cedar — равноправные built-in профили;
- Qwen: 9 профилей, динамически нормализуемых из `studio.load_voices()`.

OpenAI Custom Voice отложен. Synthetic slots `openai_female` / `openai_male` и обязательное поле `gender` не используются.

## Безопасность платных операций

Тесты, catalog/bridge checks и estimates работают offline. API keys, credentials, `.env`, runtime manifests и audio artifacts не коммитятся.

OpenAI global config сохраняет:

```text
paid_execution_enabled=false
```

Принятый native paid flow:

```text
explicit user action
→ local PREPARE confirmation
→ one-shot intent
→ network-free immutable PREPARE
→ separate paid confirmation
→ revalidation
→ maximum one provider request
→ CONSUMED
```

Без explicit user action PREPARE не выполняется. Automatic retry safe paid run = 0. `AMBIGUOUS` автоматически не retry.

## Тесты

Из корня репозитория:

```bash
python3 -m unittest discover -s audiobook-studio/tests -v
```

Команда не выполняет TTS synthesis и не отправляет provider API requests.

Принятый baseline после Book Library deployment:

```text
233 / 233 PASS
```

## Native staging app

Source находится в `native/`. Сборка использует Swift toolchain и изолированный version-keyed module cache:

```bash
audiobook-studio/native/build_native_app.sh
```

Default output:

```text
~/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app
```

Staging artifact не заменяет production Desktop app автоматически. Production deployment/update остаётся отдельной fail-safe операцией. Текущие `DEPLOY-0` и `BOOK_LIBRARY_ADD_BOOK_V1` приняты и развёрнуты.
