# Audiobook Studio — handoff после реализации Yandex backend

**Дата контрольной точки:** 2026-08-18  
**Статус:** repo-side backend реализован; локальная синхронизация на Mac ещё не выполнена.  
**Назначение:** продолжить работу без восстановления контекста по переписке и без риска сломать рабочий Qwen.

## 1. Что уже было проверено до этой точки

Yandex SpeechKit v3 инфраструктура и авторизация уже настроены и ранее подтверждены реальным HTTP 200 smoke test.

Утверждённый голосовой профиль:

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
output: WAV
loudness_normalization: LUFS
```

Секретный API key хранится только в macOS Keychain:

```text
service: AudiobookStudio-YandexSpeechKit
account: elenadymova
```

Ключ в GitHub не хранится.

Историческая контрольная точка настройки Yandex:

```text
docs/HANDOFF-2026-08-18-YANDEX.md
```

Профиль диктора:

```text
docs/YANDEX-SPEECHKIT-CURRENT-PROFILE.md
```

## 2. Что реализовано в репозитории

Добавлен изолированный Yandex SpeechKit v3 backend. Рабочий Qwen-тракт не переписывался.

Новые файлы:

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

### Реализованные возможности

- получение API key из macOS Keychain;
- ранняя проверка credentials;
- отдельная диагностика ошибки, когда один и тот же API key записан два раза подряд;
- профиль `lera / neutral / 1.04` по умолчанию;
- WAV output;
- `x-data-logging-enabled: false`;
- уникальный `x-client-request-id` для каждого реального запроса;
- сохранение ответного `x-request-id` и `x-server-trace-id`, если сервис их возвращает;
- классификация HTTP/API ошибок;
- безопасная литературная сегментация в normal mode без `unsafeMode`;
- консервативный лимит сегмента: `220` символов / `34` слова;
- stable IDs сегментов `s0001`, `s0002`, ...;
- fingerprint, зависящий от текста и TTS-профиля;
- глобальный WAV cache;
- persistent `MANIFEST.json`;
- Resume;
- атомарная запись manifest и WAV через временные файлы;
- сборка сегментов с паузами в единый WAV;
- защита от случайного двойного платного запроса после неоднозначного обрыва.

## 3. Особое правило Resume

Перед отправкой запроса сегмент записывается в manifest как:

```text
IN_FLIGHT
```

Если процесс оборвался, при следующем запуске:

1. если готовый WAV сегмента уже лежит в job — он проверяется и используется без нового API-запроса;
2. если WAV найден в fingerprint cache — он восстанавливается из cache без нового API-запроса;
3. если ни локального WAV, ни cache нет — сегмент переводится в `AMBIGUOUS`, и автоматическая повторная отправка запрещается.

Это сделано намеренно: при сетевом обрыве нельзя надёжно знать, был ли запрос уже принят/протарифицирован сервисом.

## 4. Проверки repo-side

Модульная версия backend была прогнана локально в изолированном тестовом каталоге.

Результат:

```text
Ran 9 tests
OK
```

Тесты не обращаются к Yandex API и не создают платных запросов.

Проверяется минимум:

- защита от удвоенного ключа;
- ограничения сегментатора;
- pathological long token;
- fingerprint при изменении speed;
- обе формы REST response wrapper;
- integrity mono PCM16 WAV;
- профиль Lera/neutral/1.04;
- `IN_FLIGHT` без артефакта -> `AMBIGUOUS`;
- `IN_FLIGHT` с уже готовым WAV -> восстановление без сети.

## 5. Что НЕ было сделано после реализации backend

Это важно для правильного продолжения:

- новые Yandex-файлы ещё не синхронизированы в постоянную локальную папку Studio на Mac;
- новый backend ещё не запускался на пользовательском Mac через `yandex_backend_runner.py --check`;
- новый backend ещё не выполнял реальный API-запрос;
- `.app` ещё не переключалась и не перестраивалась для выбора Yandex;
- `studio.py`, `studio_app_runner.py`, `studio-config.json`, AppleScript и Qwen runtime не менялись;
- полная книга через Yandex не запускалась.

Старый ручной SpeechKit smoke test HTTP 200 остаётся подтверждением инфраструктуры, но не заменяет локальную проверку нового программного backend.

## 6. Следующий безопасный шаг

Использовать:

```text
SYNC-YANDEX-BACKEND-CODEX-TASK.md
```

Задача должна:

1. синхронизировать на Mac только новые Yandex/backend/test файлы;
2. не менять существующий рабочий Qwen;
3. прогнать 9 offline unit tests;
4. выполнить `yandex_backend_runner.py --check`;
5. подтвердить чтение Keychain и профиль Lera/neutral/1.04;
6. НЕ выполнять `--demo` и НЕ отправлять платный API-запрос;
7. НЕ перестраивать `.app` на этом шаге.

Целевая локальная папка Studio:

```text
/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio
```

Рабочий Qwen runtime, который нельзя менять:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16
```

## 7. После PASS локальной проверки

Только после успешного sync + tests + `--check` следующий этап:

- добавить выбор backend в общий пользовательский интерфейс;
- сохранить текущий Qwen-путь как отдельную рабочую ветку выполнения;
- подключить Yandex через новый adapter;
- выполнить короткий реальный тест на искусственном литературном тексте через приложение;
- проверить manifest/cache/Resume на реальном API;
- не использовать незавершённую редакцию книги до отдельного разрешения.

## 8. Что не делать

- не создавать новый Yandex Cloud / service account / API key;
- не печатать secret key;
- не коммитить WAV, manifest runtime или secrets;
- не менять/обновлять MLX-Qwen, модель или HF cache;
- не удалять Vivian и другие голоса Qwen;
- не запускать полную книгу;
- не использовать `unsafeMode`;
- не выполнять автоматический retry для `AMBIGUOUS` запросов;
- не заменять существующее `.app` до отдельного этапа интеграции UI.
