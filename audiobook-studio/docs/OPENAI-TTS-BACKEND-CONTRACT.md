# Audiobook Studio — OpenAI TTS backend contract

**Статус:** **PRODUCTION BACKEND + NATIVE UI IMPLEMENTED OFFLINE**; **LIVE PAID SMOKE PENDING CONTROLLED CHECKPOINT**
**Дата:** 2026-08-21
**Проект:** `audiobook-studio/`
**Система:** единая `Audiobook Studio`

## 1. Главный принцип

OpenAI TTS не является отдельной студией, отдельной библиотекой книг или параллельным производственным контуром.

Целевая схема одна:

```text
Audiobook Studio
├── Qwen / MLX Local
├── Yandex SpeechKit v3
│   └── Lera / neutral / 1.04   [FROZEN / APPROVED]
└── OpenAI TTS
    ├── Onyx                    [BUILTIN / APPROVED]
    ├── Cedar                   [BUILTIN / APPROVED]
    └── Custom Voice            [DEFERRED, не реализовывать сейчас]
```

OpenAI должен переиспользовать общие слои Studio:

```text
book/source text
→ TTS preprocessing
→ common literary segmentation contract
→ engine adapter
→ segment WAV
→ fingerprint/cache
→ manifest/Resume
→ QA/review
→ chapter/book assembly
→ mastering/export
```

Не создавать для OpenAI параллельные:

- book library;
- chapter model;
- manifest system;
- Resume system;
- QA queue;
- output/mastering pipeline;
- отдельное пользовательское приложение.

## 2. Неприкосновенные решения

### Yandex

Утверждённый Yandex-диктор не участвует в OpenAI-кастинге и не пересматривается:

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
status: APPROVED / FROZEN
```

OpenAI расширяет выбор Studio, а не заменяет Lera.

### Qwen

Существующий Qwen/MLX тракт не переписывать ради OpenAI.

## 3. Текущий OpenAI production candidate

На дату проверки 2026-08-20 официальный Speech endpoint:

```text
POST https://api.openai.com/v1/audio/speech
```

Основная модель для нового backend:

```text
gpt-4o-mini-tts
```

Причины выбора:

- актуальная специализированная модель Speech API;
- поддерживает инструкции к манере речи;
- поддерживает русский язык;
- умеет выдавать WAV;
- стоимость пригодна для длинного TTS;
- встроенные голоса можно выбрать кастингом до интеграции backend.

Официальные источники:

```text
https://developers.openai.com/api/docs/guides/text-to-speech
https://developers.openai.com/api/docs/models/gpt-4o-mini-tts
```

## 4. Встроенные голоса

Официально `gpt-4o-mini-tts` предоставляет 13 built-in voices:

```text
alloy
ash
ballad
coral
echo
fable
nova
onyx
sage
shimmer
verse
marin
cedar
```

OpenAI рекомендует `marin` и `cedar` как варианты с лучшим качеством, но это не заменяет русский книжный кастинг.

Документация не должна использоваться как authority для маркировки голоса «женский» или «мужской». Утверждение профиля определяется прослушиванием русских контрольных WAV, а не обязательной gender-категорией.

Текущие утверждённые built-in профили хранятся в общей Voice Library Studio:

```text
openai_onyx
voice: onyx
status: APPROVED

