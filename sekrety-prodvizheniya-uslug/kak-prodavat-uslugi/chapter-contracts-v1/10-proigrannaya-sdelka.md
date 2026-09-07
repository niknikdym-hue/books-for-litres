# CHAPTER CONTRACT V1 — 10

**Book:** «Как продавать услуги»  
**Working title:** «Почему вы проиграли сделку — и что менять на самом деле»  
**Status:** RESERVED / WRITING-READY  
**Architecture:** APPROVED 2026-09-07  
**WRITING_ALLOWED:** YES

## BUSINESS PROBLEM

После исхода сделки продавец почти неизбежно создаёт объяснение: `проиграли из-за цены`, `выиграли благодаря кейсу`, `клиент был не наш`, `конкурент демпинговал`. Итог виден, но значительная часть решения покупателя происходила без продавца. Удобная причина попадает в память/CRM и начинает управлять следующими изменениями системы.

Экономический ущерб:

- seller inference фиксируется как fact;
- один эмоционально важный проигрыш провоцирует крупное изменение системы;
- повторяющийся реальный дефект не замечается, потому что loss codes поверхностны;
- сильный элемент продажи удаляется после одного неудачного исхода;
- price becomes default blame category without buyer evidence;
- команда учится на историях продавцов, а не на сопоставлении исходов и данных.

## UNIQUE QUESTION

**Как после исхода сделки отделить факт от объяснения продавца, добавить buyer-side evidence, увидеть повторяющийся сигнал без псевдостатистики и выбрать одно проверяемое изменение sales system?**

Ch9 = action on one live deal before outcome.  
Ch10 = learning after outcome across several deals.

## MECHANISM / CAUSAL CHAIN

`partial visibility of buyer decision + emotional impact of win/loss → convenient attribution → wrong system change / no change → repeated failure or accidental damage to strong practice`.

Counter-mechanism:

`fact of outcome → seller hypothesis → buyer feedback/evidence where available → cross-deal repetition strength → one testable system change → future observable check`.

No claim of causal/statistical certainty from a small informal sample.

## DECISION

For each emerging issue choose:

1. **NO ACTION / ONE CASE** — not enough evidence to change system;
2. **COLLECT MORE EVIDENCE** — repeated suspicion but buyer voice/data insufficient;
3. **TEST ONE CHANGE** — repeated/supportable pattern justifies a bounded change;
4. **RESTORE / REVERSE CHANGE** — later evidence contradicts prior assumption;
5. **SYSTEM UPDATE** — after a test, incorporate the better rule/tool into the relevant Ch1–9 component.

## ACTION / ARTIFACT

### Lost-Deal Learning Loop / Цикл обучения на сделках

Status: **AUTHOR-CREATED SYNTHESIS**, not a validated statistical method.

For each recent outcome record:

1. **ИСХОД / ФАКТЫ**  
   What objectively happened: win/loss/no-decision, date, offer version, known events, explicit buyer statement.

2. **НАША ВЕРСИЯ ПРИЧИНЫ**  
   Seller explanation, clearly marked as hypothesis.

3. **ЧТО СКАЗАЛ / ПОКАЗАЛ ПОКУПАТЕЛЬ**  
   Direct feedback/evidence where available. Buyer account is a perspective/evidence source, not omniscient truth.

4. **КАКОЙ ЭЛЕМЕНТ СИСТЕМЫ МОЖЕТ БЫТЬ СВЯЗАН**  
   One or more Ch1–9 components only after evidence. Do not blame a chapter/tool automatically.

5. **СИЛА СИГНАЛА**  
   - `ОДИН СЛУЧАЙ / ANECDOTAL`;
   - `ПОВТОРЯЮЩИЙСЯ СИГНАЛ`;
   - `ПОДДЕРЖАННЫЙ ПАТТЕРН` — several independent cases/evidence sources, still not automatically statistically representative.

6. **ОДНО ИЗМЕНЕНИЕ ДЛЯ ПРОВЕРКИ**  
   Make one bounded system change rather than changing everything.

7. **КАК УВИДИМ РЕЗУЛЬТАТ**  
   Define an observable future check in comparable opportunities.

