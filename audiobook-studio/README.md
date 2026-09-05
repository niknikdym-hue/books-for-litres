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

## Текущее состояние Studio

За 2026-09-03 — 2026-09-05 в `main` приняты:

- PR #45 — author-first native Studio, editable TTS working copy, manual/advisory editorial scan, provider-neutral ударения, chapter sound design, per-book delivery formats, production safeguards;
- PR #46 — Yandex synthesis timeout вынесен в config; production default 180 s, допустимо 1…600 s, silent retry не добавлен;
- PR #47 — исправлено состояние Yandex continuation/recovery UI;
- PR #48 — после готовой Yandex-главы Audio QA получает canonical authority, а не legacy/symlink execution path;
- PR #49 — семь production-шагов постоянно видимы; на шаге произношения снова виден текст книги; слово можно отправлять на проверку ударения двойным кликом; для длинного текста доступен Command-F; выбор шага сохраняется.

PR #50 (`Add simple permanent book deletion from the sidebar`) на момент этой фиксации открыт и не считается принятой функцией `main`.

## Пользовательский путь

Основной native flow:

1. Текст
2. Ударения
3. Звук глав
4. Диктор
5. Глава
6. Запись / прослушивание
7. Выпуск

Инженерные сведения, расходы и advanced Content Quality не должны доминировать в основном author flow.

## Импорт книги

MVP:

```text
TXT
UTF-8
до 20 МБ
вся книга одним файлом
```

Immutable source сохраняется без изменений. Для подготовки и озвучки создаётся отдельная TTS working copy.

## Словарь ударений

Новый канон: пользователь не исправляет одно и то же слово в каждой книге заново.

Private runtime store:

```text
<AUDIOBOOK_STUDIO_HOME>/settings/pronunciation/user-dictionary-v1.json
```

Contract:

```text
contracts/pronunciation-dictionary-v1.schema.json
```

Правило:

```text
исправить ударение в Studio
→ применить к текущей TTS working copy
→ сохранить book evidence
→ автоматически upsert в глобальный Словарь ударений
→ применять AUTO-правило в следующих книгах
```

Приоритет:

```text
exact occurrence > book override > global dictionary AUTO > default pronunciation
```

Если одно слово имеет несколько осмысленных ударений, глобальная запись переводится в `REVIEW_REQUIRED` и не применяется слепо ко всем контекстам.

Canonical representation — Unicode acute (`Ди́лон`); provider-specific синтаксис создаётся только adapter-слоем.

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

Выбранный narrator/profile сохраняется отдельно для каждой книги.

## Yandex production safety

Yandex production timeout configurable через canonical config:

```text
default = 180 s
allowed = 1…600 s
```

Timeout после отправленного запроса классифицируется безопасно; silent automatic retry не допускается.

Continuation PREPARE — одна ожидаемая async-операция. После успешной записи UI заново разрешает canonical Yandex authority перед Audio QA.

Private application-level Keychain → Yandex → Audio QA acceptance 2026-09-03: PASS. Подробные exact facts находятся в current-state authority.

## Звуковое оформление

Chapter cue — downstream-слой:

```text
clean TTS → Audio QA → approved narration → chapter cue → assembly → mastering
```

Смена звука не должна запускать TTS заново.

Поддерживаются per-book выбор, отключение звука, preview, пользовательский WAV с подтверждением прав и локальные лицензированные GarageBand assets при наличии на Mac.

## Форматы выпуска

Формат выбирается отдельно для каждой книги; default не навязывается:

- по главам;
- M4B;
- MP3;
- архив высокого качества.

Whole-book output остаётся заблокирован до готовности всех required chapters.

## Первая реальная книга

```text
book = hvatit-sebya-obestsenivat
accepted first chapter = chapter-ch001 / Введение
accepted Yandex WAV SHA-256 = 2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6
production progress = 1 / 16
WHOLE_BOOK_RELEASE_READY = FALSE
```

Первую принятую главу не пересинтезировать без реальной текстовой/произносительной причины.

Canonical opening credit:

```text
Елена Ди́лон. Хватит себя обесценивать. Читает Dilon Voices.
```

## Платные действия

Никакой provider execution без explicit owner action.

Общий cloud flow:

```text
owner action
→ offline PREPARE + current pricing
→ immutable plan/request/cost cap
→ отдельное подтверждение
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

Реальные книги, renders, cache, QA, billing, pronunciation dictionary, settings, masters и exports находятся вне Git и должны переживать обновления приложения.

## Тесты

```bash
python3 -m unittest discover -s audiobook-studio/tests -v
```

Последняя принятая UX-функциональная точка PR #49:

```text
full offline suite = 707/707 PASS
native build = PASS
Info.plist = PASS
Mach-O arm64 = PASS
strict codesign = PASS
render 1060×720 = PASS
render 900×620 = PASS
independent UX acceptance = PASS
provider/network/paid requests during implementation = 0
```

Точную текущую launch-точку всегда брать из `docs/AUDIOBOOK-STUDIO-CURRENT-STATE.md` и фактического GitHub `main`.
