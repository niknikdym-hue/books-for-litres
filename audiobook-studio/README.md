# Audiobook Studio

Audiobook Studio — единое приложение для подготовки и производства аудиокниг с подключаемыми TTS backend:

- Qwen / MLX Local — локальный синтез на Mac;
- Yandex SpeechKit v3 — облачный backend;
- OpenAI TTS — облачный backend.

Qwen, Yandex и OpenAI не являются отдельными Studio. Книги, подготовка текста, сегментация, Voice Library, cache/fingerprint, manifest/Resume, QA, сборка и export образуют один общий контур. Главный архитектурный документ — [`docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`](docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md).

## Локальный workspace

Канонический workspace по умолчанию:

```text
~/Documents/New project/Audiobook-Studio
```

Единственный resolver находится в `workspace_paths.py`. Корень можно переопределить через `AUDIOBOOK_STUDIO_HOME` или общий JSON contract, указанный в `AUDIOBOOK_STUDIO_PATH_CONTRACT`. Локальный contract по умолчанию: `Audiobook-Studio/settings/workspace-paths.json`.

Production-книги, WAV, manifests, cache, renders, masters и exports хранятся в локальном workspace, а не в Git. В `books/` репозитория остаются только template и безопасный demo profile.

## Voice Library

`voice-library.json` и `voice_library.py` задают единый schema v1 для cloud-профилей. Утверждены:

- Yandex: Lera, Ermil, Kirill, Anton;
- OpenAI: Onyx и Cedar — равноправные built-in профили;
- Qwen: 9 профилей, динамически нормализуемых из `studio.load_voices()`.

OpenAI Custom Voice отложен. Synthetic slots `openai_female` / `openai_male` и обязательное поле `gender` не используются.

## Безопасность платных операций

Тесты, catalog/bridge checks и estimates работают offline. Реальный Yandex или OpenAI synthesis допускается только через отдельное явное действие с cost gate. API keys, credentials, `.env`, runtime manifests и audio artifacts не коммитятся.

## Тесты

Из корня репозитория:

```bash
python3 -m unittest discover -s audiobook-studio/tests -v
```

Команда не выполняет TTS synthesis и не отправляет provider API requests.

## Native staging app

Source находится в `native/`. Сборка использует Swift toolchain и изолированный version-keyed module cache:

```bash
audiobook-studio/native/build_native_app.sh
```

Default output:

```text
~/Documents/New project/Audiobook-Studio/builds/native-staging/Audiobook Studio.app
```

Сборка staging artifact не устанавливает и не изменяет Desktop app.
