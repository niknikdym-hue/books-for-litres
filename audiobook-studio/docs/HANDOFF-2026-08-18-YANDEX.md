# Audiobook Studio — handoff после подключения Yandex SpeechKit

**Дата контрольной точки:** 2026-08-18  
**Назначение:** безопасно продолжить работу после перерыва без восстановления контекста по переписке.

## Что уже завершено

### Qwen / MLX Local

Рабочее состояние сохраняется без изменений:

- `Qwen Audiobook Studio.app` запускается без Terminal;
- MLX-Qwen рабочий;
- 9 дикторов сохранены;
- для текущего локального теста книги «Хватит себя обесценивать» выбран Vivian;
- следующий незавершённый шаг Qwen — вручную получить полный Stage B Vivian: `19/19 сегментов + объединённый WAV`;
- Qwen-код, модель, книги и существующие профили не удалять и не переписывать ради Yandex.

### Yandex SpeechKit v3

Подключение завершено и подтверждено реальным запросом:

```text
HTTP 200
endpoint: https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis
```

Инфраструктура:

```text
cloud: cloud-dymovaei
cloud_id: b1gd8pfugsjthr1gj4rb
folder: audiobook-studio
folder_id: b1glns7o9bvkg1emj09d
service_account: audiobook-studio-tts
role: ai.speechkit-tts.user
api_key_id: aje1jnjpk7qo5iv3j0l6
scope: yc.ai.speechkitTts.execute
```

Секретный API key хранится в macOS Keychain:

```text
service: AudiobookStudio-YandexSpeechKit
account: elenadymova
```

Секретное значение ключа не хранить в GitHub, TXT, JSON, логах или профилях книги.

## Утверждённый Yandex voice profile

После ручного кастинга выбран:

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
output: WAV
loudness_normalization: LUFS
```

Подробная фиксация:

```text
docs/YANDEX-SPEECHKIT-CURRENT-PROFILE.md
```

Контрольный альтернативный вариант, если понадобится A/B:

```text
Lera / neutral / 1.00
```

## Что осталось локально после очистки

Сохранена только финальная папка кастинга:

```text
~/Desktop/Yandex-Voice-Casting-FINAL
```

Выбранный финальный WAV:

```text
03-lera-neutral-104-FULL.wav
```

Удалено как временный мусор:

- папки `Yandex-Voice-Casting-01`, `-02`, `-03`;
- `~/yandex-tts-test.json`;
- `~/yandex-tts-response.json`;
- `~/yandex-tts-test.wav`;
- `~/yandex-tts-headers.txt`.

API key в Keychain при очистке не затрагивался.

## Известная ошибка настройки, которую не повторять

При первой записи в Keychain секретный API key случайно был записан два раза подряд:

```text
80 символов = два одинаковых 40-символьных ключа подряд
```

Это давало HTTP 401. После исправления ключ имеет длину 40 символов, запросы работают.

В production backend добавить раннюю валидацию credentials и понятную диагностику до отправки запроса.

## С чего продолжать после перерыва

Не возвращаться к созданию Yandex Cloud, сервисного аккаунта, ролей или API key — эта часть уже работает.

Следующий шаг:

**реализовать Yandex SpeechKit v3 как второй backend общей Audiobook Studio.**

Минимальная первая итерация:

1. Отдельный Yandex adapter/backend, не меняющий рабочий Qwen backend.
2. Получение API key напрямую из macOS Keychain.
3. Дефолтный профиль `lera / neutral / 1.04`.
4. WAV output.
5. `x-data-logging-enabled: false`.
6. Генерация и сохранение `x-client-request-id`.
7. Нормальная классификация API/HTTP ошибок.
8. Безопасный сегментатор для книжного текста.
9. Manifest + fingerprint + cache + Resume, чтобы готовые сегменты не синтезировались и не оплачивались повторно.
10. После этого — несколько минут тестового литературного текста через приложение, уже без ручных Terminal-команд.

## Что пока НЕ делать

- не запускать полную книгу через Yandex;
- не использовать незавершённую текущую редакцию книги как тестовый источник;
- не удалять Vivian/Qwen;
- не объединять backend-ы ценой поломки текущей `.app`;
- не коммитить WAV и секреты;
- не создавать новый API key без фактической необходимости.

## Будущая книжная контрольная точка

Когда новая аудиоверсия текста «Хватит себя обесценивать» будет готова:

```text
Yandex SpeechKit v3 — Lera / neutral / 1.04
vs
Qwen / MLX — Vivian
```

Сравнить на одном и том же реальном фрагменте книги и только после этого выбирать финального диктора полного релиза.
