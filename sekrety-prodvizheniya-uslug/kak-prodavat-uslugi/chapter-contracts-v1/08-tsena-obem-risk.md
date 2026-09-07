# CHAPTER CONTRACT V1 — 08

**Book:** «Как продавать услуги»  
**Working title:** «Цена, объём и риск»  
**Status:** RESERVED / WRITING-READY  
**Architecture:** APPROVED 2026-09-07  
**WRITING_ALLOWED:** YES

## BUSINESS PROBLEM

Цена услуги часто обсуждается как отдельное число. При напряжении продавец либо снижает его без изменения обязательства, либо защищает цену абстрактной «ценностью». В сложной услуге сумма связана с объёмом, неопределённостью, тем, что именно обещает исполнитель, вкладом клиента и тем, кто несёт последствия, если работа окажется сложнее/дольше/неопределённее ожидаемого.

Экономический ущерб:

- скидка сохраняет прежний объём и переносит весь удар в маржу/качество;
- fixed fee используется при плохо определённом объёме без механизма изменения;
- hourly/T&M перекладывает неопределённость на клиента без достаточной наблюдаемости;
- performance component привязывается к внешнему результату, который исполнитель не контролирует;
- клиент просит цену ниже, а продавец не понимает, уменьшается ли реальная финансовая экспозиция покупателя;
- стороны спорят о числе вместо конструкции сделки.

## UNIQUE QUESTION

**Как связать цену услуги с объёмом, неопределённостью, обязательством и распределением риска — и что именно менять, когда экономические условия сделки не устраивают одну из сторон?**

Ch8 работает только после того, как:
- Ch2 определила service/work result;
- Ch6 признала конфигурацию в принципе совместимой;
- Ch7 сделала инвестицию/условия видимыми.

## MECHANISM / CAUSAL CHAIN

`service heterogeneity / uncertain effort / uncertain inputs or outcome + financial exposure → buyer/provider seek risk reduction → discount / rigid fixed price / open-ended time billing / delay / guarantee demand can shift rather than remove risk`.

Counter-mechanism:

`make uncertainty explicit → identify current risk bearer → connect pricing/payment/commitment model to uncertainty → redesign scope, stages, review points, payment timing or bounded commitment`.

Price is treated as one component of transaction architecture, not proof of seller worth.

## DECISION

When there is **confirmed economic tension**, choose among:

1. **KEEP** — current price/scope/risk allocation is coherent; no change needed;
2. **CHANGE SCOPE / WORK RESULT** — lower/raise price because actual obligation changes;
3. **STAGE COMMITMENT** — separate diagnostic/pilot/first stage where uncertainty is too high for one large commitment;
4. **CHANGE RISK ALLOCATION / PRICING BASIS** — use a different combination of fixed/time/staged/hybrid/contingent terms where justified;
5. **CHANGE PAYMENT TIMING / MILESTONES** — financial exposure/timing changes without pretending service value changed;
6. **ADD A BOUNDED RISK-REDUCTION TERM** — guarantee/review/exit/renegotiation mechanism only where controllable and appropriate;
7. **DECLINE CURRENT ECONOMICS** — buyer requires a price/guarantee/configuration that makes professional delivery economically or ethically unworkable.

Discounting remains possible as a conscious commercial choice, but it must not masquerade as risk reduction if nothing about scope/commitment/economics changes.

## ACTION / ARTIFACT

### Price–Scope–Risk Map / Карта «Цена — объём — риск»

Status: **AUTHOR-CREATED SYNTHESIS**, not a validated pricing model.

For one real offer, map seven fields:

1. **ОБЯЗАТЕЛЬСТВО / РАБОЧИЙ РЕЗУЛЬТАТ**  
   What exactly is paid for? Use Ch2 output, not generic «value» language.

2. **ОБЪЁМ / ЕДИНИЦА РАБОТЫ**  
   What is fixed/limited/measurable and what can expand?

3. **КЛЮЧЕВАЯ НЕОПРЕДЕЛЁННОСТЬ**  
   What remains uncertain in effort, inputs, scope, process or output at agreement time?

4. **КТО СЕЙЧАС НЕСЁТ РИСК**  
   Provider / client / shared? What happens economically if uncertainty resolves badly?

5. **КАК ЦЕНА / МОДЕЛЬ ОПЛАТЫ СВЯЗАНА С ЭТИМ РИСКОМ**  
   Fixed fee / time-based / staged / hybrid / contingent component / other — descriptive, not ranked.

6. **КАКОЙ ЭКОНОМИЧЕСКИЙ РЫЧАГ МОЖНО ИЗМЕНИТЬ**  
   Scope/work result; staged commitment; required client input; review/renegotiation point; payment milestone/timing; pricing basis; bounded guarantee/risk-sharing where controllable.

7. **ЧТО НЕЛЬЗЯ ЛОМАТЬ ИЗМЕНЕНИЕМ ЦЕНЫ**  
   Professional quality floor, legal/ethical boundary, explicit work-result integrity, already-agreed critical delivery conditions.

