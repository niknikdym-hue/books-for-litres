# Audiobook Studio — архитектура и производственный регламент

**Статус:** основной архитектурный документ проекта  
**Версия:** 1.6
**Дата фиксации:** 2026-08-21
**Текущий проект:** `audiobook-studio/`
**Целевая система:** универсальная **Audiobook Studio** с локальным Qwen/MLX и облачными Yandex SpeechKit v3 и OpenAI TTS.

---

## 1. Назначение документа

Этот файл — основной source of truth по развитию Audiobook Studio.

Он фиксирует:

- что уже работает и не должно быть сломано;
- целевую архитектуру студии;
- общий производственный конвейер аудиокниги;
- требования к Qwen Local, Yandex SpeechKit v3 и OpenAI TTS;
- правила хранения текста, сегментов, WAV, манифестов и экспортов;
- требования к кэшу, возобновлению, QA и контролю расходов;
- требования к пользовательскому приложению без Terminal;
- порядок дальнейшей реализации.

Если отдельное техническое решение противоречит этому документу, оно считается временным и должно быть либо приведено в соответствие с архитектурой, либо явно зафиксировано здесь как новое решение.

---

## 2. Главная идея

Не создавать отдельную студию для каждого TTS-движка.

Должна существовать **одна Audiobook Studio**, у которой есть сменные движки синтеза:

1. **Qwen / MLX — Local** — работает на Mac локально.
2. **Yandex SpeechKit v3 — Cloud** — синтезирует речь в облаке через API.
3. **OpenAI TTS — Cloud** — третий сменный backend поверх общей инфраструктуры Studio.

Весь остальной процесс должен быть общим:

```text
Исходный текст книги
        ↓
TTS-подготовка текста
        ↓
Умное разбиение на сегменты
        ↓
Словари произношений / ударений / правил
        ↓
Выбор движка
   ├── Qwen / MLX Local
   ├── Yandex SpeechKit v3 Cloud
   └── OpenAI TTS Cloud
        ↓
WAV-сегменты
        ↓
Автоматический QA
        ↓
Ручной Review только проблемных мест
        ↓
Сборка главы
        ↓
Мастеринг
        ↓
WAV master → MP3 / M4B
```

Qwen, Yandex и OpenAI — не отдельные проекты, а сменные backend одного приложения.

Выбор для каждой книги имеет общий вид:

```text
Book
→ selected backend
→ selected voice profile from Voice Library
```

Backend и voice profile сохраняются в профиле конкретной книги, а не как одна глобальная настройка Studio. Поэтому разные книги могут независимо использовать Lera, Ermil, Kirill, Anton, Onyx, Cedar или любой доступный Qwen-профиль.

---

## 3. Неприкосновенные принципы

### 3.1. Не ломать рабочий Qwen

Существующий Qwen / MLX backend не удаляется и не переписывается ради подключения других providers.

Yandex добавляется отдельным adapter/backend.

### 3.2. Оригинал книги неизменяем

Исходный авторский текст хранится отдельно и никогда автоматически не перезаписывается TTS-подготовкой.

Для синтеза создаётся производная TTS-версия.

### 3.3. Terminal не является пользовательским интерфейсом

После установки обычная работа должна выполняться через `.app`.

Terminal допустим только для разработки, диагностики и первоначальной технической настройки.

### 3.4. Синтез должен быть возобновляемым

Прерывание интернета, выключение Mac, падение API или закрытие приложения не должны заставлять начинать книгу заново.

### 3.5. Никогда не пересинтезировать хороший WAV без причины

Каждый сегмент имеет текстовый hash и полный fingerprint настроек. Если они не изменились, готовый WAV берётся из кэша.

### 3.6. Для облачного движка цена известна до запуска

Перед стартом облачного job Audiobook Studio обязана показать расчёт ожидаемой стоимости и применить provider-specific local hard limit.

### 3.7. Ключи и секреты не попадают в GitHub

API keys Yandex и OpenAI не хранятся в книге, JSON-профиле, исходниках или репозитории.

### 3.8. Качество важнее скорости генерации

Цель — не получить WAV как можно быстрее, а получить литературно звучащую аудиокнигу с минимальным количеством ручного брака.

---

## 4. Текущая контрольная точка проекта

Текущий repository source contour — `audiobook-studio/`. Канонический локальный workspace — `~/Documents/New project/Audiobook-Studio`, а установленное пользовательское приложение называется `Audiobook Studio.app`.

Подтверждены:

