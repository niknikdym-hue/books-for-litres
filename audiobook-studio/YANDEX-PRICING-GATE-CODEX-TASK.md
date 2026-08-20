# CODEX TASK — Yandex SpeechKit pricing gate before real books

## Назначение

Это ОБЯЗАТЕЛЬНЫЙ gate до запуска реальной главы или книги через Yandex SpeechKit.

Репозиторий:

```text
niknikdym-hue/books-for-litres
```

Работать только в:

```text
qwen-audiobook-studio/
```

Связанный UX task:

```text
NATIVE-UX-STUDIO-CODEX-TASK.md
```

## Почему это нужно

Сейчас backend умеет считать:

```text
estimated_billing_units
```

но возвращает:

```text
unit_price: null
```

Для реальной книги этого недостаточно.

До любого платного batch пользователь должен видеть стоимость в ₽ и Studio должна иметь локальный hard limit, который не позволяет случайно запустить дорогую задачу.

---

# 1. Актуальная модель тарификации, проверенная 2026-08-20

По официальной документации Yandex Cloud для SpeechKit API v3:

- стоимость зависит от количества единиц тарификации;
- в normal mode запрос до 250 символов является одной единицей;
- длинные запросы в unsafe/streaming режиме тарифицируются блоками по 250 символов с округлением вверх;
- текущий backend намеренно использует normal mode и свои короткие сегменты;
- внутренняя ошибка сервера не тарифицируется согласно документации.

Публично найденный рублёвый тариф на момент проверки:

```text
0.21146666 ₽ / billing unit
```

ВАЖНО: Yandex отдельно предупреждает, что цены зависят от региона и договора/биллингового аккаунта.
Поэтому НЕ превращать `0.21146666` в безымянную вечную константу в коде.

Официальные источники:

```text
https://yandex.cloud/ru-kz/docs/speechkit/pricing
https://yandex.cloud/ru/docs/billing/api-ref/Sku/list
https://yandex.cloud/ru/docs/billing/pricing
```

---

# 2. Pricing contract

Добавить отдельную конфигурацию pricing, а не прятать цену в бизнес-логике.

Допустимый формат:

```json
{
  "engine": "yandex_speechkit_v3",
  "currency": "RUB",
  "unit": "billing_unit",
  "unit_price": 0.21146666,
  "pricing_model": "per_250_chars_or_request_unit",
  "source_region": "published_ruble_rate",
  "verified_at": "2026-08-20",
  "source_url": "https://yandex.cloud/ru-kz/docs/speechkit/pricing",
  "max_age_days": 30,
  "hard_limit_rub": null
}
```

Названия полей можно улучшить, но обязательно хранить:

- currency;
- unit_price;
- verified_at;
- source URL/reference;
- freshness/staleness status;
- user hard limit.

Не смешивать pricing config с API key.

---

# 3. Не считать регион безусловно подтверждённым

Публичная документация указывает региональность цен.

Поэтому Studio должна различать:

```text
price_configured
price_verified_at
price_stale
price_source
```

Если тариф старше выбранного срока (например 30 дней), UI показывает:

```text
Тариф требует проверки
```

и НЕ разрешает запуск всей книги до обновления/подтверждения тарифа.

Для короткого тестового fragment можно разрешить отдельный очень малый безопасный limit только при явном подтверждении пользователя.

Если в будущем будет доступен Billing API конкретного billing account, предусмотреть возможность получать contract price через него. Не делать это обязательным сейчас и не создавать новые credentials.

Официальный Billing API Yandex поддерживает `Sku.List` с currency и опциональным `billingAccountId`, включая STREET_PRICE и CONTRACT_PRICE. Архитектура pricing provider должна позволять позже заменить статическую проверенную запись на запрос Billing API без переделки UI.

---

# 4. Формула для текущего normal-mode backend

Текущий backend сегментирует примерно до 220 символов, то есть каждый реально отправленный сегмент в normal mode должен соответствовать одной billing unit.

Стоимость job:

```text
estimated_cost_rub = estimated_billing_units * unit_price_rub
```

Использовать Decimal/денежную арифметику, не binary float для итоговой цены.

В UI округлять отображение разумно, например до копеек:

```text
~14,17 ₽
```

