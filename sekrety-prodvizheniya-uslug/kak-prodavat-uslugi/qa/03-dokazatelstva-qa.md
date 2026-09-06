# CHAPTER QA — 03 «Доказательства вместо уверений»

**Статус:** USED-DRAFT / QA PASS-DRAFT  
**Дата:** 2026-09-07  
**Manuscript:** `../manuscript/03-dokazatelstva-vmesto-uvereniy.md`

## 1. Chapter contract fit

**PASS.**

Уникальный вопрос главы сохранён: какие наблюдаемые данные помогают покупателю оценить релевантность/качество исполнителя до покупки и как соотнести доказательство с конкретным сомнением.

Глава не забирает:

- Ch2 — определение объекта покупки;
- Ch4 — видимость будущего процесса;
- Ch7 — сборку коммерческого предложения;
- future-book territory — personal brand/content/review acquisition systems.

## 2. Central mechanism

**PASS.**

Фактический механизм:

`качество трудно наблюдать заранее → покупатель отбирает поставщиков по доступным сигналам → сигналы различаются по функции → доказательство полезно только при релевантности, достаточной проверяемости и ясной границе утверждения`.

Это отдельная intellectual function относительно Ch2 и Ch4.

## 3. Research integrity

**STRONG PASS WITH CONTEXT LIMITS.**

Source traceability: `../source-notes/03-dokazatelstva-sources.md`.

Использованы по функции:

- Pemer & Skjølsvik, Journal of Business Research (2019) — ex-ante quality signals in professional services;
- Baek & King, Journal of Services Marketing (2011) — brand credibility, perceived quality/risk/value;
- B2B service reputation research — reputation as one input to perceived value.

Не утверждается:

- универсальная иерархия сигналов для всех профессий;
- что репутация гарантирует fit;
- что отзыв/кейс/диплом автоматически доказывает качество;
- что авторская Evidence Inventory является validated scientific scale.

## 4. Original contribution / world-class gate

**PASS-DRAFT.**

Глава не повторяет совет «добавьте кейсы и отзывы».

Собственная practical contribution:

`конкретное сомнение → объект доказательства → релевантность → проверяемость → что подтверждает → чего не подтверждает → пробел`.

Это превращает proof из showcase в decision tool.

## 5. Practical value

**PASS.**

Artifact: **Evidence Inventory + Gap Map / Инвентаризация и карта пробелов в доказательствах**.

Next-business-day test: читатель может взять действующую услугу и 3–5 реальных buyer risks, затем проверить существующие кейсы/отзывы/статусы по семи полям.

Observable output:

- каждому доказательству назначена конкретная функция;
- обозначена проверяемость;
- явно записано, чего proof не подтверждает;
- отсутствующее релевантное evidence видно как gap, а не маскируется количеством материалов.

## 6. Russia application

**PASS-DRAFT / FRESHNESS REQUIRED.**

Глава не строит выдуманную российскую «лестницу доверия».

Допустимые классы локального evidence зависят от профессии: официальный реестр/лицензия где применимо, проверяемый кейс, рекомендация, демонстрация, опубликованная работа, подтверждённый опыт.

Любой конкретный regulated claim или platform claim fresh-check перед Literary Master.

## 7. Intra-book overlap

### Ch2
**PASS.** Ch2 определяет, что покупается. Ch3 проверяет основания считать исполнителя способным выполнить это обязательство.

### Ch4
**PASS WITH PROTECTED BOUNDARY.** Ch3 использует прошлое/наблюдаемое evidence. Ch4 владеет будущими stages/roles/checkpoints/change rules.

### Ch7
**PASS.** Ch3 создаёт proof objects, но не проектирует их размещение/структуру в КП.

## 8. Scene / case integrity

**PASS.**

Основная scene function соответствует reservation: impressive proof vs relevant proof.

Все ситуации — model/composite, если отдельно не указан документальный source. Не создаются фиктивные бренды/точные якобы реальные показатели.

Маркетинговый пример `+40%` используется как модель проблемы причинности; не выдаётся за документированный кейс.

## 9. Content Quality Lexicon — exact current core

Проверка выполнялась после merge system-core fix PR #59; canonical `main` на момент QA: `c8bd53459d0bba72ce44454661eb2a249c7d2de4`.

Core revision: 2.

### BLOCK review
В актуальном manuscript отсутствуют ключевые system BLOCK-паттерны/фразы, включая:

- exact `это про` (boundary-safe rule);
- `эта книга не о/про`;
- negative-first `это/речь/дело не ... а/но`;
- `без ручного управления`;
- `без хаоса`;
- `без давления`;
- `без суеты` / `без лишней суеты`;
- `без перегруза`;
- `без лишней теории`;
- `информационный шум`;
- `иллюзии контроля`;
- `тихие смыслы`;
- `мир меняется`;
- `скорость изменений`;
- `погрузимся`;
- `давайте разберёмся`.

### WARN review
После редакторской правки в manuscript не осталось декоративной конструкции `не X, а Y`, требующей сохранения как WARN.

Нормальные отрицания, не образующие шаблонной антитезы, не удаляются механически.

### Automated runner honesty
Python/offline CI для system-core fix #59 прошёл полностью, включая regression suite. Сам Chapter 3 через локальный manuscript runner в текущем connected-GitHub окружении отдельно не запускался; этот QA не подменяет такой execution ручной проверкой.

## 10. Lexicon contribution

### Candidate 1 — matcher false positive
- observed during Chapter 3 QA: normal `это проблема...` matched old PHRASE `это про` by substring;
- type: **SYSTEM MATCHER/RULE DEFECT**, not new junk phrase;
- action: rule changed to boundary-safe SYSTEM REGEX `\bэто\s+про\b`;
- regression coverage added;
- PR #59 CI: SUCCESS;
- status: **ADDED / MERGED**.

### New junk phrase/term candidate from Chapter 3
**NONE.**

Reason: recurring content words `доказательство`, `сигнал`, `репутация`, `релевантность` are semantic terms required by the chapter. Blocking/warning them would create broad false positives. Junk is controlled at phrase/rhetoric level, not by banning the subject vocabulary.

## 11. Manual anti-junk / literary review

**PASS-DRAFT.**

Cleaned:

- production anglicisms (`screening`, `evidence`, `fit`, `Evidence Gap Map`);
- unnecessary negative-first wording;
- one unnecessary `не X, а Y` WARN;
- false lexicon pressure on normal `это проблема` fixed in the system core rather than by corrupting prose.

No:

- generic «стройте доверие» conclusion;
- catalogue of proof types as the chapter’s main value;
- personal-brand leakage;
- invented universal statistics;
- decorative AI section;
- structural analogy.

## 12. Known risks for whole-book edit

1. Word `доказательство` is necessarily frequent; later rhythm pass should reduce avoidable local repetition without replacing precise terminology with vague synonyms.
2. Ch4 must not restate relevance/verifiability; it must move to future-process observability.
3. Ch7 may reuse evidence objects only as inputs to proposal structure, not reteach the Evidence Inventory.
4. Russia section must remain proportionate and current.

## 13. Decision

**CHAPTER 3 = USED-DRAFT / QA PASS-DRAFT.**

Not `ACCEPTED`, not `LOCKED`, not Literary Master.

Next allowed production object: update uniqueness/practical registries for actual Chapter 3 use, then independently gate Chapter 4.
