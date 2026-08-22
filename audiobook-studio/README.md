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
3. [`docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`](docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md) — фактическая текущая точка, принятые acceptance-факты, активный checkpoint и changelog.

Если старый authority-документ содержит устаревший **status** этапа, текущий status из `AUDIOBOOK-STUDIO-CURRENT-STATE.md` имеет приоритет. Стабильные архитектурные правила при этом не переопределяются. GitHub `main` является source of truth; chat не является source of truth проекта.

## Текущая контрольная точка

Code baseline safe native OpenAI paid workflow принят и находится в `main`. OpenAI transport, one-request safety, zero automatic retry, explicit PREPARE gate и persisted execution facts приняты; подробные forensic/acceptance сведения зафиксированы в current-state authority.

Следующий порядок:

```text
DEPLOY-0
→ post-merge runtime provisioning verification
→ production Desktop deployment / zero-action acceptance
→ BOOK LIBRARY / ADD BOOK
→ immutable source + TTS working copy
```

Не переходить к mastering/export раньше готовности production book workflow.

## Локальный workspace

Канонический workspace по умолчанию:

```text
~/Documents/New project/Audiobook-Studio
```

Единственный resolver находится в `workspace_paths.py`. Корень можно переопределить через `AUDIOBOOK_STUDIO_HOME` или общий JSON contract, указанный в `AUDIOBOOK_STUDIO_PATH_CONTRACT`. Локальный contract по умолчанию: `Audiobook-Studio/settings/workspace-paths.json`.

Production-книги, WAV, manifests, cache, renders, masters и exports хранятся в локальном workspace, а не в Git. В `books/` репозитория остаются только template и безопасный demo profile.

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

Принятый baseline после OpenAI safety fixes:

```text
214 / 214 PASS
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

Сборка staging artifact не устанавливает и не изменяет Desktop app. Production Desktop deployment является отдельным acceptance checkpoint.