но во внутренних расчётах сохранять точность тарифа.

---

# 5. Cache-aware estimate — обязательно

Для реального Resume нельзя показывать цену так, будто все сегменты будут оплачены заново.

Нужны два расчёта:

```text
total_billing_units
billable_remaining_units
```

где `billable_remaining_units` исключает:

- DONE WAV;
- CACHED WAV;
- валидные fingerprint cache hits.

UI показывает минимум:

```text
Всего: 67 сегментов
Уже готово: 24
Осталось отправить: 43
Ожидаемая дополнительная стоимость: ~9,09 ₽
```

Это особенно важно для Resume.

Не считать cache hit платным запросом.

---

# 6. Hard limit

До запуска реальной главы/книги должен существовать локальный spend guard.

Минимальный contract:

```text
hard_limit_rub
estimated_cost_rub
allowed_to_start
```

Если:

```text
estimated_cost_rub > hard_limit_rub
```

реальный Yandex run блокируется до явного изменения лимита пользователем в Settings.

Не делать кнопку «всё равно запустить» в обычном confirmation dialog.
Изменение hard limit — отдельное осознанное действие в настройках.

Начальный hard limit НЕ выдумывать.
Если пользователь ещё не задал лимит, full-book запуск должен быть недоступен и UI должен объяснить:

```text
Задайте максимальную стоимость одной задачи в Настройках.
```

Для demo оставить отдельный микролимит/явное существующее подтверждение.

---

# 7. Структурированный estimate result

Расширить backend/bridge estimate contract примерно до:

```json
{
  "engine": "yandex_speechkit_v3",
  "characters": 12480,
  "segments": 67,
  "total_billing_units": 67,
  "billable_remaining_units": 43,
  "currency": "RUB",
  "unit_price": "0.21146666",
  "estimated_total_cost": "14.16826622",
  "estimated_remaining_cost": "9.09206638",
  "price_verified_at": "2026-08-20",
  "price_stale": false,
  "hard_limit_rub": "...",
  "allowed_to_start": true,
  "remote_request_sent": false
}
```

Точный schema можно улучшить, но UI не должен вычислять бизнес-логику цены самостоятельно.

Python backend/bridge — source of truth для estimate.

---

# 8. UX

В native Studio для Yandex до запуска показывать человечески:

```text
12 480 символов · 67 сегментов
Ориентировочная стоимость: ~14,17 ₽
Тариф проверен: 20.08.2026
Лимит задачи: 50 ₽
```

При Resume:

```text
Уже готово: 24 сегмента
Осталось: 43
Дополнительная стоимость: ~9,09 ₽
```

Не показывать `billing_units` крупнее стоимости; billing units можно оставить в «Подробности».

Если price stale:

```text
Стоимость не подтверждена: тариф устарел.
Обновите тариф перед запуском книги.
```

---

# 9. Tests

Добавить tests минимум на:

1. точный Decimal calculation;
2. 1 unit;
3. несколько units;
4. cache-aware remaining cost;
5. stale tariff;
6. missing tariff;
7. hard limit PASS;
8. hard limit BLOCK;
9. отсутствие network request при estimate;
10. существующие 11 Yandex tests остаются зелёными;
11. существующие 8 universal bridge tests остаются зелёными или осознанно расширяются с сохранением старого поведения.

Никаких реальных TTS requests в этой задаче.

---

# 10. Не делать

- не запускать полную книгу;
- не запускать главу;
- не отправлять Yandex TTS request;
- не создавать WAV;
- не менять API key;
- не менять IAM;
- не менять Qwen runtime;
- не менять литературный текст книги;
- не хардкодить неподписанную цену без source metadata;
- не считать `total units` равным `remaining paid units` при Resume.

---

# 11. Результат

Сообщить:

1. какие pricing files/config добавлены;
2. какой unit price используется и с какой датой/source metadata;
3. как определяется staleness;
4. как считается cache-aware remaining cost;
5. как работает hard limit;
6. какие backend/bridge contracts изменены;
7. результаты новых pricing tests;
8. Yandex tests;
9. universal bridge tests;
10. подтверждение `remote_request_sent: false`;
11. подтверждение, что WAV не создавались.

STOP.
