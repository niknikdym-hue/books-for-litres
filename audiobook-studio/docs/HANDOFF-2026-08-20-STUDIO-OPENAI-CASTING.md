# Audiobook Studio — recoverable handoff checkpoint

**Дата:** 2026-08-20  
**Назначение:** восстановить проект после обрыва чата/смены аккаунта/новой сессии без пересборки контекста по памяти.  
**Canonical repo:** `niknikdym-hue/books-for-litres`  
**Project root:** `qwen-audiobook-studio/`

---

# 1. Как продолжать после обрыва чата

Новый исполнитель/новый чат должен сначала прочитать, в таком порядке:

1. `qwen-audiobook-studio/docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`
2. `qwen-audiobook-studio/docs/HANDOFF-2026-08-20-STUDIO-OPENAI-CASTING.md` — этот файл
3. `qwen-audiobook-studio/docs/OPENAI-TTS-BACKEND-CONTRACT.md`
4. актуальные task-файлы текущего этапа
5. `git status`, `git log --oneline --decorate -10`, `git remote -v` в локальном checkout пользователя

Нельзя считать remote `main` единственным authority, если локальный checkout пользователя опережает origin. Сначала сравнить local HEAD и remote HEAD.

---

# 2. Главная продуктовая архитектура

Должна существовать ОДНА пользовательская система:

```text
Audiobook Studio
├── Qwen / MLX Local
├── Yandex SpeechKit v3
└── OpenAI TTS
```

Это не три студии.

Общие слои:

```text
книга / source text
→ TTS preprocessing
→ literary segmentation
→ engine adapter
→ segment WAV
→ cache / fingerprint
→ manifest / Resume
→ QA / review
→ assembly
→ mastering / export
```

Каждый новый TTS provider — сменный backend общей Studio.

---

# 3. Неприкосновенный Yandex checkpoint

Yandex SpeechKit уже подключён и реальный demo успешно прошёл через `Audiobook Studio.app`.

Утверждённый профиль ЗАФИКСИРОВАН и не участвует в последующих кастингах:

```text
engine: yandex_speechkit_v3
voice: lera
role: neutral
speed: 1.04
status: APPROVED / FROZEN
```

Не сравнивать Lera с OpenAI и не заменять её.

Yandex backend уже имеет:

- Keychain credential loading;
- segmentation;
- manifest;
- cache;
- Resume;
- IN_FLIGHT / AMBIGUOUS protection;
- WAV validation;
- streaming join;
- request IDs;
- `x-data-logging-enabled: false`.

Контрольный реальный demo:

```text
speechkit-demo__lera-neutral-1.04.wav
```

Был успешно синтезирован и прослушан пользователем; качество принято.

---

# 4. Yandex pricing gate

На пользовательском Mac локально уже реализован отдельный pricing gate.

Известный локальный commit:

```text
3cb245e1eb2e78674ef31aa71af610f7658b177c
Add Yandex pricing gate and native Studio frontend
```

На момент этого handoff commit ещё НЕ опубликован в remote из-за отсутствия GitHub credentials в локальной Codex-сессии.

Известный тогда remote main HEAD:

```text
6b806e0dd416bf8cd8c4565a712e622bd2ee3a9e
```

Перед любой последующей git-операцией перепроверить фактическое состояние — эти SHA могут уже измениться.

Pricing implementation checkpoint:

```text
0.21146666 RUB / billing unit
verified_at: 2026-08-20
source: https://yandex.cloud/ru-kz/docs/speechkit/pricing
freshness: 30 days
```

Реализовано локально:

- Decimal money arithmetic;
- cache-aware `billable_remaining_units`;
- stale/missing tariff blocking;
- `hard_limit_rub`;
- full-book run blocking without valid price/limit.

Reported tests:

```text
Yandex: 11/11 PASS
Universal bridge: 8/8 PASS
Pricing: 9/9 PASS
GUI/bridge: 3/3 PASS
py_compile: PASS
Swift syntax parse: PASS
```

---

# 5. Native Studio UI checkpoint

На пользовательском Mac локально написан:

```text
qwen-audiobook-studio/native/AudiobookStudioApp.swift
```

Цель — единое нативное macOS-приложение вместо цепочки AppleScript dialogs.

Реализованные/запланированные UX элементы:

- единое окно;
- библиотека книг;
- выбор backend;
- engine-specific voice/profile;
- estimate до запуска;
- стоимость;
- Settings;
- hard limit;
- progress/status;
- Resume;
- `Готово`;
- `Прослушать`;
- `Показать в Finder`;
- technical details только отдельно.

Текущий старый Desktop app:

```text
/Users/elenadymova/Desktop/Audiobook Studio.app
```

НЕ удалять и НЕ перезаписывать, пока новая native сборка не прошла offline smoke test.