- единый native Swift UI для Qwen, Yandex и OpenAI catalog/profile selection;
- Qwen / MLX runtime как локальный backend с 9 динамически загружаемыми голосами;
- Yandex SpeechKit v3 backend с segmentation, streaming transport, WAV validation, fingerprint cache, manifest, Resume и pricing gate;
- четыре approved Yandex profiles: Lera 1.04 (frozen), Ermil 1.0, Kirill 1.0 и Anton 1.0;
- два равноправных approved OpenAI built-in profiles: Onyx и Cedar;
- production OpenAI Speech backend реализован и проверен offline: literary safety segmenter, stable fingerprint, canonical cache, atomic WAV, manifest/Resume, AMBIGUOUS safety, streaming RIFF sentinel validation, pricing/preflight и Keychain credential contract;
- первый controlled OpenAI production smoke 2026-08-21 завершился `AMBIGUOUS / INCONCLUSIVE` без retry: validator contract bug для legal streaming RIFF sentinel доказан и исправлен synthetic fixtures, но конкретный утраченный response не переоценивался; global paid execution остаётся закрыт;
- второй controlled OpenAI production smoke 2026-08-21 завершился `PASS`: один request через canonical `OpenAITTSBackend`, HTTP 200, реальный RIFF/`data` sentinel `0xFFFFFFFF`, PCM validation, atomic final/cache, manifest, Resume без сети и idempotent ledger подтверждены; global paid execution остаётся закрыт;
- единый provider-neutral Cloud Billing data layer реализован для Yandex и OpenAI: Decimal money, обязательный provenance, local settings, idempotent ledger, stale cache и offline/read-only bridge;
- native Swift UI декодирует canonical Voice Library и Cloud Billing snapshot для всех трёх engine, отображает RUB/USD без FX, сохраняет `null` как «Недоступно», показывает provenance/freshness/warnings и не предоставляет OpenAI paid-run override;
- единая Voice Library schema v1 без обязательного `gender`; OpenAI Custom Voice остаётся `DEFERRED`;
- native parse, typecheck и arm64 staging build на Swift 6.3.3 / macOS SDK 26.5 / minimum target macOS 14;
- version-keyed isolated Swift module cache, исключающий повторное использование stale SDK modules.

Текущие 9 дикторов Qwen:

- Vivian
- Serena
- Uncle_Fu
- Dylan
- Eric
- Ryan
- Aiden
- Ono_Anna
- Sohee

---

## 5. Входной формат книги

### MVP

Основной входной формат:

- UTF-8 TXT.

### Позже

Можно добавить:

- DOCX;
- EPUB при необходимости.

### Для каждой книги хранить

- slug / ID книги;
- название;
- автора;
- язык;
- исходный файл;
- структуру глав;
- TTS-версию;
- словарь книги;
- выбранного диктора;
- выбранный движок;
- параметры синтеза;
- manifest генерации;
- статусы QA;
- мастер-файлы и экспорты.

---

## 6. TTS Preprocessor

Это обязательный общий слой перед любым движком.

Он должен создавать отдельный `tts_text`, не изменяя `source_text`.

### Обязанности

- нормализация кавычек и тире;
- корректная обработка многоточий;
- преобразование чисел в произносимую форму там, где это требуется;
- даты;
- проценты;
- валюты;
- сокращения;
- инициалы;
- специальные символы;
- заголовки глав;
- управление паузами;
- ударения;
- произношение фамилий, имён, терминов и иностранных слов;
- исключение служебной разметки из речи;
- движок-специфическая разметка только на последнем этапе адаптации.

### Словари

Должны существовать минимум два уровня:

1. **Global pronunciation dictionary** — общие исправления для всех книг.
2. **Book pronunciation dictionary** — исключения конкретной книги.

Приоритет:

```text
book dictionary > global dictionary > automatic normalization
```

Исправление произношения в словаре должно автоматически применяться ко всем соответствующим местам книги при следующем синтезе.

---

## 7. Segmenter

Разбиение должно быть литературным, а не механическим.

Порядок:

```text
книга → глава → смысловой блок → абзац → предложения → TTS-сегмент
```

### Требования

- не разрывать предложение посередине;
- по возможности не разрывать короткий абзац;
- учитывать реплики и диалоги;
- учитывать ограничения конкретного TTS backend;
- позволять разный размер сегмента для Qwen и Yandex;
- сохранять стабильные segment IDs при неизменённой структуре.

Пример ID:

```text
ch03_s0047
```

### Для каждого сегмента хранить

- `segment_id`;
- chapter ID;
- исходный текст;
- TTS-текст;
- source hash;
- TTS hash;
- движок;
- голос;
- voice role / style;
- speed;
- pitch;
- дополнительные параметры;
- статус;
- число попыток;
- путь к WAV;
- длительность;
- QA status;
- timestamp генерации.

---

## 8. Общий интерфейс TTS Engine

Все движки должны подчиняться одному внутреннему контракту.

Минимальные операции:

```text
list_voices()
validate_config()
estimate(segment | chapter | book)
synthesize(segment)
healthcheck()
```

Результат `synthesize()` должен возвращать не просто файл, а структурированный результат:

- success / error;
- engine;
- voice;
- output path;
- duration;
- request ID, если есть;
- стоимость / billing units, если применимо;
- retryable / non-retryable error;
- диагностические данные без секретов.

---

## 9. Backend A — Qwen / MLX Local

Существующая локальная система сохраняется.

### Уже существующая база

- общий native `Audiobook Studio.app`;
- MLX-Qwen;
- локальные book profiles в canonical workspace;
- `voices.json`;
- 9 дикторов;
- динамический Qwen voice catalog через `studio.load_voices()`.

