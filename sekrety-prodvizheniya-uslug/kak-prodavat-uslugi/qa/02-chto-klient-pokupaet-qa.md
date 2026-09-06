# CHAPTER QA — 02 «Что именно клиент должен решиться купить»

**Статус:** USED-DRAFT / QA PASS-DRAFT  
**Дата:** 2026-09-07  
**Manuscript:** `../manuscript/02-chto-klient-dolzhen-reshitsya-kupit.md`

## 1. Chapter contract fit

### Unique question
PASS.

Глава отвечает только на вопрос: как определить сам объект покупки профессиональной услуги — ситуацию, контролируемый рабочий результат, границы, условия, роль клиента и неконтролируемый внешний outcome.

Она не решает:

- Ch1 — диагностику видов buyer uncertainty;
- Ch3 — подбор доказательств;
- Ch4 — детальную видимость процесса/этапов/checkpoints;
- Ch5 — диагностический разговор;
- Ch7 — сборку коммерческого предложения;
- Ch8 — price/scope/risk economics.

## 2. Central mechanism

PASS.

Фактический ход текста:

`широкое название/перечень работ → разные mental models сторон → неясный объект решения → ожидания расходятся → явное определение рабочего результата/границ/участия делает покупку представимой и сравнимой`.

Это отличается от Ch1: Ch1 диагностирует uncertainty, Ch2 изменяет service definition.

## 3. Research integrity

PASS WITH BOUNDARIES.

Использовано по функциям:

- Laroche et al. — mental intangibility / perceived risk;
- Mota & Santos — uncertainty in business-service specification;
- Dong et al. — customer participation outcomes depend on readiness/boundary conditions;
- Cermak et al. — participation in specification/delivery as a service variable;
- Rospotrebnadzor 2026 — узкий Russia B2C application по достоверной информации до договора.

Exact six-field `Service Decision Definition` прямо остаётся **author-created synthesis**. Текст не выдаёт его за validated universal scientific model.

Source traceability: `../source-notes/02-chto-klient-pokupaet-sources.md`.

## 4. Customer-participation boundary

PASS.

Ключевой риск contract был: превратить «роль клиента» в оправдание слабого результата.

Draft делает обратное:

- участие клиента задаётся конкретно;
- роль должна быть выполнимой;
- исполнитель обязан спроектировать процесс так, чтобы клиент мог выполнить свою часть;
- disclaimer «всё зависит от клиента» отвергается как слабый design.

## 5. World-class benchmark

PASS-DRAFT.

Глава не повторяет generic `sell results, not hours` и не копирует Beckwith/productization frameworks.

Собственная contribution на уровне chapter:

- различение controllable work result и external outcome;
- границы control/participation включены прямо в объект решения;
- buyer получает проверяемый six-field artifact.

Risk to watch in whole-book edit: практический блок не должен ощущаться workbook-приложением; сейчас он встроен в причинный аргумент и оправдан экономической функцией.

## 6. Practical value

PASS.

Artifact: **Service Decision Definition / Определение покупаемого решения**.

Next-business-day result: читатель может взять одну действующую услугу и переписать её по шести полям.

Observable test: незнакомый подходящий buyer может пересказать ситуацию, рабочий результат, границы, роль клиента и non-guaranteed outcome.

Artifact не дублирует Buyer Uncertainty Map Ch1.

## 7. Russia application

PASS-DRAFT / FRESHNESS REQUIRED.

Российский слой узкий и materially relevant:

- B2C — информация об исполнителе/услуге до договора и возможность осознанного выбора;
- B2B — коммерческая ясность scope/assumptions/roles без выдуманных универсальных юридических норм.

Нет платформенного справочника и нет поглощения legacy Yandex Direct territories.

Перед Literary Master перепроверить актуальные нормы/официальные разъяснения.

## 8. Intra-book overlap

### Ch1
PASS.

Ch1 может называть result/process/provider uncertainty, но не формирует Service Decision Definition.

### Ch3
PASS WITH BOUNDARY.

Финал Ch2 только ставит вопрос о proof. Evidence Inventory не создаётся и критерии доказательств не раскрываются.

### Ch4
PASS WITH BOUNDARY.

Ch2 фиксирует client role/границы как часть определения услуги. Подробные stages/roles/checkpoints/change rules остаются Ch4.

### Ch5
PASS.

Ch2 не учит discovery/questions.

## 9. Scene / analogy audit

Scene function matches reserved Ch2 function: стороны вкладывают разные outcomes/scope в одно широкое название услуги.

No analogy reserved or used as a structural crutch.

Marketing example remains generic service-definition example and does not spend Yandex Direct niche territory.

## 10. Content Quality Lexicon

Current canonical system core checked against `main` revision 1.

### Direct BLOCK phrase check
No occurrences found in manuscript for the current exact BLOCK phrases, including:

- `это про`;
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
- `давайте разберёмся`;
- `эта книга не о/про`.

### Negative-first regex review
- `Речь не о том, чтобы...` does not contain the required `а/но` contrast before sentence end and therefore does not match current BLOCK regex `CQ-RU-NEGATIVE-FIRST-002`.
- No decorative `не X, а Y` construction requiring WARN remediation found in current draft.

### WARN terms
No meaningful current matches for `не обязан`, `шум`, `иллюзия`, `магия`, `волшебство`, `звучать`, `опора` as lexicon terms.

### Execution honesty
Automated Content Quality runner was **not executed** in the current environment. This QA records direct text/core inspection only and must not be represented as automated PASS.

## 11. Manual anti-junk

PASS-DRAFT.

Checked:

- no meta-intro `сейчас разберём`;
- no universal `value/trust` slogans;
- no fake precision or invented statistics;
- no repeated inspirational conclusion;
- no manufactured real case;
- no AI-trend decoration;
- internal English production vocabulary mostly absent; `mental intangibility` appears once as a research term with immediate Russian explanation.

## 12. Known risks for later whole-book edit

1. Ch2 and Ch4 both touch client role; Ch4 must add process observability rather than restate participation boundaries.
2. Six-field artifact is deliberately practical; later rhythm audit must ensure the series does not become a sequence of identically formatted worksheets.
3. Marketing/agency examples are useful here but should not dominate later chapters.
4. Russian legal paragraph must be freshness-checked and kept proportionate.

## 13. Decision

**CHAPTER 2 = USED-DRAFT / QA PASS-DRAFT.**

Not `ACCEPTED`, not `LOCKED`, not Literary Master.

Next allowed action: update uniqueness/practical registries for actual draft use, then independently gate Chapter 3.
