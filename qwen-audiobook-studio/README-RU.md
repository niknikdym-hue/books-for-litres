# Qwen Audiobook Studio — пользовательская версия

## Как запускается

После однократной установки на рабочем столе находится:

`Qwen Audiobook Studio.app`

Запуск — обычным двойным кликом. Terminal пользователю не нужен и не открывается.

## Что показывает приложение

Последовательно появляются стандартные окна macOS:

1. **Выберите книгу**.
2. **Что генерировать**.
3. **Выберите диктора**.
4. **Запустить генерацию?**

После подтверждения генерация запускается в фоне.

Когда WAV готов:
- macOS показывает уведомление;
- Finder автоматически открывает папку результата.

## Где лежат результаты

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/renders/`

Для каждого запуска создаётся отдельная timestamp-папка. Старые рендеры не перезаписываются.

## Что уже доступно

Книга:

`Хватит себя обесценивать — Елена Дилон`

Текущий разрешённый режим:

`Stage B — длинный тест выбранного диктора`

Диктор по умолчанию:

`Vivian`

Все 9 встроенных дикторов остаются в меню:

- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

## Что студия НЕ делает

- не копирует модель для каждой книги;
- не скачивает Qwen заново;
- не создаёт новое TTS-окружение;
- не редактирует мастер книги;
- не перезаписывает старые WAV;
- не удаляет других дикторов;
- не запускает полную книгу, пока такой режим явно не добавлен в профиль книги.

## Как добавляются новые книги

Новая книга добавляется новым JSON-профилем в `books/`. После этого она автоматически появляется в меню `.app`.

Модель при этом остаётся одна и та же. Можно выбрать любого из 9 дикторов.

Шаблон:

`books/BOOK-TEMPLATE.json`

## Рабочий движок Qwen

Студия использует уже проверенную среду:

`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

Модель:

`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`

MLX-Audio:

`v0.4.5`

## Однократная установка кнопки

Точное задание для Codex:

`INSTALL-STUDIO-CODEX-TASK.md`

После его выполнения основной пользовательский интерфейс — только `Qwen Audiobook Studio.app`.

## Архитектура дальнейшего развития

Рабочая Qwen Studio сохраняется и становится локальным backend универсальной **Audiobook Studio**. Второй backend — Yandex SpeechKit v3; общими для обоих движков должны стать TTS-подготовка, сегментация, словари произношений, очередь, cache/manifest, Resume, QA, Review, сборка, mastering и export.

Основной архитектурный документ проекта:

`docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`

Он является source of truth для архитектурных принципов и должен обновляться при изменении базовых архитектурных решений.

## Yandex SpeechKit v3 — текущий статус

Yandex Cloud / IAM / API key уже настроены; прежний ручной smoke test SpeechKit v3 завершён HTTP 200.

Утверждённый профиль:

```text
voice: lera
role: neutral
speed: 1.04
```

Полная фиксация профиля:

`docs/YANDEX-SPEECHKIT-CURRENT-PROFILE.md`

Исторический handoff после настройки Yandex:

`docs/HANDOFF-2026-08-18-YANDEX.md`

### Repo-side backend реализован

В репозитории уже добавлен отдельный Yandex backend, не изменяющий рабочие Qwen-файлы:

```text
backends/__init__.py
backends/yandex_types.py
backends/yandex_segmenter.py
backends/yandex_client.py
backends/yandex_speechkit.py
yandex-config.json
yandex_backend_runner.py
tests/test_yandex_speechkit.py
```

Backend включает Keychain credentials, профиль Lera/neutral/1.04, безопасную сегментацию, `x-client-request-id`, `x-data-logging-enabled: false`, WAV validation, fingerprint cache, persistent manifest и Resume с защитой от автоматической повторной оплаты неоднозначного `IN_FLIGHT` запроса.

Repo-side offline test suite:

```text
Ran 9 tests
OK
```

На текущей контрольной точке новый backend **ещё не синхронизирован в постоянную локальную папку Studio на Mac и ещё не подключён к `.app`**.

### Актуальная точка продолжения

Сначала читать:

`docs/HANDOFF-2026-08-18-YANDEX-BACKEND.md`

Следующая безопасная задача для Codex:

`SYNC-YANDEX-BACKEND-CODEX-TASK.md`

Она должна перенести только новые Yandex-файлы в локальную Studio, выполнить offline tests и `yandex_backend_runner.py --check` без TTS API request, без WAV и без изменения рабочего Qwen/`.app`.

Только после PASS этой локальной проверки переходить к отдельному этапу подключения выбора backend в пользовательский `.app`.

Заново создавать Yandex Cloud, сервисный аккаунт, роли или API key не требуется.