### Требования к дальнейшей интеграции

- не ломать общий native launcher/bridge;
- не скачивать модель заново для каждой книги;
- не копировать модель в проект книги;
- поддержать общий manifest;
- поддержать общую очередь;
- поддержать общий QA;
- поддержать общий экспорт;
- выдавать те же структурированные метаданные, что и облачный backend.

### Преимущество Qwen

Локальные перегенерации не тарифицируются. Поэтому Qwen может использоваться не только как финальный диктор, но и как черновой TTS для проверки подготовленного текста до платной отправки в Yandex.

---

## 10. Backend B — Yandex SpeechKit v3 Cloud

### 10.1. Авторизация

Production-схема:

- отдельный сервисный аккаунт для Audiobook Studio;
- минимальная роль `ai.speechkit-tts.user` на нужный каталог;
- API key сервисного аккаунта;
- передача ключа через локальное безопасное хранилище / environment;
- ключ не хранить в GitHub.

Для API key используется авторизация вида:

```text
Authorization: Api-Key <API_KEY>
```

При API key сервис может использовать каталог сервисного аккаунта без передачи folder ID в каждом запросе — конкретную реализацию проверять на smoke test используемого endpoint.

### 10.2. Конфиденциальность

В клиенте явно задавать:

```text
x-data-logging-enabled: false
```

Даже если это значение соответствует текущему поведению сервиса по умолчанию, Studio должна фиксировать намерение явно.

Для диагностики генерировать собственный:

```text
x-client-request-id: <UUID>
```

и сохранять его в manifest/log.

### 10.3. API v3 и длинные тексты

У SpeechKit v3 стандартный безопасный режим имеет ограничения на размер/длительность одной фразы. Для более длинных запросов существуют `unsafe_mode` и потоковый режим; документация также указывает максимальный размер запроса на синтез до 5000 символов.

Studio **не должна** отправлять целую главу одним запросом.

Разбиение выполняет собственный Segmenter, а не API Яндекса.

Оптимальный размер Yandex-сегмента должен быть определён отдельным A/B/quality benchmark. Он не фиксируется жёстко до практического теста на книжном тексте.

### 10.4. Формат master-аудио

Целевой внутренний формат:

```text
WAV / LPCM
mono
48 kHz
16 bit, если выбранный endpoint/контейнер и сборка используют эту глубину
```

Если API возвращает другой допустимый lossless/PCM вариант, конвертация в единый master-format выполняется один раз через FFmpeg перед сборкой.

MP3 не является мастер-форматом.

### 10.5. Голосовые параметры

Adapter должен поддерживать доступные конкретному голосу параметры:

- voice;
- role / style;
- speed;
- pitch, если доступен выбранному методу;
- language;
- нормализацию / output format;
- TTS-разметку.

Параметры не должны быть зашиты в код. Они хранятся в voice profile / render profile.

### 10.6. Ошибки и retries

Автоматически повторять только retryable ошибки:

- временный network failure;
- timeout;
- rate limit;
- временная ошибка сервиса.

Не повторять бесконечно:

- неверный ключ;
- отсутствие роли;
- невалидный текст/markup;
- неподдерживаемый голос;
- неверные параметры.

Retry policy:

```text
bounded retries + exponential backoff + jitter
```

После лимита попыток сегмент получает статус `FAILED` и попадает в Review/Errors.

---

## 11. Voice Library

Studio использует единую нормализованную библиотеку дикторов независимо от движка. Канонический tracked registry `voice-library.json` хранит утверждённые cloud-профили, а существующий Qwen-каталог подключается динамически через `studio.load_voices()` и не копируется во второй JSON.

Обязательный общий contract профиля:

- `profile_id`;
- `provider`;
- `engine`;
- `label`;
- `voice_source`;
- `voice`;
- `language`;
- `status`.

Engine-specific metadata остаются опциональными: Yandex использует `role` и `speed`; OpenAI — `model`, `instructions` и `response_format`. `gender` не является обязательным identity dimension. Будущий OpenAI Custom Voice подключается через `voice_source: custom`, но остаётся `DEFERRED` до отдельного этапа.

Выбранный `profile_id` хранится на уровне книги вместе с выбранным backend. Он не является глобальным диктором для всей Studio.

Текущий approved set:

- Yandex: `yandex_lera`, `yandex_ermil`, `yandex_kirill`, `yandex_anton`;
- OpenAI: `openai_onyx`, `openai_cedar`;
- Qwen: 9 runtime profiles, динамически нормализуемых из `studio.load_voices()`.

Synthetic slots `openai_female` / `openai_male` не существуют. Onyx и Cedar равноправны.

---

## 12. Voice Test / A-B audition

До полной генерации книги Studio должна уметь синтезировать одинаковый контрольный фрагмент несколькими голосами.

Для литературного теста выбирать фрагмент, содержащий:

