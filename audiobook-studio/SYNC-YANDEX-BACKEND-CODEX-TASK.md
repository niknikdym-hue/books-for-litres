# CODEX TASK — безопасно синхронизировать Yandex backend Audiobook Studio на Mac

## Цель

Перенести уже реализованный и протестированный repo-side Yandex SpeechKit v3 backend в существующую постоянную локальную Audiobook Studio и выполнить только безопасные локальные проверки.

На этом шаге:

- НЕ отправлять запросы в Yandex SpeechKit;
- НЕ генерировать пользовательские WAV;
- НЕ перестраивать `.app`;
- НЕ менять рабочий Qwen/MLX runtime.

## Источник

Репозиторий:

```text
niknikdym-hue/books-for-litres
```

Исходная папка:

```text
qwen-audiobook-studio/
```

Получить актуальный `main` штатным безопасным способом.

## Целевая локальная папка

```text
/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio
```

Она должна существовать и содержать рабочие исходные файлы Qwen Audiobook Studio.

## Критическая граница — Qwen не трогать

НЕ изменять и НЕ перезаписывать на этом шаге:

```text
studio.py
studio_app_runner.py
studio-config.json
voices.json
Qwen-Audiobook-Studio.applescript
books/
```

НЕ менять, НЕ обновлять и НЕ удалять рабочий runtime:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16
```

В частности:

- не переустанавливать Python environment;
- не менять `mlx-audio`;
- не скачивать Qwen/model повторно;
- не чистить HF cache;
- не удалять существующие Qwen renders.

### Важное уточнение про `.app`

Путь:

```text
/Users/elenadymova/Desktop/Qwen Audiobook Studio.app
```

на этой задаче НЕ является обязательным входным условием.

Если `.app` отсутствует:

- просто зафиксировать `Desktop app: ABSENT`;
- НЕ создавать его;
- НЕ восстанавливать;
- НЕ перестраивать;
- НЕ считать это причиной для STOP;
- продолжить синхронизацию и локальные проверки Yandex backend.

Наличие `.app` потребуется на отдельном следующем этапе GUI-интеграции, но не для backend sync/check.

STOP требуется, если неожиданно отсутствуют или конфликтуют защищённые рабочие объекты, необходимые именно для этой задачи: целевая папка Studio, перечисленные Qwen-файлы, `books/` или рабочий Qwen Python runtime.

## Что синхронизировать

Создать недостающие каталоги `backends/` и `tests/` в target, если их нет.

Скопировать из актуального репозитория только следующие файлы:

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

`.gitignore` в runtime-каталог копировать не требуется.

Если в target уже существуют одноимённые Yandex-файлы, сначала сравнить их с repo `main`:

- если совпадают — оставить;
- если отличаются — заменить только эти Yandex-файлы актуальной repo-версией;
- не распространять замену на другие файлы Studio.

## Проверить конфигурацию без вывода секрета

В `yandex-config.json` ожидается:

```text
engine: yandex_speechkit_v3
keychain_service: AudiobookStudio-YandexSpeechKit
keychain_account: elenadymova
voice: lera
role: neutral
speed: 1.04
output: WAV
loudness_normalization: LUFS
```

Secret API key НЕ читать/печатать вручную и НЕ записывать в файлы.

Backend сам читает его из macOS Keychain.

## Python для проверки

Использовать уже существующий Python рабочего Qwen runtime только как интерпретатор:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python
```

Не устанавливать дополнительные пакеты: Yandex backend MVP использует стандартную библиотеку Python.

## Шаг 1 — compile check

Из target Studio выполнить compile только новых файлов:

```bash
PY="/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python"
cd "/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio"

"$PY" -m py_compile \
  backends/__init__.py \
  backends/yandex_types.py \
  backends/yandex_segmenter.py \
  backends/yandex_client.py \
  backends/yandex_speechkit.py \
  yandex_backend_runner.py \
  tests/test_yandex_speechkit.py
```

Если FAIL — STOP. Не пытаться чинить Qwen или окружение.

## Шаг 2 — offline unit tests

Выполнить:

```bash
"$PY" -m unittest discover -s tests -p 'test_yandex_speechkit.py' -v
```

Ожидание:

```text
Ran 11 tests
OK
```

В актуальном наборе дополнительно проверяется потоковая сборка joined WAV без удержания всей аудиокниги в RAM и блокировка сборки сегментов с несовместимым sample rate.

Эти тесты не должны:

- обращаться к Yandex API;
- загружать Qwen;
- создавать платный запрос;
- создавать пользовательские WAV (временные тестовые WAV создаются только внутри временных каталогов unit tests и автоматически удаляются).

Если результат не `11 tests / OK` — STOP и сообщить точную ошибку.

## Шаг 3 — локальный Yandex backend check

После PASS unit tests выполнить:

```bash
"$PY" yandex_backend_runner.py --check
```

Важно: `--check` может прочитать существующую запись Keychain, но НЕ должен отправлять сетевой TTS-запрос.

Ожидаемые признаки PASS:

```text
"ok": true
"engine": "yandex_speechkit_v3"
"voice": "lera"
"role": "neutral"
"speed": "1.04"
"credentials_present": true
"remote_request_sent": false
```

Также runner напечатает локальную оценку сегментов искусственного demo-текста.

Secret API key в stdout/stderr появляться НЕ должен.

Если Keychain-check не проходит:

- STOP;
- сообщить ошибку;
- НЕ создавать новый API key;
- НЕ менять IAM / service account / roles;
- НЕ записывать ключ повторно без отдельной диагностики.

## Шаг 4 — убедиться, что ничего лишнего не произошло

После проверок подтвердить:

- `studio.py` не изменён;
- `studio_app_runner.py` не изменён;
- `studio-config.json` не изменён;
- `voices.json` не изменён;
- `books/` не изменён;
- AppleScript не изменён;
- Qwen runtime/model/cache не изменены;
- `renders/` не удалялся;
- `renders-yandex/` не содержит нового demo WAV от этой задачи;
- ни один `--demo` не запускался;
- сетевой SpeechKit TTS request не выполнялся;
- состояние desktop `.app` только зафиксировано как PRESENT или ABSENT; оно не изменялось этой задачей.

## Запрещено на этой задаче

НЕ выполнять:

```text
yandex_backend_runner.py --demo
```

НЕ отправлять curl/Python smoke requests в SpeechKit.

НЕ создавать и НЕ менять `.app`.

НЕ добавлять Yandex в AppleScript/menu сейчас.

НЕ запускать Stage B Qwen.

НЕ запускать полную книгу.

НЕ использовать незавершённый текст книги как тест.

## Что сообщить по завершении

Коротко и конкретно:

1. какие Yandex-файлы синхронизированы;
2. compile check PASS/FAIL;
3. unit tests: фактическое число и PASS/FAIL;
4. `--check`: PASS/FAIL;
5. найден ли Keychain credential без раскрытия секрета;
6. подтверждение `remote_request_sent: false`;
7. подтверждение: пользовательские WAV не создавались;
8. подтверждение: Qwen, книги и существующие renders не изменялись;
9. состояние desktop `.app`: PRESENT или ABSENT, без попытки его создать/исправить.

После этого STOP. Интеграцию Yandex в GUI и восстановление/сборку `.app`, если она действительно нужна, выполнять отдельным следующим этапом.