## OBSERVABLE CHECK

For every proposed economic change reader can answer:

- what exactly changes besides the number;
- which uncertainty/risk is reduced, transferred or retained;
- who bears remaining downside;
- whether provider can still deliver the stated quality/work result;
- whether buyer can understand maximum/likely financial exposure well enough for this service type;
- what rule applies if scope/inputs change materially.

Fail conditions:

- `скидка 15%` with identical obligation and no conscious margin rationale;
- `дороже = качественнее` as price defense;
- fixed fee hides undefined/unbounded scope;
- T&M/open-ended billing hides client exposure;
- performance payment depends primarily on factors outside provider control;
- guarantee promises uncontrollable outcome;
- three packages/anchoring replaces analysis of actual economics;
- seller explains price only through self-worth or «ценность».

## EVIDENCE FUNCTION

### Alavi, Habel, Schwenke & Schmitz — JAMS, 2020
`Price negotiating for services: elucidating the ambivalent effects on customers’ negotiation aspirations`  
https://doi.org/10.1007/s11747-019-00676-4

Use:
- five empirical studies / almost 1,300 customers;
- service heterogeneity can raise negotiation aspirations through risk/legitimacy; inseparability/integration can produce opposite pressure;
- supports service-price negotiation as uncertainty/interaction-sensitive.

Boundary:
- no manipulation tactics imported;
- no universal service-negotiation rule.

### Mitchell, Moutinho & Lewis — Service Industries Journal
`Risk Reduction in Purchasing Organisational Professional Services`  
https://doi.org/10.1080/02642060308565621

Use:
- financial risk important in studied organisational professional-service purchasing;
- risk-reduction framework includes clarifying/simplifying/risk sharing.

Boundary:
- context-specific organisational/not-for-profit study; no universal tool ranking.

### Homburg & Stebel — Management Accounting Research, 2009
`Determinants of contract terms for professional services`  
https://doi.org/10.1016/j.mar.2008.10.001

Use:
- professional services involve transactional uncertainty/double moral hazard;
- service characteristics affect contract type;
- performance-based contracts may not be optimal even when output is measurable/verifiable.

Boundary:
- German management-consulting context; no universal fee model.

### Jørgensen, Mohagheghi & Grimstad — IJPM, 2017
`Direct and indirect connections between type of contract and software project outcome`  
https://doi.org/10.1016/j.ijproman.2017.09.003

Use:
- in two studied software-project data sets fixed price associated with higher failure risk than T&M and with different behaviors/client involvement;
- demonstrates contract form can shift incentives/risk and is not neutral.

Boundary:
- software context; do not generalize `T&M better`.

### Gopal — Decision Sciences, 2010
`The Role of Contracts on Quality and Returns to Quality in Offshore Software Development Outsourcing`  
https://doi.org/10.1111/j.1540-5915.2010.00278.x

Use:
- counterevidence/context: different contract incentive/quality relationships reported in another offshore-software sample;
- strengthens non-universal conclusion.

### Huang et al. — Information Systems Research, 2021
`The Power of Renegotiation and Monitoring in Software Outsourcing`  
https://doi.org/10.1287/isre.2021.1026

Use:
- monitoring/renegotiation as responses to information asymmetry/uncertainty;
- supports review/change mechanisms when uncertainty cannot be eliminated at agreement time.

Boundary:
- software outsourcing analytical context; no universal clause recommendation.

### Price-quality guardrails
FTC working paper, 2002: `Price and Quality Relationships in Local Service Industries`  
https://www.ftc.gov/reports/price-quality-relationships-local-service-industries

Use:
- reported positive price-quality correlations were far from universal across 19 studied local service industries;
- guards against `high price = high quality`.

Turley & Kelley, 1995  
https://doi.org/10.1300/J127v01n01_06

Use:
- price-quality inference in services varied with awareness/context in experiment;
- supplementary context-dependence evidence.

### Service guarantee boundary
IJHM 2012, `Service guarantees in the hotel industry...`  
https://doi.org/10.1016/j.ijhm.2011.09.012

Use:
- guarantee design can affect perceived risk/quality in studied hotel context.

Boundary:
- no blanket professional-service guarantee; only controllable/bounded commitments.

Detailed traceability: `../source-notes/08-tsena-obem-risk-sources.md`.

## WORLD-CLASS BENCHMARK

Chapter must beat generic advice:
- `charge for value`;
- `never discount`;
- `raise prices to signal quality`;
- `fixed fee is better`;
- `hourly is obsolete`;
- `performance pricing aligns incentives`;
- `offer three packages`.

Contribution:

**economic terms as explicit allocation of uncertainty, obligation and financial risk in hard-to-evaluate services**.

Reader leaves with transaction-design reasoning, not confidence rhetoric.

## AI-ERA RELEVANCE