- обычную публицистическую речь;
- длинное предложение;
- эмоциональный переход;
- короткую реплику;
- тире/кавычки;
- слово с потенциально спорным ударением;
- паузу между смысловыми блоками.

Главный практический тест после подключения Яндекса:

```text
Vivian / Qwen
vs
3–5 лучших русских голосов Yandex
```

Сравнивать:

- естественность;
- литературность;
- эмоциональную убедительность;
- паузы;
- ударения;
- длинные предложения;
- стабильность между сегментами;
- артефакты;
- объём ручных исправлений;
- скорость генерации;
- стоимость финального результата.

Победителя определяет прослушивание, а не название модели.

---

## 13. Очередь генерации

Studio должна иметь persistent job queue.

Состояния сегмента минимум:

```text
PENDING
RUNNING
DONE
FAILED
NEEDS_REVIEW
APPROVED
INVALIDATED
```

Пользователь должен видеть по главе и книге:

- всего сегментов;
- готово;
- в очереди;
- ошибки;
- требует проверки;
- утверждено.

Операции:

- Start;
- Pause;
- Resume;
- Stop safely;
- Retry failed;
- Regenerate selected;
- Regenerate range;
- Regenerate chapter;
- Invalidate by text/config change.

### Resume

После перезапуска приложение читает manifest и продолжает только незавершённые/невалидные сегменты.

---

## 14. Cache и fingerprint

Ключ кэша должен учитывать как минимум:

```text
tts_text_hash
+ engine
+ model/version
+ voice
+ role/style
+ speed
+ pitch
+ output settings
+ pronunciation/markup revision
```

Если fingerprint совпадает и WAV прошёл integrity check — повторный синтез не нужен.

Изменение одного предложения не должно инвалидировать всю книгу.

---

## 15. Контроль расходов Yandex

Стоимость не зашивается в исходный код навечно.

Тариф может меняться и зависит от региона/аккаунта. В конфигурации хранится актуальная billing unit price с датой проверки.

Расчёт для API v3 строится по billing units Яндекса:

```text
units(segment) = ceil(billable_characters / 250)
cost(segment) = units × current_unit_price
cost(job) = sum(cost(segment))
```

Studio должна показывать до запуска:

```text
Символов
Сегментов
Billing units
Ориентировочная стоимость
Максимально допустимая стоимость job
```

### Локальный hard limit

Пример настройки:

```text
MAX_JOB_COST_RUB=1000
```

Если оценка выше лимита, job не стартует без явного подтверждения/изменения лимита.

Дополнительно использовать бюджет/уведомления Yandex Cloud как второй уровень защиты.

---

## 16. Автоматический QA аудио

После каждого синтеза сегмент проходит автоматическую проверку.

Минимум:

- файл существует;
- размер > 0;
- контейнер читается;
- длительность > минимального порога;
- длительность не аномально мала относительно текста;
- нет технического обрыва;
- нет грубого clipping;
- нет аномальной тишины;
- sample rate соответствует pipeline;
- число каналов ожидаемое;
- WAV можно декодировать FFmpeg;
- checksum сохранён.

Подозрительные результаты получают `NEEDS_REVIEW`.

Цель: человек не прослушивает десять часов в поисках технического брака — он получает очередь подозрительных мест плюс выборочный контроль нормальных сегментов.

---

## 17. Manual Review

Целевой экран:

```text
[ текст сегмента ]        [ waveform / player ]

OK
Перегенерировать
Исправить произношение
Изменить паузу
Изменить скорость
Другой голос/role для теста
```

После исправления:

1. обновляется TTS-текст/правило;
2. инвалидируется только нужный сегмент;
3. генерируется новый WAV;
4. автоматически запускается QA;
5. новая версия подставляется в сборку главы.

История предыдущих рендеров не должна теряться до явной очистки.

---

## 18. Сборка глав

После утверждения сегментов Studio создаёт chapter master.

Сборка должна учитывать:

- порядок segment IDs;
- межфразовые паузы;
- межабзацные паузы;
- паузы между смысловыми блоками;
- начало/конец главы;
- отсутствие щелчков на стыках;
- единый sample format.

Нельзя ограничиться «слепым concat», если это создаёт неестественный ритм.

---

## 19. Mastering

После сборки:

- единая целевая громкость;
- нормализация;
- контроль true peak / clipping;
- проверка стыков;
- корректная тишина в начале и конце;
- при необходимости мягкая техническая обработка без изменения характера голоса.

Master хранится в WAV.

Из master создаются delivery-файлы.

---

## 20. Export

Минимум:

### WAV по главам

```text
01-<chapter>.wav
02-<chapter>.wav
...
```

### MP3

Метаданные:

- title;
- author;
- chapter title;
- track number;
- cover art;
- album / book title.

### Позже — M4B

Один файл аудиокниги:

- главы;
- chapter markers;
- обложка;
- основные метаданные.

---

## 21. Рекомендуемая структура данных

Целевая структура может выглядеть так:

```text
audiobook-studio/
    docs/
        AUDIOBOOK-STUDIO-ARCHITECTURE.md

    books/
        BOOK-TEMPLATE.json
        <book-profile>.json

    voices.json
    studio-config.json

    runtime-data/                 # не обязательно хранить в Git
        books/
            <book-slug>/
                source/
                tts/
                dictionaries/
                manifests/
                segments/
                audio/
                    qwen/
                    yandex/
                qa/
                chapters/
                masters/
                exports/
```

Большие WAV и секреты не должны попадать в git случайно.

Фактическое runtime-хранилище может оставаться вне репозитория на пользовательском Mac; repo хранит код, профили, схемы и документацию.

---

## 22. UI целевой Audiobook Studio

Основные разделы:

### Books

- список книг;
- добавить книгу;
- статус проекта;
- текущий движок/диктор;
- прогресс.

### Text

- исходный текст read-only;
- TTS-версия;
- словарь;
- предупреждения normalizer.

### Voices

- Qwen voices;
- Yandex voices;
- samples;
- A/B audition.

### Generate

- engine;
- voice;
- параметры;
- сегменты;
- оценка стоимости для облака;
- Start/Pause/Resume.

### Review

- QA queue;
- text + player;
- исправление и локальная перегенерация.

### Assemble

- главы;
- паузы;
- сборка;
- технический QA.

### Export

- WAV;
- MP3;
- позже M4B;
- metadata/cover.

### Settings

- пути;
- backend settings;
- Yandex connection status;
- локальные лимиты расходов;
- FFmpeg;
- storage cleanup.

---

## 23. Аппаратный профиль рабочего Mac

Контрольная машина проекта:

```text
MacBook Air
Apple M1
8 CPU cores
8 GB unified memory
SSD ~228 GiB
свободно на момент проверки ~65 GiB
```

### Следствия для архитектуры

- не держать всю книгу или весь WAV в RAM;
- писать сегменты сразу на SSD;
- использовать потоковую обработку FFmpeg;
- ограничивать параллелизм;
- Yandex Cloud не требует локальной GPU;
- Qwen Local должен оставаться оптимизированным под M1/8 GB;
- не допускать заполнения SSD временными рендерами.

### Дисковая политика

Целевой резерв:

- стараться оставлять минимум 25–30 GiB свободного места;
- устанавливать лимит runtime storage;
- после успешного master/export предлагать безопасную очистку временных файлов;
- никогда автоматически не удалять source, approved masters и единственную копию WAV без явной политики retention.

---

## 24. Безопасность

### Никогда не коммитить

- Yandex API key;
- IAM tokens;
- `.env` с реальными секретами;
- приватные credentials;
- системные идентификаторы компьютера;
- временные diagnostic dumps с Authorization headers.

### Разрешено хранить

`.env.example` только с пустыми значениями:

```text
YANDEX_SPEECHKIT_API_KEY=
YANDEX_SPEECHKIT_FOLDER_ID=
MAX_JOB_COST_RUB=1000
```

Если API key выбран как production-способ и folder ID не нужен конкретному endpoint, соответствующее поле может оставаться пустым.

Логи обязаны маскировать секреты.

---

## 25. Логи и manifest

Для каждой генерации сохранять:

- job ID;
- book;
- chapter;
- segment;
- engine;
- model/voice;
- параметры;
- hash;
- start/end time;
- result;
- retry count;
- request ID;
- billing units / estimated cost для Yandex;
- output file;
- checksum;
- QA status.

Не сохранять API key.

Логи должны позволять ответить на вопрос:

> почему этот конкретный WAV был создан именно так и нужно ли платить/генерировать его повторно?

---

## 26. Производственный workflow одной книги

### Этап A — подготовка

1. Импорт source.
2. Определение глав.
3. Создание TTS-copy.
4. Применение словарей.
5. Segmenter.
6. Проверка текста.

### Этап B — выбор диктора

1. Контрольный литературный фрагмент.
2. Несколько voice profiles.
3. A/B audition.
4. Фиксация render profile.

### Этап C — генерация

1. Estimate.
2. Cost guard для Yandex.
3. Queue.
4. Cache hit check.
5. Synthesis.
6. Automatic QA.
7. Resume при необходимости.

### Этап D — редактура аудио

1. QA Queue.
2. Исправление произношения/паузы.
3. Точечная перегенерация.
4. Approve.

### Этап E — сборка

1. Assemble chapters.
2. Technical QA.
3. Mastering.
4. Master WAV.

### Этап F — выпуск

1. MP3 chapters.
2. Metadata.
3. Cover.
4. M4B при наличии режима.
5. Финальная проверка.
6. Очистка только безопасных временных файлов.

---

## 27. Текущий implementation contour

Repository хранит provider-neutral production source, tests и contracts. Локальный workspace хранит пользовательские книги, runtime, audio artifacts, manifests, cache, builds и exports.

Production entry points имеют разные обязанности и не являются дубликатами:

