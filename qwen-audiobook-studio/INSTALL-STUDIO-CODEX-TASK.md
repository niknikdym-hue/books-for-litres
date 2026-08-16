# CODEX TASK — установить Qwen Audiobook Studio как обычное macOS-приложение

## Результат для пользователя

На рабочем столе должна появиться обычная кнопка-приложение:

`~/Desktop/Qwen Audiobook Studio.app`

Пользователь запускает её двойным кликом. Terminal при обычной работе студии НЕ должен открываться.

Приложение показывает native macOS dialogs:
1. выбрать книгу;
2. выбрать режим генерации;
3. выбрать одного из 9 дикторов;
4. подтвердить запуск.

Генерация идёт в фоне. После завершения Finder открывает папку готового рендера, macOS показывает notification.

## Критические границы

НЕ переустанавливать и НЕ менять рабочий Qwen/MLX runtime:

`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

НЕ скачивать модель повторно.
НЕ менять `mlx-audio`.
НЕ чистить HF cache.
НЕ трогать старые TTS.
НЕ менять мастер книги.
НЕ запускать генерацию при установке.

## Источник

Репозиторий:

`niknikdym-hue/books-for-litres`

Исходная папка:

`qwen-audiobook-studio/`

Сначала получить актуальную версию репозитория штатным безопасным способом. Не изменять никакие другие файлы проекта.

## Постоянная папка студии

Создать:

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio`

Скопировать туда содержимое `qwen-audiobook-studio/`, сохранив структуру `books/`.

Не копировать модель внутрь студии.
Не копировать `.venv` внутрь студии.
Студия должна ссылаться на существующий рабочий runtime через `studio-config.json`.

## Обязательная предварительная проверка

Проверить существование:

- `/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python`
- `/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/hf-cache`
- `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/studio.py`
- `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/studio_app_runner.py`
- `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/Qwen-Audiobook-Studio.applescript`
- `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/books/hvatit-sebya-obestsenivat.json`

Если рабочий Qwen runtime отсутствует — STOP. Ничего не устанавливать автоматически.

## Проверить backend БЕЗ загрузки модели

Использовать Python существующей среды и выполнить только безопасные catalog calls:

- `studio_app_runner.py --list-books`
- `studio_app_runner.py --list-jobs --book hvatit-sebya-obestsenivat.json`
- `studio_app_runner.py --list-voices`
- `studio_app_runner.py --default-speaker --book hvatit-sebya-obestsenivat.json`

Ожидания:
- книга: `Хватит себя обесценивать — Елена Дилон`;
- режим: `Stage B — длинный тест выбранного диктора`;
- 9 дикторов;
- default speaker: `Vivian`.

Эти команды НЕ должны загружать модель и НЕ должны создавать WAV.

## Сборка macOS app

Проверить, что `/usr/bin/osacompile` доступен.

Target:

`/Users/elenadymova/Desktop/Qwen Audiobook Studio.app`

Если target уже существует — STOP и сообщить, не удалять/перезаписывать неизвестное приложение автоматически.

Собрать приложение штатным macOS `osacompile` из:

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/Qwen-Audiobook-Studio.applescript`

Приложение должно быть обычным AppleScript app bundle. Оно НЕ должно иметь `LSUIElement`-хаки и НЕ должно запускать Terminal.app.

## Smoke UI без генерации

Не нажимать кнопку запуска генерации автоматически.

Проверить только статически/структурно:
- `.app` существует;
- `Contents/Info.plist` существует;
- executable внутри bundle существует;
- `osadecompile` приложения успешно возвращает исходный script;
- в декомпилированном script нет `tell application "Terminal"` и нет `open -a Terminal`;
- есть вызов `studio_app_runner.py`;
- есть `choose from list` для GUI;
- фоновой запуск использует shell напрямую через AppleScript `do shell script`, stdout/stderr перенаправлены в log.

## Логи и результаты

Студия использует:

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/logs/`

для app launch logs и:

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/renders/`

для готовых WAV.

Каждый render создаётся в новой timestamp-папке; существующие WAV не перезаписываются.

## Не использовать `.command` как пользовательский интерфейс

Файлы `.command`, если они присутствуют в исходной папке, не выносить пользователю на Desktop и не предлагать как основной способ запуска.

Основной и единственный пользовательский запуск после установки:

`Qwen Audiobook Studio.app`

## Что сообщить по завершении

Коротко:
- путь к установленному `.app`;
- studio backend check PASS/FAIL;
- число найденных книг;
- число найденных дикторов;
- default для текущей книги;
- подтверждение: модель при установке не грузилась, WAV не генерировались;
- подтверждение: Terminal.app в launcher не используется.

После установки STOP. Stage B не запускать автоматически.
