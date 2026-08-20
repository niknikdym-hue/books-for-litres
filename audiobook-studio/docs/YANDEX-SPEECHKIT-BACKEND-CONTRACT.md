# Audiobook Studio — Yandex SpeechKit backend contract

**Статус:** текущий provider-specific contract

**Backend:** Yandex SpeechKit v3 Cloud

Yandex SpeechKit — сменный backend единой Audiobook Studio. Он не имеет отдельной библиотеки книг, manifest-системы, QA или пользовательского приложения.

## Утверждённые Voice Library profiles

| profile_id | voice | role | speed | status |
| --- | --- | --- | --- | --- |
| `yandex_lera` | `lera` | `neutral` | `1.04` | approved, frozen |
| `yandex_ermil` | `ermil` | `neutral` | `1.0` | approved |
| `yandex_kirill` | `kirill` | `neutral` | `1.0` | approved |
| `yandex_anton` | `anton` | `neutral` | `1.0` | approved |

Точный machine-readable authority — `voice-library.json`. Filipp, Zahar, Alexander и Madi_ru не являются approved profiles.

## Transport и credentials

- REST v3 endpoint хранится в `yandex-config.json`;
- API key читается только из macOS Keychain;
- секрет не хранится в source, config, manifest или log;
- каждый запрос получает `x-client-request-id`;
- `x-data-logging-enabled` явно установлен в `false`;
- output валидируется как WAV до принятия в job/cache.

## Segmentation, manifest и Resume

Studio не отправляет целую главу одним запросом. Backend использует собственные limits поверх общего книжного pipeline, persistent manifest, fingerprint cache и потоковую сборку WAV.

Если запрос был `IN_FLIGHT`, соединение завершилось неоднозначно и локального валидного WAV нет, сегмент переходит в `AMBIGUOUS`. Такой запрос нельзя автоматически повторять: сначала требуется явное решение, чтобы не допустить повторной оплаты.

## Pricing safety

Актуальная tariff metadata хранится в `yandex-pricing.json`, а расчёт выполняется через `backends/yandex_pricing.py` с `Decimal`. Estimate учитывает cache hits, блокирует missing/stale tariff и применяет local hard limit до запуска. Estimate и healthcheck не отправляют TTS requests.

Цена, ограничения и provider metadata являются изменяемыми внешними данными и должны проверяться по официальной документации перед production synthesis.
