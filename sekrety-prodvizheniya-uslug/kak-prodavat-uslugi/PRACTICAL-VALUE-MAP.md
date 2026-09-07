# PRACTICAL VALUE MAP — «Как продавать услуги»

**Статус:** ARCHITECTURE-APPROVED / WRITING IN PROGRESS  
**Дата:** 2026-09-07  
**Definition:** APPROVED  
**Architecture v1:** APPROVED  
**WRITING:** PER-CHAPTER ONLY AFTER CONTRACT PASS

## 1. Главный gate

Каждая глава должна отвечать:

1. какую реальную коммерческую проблему решает;
2. какое новое решение читатель сможет принять;
3. что конкретно он сделает;
4. какой business artifact создаст/изменит;
5. как проверит качество результата;
6. как output применяется в России;
7. чем он уникален относительно соседних глав и серии.

Слабая practical value = `REWORK / MERGE / DELETE` даже после Architecture approval.

## 2. Book-level practical promise

После книги у читателя должна остаться **рабочая система продажи собственной профессиональной услуги**, а не конспект советов.

| Ch | Business problem | Decision | Artifact | Observable check | Russia application | Status |
|---:|---|---|---|---|---|---|
| 1 | непонятна реальная причина no-decision | какую uncertainty диагностировать | Buyer Uncertainty Map | 3–5 сделок разложены по конкретным hypotheses/evidence | B2C / owner-led B2B / multi-stakeholder B2B | **USED-DRAFT** |
| 2 | услуга описана задачами/компетенциями | что именно buyer решается купить | Service Decision Definition | ясны situation/work result/boundaries/client role/non-guaranteed outcome | B2C clarity + B2B scope/assumptions | **USED-DRAFT** |
| 3 | proof заменён self-claims / нерелевантными регалиями | какое evidence отвечает на конкретный buyer risk | Evidence Inventory + Gap Map | у каждого proof есть relevance/verifiability/support/limits/gap | cases/reviews/credentials/registries only where relevant | **USED-DRAFT** |
| 4 | delivery — black box | что показать о future process | Process Visibility Map | ясны stages/inputs/outputs/roles/checkpoints/change rules | small agency/IT/consulting/professional-service contexts | **USED-DRAFT** |
| 5 | предложение делается до достаточного понимания задачи | достаточно ли информации для проектирования offer | Diagnostic Conversation Map | fact/assumption/unknown + materially relevant gaps explicitly separated | individual / owner-led small B2B / multi-stakeholder B2B | **USED-DRAFT** |
| 6 | понятная задача продаётся в несовместимой конфигурации | proceed / redesign / decline-refer | Критерии совместимости сделки | шесть compatibility conditions проверены; hard no-go не маскируется score | solo/NPD / ИП / small agency / regulated-professional boundary | **USED-DRAFT** |
| 7 | КП содержит seller information, но не собирает buyer decision | какую информацию оставить/убрать, чтобы решение можно было восстановить без продавца | Offer Decision Sheet / Карта решения по предложению + revision of one real proposal | independent buyer-retell test covers task/service/proof/process/conditions/investment/limits/next action | short/simple B2B, formal procurement, distributed B2C decision information | **USED-DRAFT** |
| 8 | price отделена от scope/risk | что менять при ценовом напряжении | Price–Scope–Risk Map | price change связан с scope/obligation/risk | payment/staging/B2B-B2C after fresh check | RESERVED / HIGH BLOCKER |
| 9 | одинаковая фраза скрывает разные причины | clarify/redesign/wait/decline etc. | Uncertainty/Objection Diagnostic | competing hypotheses проверяются до response | no unsupported Russia stereotypes | RESERVED / HIGH BLOCKER |
| 10 | seller неверно объясняет wins/losses | какое system change тестировать | Lost-Deal Learning Loop + system assembly | facts/assumptions/pattern/test separated | usable without BI stack | RESERVED |

`Personal Service Sales System` — не одиннадцатый tool. Это финальная интеграция Ch1–10.

## 3. Actual practical QA so far

### Ch1 — Buyer Uncertainty Map
- next-business-day: PASS;
- creates a new diagnostic action: PASS;
- Russian applicability: PASS-DRAFT;
- does not duplicate later objection handling: PASS WITH Ch9 PROTECTION.