Practical starting set for solo/small business: review 5–10 recent outcomes if available, explicitly **not** as a statistically valid sample by default.

## OBSERVABLE CHECK

Reader can take recent outcomes and:

- separate outcome fact from seller explanation;
- mark whether direct buyer evidence exists;
- refuse to call one case a pattern;
- identify one repeated decision-relevant issue;
- choose one bounded change;
- define what future evidence would support/refute that change.

Fail conditions:

- every loss gets exactly one mandatory reason code treated as truth;
- 5–10 deals converted into percentages with false significance;
- `buyer said price` treated as objective sole cause without context;
- buyer feedback request becomes another sales attempt;
- only losses are analyzed;
- one painful loss triggers multiple simultaneous system changes;
- AI-generated call summary replaces evidence;
- chapter becomes CRM/BI implementation manual.

## EVIDENCE FUNCTION

### Friend, Curasi, Boles & Bellenger — Industrial Marketing Management, 2014
`Why are you really losing sales opportunities? A buyers' perspective on the determinants of key account sales failures`  
https://doi.org/10.1016/j.indmarman.2014.06.002

Use:
- 35 semi-structured buyer-side post-mortem cases after failed key-account proposals;
- authors explicitly identify attribution-bias risk when sales failure is studied only through salesperson/manager/selling-firm data;
- buyer-side themes were multi-dimensional rather than one simple reason.

Boundary:
- qualitative key-account industrial B2B context;
- do not import the three reported themes as universal taxonomy;
- buyer account adds perspective/evidence, not perfect objective truth.

### European Journal of Marketing, 2020/2021
`Impacts of salespeople’s biased and unbiased performance attributions on job satisfaction`  
https://doi.org/10.1108/EJM-11-2018-0816

Use:
- experimental/data evidence from 209 salespeople showing perceptual attribution errors in performance appraisal;
- supports explicit separation of seller explanation from fact.

Boundary:
- performance-appraisal context, not direct deal-coding validation.

### Mallin & Mayo — Journal of Personal Selling & Sales Management, 2006
`Why Did I Lose? A Conservation of Resources View of Salesperson Failure Attributions`  
https://doi.org/10.2753/PSS0885-3134260402

Use:
- partial support that high-impact losses can lead salespeople toward external attributions;
- useful guardrail against comfortable external stories after painful loss.

Boundary:
- not proof that every salesperson externalizes every failure.

### Gartner 2024 win/loss case study
https://www.gartner.com/en/documents/5597559

Use:
- current professional-practice example of structured buyer interviews/surveys to understand buying decision drivers.

Boundary:
- proprietary case/practice example; no universal effect size.

Detailed traceability: `../source-notes/10-proigrannaya-sdelka-sources.md`.

## WORLD-CLASS BENCHMARK

Most sales books optimize behavior before close. This chapter must make the book **adaptive after outcome**.

Contribution:

**evidence ladder + bounded learning loop for a small professional-service practice**:

`outcome fact → seller hypothesis → buyer evidence → repetition strength → one test → system update`.

This is stronger than:
- CRM loss-code list;
- motivational postmortem;
- anecdotal `lessons learned`;
- giant enterprise BI/win-loss program copied into solo practice.

## BUYER FEEDBACK BOUNDARY

A lost buyer does not owe an interview.

Where relationship/context permit, lightweight neutral questions may gather evidence, e.g.:
- `Если вам удобно, какой один фактор сильнее всего повлиял на выбор?`
- `Что в нашем предложении было менее подходящим, чем в выбранном варианте?`
- for no-decision: `Что изменилось между началом выбора и решением отложить проект?`

Do not:
- dispute feedback;
- convert feedback request into sales retry;
- ask leading `это из-за цены?`;
- pressure after clear refusal.

## WINS / LOSSES / NO-DECISION

Analyze all three where possible.

Reason:
- winning outcome can create false attribution too;
- comparing different outcomes can prevent overreacting to one loss;
- no-decision is a real outcome, not missing data.

No causal/statistical inference is claimed from informal small samples.

## SYSTEM ASSEMBLY

Final chapter may show the operating loop:

