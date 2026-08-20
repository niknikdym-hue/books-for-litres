# Audiobook Studio — handoff после реализации Yandex backend

**Дата контрольной точки:** 2026-08-18  
**Статус:** repo-side backend реализован; локальная синхронизация на Mac ещё не выполнена.  
**Назначение:** продолжить работу без восстановления контекста по переписке и без риска сломать рабочий Qwen.

## 1. Уже подтверждено до реализации backend

Yandex SpeechKit v3 инфраструктура и авторизация настроены; прежний ручной smoke test завершён HTTP 200.

Утверждённый профиль:

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
output: WAV
loudness_normalization: LUFS
```

Secret API key хранится только в macOS Keychain:

```text
service: AudiobookStudio-YandexSpeechKit
account: elenadymova
```

Не хранить секрет в GitHub, JSON, TXT или логах.

Связанные документы:

```text
docs/HANDOFF-2026-08-18-YANDEX.md
docs/YANDEX-SPEECHKIT-CURRENT-PROFILE.md
```

## 2. Что реализовано в репозитории

Добавлен отдельный Yandex SpeechKit v3 backend. Рабочий Qwen-тракт не переписывался.

```text
backends/__init__.py
backends/yandex_types.py
backends/yandex_segmenter.py
backends/yandex_client.py
backends/yandex_speechkit.py
yandex-config.json
yandex_backend_runner.py
tests/test_yandex_speechkit.py
.gitignore
```

Реализовано:

- чтение API key из macOS Keychain;
- ранняя проверка credentials;
- специальная диагностика ошибки «один ключ записан два раза подряд»;
- профиль `lera / neutral / 1.04` по умолчанию;
- WAV + LUFS;
- `x-data-logging-enabled: false`;
- уникальный `x-client-request-id`;
- сохранение `x-request-id` / `x-server-trace-id`, если они возвращаются;
- классификация HTTP/API ошибок;
- normal mode без `unsafeMode`;
- литературная сегментация с запасом: `220` символов / `34` слова;
- stable segment IDs `s0001`, `s0002`, ...;
- fingerprint по тексту и TTS-профилю;
- глобальный WAV cache;
- persistent `MANIFEST.json`;
- Resume;
- атомарная запись manifest/WAV;
- потоковая сборка joined WAV сегмент за сегментом без удержания всей книги в RAM;
- паузы при сборке;
- проверка совместимости WAV-параметров;
- защита от случайного повторного платного запроса после неоднозначного обрыва.

## 3. Правило Resume для платного API

До запроса сегмент получает статус:

```text
IN_FLIGHT
```

После прерывания:

1. если готовый WAV уже есть в job — проверить и использовать без сети;
2. если WAV найден в fingerprint cache — восстановить без сети;
3. если результата нигде нет — поставить `AMBIGUOUS` и запретить автоматическую повторную отправку.

Это защищает от двойной оплаты в ситуации, когда неизвестно, успел ли сервис принять запрос до сетевого обрыва.

## 4. Проверки

До bounded-memory доработки базовый модульный suite был прогнан полностью:

```text
Ran 9 tests
OK
```

После этого сборка joined WAV переделана с накопления всех аудиобайтов в RAM на потоковую запись. Добавлены ещё два unit test:

- joined WAV сохраняет ожидаемую длительность и паузу;
- несовпадающий sample rate блокируется, незавершённый итоговый WAV не остаётся.

Оба новых сценария проверены отдельно успешно.

Текущий test suite в `main` содержит:

```text
11 tests
```

Полный прогон актуальных 11 тестов должен быть подтверждён на пользовательском Mac во время безопасной sync-задачи. Именно результат Mac-проверки считается входным gate перед интеграцией `.app`.

## 5. Что после реализации backend ещё НЕ сделано

- Yandex-файлы ещё не синхронизированы в постоянную локальную Studio на Mac;
- `yandex_backend_runner.py --check` ещё не запускался на пользовательском Mac;
- новый backend ещё не выполнял реальный API-запрос;
- `.app` ещё не умеет выбирать Yandex;
- `studio.py`, `studio_app_runner.py`, `studio-config.json`, AppleScript и Qwen runtime не менялись;
- полная книга через Yandex не запускалась.

Прежний ручной HTTP 200 подтверждает облачную инфраструктуру, но не заменяет локальную проверку нового backend.

## 6. Следующий обязательный gate

Использовать:

```text
SYNC-YANDEX-BACKEND-CODEX-TASK.md
```

Задача должна:

1. перенести только Yandex/backend/test файлы в
   `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio`;
2. не менять рабочий Qwen;
3. выполнить compile check;
4. получить `Ran 11 tests / OK`;
5. выполнить `yandex_backend_runner.py --check`;
6. подтвердить Keychain credential без раскрытия секрета;
7. подтвердить `remote_request_sent: false`;
8. не запускать `--demo`, не генерировать пользовательские WAV и не перестраивать `.app`.

Рабочий Qwen runtime, который нельзя менять:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16
```

## 7. После PASS этого gate

Только затем:

- добавить выбор backend в общий пользовательский интерфейс;
- оставить Qwen как отдельный неизменённый рабочий путь;
- подключить Yandex через новый adapter;
- выполнить короткий реальный тест на искусственном литературном тексте через приложение;
- проверить manifest/cache/Resume уже на реальном API;
- не использовать незавершённую редакцию книги до отдельного разрешения.

## 8. Не делать

- не создавать новый Yandex Cloud / service account / API key;
- не печатать secret key;
- не менять MLX-Qwen, модель или HF cache;
- не удалять Vivian и другие Qwen voices;
- не запускать полную книгу;
- не использовать `unsafeMode`;
- не выполнять auto-retry для `AMBIGUOUS`;
- не заменять существующее `.app` до отдельного этапа GUI-интеграции.
