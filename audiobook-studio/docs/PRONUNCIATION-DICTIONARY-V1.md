# Audiobook Studio — Словарь ударений V1

**Статус:** ACCEPTED canonical implementation authority  
**Дата authority:** 2026-09-05  
**Acceptance:** 2026-09-05 / PR #51  
**Contract:** `contracts/pronunciation-dictionary-v1.schema.json`

## Назначение

Пользователь не должен исправлять одно и то же ударение в каждой книге заново.

Любая осознанная правка ударения в Audiobook Studio сохраняется в постоянный пользовательский **Словарь ударений**. При следующей подготовке Studio автоматически использует сохранённое решение только тогда, когда оно безопасно однозначно.

## Каноническое хранилище

Private runtime data:

```text
<AUDIOBOOK_STUDIO_HOME>/settings/pronunciation/user-dictionary-v1.json
```

Файл не является Git-артефактом и должен переживать обновления Studio.

Требования:

- schema v1;
- atomic temp + fsync + replace;
- cross-process advisory lock;
- permissions 0600;
- strict UTF-8;
- corrupt/higher schema fail closed и не перезаписывается пустым файлом;
- provider/model/network/paid/billing operations = 0.

## Каноническое представление

Provider-neutral Unicode acute:

```text
Дилон → Ди́лон
замок → за́мок / замо́к
```

Provider-specific rendering — только adapter layer:

- Yandex SpeechKit: canonical acute → `+` перед ударной гласной;
- OpenAI TTS: canonical acute → pronunciation instruction;
- Qwen/другой backend: собственный adapter.

## Сохранение owner correction

Для обычного однозначного слова:

```text
исправить ударение
→ применить к текущему TTS context/book
→ сохранить book/occurrence evidence
→ upsert в global dictionary
→ AUTO использовать в следующих книгах
```

Отдельная галочка «запомнить» не требуется.

Immutable `source/original.txt` не изменяется.

## Приоритет

```text
exact OCCURRENCE
> BOOK
> GLOBAL AUTO
> automatic/default pronunciation
```

## Контекстные омографы

Known homograph нельзя сначала записывать как `AUTO`, ожидая второго варианта.

V1 canonical contextual case:

```text
замок
→ за́мок = строение, дворец или крепость
→ замо́к = запирающее устройство
```

Registry:

```text
pronunciation-contextual-v1.json
```

Для known contextual word:

```text
mode = REVIEW_REQUIRED
preferred = null
```

Правила:

- выбор `замо́к` в одном предложении — решение этого места, не глобальное `замок → замо́к`;
- global entry хранит оба curated variants;
- `REVIEW_REQUIRED` никогда не auto-applies;
- user chooses exact contextual occurrence;
- unresolved context блокирует только реально затронутый Yandex chapter/OpenAI segment;
- V1 не делает silent AI/context guess.

## Обязательная коррекция legacy `замок → замо́к / AUTO`

Реальная owner-test запись существовала до уточнения homograph policy.

Production migration PR #51 доказала:

```text
normalized_word = замок
revision 10 → 11
old mode = AUTO
new mode = REVIEW_REQUIRED
preferred = null
variants = [за́мок, замо́к]
```

При migration:

- существующий BOOK choice `замо́к` сохранён;
- immutable source сохранён;
- working text bytes сохранены;
- profile bytes сохранены;
- повторный запуск не меняет revision (`11 → 11`);
- duplicates не создаются;
- provider/network/model/paid = 0;
- billing mutation = false.

```text
KNOWN_HOMOGRAPH_ZAMOK_REPAIR = ACCEPTED
```

## Автоприменение

При import/preparation/reopen:

1. загрузить global dictionary;
2. взять только `mode=AUTO`;
3. никогда не auto-apply `REVIEW_REQUIRED`;
4. не трогать места с более точным BOOK/OCCURRENCE override;
5. применять canonical stress Unicode-safe и case-insensitive;
6. корректировать старый acute, если owner изменил решение;
7. помечать stale только затронутые preparation/synthesis identities;
8. не пересинтезировать unrelated good WAV.

## Migration existing BOOK rules

- один непротиворечивый вариант и слово не contextual → `AUTO`, source `MIGRATED_BOOK_RULE`;
- разные варианты → `REVIEW_REQUIRED`;
- existing global AUTO known homograph → downgrade to `REVIEW_REQUIRED`;
- migration idempotent;
- immutable source untouched.

`Дилон → Ди́лон` сохраняется как safe global AUTO при однозначном accepted evidence.

## Native UI

Раздел:

```text
Произношение → Словарь ударений
```

Пользователь может:

- искать слово;
- видеть `слово → ударение`;
- видеть human status `Зависит от контекста`;
- отключать/удалять user rules;
- выбирать вариант омографа в карточке конкретного предложения.

Для `замок` UI показывает:

```text
замок → за́мок / замо́к · зависит от контекста
```

## Safety / identity

Dictionary mutation сама не выполняет TTS.

Если correction реально меняет speech identity:

```text
working/pronunciation identity changes
→ affected prepared/segment identity becomes stale
→ fresh PREPARE only for affected speech
```

## Acceptance evidence — PR #51

```text
PR = #51 Protect contextual homographs in pronunciation dictionary
feature HEAD = 2944a56e4844eecb10c445ac6e28de38d682f0fa
merge = c3b0b301e6f04714f318a0a6d4ab21252011a947
GitHub Audiobook Studio Offline run #332 = SUCCESS
full offline suite = 750/750 PASS
native 1060×720 = PASS
native 900×620 = PASS
independent UX review = PASS
Mach-O / Info.plist / strict codesign = PASS
provider requests = 0
network TTS = 0
model calls = 0
paid execution = 0
billing mutation = false
```

## Definition of Done — satisfied

1. owner correction persists in private global dictionary;
2. restart preserves dictionary;
3. safe AUTO is reused in new books;
4. BOOK/OCCURRENCE overrides win;
5. known/conflicting homograph never silently auto-applies;
6. real `замок → замо́к` legacy entry repaired;
7. Yandex/OpenAI render from one canonical entry;
8. immutable source remains unchanged;
9. updater preserves dictionary;
10. migration/persistence/conflict/priority/provider regressions pass.

```text
PRONUNCIATION_DICTIONARY_V1 = ACCEPTED
```
