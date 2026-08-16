# Qwen3-TTS 0.6B CustomVoice — актуальный выбор для SHORT TEST

Дата проверки: 2026-08-16

## Решение

Активный кандидат для следующего локального теста аудиокниги:

`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`

Важно: это **НЕ прежний voice-cloning pipeline**.

Ранее забракован именно путь Qwen3-TTS 0.6B + MLX + voice cloning: он дал плохой клонированный звук («звуковая каша») и оказался слишком тяжёлым по настройке. Этот FAIL нельзя переносить на `CustomVoice` с готовыми встроенными дикторами.

## Что подтверждено официально

Официальный model card Qwen:
`https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`

Официальный репозиторий:
`https://github.com/QwenLM/Qwen3-TTS`

Подтверждено:

- русский входит в 10 официально поддерживаемых языков;
- модель имеет 9 готовых premium timbres;
- официальный README прямо указывает, что каждый готовый speaker может говорить на любом поддерживаемом моделью языке;
- для лучшего качества Qwen рекомендует native language конкретного speaker, но русский синтез для этих speaker поддерживается;
- voice cloning для `CustomVoice` не нужен;
- вызов: `generate_custom_voice(text=..., language="Russian", speaker=...)`;
- модель и Python package опубликованы под Apache-2.0;
- репозиторий модели занимает примерно 2.5 GB, основной `model.safetensors` около 1.81 GB;
- модель существенно легче 1.7B-вариантов и поэтому является первым разумным кандидатом для MacBook Air M1 / 8 GB.

## Готовые голоса

Все 9 должны быть прослушаны на одном и том же коротком русском фрагменте, потому что по описанию нельзя надёжно предсказать русский акцент и книжную естественность.

1. `Vivian` — bright young female; native Chinese.
2. `Serena` — warm, gentle young female; native Chinese.
3. `Uncle_Fu` — seasoned low/mellow male; native Chinese.
4. `Dylan` — youthful clear male; native Chinese / Beijing.
5. `Eric` — lively slightly husky male; native Chinese / Sichuan.
6. `Ryan` — dynamic rhythmic male; native English.
7. `Aiden` — sunny clear-midrange male; native English.
8. `Ono_Anna` — playful female; native Japanese.
9. `Sohee` — warm female; native Korean.

Нативного русского speaker в штатной девятке нет. Поэтому gate — только реальное прослушивание русского WAV.

## Apple Silicon / M1

Официальный `main` Qwen всё ещё содержит CUDA-ориентированные примеры. На 2026-08-16 Apple Silicon support ещё не смержен.

Но в официальном репозитории открыт PR:
`https://github.com/QwenLM/Qwen3-TTS/pull/345`

PR #345: `Add MLX / Apple Silicon (MPS) backend support`.

Проверенный на 2026-08-16 head SHA:
`26a5dacbc1644772df13f34966838e601a59c03c`

Автор PR сообщает, что на Apple Silicon / MPS успешно прошли все четыре example scripts, включая `test_model_12hz_custom_voice.py`.

Из PR:
- MPS auto-detection;
- `bfloat16` -> `float16` fallback on MPS;
- FlashAttention2 отключается вне CUDA;
- CustomVoice example реально прогнан на Apple Silicon.

Статус PR на 2026-08-16: OPEN, не merged.

Поэтому этот путь считается **проверяемым, но не production-stable upstream**. Работать только в отдельном каталоге, pinned к указанному head SHA. Старую Qwen-среду не трогать.

## Python

Официальный `pyproject.toml` поддерживает Python `>=3.9`, включая 3.11.

На Mac уже сохранён Homebrew Python 3.11.16:
`/opt/homebrew/Cellar/python@3.11/3.11.16`

Новый Python устанавливать не нужно. Для теста создаётся отдельный venv внутри нового тестового каталога.

## Реальный риск: русский язык

В официальных GitHub Discussions Qwen есть открытые сообщения о неправильных русских ударениях и отсутствии надёжного штатного stress-control.

Основная дискуссия:
`https://github.com/QwenLM/Qwen3-TTS/discussions/185`

Это не причина заранее закрывать модель, но это обязательный HUMAN GATE.

Поэтому тест оценивает отдельно:
- общий русский акцент;
- естественность фразовой интонации;
- правильность ударений;
- стабильность тембра;
- пригодность для длинного книжного чтения.

Никакие знаки ударения не добавлять в мастер книги. Если впоследствии потребуется техническая preprocessing-копия — она должна быть отдельной.

## Правильный порядок теста

### Stage A — технический smoke

Один speaker: `Serena`.
Один короткий русский фрагмент.

Цель: доказать, что 0.6B CustomVoice реально грузится и даёт WAV на M1 / 8 GB без OOM и без ремонта старых TTS.

Если Stage A технически проходит — Stage B.

### Stage B — blind voice audition

Один и тот же короткий фрагмент генерируется всеми 9 speaker.

Файлы именовать нейтрально по speaker, не менять текст и базовые generation settings между голосами.

Пользователь слушает все 9 и выбирает максимум 2 финалистов.

### Stage C — только для финалистов

- титульная строка;
- отдельный русский stress/accuracy diagnostic;
- более длинный книжный фрагмент;
- при необходимости один аккуратный `instruct` для книжной манеры.

До выбора финалистов не тратить время на тонкую режиссуру.

## STOP-условия

Сразу остановить этот путь, если:

- M1/8 GB не может загрузить модель без OOM / тяжёлого swap;
- Apple-Silicon PR требует каскада сторонних фиксов;
- все 9 голосов звучат по-русски с явно иностранным акцентом;
- системные ошибки ударений слишком часты для книжного текста;
- речь снова воспринимается как авточтец;
- для приемлемого результата требуется возвращаться к voice cloning.

## Текущий статус

`QWEN CLONING PATH: FAIL / CLOSED`
`QWEN 0.6B CUSTOMVOICE: SELECTED FOR SHORT TEST`
`RUSSIAN: OFFICIALLY SUPPORTED`
`PRESET SPEAKERS: 9`
`NATIVE RUSSIAN PRESET SPEAKER: NO`
`CLONING REQUIRED: NO`
`MODEL LICENSE: APACHE-2.0`
`MAC APPLE SILICON: PR #345 / TESTED BY PR AUTHOR / NOT MERGED`
`M1 8GB: TO BE PROVEN BY REAL SHORT TEST`
`FULL BOOK: HOLD`