### Ch2 — Service Decision Definition
- next-business-day: PASS;
- six fields are author-created synthesis, clearly labelled;
- observable stranger-retell test: PASS;
- separates controllable work result from external outcome and specifies client participation boundary;
- does not duplicate Ch3 evidence or Ch4 process map: PASS WITH PROTECTED BOUNDARIES.

### Ch3 — Evidence Inventory + Gap Map
- next-business-day: PASS;
- reader maps 3–5 real buyer risks to evidence instead of collecting generic credentials;
- observable fields: relevance, verifiability, supported claim, limits, gap;
- author-created synthesis clearly labelled;
- does not duplicate Ch2 service definition;
- Ch4 protected: future stages/roles/checkpoints are not part of this artifact;
- Russia layer avoids invented universal hierarchy of reviews/registries.

### Ch4 — Process Visibility Map
- next-business-day: PASS;
- reader turns a hidden delivery process into 4–7 decision-relevant stages;
- observable fields: input, output, provider/client role, checkpoint/decision, change rule;
- does not become a PM/Gantt manual;
- Ch2 role/boundary definition is not repeated: Ch4 owns timing, intermediate outputs and change logic;
- future-process observability remains distinct from Ch3 proof.

### Ch5 — Diagnostic Conversation Map
- next-business-day: PASS;
- reader can apply the map to the next enquiry before opening a proposal template;
- core action: separate fact / assumption / unknown and identify only gaps that can materially change solution design;
- four legitimate outcomes: design offer / verify / reframe together / do not prescribe yet;
- does not become a question script or pain-amplification tool;
- Ch6 fit/no-go criteria remain protected.

### Ch6 — Критерии совместимости сделки
- next-business-day: PASS;
- hard merge test vs Ch5: PASS on actual draft;
- six conditions: provider capability, controllable commitment, client inputs/participation, scope/time/capacity, expectation boundaries, professional/ethical/legal limits;
- no numeric lead score; one hard no-go can outweigh multiple positives;
- decisions: proceed / redesign configuration / decline-refer;
- rejects personality/red-flag/chemistry framing;
- practical value is protection against delivery loss/capacity displacement, not just conversion optimization.

### Ch7 — Offer Decision Sheet / Карта решения по предложению
- next-business-day: PASS;
- reader audits and rewrites one existing real proposal rather than generating a generic template;
- eight fields integrate Ch2–6 without reteaching their tools;
- buyer-retell test checks whether decision logic survives without seller explanation;
- no ideal page count/visual format/three-package recipe;
- price must be visible, but its economic design remains protected for Ch8;
- short ≠ automatically good; decision complexity and objective requirements determine necessary detail.

## 4. Next-business-day test

Каждый artifact должен быть применим к реальной продаже уже на следующий рабочий день. «Повышать ценность / доверие / качество» не считается action.

## 5. Economic significance test

Отдельная глава допустима только если её ошибка частая или дорогая и влияет на потерю сделки, unnecessary discount, bad fit, expectation conflict или wasted capacity/time.

Ch6 **прошла hard merge-test на фактическом draft** и остаётся отдельной: её decision/artifact/economic function не дублируют Ch5.

## 6. Russia applicability

В каждой главе global mechanism сохраняется, а локальный слой меняет конкретное действие только там, где российская практика materially relevant. Legal/tax/payment/platform specifics получают freshness check перед master.

## 7. No duplicate tools

Запрещено:

- делать отдельный checklist для уже существующего artifact;
- повторять diagnostic questions внутри proposal/objection tools;
- выдавать chapter summary за самостоятельный tool;
- создавать workbook-пункты ради объёма;
- переименовывать один и тот же reader action.

## 8. Tool evidence rule

Каждый artifact маркируется по происхождению: research-derived / synthesis / author-created framework / checklist from chapter logic. Авторский synthesis не называется scientifically validated без evidence.

## 9. Whole-book completion test

Practical gate FAIL, если reader должен сам придумывать применение, outputs дублируются, российская реальность требует самостоятельного «перевода», либо tools устаревают вместе с одной platform.

## 10. Current status

Ch1–7 practical outputs = **USED-DRAFT / QA PASS-DRAFT**.

Ch8–10 remain `RESERVED` until their own contract gates. No later chapter may create renamed versions of Ch1–7 tools.
