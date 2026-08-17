# Yandex SpeechKit v3 — текущий утверждённый профиль

**Статус:** утверждён по результатам ручного кастинга  
**Дата:** 2026-08-18  
**Проект:** Audiobook Studio  
**Backend:** Yandex SpeechKit v3 Cloud

## Текущий основной профиль

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
output: WAV
loudness_normalization: LUFS
x-data-logging-enabled: false
```

Это текущий основной Yandex-профиль для дальнейших книжных тестов Audiobook Studio.

Он выбран вручную по результатам трёх последовательных этапов прослушивания:

1. Первый кастинг — 12 женских русских голосов SpeechKit.
2. Второй тур — финалисты Lera, Zhanar RU и Yulduz RU с доступными подходящими ролями.
3. Третий и финальный тур — Lera / neutral с разными скоростями.

Финальный выбор пользователя:

```text
Lera / neutral / speed 1.04
```

Ближайший альтернативный вариант, который также звучал хорошо:

```text
Lera / neutral / speed 1.00
```

Он не является основным профилем, но может использоваться как контрольный A/B вариант при необходимости.

## Проверенная техническая схема

REST endpoint:

```text
https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis
```

Авторизация:

```text
Authorization: Api-Key <API_KEY_FROM_KEYCHAIN>
```

API key хранится только в macOS Keychain.

Keychain service:

```text
AudiobookStudio-YandexSpeechKit
```

Keychain account:

```text
elenadymova
```

В GitHub ключ не сохранять.

## Yandex Cloud

```text
cloud: cloud-dymovaei
cloud_id: b1gd8pfugsjthr1gj4rb
folder: audiobook-studio
folder_id: b1glns7o9bvkg1emj09d
service_account: audiobook-studio-tts
role: ai.speechkit-tts.user
api_key_id: aje1jnjpk7qo5iv3j0l6
api_key_scope: yc.ai.speechkitTts.execute
```

`api_key_id` — идентификатор ключа, не его секретное значение.

## Проверка подключения

SpeechKit v3 smoke test успешно пройден:

```text
HTTP 200
```

Сервис вернул Base64 WAV в `result.audioChunk.data`, после чего WAV успешно формировался локально.

Подтверждено, что рабочая схема получает API key из Keychain и не требует хранения секрета в проекте.

## Важный диагностический факт

Во время первоначальной настройки в Keychain случайно оказался API key, записанный два раза подряд. Длина строки была 80 символов вместо 40, что приводило к HTTP 401.

После исправления длина рабочего ключа — 40 символов, smoke test успешен.

Будущий backend должен валидировать наличие и базовую корректность ключа до запуска синтеза и выдавать понятную ошибку вместо отправки заведомо некорректного значения в API.

## Финальные локальные тесты

На Mac сохранена папка:

```text
~/Desktop/Yandex-Voice-Casting-FINAL
```

Финальный выбранный файл:

```text
03-lera-neutral-104-FULL.wav
```

Папки предыдущих туров кастинга удалены пользователем. Технические файлы `~/yandex-tts-*` также удалены после успешного тестирования.

Большие WAV не должны добавляться в GitHub.

## Отношение к Qwen

Этот профиль не заменяет и не удаляет локальный Qwen backend.

Текущий локальный baseline остаётся:

```text
Qwen / MLX Local
voice: Vivian
```

Для книги «Хватит себя обесценивать» финальное сравнение `Yandex Lera 1.04` против `Qwen Vivian` выполняется только после готовности новой аудиоверсии текста книги.

## Следующий технический шаг

Реализовать Yandex SpeechKit v3 как второй backend существующей Audiobook Studio, не ломая рабочую Qwen Studio.

Первый минимальный production-контур Yandex backend должен включать:

- получение API key из macOS Keychain;
- профиль `lera / neutral / 1.04`;
- WAV output;
- `x-data-logging-enabled: false`;
- `x-client-request-id`;
- понятную обработку HTTP/API ошибок;
- проверку ключа до синтеза;
- собственный безопасный Segmenter;
- manifest/cache/Resume без повторной оплаты уже готовых сегментов.
