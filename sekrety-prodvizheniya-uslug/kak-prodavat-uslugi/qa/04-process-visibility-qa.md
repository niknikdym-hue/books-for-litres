# CHAPTER QA — 04 «Показать работу до начала работы»

**Статус:** USED-DRAFT / QA PASS-DRAFT  
**Дата:** 2026-09-07  
**Manuscript:** `../manuscript/04-pokazat-rabotu-do-nachala-raboty.md`

## 1. Chapter contract fit

**PASS.**

Глава сохраняет собственный вопрос: что нужно показать о **будущем процессе оказания услуги до покупки**, чтобы покупатель мог представить совместную работу, роли, промежуточные результаты, точки решения и правила изменения плана.

Она не забирает:

- Ch2 — определение самого объекта покупки;
- Ch3 — прошлые доказательства качества/релевантности исполнителя;
- Ch5 — диагностику задачи до предложения;
- Ch7 — сборку коммерческого предложения;
- PM/onboarding/customer-success territory.

## 2. Central mechanism

**PASS.**

Фактический mechanism:

`плохо наблюдаемый будущий процесс + неясные роли/правила изменений → process/participation uncertainty → perceived risk / expectation mismatch`.

Практическое решение — selective observability: покупателю показываются только те части будущей работы, которые materially помогают принять решение и выполнить свою роль.

## 3. Research integrity

**PASS WITH CONTEXT LIMITS.**

Source traceability: `../source-notes/04-process-visibility-sources.md`.

Использованы по функции:

- Liu, Xu & Ling (2017) — backstage/service-process cues and pre-purchase perceived risk in studied experimental conditions;
- KIBS customer-participation research — participation in specification, solution choice and delivery complications; role/resource limitations;
- Dong & Sivakumar (2017) — participation has different domains/boundaries;
- Chen, Raab & Tanford (2015) — role clarity as a participation antecedent in hospitality context.

Не утверждается:

- универсальный conversion uplift от «прозрачности»;
- что максимальная прозрачность всегда лучше;
- что visual map имеет универсально измеримый эффект;
- что авторская Process Visibility Map является validated scientific scale.

## 4. Original contribution / world-class gate

**PASS-DRAFT.**

Глава не ограничивается советом «покажите процесс».

Contribution:

`будущий процесс → значимые этапы → входы/выходы → роли → checkpoints/decisions → change rules → остаточная uncertainty`.

Это превращает process visibility в transaction-design tool, а не content-marketing приём.

## 5. Practical value

**PASS.**

Artifact: **Process Visibility Map / Карта видимого процесса**.

Next-business-day use: читатель может взять одну действующую услугу и сократить внутренний процесс до 4–7 materially relevant этапов, где видны:

- input;
- observable output;
- provider/client role;
- decision/checkpoint;
- rule for change.

Observable check: незнакомый buyer способен объяснить, что произойдёт после оплаты и когда ему придётся принимать решение/участвовать.

## 6. Russia application

**PASS-DRAFT / NO UNSUPPORTED RUSSIA CLAIMS.**

Manuscript не вводит универсальную «российскую процедуру». Применение строится через типичные small-agency / IT / consulting / professional-service ситуации.

Specific legal/document/payment claims в текущем тексте не являются опорой главы. Если они появятся позже, required fresh official-source check before Literary Master.

## 7. Intra-book overlap

### Ch2
**PASS WITH BOUNDARY.** Ch2 говорит, что входит в услугу и какова роль клиента на definition level. Ch4 владеет последовательностью этапов, входами/выходами, checkpoints и change logic.

### Ch3
**PASS.** Ch3 = evidence о прошлом/наблюдаемой способности исполнителя. Ch4 = observability будущей совместной работы.

### Ch5
**PASS.** Ch4 описывает уже выбранную конструкцию delivery. Ch5 будет определять, что нужно узнать о конкретной задаче до предложения.

## 8. Scene / case integrity

**PASS.**

Основная scene function: компетентный поставщик и понятная услуга всё равно выглядят рискованно, если после оплаты начинается black box.

Все ситуации — model/composite; fictional documentary success metrics не создаются.

## 9. Content Quality Lexicon — current core v2

Canonical system core: revision 2.

### Manual BLOCK review
Direct review не обнаружил ключевых system BLOCK-фраз/паттернов, включая:

- exact `это про`;
- `эта книга не о/про`;
- `без хаоса` / `без давления` / `без суеты`;
- `информационный шум`;
- `иллюзии контроля`;
- `тихие смыслы`;
- `мир меняется`;
- `скорость изменений`;
- `погрузимся`;
- `давайте разберёмся`.

### WARN / manual cleanup candidates
1. `Исследования ... дают для этого интересную опору.` — слово `опора` попадает в system WARN-family; смысл точный, но до master лучше заменить на `основание`.
2. `Покупатель видит не результат, которого ещё нет, а способ получить более точное знание.` — содержательная, но стилистически типовая `не X, а Y`; до master предпочтительно переписать напрямую.
3. `backstage cues` — исследовательский англоязычный термин в literary prose. В source notes он нужен; в master лучше оставить русское объяснение без production/research jargon, если английский термин не несёт отдельной пользы читателю.

### Automated runner honesty
Отдельный manuscript runner на Chapter 4 в connected-GitHub environment не запускался. QA не заявляет automated PASS.

## 10. Manual anti-junk / literary review

**PASS-DRAFT WITH THREE CLEANUP ITEMS.**

Сильные стороны:

- нет generic `прозрачность = доверие`;
- нет PM-manual leakage;
- нет «покажите закулисье» как декоративной метафоры;
- промежуточные outputs связаны с decisions, а не с количеством активности;
- uncertainty не маскируется ложной календарной точностью;
- практический tool встроен в argument, а не приклеен как workbook appendix.

## 11. Known whole-book risks

1. Ch7 может использовать Process Visibility Map только как input для offer structure, но не переучивать ей.
2. Ch5 не должен повторять Ch4 роли/inputs — его предмет information gaps до offer.
3. В whole-book edit проверить, не образовался ли повтор слова `процесс` плотными сериями; precise term не заменять расплывчатыми synonyms механически.
4. Cleanup candidates из §9 закрыть до Literary Master.

## 12. Decision

**CHAPTER 4 = USED-DRAFT / QA PASS-DRAFT.**

Not `ACCEPTED`, not `LOCKED`, not Literary Master.

Next allowed production object: update registries for actual Chapter 4 use, then close Chapter 5 research/admission gate before Writing.