Ch1 diagnose purchase uncertainty  
→ Ch2 define the service decision object  
→ Ch3 make relevant proof visible  
→ Ch4 make future delivery observable  
→ Ch5 establish information sufficiency  
→ Ch6 check compatibility  
→ Ch7 assemble decision-complete proposal  
→ Ch8 design economics/risk  
→ Ch9 diagnose live stall  
→ Ch10 learn from outcome.

**This is assembly, not a new T11 framework.**

The practical rule: update only the component supported by evidence; do not rerun/rebuild all nine prior tools after each outcome.

## RUSSIA APPLICATION

Method must work without enterprise systems:

### Self-employed / NPD
Simple spreadsheet/notes are sufficient. Do not require CRM.

### ИП / small agency
CRM can supply factual event history if available, but loss reason field remains seller-entered hypothesis unless buyer evidence supports it.

### B2B team
Buyer/procurement debrief can be useful where available and appropriate.

Do not introduce personal-data recording/call-analysis mechanics as core. Any concrete storage/recording/privacy recommendation requires fresh Russian legal check.

## FRESHNESS

Core attribution/learning logic: evergreen/context-dependent.  
Gartner/current win-loss practice: contextual/current; recheck only if quoted specifically.  
No platform dependency.

## SCENE / CASE

Model/research-backed contrast:

A small agency marks a lost proposal as `ДОРОГО` because buyer mentioned price near the end. Seller lowers prices in later offers. A later neutral buyer conversation reveals that selected competitor cost roughly the same, but buyer saw competitor as more adapted to internal implementation constraints. One deal does not prove a system problem; after similar buyer-side evidence appears in several outcomes, agency tests one bounded change in proposal/process visibility rather than a blanket price cut.

Function: seller attribution → buyer evidence → repeated signal → one system test.

Do not reuse Ch9 live `дорого` diagnosis; outcome is already known.

## ANALOGY

**NONE RESERVED.**

Avoid mirror/autopsy/black-box metaphors as structural devices. The evidence ladder is direct enough.

## NOT THIS CHAPTER

- no Ch9 live objection diagnosis;
- no CRM implementation;
- no BI/statistical dashboard;
- no retention/LTV;
- no acquisition/channel analytics;
- no buyer interview research manual;
- no automatic call-analysis/AI system;
- no new eleventh framework;
- no universal loss-reason taxonomy.

## COMPOSITION

Comfortable seller explanation after loss → buyer-side sales-failure research exposes attribution problem → fact vs inference → buyer feedback as evidence but not truth → one-case vs repeated signal → Lost-Deal Learning Loop → wins/no-decision complication → one bounded test → assemble Ch1–9 into adaptive operating loop → final reader action.

Avoid another chapter that starts from a live hesitation. Outcome must already be known.

## UNIQUENESS

### vs Ch9
Ch9 = live post-offer cause verification before outcome.  
Ch10 = post-outcome evidence/pattern learning across cases.

### vs Ch5
Both distinguish fact/assumption, but functions differ:
- Ch5 uses epistemic discipline to design one relevant offer;
- Ch10 uses outcome/buyer evidence across deals to decide system change.

Do not copy Ch5 seven-field diagnostic map.

### vs whole book
Only Ch10 is allowed to assemble T01–T09 into an operating sequence, and assembly itself does not become T11.

## ANTI-JUNK / CONTENT QUALITY

Known risks:
- `проигрыши — ваши лучшие учителя` cliché;
- fake `data-driven` language from tiny sample;
- percentage dashboards from 5 deals;
- `buyer truth` absolutism;
- shame/blame postmortem;
- `не X, а Y` rhetorical repetition;
- production anglicisms `win/loss / pattern / loop` in literary prose;
- repeating Ch9 hypothesis tool;
- ending with motivational summary instead of operating rule.

## PRE-WRITING DECISION

- World-class: **PASS**;
- Original contribution: **PASS**;
- Practical value: **PASS**;
- Research/evidence: **PASS WITH QUALITATIVE/ATTRIBUTION BOUNDARIES**;
- Russia application: **PASS / LOW-TECH BY DESIGN**;
- Intra-book uniqueness: **PASS**;
- Ch9 boundary: **PASS**;
- Architecture fit: **PASS**.

**WRITING_ALLOWED=YES**.
