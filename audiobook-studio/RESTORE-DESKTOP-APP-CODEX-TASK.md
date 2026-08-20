# CODEX TASK — вернуть Qwen Audiobook Studio.app на рабочий стол

## Цель

Пользователь случайно удалил только кнопку запуска приложения с рабочего стола.
Нужно восстановить:

`/Users/elenadymova/Desktop/Qwen Audiobook Studio.app`

Использовать уже исправленный launcher из репозитория.

## Важно

НЕ переустанавливать Qwen/MLX.
НЕ скачивать модель.
НЕ менять Python, venv, HF cache.
НЕ менять профили книг.
НЕ трогать существующие WAV и renders.
НЕ запускать Stage B или любую генерацию.
НЕ удалять и не менять папку студии.

Рабочая студия уже установлена здесь:

`/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio`

Рабочий runtime уже существует здесь:

`/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16`

## Источник launcher

Репозиторий:

`niknikdym-hue/books-for-litres`

Актуальный файл:

`qwen-audiobook-studio/Qwen-Audiobook-Studio.applescript`

Он уже содержит исправление `/bin/test` и не должен использовать `/usr/bin/test`.

## Действия

1. Получить актуальный `qwen-audiobook-studio/Qwen-Audiobook-Studio.applescript` из репозитория.
2. Проверить, что в нём есть `/bin/test` и нет `/usr/bin/test`.
3. Проверить, что существует `/usr/bin/osacompile`.
4. Проверить, что target `/Users/elenadymova/Desktop/Qwen Audiobook Studio.app` сейчас отсутствует.
   - Если уже существует — STOP, ничего не перезаписывать.
5. Собрать приложение штатным `osacompile` прямо в:

`/Users/elenadymova/Desktop/Qwen Audiobook Studio.app`

6. Проверить структуру app bundle:
   - `Contents/Info.plist` существует;
   - executable существует;
   - `osadecompile` успешно возвращает script;
   - в декомпилированном script есть `/bin/test`;
   - нет `/usr/bin/test`;
   - нет запуска `Terminal.app`.
7. UI smoke test: открыть приложение только до окна `Выберите книгу`, затем нажать `Отмена`.
8. Убедиться, что после проверки не осталось процессов Studio и никакая генерация не стартовала.

## Финальный ответ

Коротко сообщить:
- `RESTORE DESKTOP APP: PASS/FAIL`;
- путь к восстановленному `.app`;
- подтверждение, что окно `Выберите книгу` появилось;
- подтверждение, что Terminal не запускался;
- подтверждение, что генерация не запускалась;
- подтверждение, что Qwen/MLX/runtime/WAV не изменялись.