- `audiobook_studio_app_runner.py` — общий offline-first bridge для native UI;
- `studio_app_runner.py` — Qwen-specific catalog/run adapter;
- `yandex_backend_runner.py` — provider CLI для Yandex health/demo boundary;
- `openai_backend_runner.py` — provider CLI для OpenAI status, credential fact, pricing, cache-aware preflight и fail-closed production run boundary;
- `paid_run.py` — Python-authoritative immutable one-time approval для максимум одного нового OpenAI TTS request;
- `voice_library.py` — единственный нормализатор общей Voice Library;
- `workspace_paths.py` — единственный resolver локального workspace.

Provider-neutral atomic JSON и PCM WAV integrity helpers находятся в `backends/common.py`. OpenAI использует общие Studio book/job/profile semantics и canonical workspace (`cache/openai`, `jobs`), не создавая отдельной библиотеки книг, QA, mastering или export pipeline.

Общий WAV validator строго проверяет finalized RIFF/chunk sizes и отдельно поддерживает streaming sentinel `0xFFFFFFFF` для RIFF и/или `data`, вычисляя фактический PCM payload до EOF. Sentinel принимается только при полном structural PCM contract и frame alignment. HTTP Content-Length остаётся независимой transport-проверкой. Для будущего `AMBIGUOUS` после полученного audio response OpenAI сохраняет local-only forensic artifact вне final/cache и allow-listed diagnostics без credentials/raw headers; historical manifest первого smoke не изменяется.

Production-семантика streaming WAV подтверждена вторым controlled OpenAI smoke на профиле `openai_cedar`: один streamed WAV с RIFF и `data` sentinel прошёл общий validator, был атомарно установлен и переиспользован через cache/Resume без второго network request. Smoke не является основанием для снятия `paid_execution_enabled = false` или включения native paid action.

AppleScript launchers больше не входят в production contour: canonical UI реализован в `native/AudiobookStudioApp.swift`.

---

## 28. Критерии готовности Yandex MVP

Yandex backend считается пригодным к реальной книге только если одновременно выполнено:

- API key не хранится в repo;
- авторизация работает через сервисный аккаунт;
- один сегмент синтезируется стабильно;
- book/chapter batch умеет Resume;
- готовый сегмент не оплачивается повторно при cache hit;
- стоимость показывается до запуска;
- локальный cost limit работает;
- retry не может уйти в бесконечный цикл;
- request IDs логируются;
- данные не логируются Яндексом по нашему явному флагу;
- WAV проходит integrity QA;
- можно перегенерировать один сегмент;
- можно собрать главу без ручного Terminal-workflow;
- качество выбранного голоса проверено на литературном фрагменте.

---

## 29. Что сознательно НЕ делаем сейчас

- не создаём отдельные provider-specific приложения и production contours;
- не удаляем и не переписываем рабочий Qwen backend;
- не реализуем OpenAI Custom Voice;
- не создаём synthetic voice slots или обязательное gender-измерение;
- не хардкодим цену SpeechKit навечно;
- не хардкодим один размер сегмента без тестов;
- не складываем API keys в JSON;
- не храним пользовательские книги и runtime audio в repository;
- не генерируем всю книгу заново после правки одной фразы;
- не используем MP3 как единственный master;
- не заставляем пользователя управлять книгой через Terminal.

---

## 30. Workspace и native build contracts

Canonical workspace resolver: `workspace_paths.py`.

```text
default: ~/Documents/New project/Audiobook-Studio
environment override: AUDIOBOOK_STUDIO_HOME
contract override: AUDIOBOOK_STUDIO_PATH_CONTRACT
default local contract: Audiobook-Studio/settings/workspace-paths.json
```

Provider-specific paths всегда выводятся из единого корня. Второй независимый resolver или machine-specific absolute paths в production source не допускаются.

Native staging build создаётся `native/build_native_app.sh` в `Audiobook-Studio/builds/native-staging/Audiobook Studio.app`. Build использует minimum target macOS 14 и изолированный module cache, ключ которого включает версию Swift compiler и macOS SDK. Staging build не заменяет Desktop app автоматически.

---

## 31. Единый Cloud Billing contract

Cloud Billing является общей инфраструктурой Studio, а не частью конкретного TTS adapter. Канонический implementation — `cloud_billing.py`.

Каждое денежное значение имеет один обязательный provenance:

```text
provider_reported
local_actual
local_estimate
user_confirmed
unavailable
```

Estimate никогда не записывается как actual, а локальный расчёт не называется provider balance. Денежная арифметика выполняется только через `Decimal`; RUB и USD не конвертируются и не суммируются между собой.

Общий UI/bridge contract для каждого provider содержит:

```text
provider / currency
spent / spent_source / spent_as_of
remaining / remaining_source / remaining_as_of
current_job_estimate / current_job_estimate_source
projected_remaining / projected_remaining_source
freshness / status / warnings
last_successful_refresh / last_attempt / stale_after_seconds
hard_limit / low_balance_threshold
```

Недоступное значение передаётся как `null` с source/status `unavailable`, а не как ноль.

### 31.1. Локальные settings и ledger

Канонические пути выводятся только через `workspace_paths.py`:

```text
settings: Audiobook-Studio/settings/cloud-billing.json
ledger:   Audiobook-Studio/runtime/billing/ledger.json
cache:    Audiobook-Studio/runtime/billing/provider-cache.json
```

Settings schema versioned и local-only. В ней допустимы billing account ID, user-confirmed OpenAI baseline, timestamps, low-balance thresholds, OpenAI per-job hard limit и freshness preferences. Credentials, API keys, IAM/Admin tokens и cookies запрещены.

Ledger отражает только фактические Studio billing events. Запись защищена file lock, выполняется atomic replace и имеет deterministic transaction ID. Точный повтор является idempotent no-op; conflicting transaction или повторное использование request ID отклоняются. Если точную стоимость completed request нельзя доказать, event сохраняется с `actual_cost: null` и `cost_source: unavailable`; estimate не подставляется.

### 31.2. Yandex

Read-only provider balance поддерживается через документированный:

```text
GET https://billing.api.cloud.yandex.net/billing/v1/billingAccounts/{id}
```

Успешное поле `balance` получает `remaining_source: provider_reported`. Billing account ID хранится только в local settings.

Yandex Billing API документированно требует IAM Bearer token. Существующий SpeechKit API key (`Authorization: Api-Key`) нельзя молча использовать как Billing credential. Для будущего refresh предусмотрен отдельный optional Keychain service `AudiobookStudio-YandexBilling-IAM`; Studio его не создаёт и не изменяет. Минимальная read-only роль — `billing.accounts.viewer`. При отсутствии ID, IAM credential или permission balance остаётся explicit unavailable, а SpeechKit продолжает работать по прежнему contract.

Yandex `hard_limit_rub` не заменяется provider balance и остаётся отдельным последним pricing guard.

### 31.3. OpenAI

Provider-wide costs и audio speech usage могут читаться только через документированные Organization Administration endpoints:

```text
GET https://api.openai.com/v1/organization/costs
GET https://api.openai.com/v1/organization/usage/audio_speeches
```

Они используют отдельный optional Admin credential из Keychain service `AudiobookStudio-OpenAI-Admin`. Production TTS key не считается Admin key и не проверяется как таковой. Costs являются дополнительным provider-wide metadata и не заменяют локальный Studio spend.

Документированный поддерживаемый endpoint точного prepaid credit balance в текущей реализации отсутствует. Studio не использует dashboard scraping, undocumented endpoints, browser cookies или session tokens. Поэтому OpenAI `remaining` по умолчанию `null/unavailable`.

Optional user-confirmed USD baseline хранится локально с `confirmed_at`. Расчёт `baseline - known local actual since confirmation` получает `remaining_source: local_estimate` и обязательное предупреждение о возможном использовании OpenAI вне Studio. Stale baseline не становится fresh автоматически.

OpenAI имеет отдельный local per-job hard limit в USD; default `1.00 USD`. Он не является balance. Canonical `paid_execution_enabled = false` сохраняется: разрешение на один request существует только внутри повторно валидированного и атомарно consumed one-time plan, а не как global unlock.

### 31.4. Refresh и решения

Refresh ограничен минимальным interval и выполняет только read-only Billing/Organization requests. Последний успешный provider value может сохраняться после сетевой ошибки только как `STALE` с датой. Не выполняются TTS synthesis, IAM changes, purchase, auto-recharge, budget creation или provider-side configuration changes.

Preflight decision contract:

```text
ALLOW
BLOCK
REQUIRES_CONFIRMATION
BALANCE_UNKNOWN
```

Projected remaining вычисляется только при известных remaining и current-job estimate и всегда маркируется `local_estimate`.

### 31.5. Native UI integration

Native `Audiobook Studio` использует один engine selector: Qwen, Yandex и OpenAI. Голоса загружаются только из `voice_library` canonical UI snapshot: 9 Qwen, 4 Yandex и approved OpenAI Onyx/Cedar. Yandex production-default остаётся Lera / neutral / 1.04; OpenAI показывает model `gpt-4o-mini-tts`, WAV и явный blocked paid status.

Cloud backend получает компактную секцию «Расходы и лимиты» с `spent`, `remaining`, `current_job_estimate`, `projected_remaining`, provenance, freshness, warnings и hard limit. `null` никогда не форматируется как ноль. RUB и USD имеют разные formatter, а `local_estimate` визуально маркируется `≈`. Qwen вместо billing показывает отсутствие API-расходов.

Кнопка refresh вызывает только `--billing-status --provider <provider> --refresh`. Нормальное отсутствие account ID, IAM/Admin credential или документированного OpenAI prepaid balance остаётся inline unavailable state, а не fatal UI error. OpenAI hard limit изменяется только через атомарный provider-neutral bridge command `--set-billing-setting`; Swift не пишет Cloud Billing JSON напрямую.

### 31.5. Safe native OpenAI paid execution v1

Статус: **ACCEPTED AND DEPLOYED**. Global `paid_execution_enabled` остаётся `false`.

Native OpenAI workflow использует реальные prepared jobs из canonical book profiles и две bridge responsibility:

```text
--prepare-paid-run --provider openai --book <book> --job <job> --profile-id <profile>
--execute-paid-plan --plan-id <id> --plan-digest <sha256>
```

Native safety flow:

```text
primary action
→ local PREPARE confirmation
→ one-shot intent consume
→ network-free immutable PREPARE
→ separate paid confirmation
→ maximum one new provider request
→ plan consumed
```

Launch, reload и изменение engine/profile/book/job сами по себе не вызывают PREPARE (`PREPARE = 0`). Любое изменение execution selection инвалидирует pending one-shot intent. `CACHE_ONLY` также начинается только явным local user action, но выполняется с provider network `0`.

Prepare не синтезирует audio и не вызывает TTS network. Он строит production segmentation/fingerprints, проверяет manifest, cache, Resume, AMBIGUOUS/FAILED, pricing freshness, shared Cloud Billing hard limit и Keychain credential availability, затем детерминированно выбирает только первый `PENDING + MISS`.

Immutable JSON plans хранятся атомарно в `Audiobook-Studio/runtime/paid-run-plans/`, TTL по умолчанию 10 минут. Plan states: `PREPARED`, `CONSUMING`, `CONSUMED`, `EXPIRED`, `BLOCKED`; decisions: `READY_FOR_CONFIRMATION`, `CACHE_ONLY`, `BLOCKED`.

Перед TTS network execute повторно валидирует тот же SHA-256 digest и все execution-critical facts. Затем plan атомарно переводится `PREPARED → CONSUMING`; ни crash, ни повторный вызов не возвращают его в `PREPARED`. Временный `paid_execution_enabled=True` существует только in-process внутри validated execute и не записывается в config.

Технический invariant production code:

```text
one user confirmation = max_network_requests 1
automatic retries = 0
multi-segment automatic batch = forbidden
```

После одного successful segment остальные сохраняют свои состояния, а общий manifest становится `PARTIAL`, если есть pending. Valid cache-only plan materializes audio с network `0` и ledger additions `0`. Matching `AMBIGUOUS` и unresolved `FAILED` блокируют plan до явного разрешения; кнопки implicit retry нет. Exact future OpenAI audio cost и prepaid balance остаются `null / unavailable`, никогда не превращаются в estimate-as-actual или `$0`.

Live native acceptance выполнил ровно один OpenAI request из фактически выбранного process state `openai_onyx`: automatic retry `0`, HTTP `200`, request ID `req_ec29b6810200449791be47c8aabf201f`, `audio/wav`, PCM 24 kHz / 16-bit / mono, duration 7.85 sec. WAV validation, atomic final, cache и `SUCCEEDED` manifest прошли; billing получил один event с unknown actual cost, без подмены exact cost/balance. Это не Cedar failure и не profile substitution: historical Cedar production transport validation остаётся отдельным принятым доказательством.

Для новых consumed plans execution fact сохраняется в самом plan: при `network_requests = 1` — `remote_request_sent = true`; при `network_requests = 0` / `CACHE_ONLY` — `false`; при `AMBIGUOUS` после начала network — `true` и automatic retry `0`. Historical forensic plans задним числом не переписываются.

Accepted build развёрнут как production Desktop bundle `/Users/elenadymova/Desktop/Audiobook Studio.app`. Следующий product checkpoint: `BOOK LIBRARY / ADD BOOK + IMMUTABLE SOURCE / TTS WORKING COPY`.

---

## 32. Официальные источники Yandex для реализации

Перед изменениями API, лимитов и тарификации проверять текущую документацию, а не полагаться на сохранённые цифры.

- SpeechKit API v3 quickstart: `https://yandex.cloud/ru/docs/speechkit/quickstart/tts-quickstart-v3`
- Authentication: `https://yandex.cloud/ru/docs/speechkit/concepts/auth`
- API v3 synthesis examples: `https://yandex.cloud/ru/docs/speechkit/tts/api/tts-examples-v3`
- Streaming synthesis: `https://yandex.cloud/ru/docs/speechkit/tts/api/tts-streaming`
- SpeechKit pricing: `https://yandex.cloud/ru/docs/speechkit/pricing`
- Audio formats: `https://yandex.cloud/ru/docs/speechkit/formats`
- Support / diagnostic headers: `https://yandex.cloud/ru/docs/speechkit/concepts/support-headers`

**Правило:** цена, список голосов, параметры голосов, API-лимиты и billing rules считаются изменяемыми внешними данными и проверяются перед production-релизом.

---

# Итоговое архитектурное решение

**Audiobook Studio — единый производственный конвейер аудиокниг с подключаемыми TTS backend.**

Qwen/MLX остаётся локальным backend. Yandex SpeechKit v3 и OpenAI TTS являются облачными backend. Текстовая подготовка, сегментация, словари, Voice Library, manifest, cache, очередь, Resume, QA, Review, сборка, mastering и export являются общей инфраструктурой и не дублируются по движкам.

Это направление считается базовой архитектурой дальнейшей разработки проекта.