### Stanford Digital Economy Lab working paper, 23 Aug 2026
Brynjolfsson & Petropoulos, `Pricing Consulting Services in the Age of Agentic AI`  
https://digitaleconomy.stanford.edu/publication/pricing-consulting-services-in-the-age-of-agentic-ai-a-strategy-map-for-executives/

Use:
- current 2026 context: AI changes observability/cost of professional-service inputs and can change fit of time/project/hybrid/outcome pricing;
- reinforces need to ask what client actually pays for when effort becomes cheaper/less observable.

Boundary:
- working paper / consulting context;
- do not copy its strategy map;
- no claim that hourly billing disappears universally.

Current international journalism on law/consulting fee pressure may illustrate the shift at final writing/freshness pass, but does not constitute core proof.

## RUSSIA APPLICATION

No universal Russia fee model.

### B2C current information layer
Rospotrebnadzor, 6 Mar 2026:  
https://zpp.rospotrebnadzor.ru/news/federal/572346

Use:
- current reminder that price information must be communicated to consumers before contract conclusion in applicable consumer-service relationships.

Rospotrebnadzor, 13 May 2026:  
https://zpp.rospotrebnadzor.ru/news/federal/574017

Use:
- payment-form/order rules are legally time-sensitive; any detailed recommendation requires fresh check.

Do not universalize household/consumer-service rules to B2B professional services.

### Self-employed / NPD transaction hygiene
FNS 2026 reminders: self-employed/NPD sellers must form and transfer receipts on income received from customers/clients.  
Examples:
- https://www.nalog.gov.ru/rn53/news/activities_fts/16643640/
- https://www.nalog.gov.ru/rn38/ifns/ifns3852/events/16631227/

Use only as narrow post-payment/document hygiene, not pricing logic.

### B2B
Contract/payment structure depends on parties/industry/project; no invented Russian norm for `50/50`, full prepayment or postpayment.

## FRESHNESS

Core economics/research: evergreen/context-dependent.  
AI pricing context: HIGH freshness; recheck before master.  
Russian B2C payment/legal/NPD claims: HIGH freshness; official-source recheck before master.

## SCENE / CASE

Model/composite:

Agency/consultant issues a 300,000-ruble proposal for a project with uncertain first-stage data. Client says: `дорого, сделайте 240`.

Three seller options are compared:
1. pure discount with same promise/scope;
2. narrower defined work result/scope;
3. staged first commitment that resolves uncertainty before larger second stage.

Function: **confirmed economic tension → transaction redesign**, not generic objection handling.

No claim that staged model is always best.

## ANALOGY

**NONE RESERVED.**

Avoid balance-scales / blanket / poker / skin-in-the-game metaphors. Risk allocation is explained directly.

## NOT THIS CHAPTER

- not Ch6 compatibility/no-go recheck;
- not Ch7 proposal audit;
- not Ch9 ambiguous objection diagnosis;
- not company-wide pricing strategy;
- not accounting/margin model;
- not tax chapter;
- not universal guarantee playbook;
- not value-pricing ideology;
- not negotiation tactics chapter.

## COMPOSITION

Confirmed price conflict → show same-number discount problem → service-price negotiation evidence → price-quality cue counterexample → economic risk allocation → contrasting contract-model evidence → Price–Scope–Risk Map → alternative levers (scope/staging/model/payment/review/bounded risk reduction) → Russia/current AI boundary → transition to Ch9: first verify whether a surface objection is actually economic before using Ch8.

## UNIQUENESS

### vs Ch6
Ch6 asks whether configuration is workable. Ch8 assumes workable deal and redesigns economics/risk allocation.

### vs Ch7
Ch7 requires investment/terms visibility. Ch8 explains/reconfigures them.

### vs Ch9
Ch8 starts only after price/economic tension is **confirmed**. Ch9 owns causal diagnosis when `дорого / подумаю / не сейчас` is ambiguous.

## ANTI-JUNK / CONTENT QUALITY

Known risks:
- `charge what you’re worth`;
- «ценность должна быть выше цены» slogan without mechanism;
- high-price bravado;
- never-discount absolutism;
- universal value/fixed/outcome pricing claims;
- three-package anchoring recipe;
- fake scarcity;
- production anglicisms `scope / risk allocation / fixed fee / T&M` in literary prose;
- decorative `не X, а Y` contrasts;
- legal/accounting overreach;
- invented Russian payment norms.

## PRE-WRITING DECISION

- World-class: **PASS**;
- Original contribution: **PASS**;
- Practical value: **PASS**;
- Russia application: **PASS WITH HIGH FRESHNESS BOUNDARY**;
- Research/evidence: **PASS WITH CONTEXT/TRANSFER LIMITS**;
- AI-era relevance: **PASS AS CURRENT CONTEXT**;
- Intra-book uniqueness: **PASS**;
- Architecture fit: **PASS**.

**WRITING_ALLOWED=YES**.
