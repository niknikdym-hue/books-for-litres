# CODEX TASK — собрать универсальную Audiobook Studio.app: Qwen + Yandex

## Исходное подтверждённое состояние

Работаем из актуального `main` репозитория:

```text
niknikdym-hue/books-for-litres
```

Папка проекта:

```text
qwen-audiobook-studio/
```

Локальная рабочая Studio:

```text
/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio
```

Подтверждено на пользовательском Mac:

- Yandex backend синхронизирован локально;
- compile check: PASS;
- `tests/test_yandex_speechkit.py`: `Ran 11 tests / OK`;
- из обычного пользовательского Terminal `yandex_backend_runner.py --check`: PASS;
- `credentials_present: true`;
- `voice: lera`;
- `role: neutral`;
- `speed: 1.04`;
- `remote_request_sent: false`.

Codex-среда ранее не видела пользовательский Keychain (`security` 44), но это НЕ проблема backend: обычный пользовательский Terminal Keychain видит. Не пытаться чинить Keychain из Codex.

Desktop app сейчас отсутствует. Это ожидаемое состояние и НЕ STOP-условие.

## Цель этого этапа

Создать рядом с существующей Qwen-логикой новую универсальную пользовательскую оболочку:

```text
Audiobook Studio.app
```

Она должна сначала предлагать выбор движка:

1. `Qwen — локально`
2. `Yandex SpeechKit — Lera neutral 1.04`

На этом этапе сохранить старый Qwen-код как эталон и не ломать его.

## Архитектурное правило

НЕ переделывать монолитный `studio.py` и НЕ встраивать Yandex внутрь него.

НЕ переписывать существующий `studio_app_runner.py` без крайней необходимости.

Предпочтительная реализация — добавить отдельный универсальный bridge, например:

```text
audiobook_studio_app_runner.py
```

и отдельный AppleScript:

```text
Audiobook-Studio.applescript
```

Universal bridge должен делегировать Qwen существующей рабочей логике, а Yandex — существующему `yandex_backend_runner.py` / `backends/yandex_*`.

## Qwen-ветка в новой app

После выбора `Qwen — локально` пользователь должен получить тот же сценарий, что был в старой Qwen app:

- выбор книги;
- выбор job;
- выбор одного из существующих Qwen voices;
- подтверждение;
- запуск в фоне без Terminal;
- существующая логика генерации и уведомлений.

Использовать существующие:

```text
studio.py
studio_app_runner.py
studio-config.json
voices.json
books/
```

Не менять модель, runtime, HF cache, параметры генерации и формат существующих book profiles.

## Yandex-ветка в первой универсальной app

Пока НЕ подключать незавершённый текст книги и НЕ давать запуск полного book job через Yandex.

В первой версии Yandex-ветка должна работать только с коротким искусственным литературным demo-текстом, уже определённым в `yandex_backend_runner.py`.

Перед реальным demo-запуском UI должен показать:

- engine: Yandex SpeechKit v3;
- voice: Lera;
- role: neutral;
- speed: 1.04;
- число символов demo;
- число сегментов;
- estimated billing units;
- явное предупреждение, что нажатие кнопки запуска отправит реальные SpeechKit-запросы.

Кнопки подтверждения должны быть однозначными, например:

```text
Отмена
Синтезировать тест
```

Никакого запуска по умолчанию или без отдельного подтверждения.

При реальном пользовательском запуске Yandex demo universal bridge может делегировать существующему:

```text
yandex_backend_runner.py --demo
```

Но В ЭТОЙ CODEX-ЗАДАЧЕ `--demo` НЕ ЗАПУСКАТЬ.

## Offline-команды universal bridge

Добавить понятный CLI-контракт, достаточный для AppleScript и локальных проверок. Допустимый вариант:

```text
--list-engines
--list-books
--list-jobs --book ...
--list-voices --engine qwen
--default-speaker --book ...
--yandex-check
--yandex-estimate-demo
--run-qwen ...
--run-yandex-demo
```

Названия можно скорректировать, если интерфейс получится чище, но обязательны свойства:

- все list/check/estimate операции OFFLINE;
- только явно названный run Yandex demo имеет право отправлять SpeechKit request;
- Qwen run использует старую рабочую реализацию;
- Yandex demo использует существующий backend, без дублирования HTTP-кода.

