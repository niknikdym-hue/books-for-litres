# Audiobook Studio

Audiobook Studio — local-first macOS приложение для полного производства аудиокниги с несколькими TTS backend:

- Qwen / MLX Local;
- Yandex SpeechKit v3;
- OpenAI TTS.

Одна программа ведёт автора по цепочке:

```text
книга → текст → ударения → звуковое оформление → диктор → глава → запись → QA → сборка → мастеринг → выпуск
```

GitHub `main` — source of truth. Chat не является project authority.

## Canonical authority

Использовать документы в таком порядке:

1. [`docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md`](docs/AUDIOBOOK-STUDIO-ARCHITECTURE.md) — стабильные архитектурные invariants;
2. [`docs/PRONUNCIATION-DICTIONARY-V1.md`](docs/PRONUNCIATION-DICTIONARY-V1.md) — канон глобального пользовательского Словаря ударений;
3. provider-specific contracts;
4. [`docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md`](docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md) — фактическая текущая production-точка.

## Текущая Studio feature-точка

Последний принятый Studio merge:

```text
PR #52
fa5e1ed9a3796333246af88b5fddd697720f0055
```

После PR #49 дополнительно приняты:

- **PR #51** — global pronunciation dictionary + contextual homograph safety;
- **PR #50** — simple permanent/archive book deletion from sidebar с сохранением external source/audio/billing/provider records;
- **PR #52** — fix native chapter-cue crash и явный trimming UX.

## Пользовательский путь

Семь постоянных native production steps:

1. Текст
2. Ударения
3. Звук глав
4. Диктор
5. Глава
6. Запись / прослушивание
7. Выпуск

Все шаги видимы и кликабельны. На `Ударения` доступен текст книги, double-click word и Command-F.

Инженерные SHA/fingerprint, billing и advanced Content Quality не должны доминировать в author flow.

## Импорт книги

MVP:

```text
TXT
UTF-8
до 20 МБ
вся книга одним файлом
```

Immutable source остаётся неизменным. Для подготовки и TTS используется отдельная working copy.

Book Library поддерживает recoverable archive и owner-confirmed permanent removal Studio book profile/imported assets. Внешний исходный TXT, произведённое audio, billing и provider records при permanent removal сохраняются.

## Словарь ударений

Private runtime store:

```text
<AUDIOBOOK_STUDIO_HOME>/settings/pronunciation/user-dictionary-v1.json
```

Contract:

```text
contracts/pronunciation-dictionary-v1.schema.json
```

Основное правило:

```text
исправить ударение в Studio
→ применить к текущему context/book
→ сохранить owner evidence
→ автоматически upsert в global dictionary
→ применять в следующих книгах только если запись безопасна для AUTO
```

Priority:

```text
exact occurrence > book override > global AUTO > default pronunciation
```

### Контекстные омографы

Studio не делает silent guess для слов, где ударение зависит от значения.

V1 canonical case:

```text
замок
→ за́мок = строение, дворец или крепость
→ замо́к = запирающее устройство
```

Такое слово хранится как:

```text
mode = REVIEW_REQUIRED
preferred = null
```

В конкретном предложении пользователь выбирает нужный вариант; unresolved pronunciation блокирует только затронутый Yandex chapter/OpenAI segment.

Реальная ранее созданная owner-test запись `замок → замо́к / AUTO` уже мигрирована production-кодом в `за́мок / замо́к / REVIEW_REQUIRED`: revision `10→11`, повторный repair идемпотентен, существующий BOOK choice `замо́к` сохранён.

`PRONUNCIATION_DICTIONARY_V1 = ACCEPTED` после PR #51, full offline `750/750 PASS`, 1060×720 и 900×620 PASS, independent UX PASS, GitHub CI PASS, provider/network/model/paid = 0.

Canonical representation — Unicode acute (`Ди́лон`). Provider-specific Yandex/OpenAI rendering создаётся adapter-слоем.

## Voice Library

Approved Yandex:

- Lera — neutral / 1.04;
- Ermil — neutral / 1.0;
- Kirill — neutral / 1.0;
- Anton — neutral / 1.0.

Approved OpenAI:

- Onyx;
- Cedar.

Qwen profiles загружаются из local runtime catalog.

Narrator/profile сохраняется per book.

## Yandex production safety

```text
timeout default = 180 s
allowed = 1…600 s
silent automatic retry after ambiguous/sent request = 0
```

Continuation PREPARE — одна ожидаемая async-operation. После успешной записи Audio QA получает re-resolved canonical Yandex authority.

Private Keychain → Yandex → Audio QA acceptance 2026-09-03: PASS.

## Звуковое оформление

Chapter cue — downstream:

```text
clean TTS → Audio QA → approved narration → chapter cue → assembly → mastering
```

Смена cue или trimming не запускает TTS заново.

Поддерживаются:

- `Без звука`;
- preview/playback;
- per-book selection;
- favorites/genre selection;
- user WAV с owner rights attestation;
- локальные лицензированные GarageBand assets при наличии;
- explicit optional trimming;
- exact saved-fragment preview;
- one-click restore full sound.

После PR #52 выбор cue по умолчанию использует **весь звук, который пользователь прослушал**. Скрытого trimming больше нет. PR #52 также устранил native crash из zero-width SwiftUI Slider range. Full offline `757/757 PASS`, native build/codesign PASS, GitHub CI PASS.

На Mac найден реальный `Lounge Vibes 05.caf`; он показывается под честным именем как любимый вариант владельца. Exact исторический asset `Lounge Vibes 05.7` не найден.

## Форматы выпуска

Per-book, без default:

- по главам;
- M4B;
- MP3;
- архив высокого качества.

Whole-book output закрыт до полного required chapter set.

## Первая реальная книга

```text
book = hvatit-sebya-obestsenivat
accepted first chapter = chapter-ch001 / Введение
accepted Yandex WAV SHA-256 = 2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
WHOLE_BOOK_RELEASE_READY = FALSE
```

Принятый WAV не пересинтезировать без реального изменения затронутого text/pronunciation identity.

Canonical opening credit:

```text
Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.
```

## Платные действия

Никакой provider execution без explicit owner action.

```text
owner action
→ offline PREPARE + current pricing
→ immutable plan/request/cost cap
→ separate confirmation
→ authority/price revalidation
→ bounded provider execution
→ automatic QA
→ human review exact output
```

Automatic retry ambiguous paid action = 0.

## Локальный workspace

Default:

```text
~/Documents/New project/Audiobook-Studio
```

Path authority — `workspace_paths.py`.

Реальные книги, renders, cache, QA, billing, pronunciation dictionary, settings, masters и exports находятся вне Git и должны переживать обновления `.app`.

## Тесты

```bash
python3 -m unittest discover -s audiobook-studio/tests -v
```

Последняя Studio acceptance point — PR #52:

```text
full offline suite = 757/757 PASS
fresh native build = PASS
strict codesign = PASS
GitHub CI = PASS
provider/remote/paid = 0
```

Точную текущую launch-точку всегда брать из `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md` и фактического GitHub `main`.