Последняя диагностика native build выявила два конкретных blocker:

1. некорректные `CodingKeys` у `YandexEstimate` в `native/AudiobookStudioApp.swift`;
2. `native/build_native_app.sh` должен корректно использовать `-parse-as-library` для файла с `@main`.

Полноценный Xcode пока не признан обязательным blocker: SwiftUI/AppKit импортировались текущим Command Line Tools toolchain.

Следующий native шаг: исправить ТОЛЬКО подтверждённые build defects, typecheck, собрать staging `.app`, сделать offline smoke test. Не выполнять TTS.

---

# 6. Qwen checkpoint

Qwen/MLX — существующий рабочий backend.

Не переписывать ради Yandex/OpenAI.

Рабочий runtime пользователя:

```text
/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16
```

Сохранены 9 voices:

```text
Vivian
Serena
Uncle_Fu
Dylan
Eric
Ryan
Aiden
Ono_Anna
Sohee
```

Не скачивать модель заново, не менять HF cache, не трогать старые renders без отдельной задачи.

---

# 7. OpenAI decision checkpoint

Пользователь решил подключить OpenAI как дополнительный backend общей Studio.

Текущий scope OpenAI:

```text
1 approved female built-in narrator
1 approved male built-in narrator
```

Custom Voice / синтез голоса пользователя:

```text
DEFERRED
```

Возможность должна оставаться архитектурно открытой, но сейчас не реализуется.

Lera НЕ участвует в OpenAI casting.

OpenAI contract:

```text
qwen-audiobook-studio/docs/OPENAI-TTS-BACKEND-CONTRACT.md
```

Основная candidate model:

```text
gpt-4o-mini-tts
```

Built-in voices на дату проверки:

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

Кастинг проводится на русском контрольном книжном тексте.
Не назначать пол/роль по названию voice — выбирать после прослушивания.

---

# 8. OpenAI billing checkpoint

На API-счёте пользователя есть примерно:

```text
$10
```

Этого достаточно для короткого voice casting.

Публичная pricing reference на 2026-08-20 для `gpt-4o-mini-tts`:

```text
text input: $0.60 / 1M text tokens
audio output: $12.00 / 1M audio tokens
```

Перед production integration нужен отдельный OpenAI pricing provider + hard limit. Не использовать Yandex billing-unit formula.

Для кастинга установить малый task budget cap; задача не должна иметь возможность потратить весь balance.

---

# 9. OpenAI Stage OAI-1 — следующий отдельный этап

Цель:

```text
выбрать 1 женский + 1 мужской built-in OpenAI narrator
```

Первый casting round:

- один одинаковый искусственный русский книжный фрагмент;
- WAV для каждого доступного built-in voice;
- одинаковая модель;
- одинаковый instruction preset, насколько это разумно;
- manifest с model/voice/instructions/text hash/cost metadata;
- никакой реальной книги;
- никакой интеграции в production UI до выбора победителей.

После пользовательского прослушивания:

```text
openai_female = <approved voice>
openai_male = <approved voice>
```

Только потом Stage OAI-2 backend.

---

# 10. Git/repository recovery rule

Если чат оборвался:

1. НЕ создавать новый параллельный проект.
2. НЕ писать backend с нуля по памяти.
3. Проверить remote repo.
4. Проверить локальный checkout пользователя.
5. Сравнить local HEAD с origin/main.
6. Сохранить все существующие непубликованные commits.
7. Не делать `reset --hard`, force-push или rebase без отдельного решения.
8. Не добавлять `.DS_Store`, WAV, renders, logs, credentials.
9. Продолжать внутри `qwen-audiobook-studio/`.

Текущая ChatGPT-side branch, созданная для безопасной фиксации OpenAI-архитектуры без вмешательства в отстающий remote main:

```text
chatgpt/openai-voice-casting-20260820
```

Эту ветку нельзя механически merge в `main`, пока не проверено, не появились ли на пользовательском Mac более новые непубликованные commits. Сначала reconcile history.

---

# 11. Безопасность секретов

Никогда не коммитить:

- OpenAI API key;
- Yandex API key;
- Keychain dump;
- access token;
- GitHub PAT;
- credentials в логах.

Credential setup — отдельный локальный шаг.

---

# 12. Definition of continuity

Работа считается восстановимой после потери чата, если новый исполнитель может по repo + local git state ответить на вопросы:

- что строится;
- какие backends существуют;
- какой Yandex voice утверждён;
- что локально не опубликовано;
- что блокирует native app;
- какой следующий OpenAI этап;
- какие действия запрещены;
- какой следующий безопасный шаг.

Этот файл должен обновляться после каждого существенного архитектурного checkpoint, а не только в переписке.