openai_cedar
voice: cedar
status: APPROVED
```

Оба профиля равноправны: они не маркируются как primary/backup. Женского OpenAI-профиля сейчас нет. Production contract использует массив `approved_profiles[]` и не требует фиксированного количества или гендерных слотов.

## 5. Custom Voice — только архитектурный резерв

Custom Voice сейчас НЕ создавать и НЕ подключать.

Но schema будущего OpenAI voice profile не должна блокировать его добавление позже.

Допустимая модель:

```json
{
  "engine": "openai_tts",
  "voice_source": "builtin",
  "voice": "<approved voice>",
  "profile_id": "<approved_profile_id>"
}
```

Позже `voice_source` может стать `custom`, не меняя общий Studio pipeline.

На текущем этапе запрещено:

- создавать voice consent;
- загружать voice sample;
- создавать custom voice;
- добавлять UI для клонирования/синтеза пользовательского голоса.

## 6. Управление чтением

`gpt-4o-mini-tts` поддерживает speech instructions, включая управление:

- intonation;
- speed;
- tone;
- emotional range;
- accent и другими характеристиками подачи.

В Studio это должно быть engine-specific profile metadata, а не свободное поле, которое пользователь каждый раз пишет заново.

После кастинга для каждого победителя зафиксировать отдельный стабильный audiobook instruction preset.

Пример структуры:

```json
{
  "profile_id": "openai_onyx",
  "model": "gpt-4o-mini-tts",
  "voice": "onyx",
  "instructions": "...",
  "response_format": "wav",
  "language": "ru"
}
```

Не делать бесконтрольную генерацию десятков prompt-вариантов в production UI.

## 7. Audio format

Для производственного pipeline запрашивать:

```text
response_format: wav
```

Studio должна валидировать фактический WAV и при необходимости приводить его к единому внутреннему master-format общим audio pipeline, а не специальным OpenAI-скриптом.

## 8. Segmentation

Не копировать Yandex-ограничение `220 chars / 34 words` как универсальную истину.

OpenAI adapter получает сегменты из общего literary segmenter, но имеет собственные backend limits/profile.

У модели `gpt-4o-mini-tts` на дату проверки заявлен максимум 2000 input tokens. Production segment limits должны иметь значительный запас и определяться отдельным quality benchmark.

Во время voice casting используется один короткий фиксированный русский фрагмент; полноценный OpenAI segmenter в кастинговой задаче не нужен.

## 9. Authentication

API key OpenAI:

- никогда не хранить в GitHub;
- не хранить в JSON профиля книги;
- не печатать в лог;
- не помещать в Swift source;
- не помещать в WAV metadata.

Production-вариант Studio должен использовать локальное безопасное хранилище (macOS Keychain) или иной общий secrets provider.

Casting task сначала проверяет наличие доступного credential. Если его нет — STOP с инструкцией, не создавать ключ автоматически.

## 10. Pricing contract

На 2026-08-20 официальная цена `gpt-4o-mini-tts`:

```text
text input:  $0.60 / 1M text tokens
audio output: $12.00 / 1M audio tokens
```

Источник:

```text
https://developers.openai.com/api/docs/models/gpt-4o-mini-tts
```

Цена должна быть metadata-driven, как Yandex pricing:

- model;
- currency;
- input unit price;
- output audio unit price;
- verified_at;
- source URL;
- freshness/staleness;
- local hard limit.

Нельзя считать стоимость OpenAI по Yandex billing-unit formula.

Для production estimate Studio должна использовать фактическую модель тарификации OpenAI и показывать пользователю ожидаемую стоимость до платного запуска.

Для кастинга действует отдельный малый budget cap; задача не должна иметь возможность случайно израсходовать весь API balance.

## 11. Cache / Resume

OpenAI обязан использовать тот же принцип, что и другие cloud backends:

```text
fingerprint = text + engine + model + voice + instructions + audio format + relevant parameters
```

При неизменном fingerprint хороший WAV не синтезируется повторно.

Production estimate должен быть cache-aware: cache hit не считается новым платным synthesis request.

После неоднозначного сетевого обрыва не делать безусловный автоматический retry, если неизвестно, был ли запрос обработан.

## 12. User interface

После production-интеграции в едином native Studio:

```text
Движок
[ Qwen — локально ]
[ Yandex SpeechKit — облако ]
[ OpenAI — облако ]
```

При выборе OpenAI показывать только утверждённые профили из общей Voice Library:

```text
Onyx
Cedar
```

Не создавать отсутствующий женский placeholder и не показывать пользователю все 13 голосов в обычном production UI после завершения кастинга.

Custom Voice не показывать до отдельного этапа.

До запуска платного OpenAI job показать стоимость и применить OpenAI hard limit.

## 13. Disclosure

OpenAI требует ясно сообщать конечным пользователям, что TTS-голос является AI-generated, а не человеческой записью.

При production-интеграции предусмотреть один корректный disclosure-механизм на уровне продукта/экспорта. Не вставлять автоматически речевую фразу в начало каждой книги без отдельного продуктового решения.

## 14. Stage gates

### Stage OAI-1 — Voice Casting

Результат: утверждены два равноправных built-in профиля `openai_onyx` и `openai_cedar`; женский профиль отсутствует.

Разрешено:

- короткие реальные Speech API requests;
- только искусственный/контрольный русский текст;
- WAV casting samples;
- оценка стоимости;
- сохранение casting manifest.

Запрещено:

- менять Studio UI;
- добавлять production book run;
- использовать реальную книгу;
- менять Yandex/Qwen.

### Stage OAI-2 — Backend

Статус: `PASS / IMPLEMENTED OFFLINE`.

Поверх утверждённых профилей общей Voice Library реализованы:

- `openai_client`;
- `openai_tts` adapter;
- secure credentials;
- pricing provider;
- cache/manifest/Resume contract;
- tests без реальных запросов.

Общий Cloud Billing / spending data layer реализован, включая OpenAI local hard limit, local actual ledger, optional Organization Costs metadata и честный `remaining: unavailable | local_estimate`. Production transport остаётся закрыт явным `paid_execution_enabled = false` до отдельного controlled smoke checkpoint. Реальный OpenAI request и live paid smoke не выполнялись.

### Stage OAI-3 — Native Studio integration

Статус: `PASS / IMPLEMENTED OFFLINE`; controlled paid smoke остаётся `PENDING`.

Единый native UI теперь показывает третий engine OpenAI, approved Onyx/Cedar из canonical Voice Library, model/WAV/status и общий Cloud Billing contract. Exact OpenAI remaining и future audio charge не фабрикуются: UI показывает `Недоступно`; local USD hard limit редактируется через atomic Python bridge. OpenAI production action видим, но disabled, и не имеет hidden override.

Только после отдельного разрешённого этапа можно выполнить:

- один controlled integration smoke test.

## 15. Acceptance principle

OpenAI считается частью Audiobook Studio только если он является сменным backend общего pipeline.

Наличие отдельного скрипта, который просто отправляет текст в OpenAI и кладёт WAV в случайную папку, НЕ считается интеграцией Studio.
