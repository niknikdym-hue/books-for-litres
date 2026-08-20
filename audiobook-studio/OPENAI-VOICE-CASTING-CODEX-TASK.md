# CODEX TASK — OpenAI Voice Casting (Stage OAI-1)

## 0. Recovery gate — обязательно

Если задача открыта в новом чате/аккаунте и предыдущая переписка недоступна, сначала прочитать полностью:

```text
qwen-audiobook-studio/docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md
qwen-audiobook-studio/docs/HANDOFF-2026-08-20-STUDIO-OPENAI-CASTING.md
qwen-audiobook-studio/docs/OPENAI-TTS-BACKEND-CONTRACT.md
```

Затем проверить локальный git state пользователя:

```bash
git status
git log --oneline --decorate -10
git remote -v
```

Не считать remote `main` authority, если локальный `main` опережает origin.
Не делать reset/rebase/force-push.

---

# 1. Назначение

Провести только voice casting встроенных OpenAI TTS voices на русском тексте и подготовить выбор:

```text
1 женский OpenAI narrator
1 мужской OpenAI narrator
```

Это Stage OAI-1.

НЕ интегрировать OpenAI в production Studio в этой задаче.
НЕ создавать отдельную OpenAI Studio.

OpenAI — будущий третий backend общей Audiobook Studio.

---

# 2. Неприкосновенные решения

Yandex profile уже утверждён:

```text
Lera / neutral / 1.04
```

Он FROZEN и НЕ участвует в сравнении.

Не менять:

- Yandex backend;
- Yandex pricing;
- Qwen backend/runtime/model/cache;
- native Studio frontend;
- старый Desktop `.app`;
- тексты реальных книг.

Custom Voice сейчас НЕ делать.

---

# 3. OpenAI model и endpoint

Использовать актуальный OpenAI Speech API contract, подтверждая его по официальной документации перед запуском.

Ожидаемый baseline на 2026-08-20:

```text
POST https://api.openai.com/v1/audio/speech
model: gpt-4o-mini-tts
response_format: wav
```

Официальные references:

```text
https://developers.openai.com/api/docs/guides/text-to-speech
https://developers.openai.com/api/docs/models/gpt-4o-mini-tts
```

Если API/voice list/pricing изменились — не молча использовать старые данные. Зафиксировать актуальные значения в casting manifest/report.

---

# 4. Голоса первого круга

Проверить весь текущий built-in voice set, чтобы не угадывать пол и качество по названию.

Baseline list на 2026-08-20:

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

Если официальный API/docs показывают другой актуальный список — использовать актуальный и сообщить diff.

Не маркировать заранее voice как male/female на основании названия.

---

# 5. Casting text

Использовать ОДИН и тот же искусственный русский литературный фрагмент для всех голосов.

Требования к тексту:

- 45–70 секунд ожидаемой речи;
- современная литературно-публицистическая русская проза;
- несколько длинных и коротких предложений;
- вопрос;
- прямая речь или реплика;
- имена/числа не нужны;
- без текста существующих книг пользователя;
- без спорных ударений и редких терминов, чтобы тестировать голос, а не словарь.

Casting text сохранить отдельно в repo как UTF-8 TXT, чтобы все будущие повторные тесты использовали тот же source.

Предпочтительный path:

```text
qwen-audiobook-studio/casting/openai/openai-russian-casting-text.txt
```

---

# 6. Speech instructions

Для первого круга использовать единый нейтральный audiobook instruction preset для всех voices.

Цель — сравнить голоса, а не prompt engineering.

Пример смысла инструкции:

```text
Read in natural modern Russian as a professional audiobook narrator.
Calm, expressive but restrained, no advertising tone, no theatrical overacting.
Preserve punctuation, natural sentence rhythm and paragraph pauses.
```

Фактический instruction сохранить в manifest дословно.

Не делать отдельный уникальный prompt на каждый voice в первом круге.

---

# 7. Credentials

OpenAI API key НЕ коммитить.

Сначала определить, есть ли credential в безопасном локальном источнике.

Допустимые варианты:

- macOS Keychain;
- environment variable, установленная пользователем;
- иной уже существующий local secrets provider.

Если credential отсутствует:

```text
STOP
```

и сообщить пользователю, что нужно один раз безопасно подключить OpenAI API credential.

Не просить вставлять API key в task-файл/repo.
Не печатать полный key в stdout/log.
Не создавать новый API key автоматически.

---

# 8. Budget safety

У пользователя на API-счёте примерно `$10`.

Casting не должен иметь возможность потратить заметную часть баланса.

Установить локальный casting hard cap:

```text
MAX_CASTING_COST_USD = 1.00
```

Это верхний аварийный предел, а не целевой расход.

Перед реальными requests:

1. оценить ожидаемый верхний порядок стоимости;
2. показать количество voices и число planned requests;
3. убедиться, что plan значительно ниже $1;
4. при невозможности безопасно оценить — STOP.

Не делать auto-loop/retry без bounded retry policy.

---

# 9. Output structure

Casting artifacts должны лежать организованно и не смешиваться с production renders.

Предпочтительно локально:

```text
<Studio>/casting/openai/<timestamp>/
├── CASTING-MANIFEST.json
├── 01-<voice>.wav
├── 02-<voice>.wav
...
└── README.txt
```

В GitHub НЕ коммитить WAV.

В repo коммитить только:

- casting source text;
- casting config/schema;
- casting runner/tests, если они нужны;
- report/template без бинарного аудио.

`.gitignore` должен исключать generated casting WAV/output directories.

---

# 10. Manifest

Для каждого sample записать минимум:

```text
provider: openai
model
voice
instructions
response_format
text_sha256
request_started_at
request_completed_at
success/error
output filename
size
WAV validation result
usage metadata, если API возвращает
estimated/known cost metadata
```

Не записывать API key.

Casting manifest должен позволять понять спустя месяцы, чем именно был создан каждый WAV.

---

# 11. Audio validation

После каждого успешного response:

- подтвердить RIFF/WAVE;
- проверить, что файл не пуст;
- duration > 0;
- зафиксировать sample rate/channels/sample width;
- не перекодировать до первичного пользовательского прослушивания без необходимости.

Если voice request упал — сохранить ошибку структурированно и не создавать фиктивный WAV.

---

# 12. Retry policy

Для casting можно сделать максимум один осознанный retry только для явно retryable transport/rate-limit ошибки и только если известно, что response не был успешно получен.

Не делать бесконечный retry.

При неоднозначной ситуации, где запрос мог быть принят и списание могло произойти, отметить sample как `AMBIGUOUS` и не повторять автоматически.

---

# 13. User review package

После завершения первого круга пользователю нужен простой набор WAV для прослушивания.

Имена должны позволять однозначно видеть voice.

Дополнительно создать текстовый summary:

```text
voice
file
success
approx duration
technical WAV properties
```

НЕ пытаться автоматически объявить победителя на основании спектральных метрик.

Итог male/female выбирается пользователем после прослушивания.

После первого прослушивания пользователь может разделить голоса на:

```text
female candidates
male candidates
reject
```

После этого отдельным вторым коротким round можно синтезировать только finalists на более сложном 2–3 минутном тексте.

---

# 14. Tests

До реального casting requests добавить offline tests минимум на:

- config loading;
- voice list;
- request payload generation;
- no secret in logs/manifest;
- WAV response validation;
- budget cap blocking;
- bounded retry;
- manifest write;
- generated output excluded from git.

Tests не должны отправлять OpenAI requests.

---

# 15. Не делать

В Stage OAI-1 запрещено:

- добавлять OpenAI в native production UI;
- создавать book/chapter OpenAI generation;
- делать Resume production engine;
- делать production OpenAI pricing provider сверх минимальной casting estimate safety;
- использовать реальные книги;
- сравнивать/менять Lera;
- менять Qwen;
- делать Custom Voice;
- загружать голос пользователя;
- коммитить WAV;
- тратить > $1 casting cap;
- трогать GitHub history пользователя reset/rebase/force-push.

---

# 16. Git safety при текущем состоянии

На момент создания задачи пользовательский Mac имел непубликованные локальные Audiobook Studio commits, а remote main отставал.

Поэтому перед изменениями:

- проверить local checkout пользователя;
- работать поверх фактического local HEAD, если он содержит более новые Studio changes;
- не сбрасывать local commits к remote;
- не cherry-pick ChatGPT branch вслепую;
- reconcile `docs/OPENAI-TTS-BACKEND-CONTRACT.md` и handoff с локальной историей аккуратно.

ChatGPT-side branch с этими документами:

```text
chatgpt/openai-voice-casting-20260820
```

---

# 17. Stop point

После первого casting round сообщить:

1. фактическую model;
2. актуальный список tested voices;
3. точный casting text path/hash;
4. instruction preset;
5. число requests;
6. estimated/actual known cost;
7. output folder;
8. WAV validation summary;
9. какие samples failed/ambiguous;
10. tests;
11. git status;
12. commit SHA для source/config/test changes, если commit разрешён текущим git state.

Затем STOP.

Не выбирать за пользователя финальные male/female voices без прослушивания.