## Важное ограничение Keychain

Codex НЕ должен считать ошибкой, если его sandbox сам не видит пользовательский Keychain.

Для offline проверки universal bridge предусмотреть режим, который может проверить конфигурацию Yandex без обязательного чтения credential, либо корректно отделить:

```text
backend_config_ok: true
keychain_check: unavailable_in_codex_environment
remote_request_sent: false
```

Не создавать новый API key.
Не менять Keychain.
Не менять IAM / service account / roles.

Пользовательский Keychain уже подтверждён вручную и работает из обычного Terminal.

## Новый app bundle

Собрать новый bundle:

```text
/Users/elenadymova/Desktop/Audiobook Studio.app
```

Использовать штатный macOS `osacompile` или эквивалентную локальную сборку AppleScript app.

Название именно:

```text
Audiobook Studio.app
```

Не создавать старое имя `Qwen Audiobook Studio.app`.

Новая app должна работать без открытия Terminal пользователем.

## Что НЕ менять

До отдельной причины не менять содержимое:

```text
studio.py
studio-config.json
voices.json
books/
backends/yandex_types.py
backends/yandex_segmenter.py
backends/yandex_client.py
backends/yandex_speechkit.py
yandex-config.json
```

Существующий `studio_app_runner.py` также предпочтительно оставить без изменений и использовать как Qwen delegate.

Не менять:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16
```

Не переустанавливать Python packages.
Не скачивать модели.
Не чистить caches/renders.

## Тесты

Добавить offline-тесты для нового universal bridge, если его логика содержит нетривиальное ветвление.

Минимально проверить:

1. список движков содержит Qwen и Yandex;
2. Qwen list-books/list-jobs/list-voices делегируется без изменения данных;
3. Yandex profile возвращает Lera / neutral / 1.04;
4. Yandex estimate demo не отправляет network request;
5. команда реального Yandex run отделена от offline-check и не вызывается тестами;
6. ошибки одного engine не приводят к модификации другого.

Существующие Yandex tests также должны остаться зелёными:

```bash
"$PY" -m unittest discover -s tests -p 'test_yandex_speechkit.py' -v
```

Ожидание:

```text
Ran 11 tests
OK
```

## Compile / syntax gate

Использовать существующий Python только как интерпретатор:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python
```

Проверить `py_compile` для всех новых/изменённых Python-файлов.

AppleScript должен компилироваться без ошибок.

## Критически важно: никаких реальных генераций в этой задаче

Codex НЕ должен:

- запускать `yandex_backend_runner.py --demo`;
- запускать новый `--run-yandex-demo`;
- отправлять curl/Python запросы в SpeechKit;
- генерировать пользовательский WAV;
- запускать Qwen Stage B;
- загружать Qwen model ради проверки GUI;
- запускать полную книгу;
- использовать текущий текст «Хватит себя обесценивать» как demo.

Разрешены только offline list/check/estimate/tests и компиляция app bundle.

## Проверка app

После сборки проверить только существование и структуру bundle без запуска реальной генерации.

Можно выполнить безопасную проверку, что:

- bundle существует;
- AppleScript скомпилирован;
- universal runner существует в локальной Studio;
- app ссылается на правильный Python и Studio path.

Не нажимать автоматически кнопки запуска синтеза.

## Что сообщить пользователю

Короткий итог:

1. какие новые/изменённые файлы добавлены;
2. изменялись ли старые Qwen-файлы;
3. Python compile PASS/FAIL;
4. старые Yandex tests: `11/11 OK` или точный FAIL;
5. новые universal bridge tests: фактическое число / PASS/FAIL;
6. AppleScript compile PASS/FAIL;
7. создан ли `/Users/elenadymova/Desktop/Audiobook Studio.app`;
8. подтверждение: Yandex request не отправлялся;
9. подтверждение: WAV не создавались;
10. подтверждение: Qwen runtime/model/cache/renders и книги не изменены.

После этого STOP.

Следующий этап будет пользовательским: вручную открыть новую `Audiobook Studio.app` и провести один короткий контролируемый тест Yandex Lera 1.04 на искусственном demo-тексте.