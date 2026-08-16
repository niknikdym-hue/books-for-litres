# CODEX TASK — исправить launcher Qwen Audiobook Studio.app

## Причина

Установленный launcher падает с:

`sh: /usr/bin/test: No such file or directory`

В исходном AppleScript был неверный путь `/usr/bin/test`.
В репозитории это уже исправлено на штатный macOS путь `/bin/test`.

## Задача

Исправить ТОЛЬКО установленный launcher приложения.

Не переустанавливать Qwen/MLX.
Не скачивать модель.
Не менять Python/venv/HF cache.
Не менять профили книг, runner, голоса или master.
Не запускать генерацию.

## Репозиторий

`niknikdym-hue/books-for-litres`

Актуальный source:

`qwen-audiobook-studio/Qwen-Audiobook-Studio.applescript`

Проверить, что в актуальном source:

- есть `/bin/test -x`;
- есть `/bin/test -f`;
- НЕТ `/usr/bin/test`.

## Локальная постоянная папка

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio`

Обновить в ней только:

`Qwen-Audiobook-Studio.applescript`

из актуального репозитория.

## Установленное приложение

`/Users/elenadymova/Desktop/Qwen Audiobook Studio.app`

Сначала `/usr/bin/osadecompile` существующего приложения и убедиться, что это именно наш Qwen Audiobook Studio launcher (содержит `studio_app_runner.py` и property `studioDir` на `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio`).

Если это не наш launcher — STOP, ничего не удалять.

Если это наш launcher:
1. удалить только этот app bundle;
2. пересобрать его через `/usr/bin/osacompile` из исправленного локального `Qwen-Audiobook-Studio.applescript` в тот же путь;
3. проверить, что `.app` существует;
4. `/usr/bin/osadecompile` нового app;
5. подтвердить, что в декомпилированном launcher есть `/bin/test` и нет `/usr/bin/test`;
6. подтвердить, что нет `tell application "Terminal"` и `open -a Terminal`.

## Безопасный UI smoke

Запустить приложение один раз только до первого окна выбора книги.

Если появилось native окно `Выберите книгу` — PASS, затем нажать/выполнить Cancel. Никакой генерации не запускать.

Если launcher снова падает — STOP и дать точный текст новой ошибки, не чинить каскадом.

## Что сообщить

Коротко:
- `LAUNCHER FIX: PASS/FAIL`;
- путь к `.app`;
- `/bin/test`: подтверждено;
- `/usr/bin/test`: отсутствует;
- native окно выбора книги: PASS/FAIL;
- модель не загружалась;
- WAV не генерировались;
- Terminal.app не использовался.
