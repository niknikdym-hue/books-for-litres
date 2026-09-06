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
| 3 | proof заменён self-claims | какое evidence закрывает конкретный risk | Evidence Inventory + Gap Map | у каждого proof указаны relevance/limits | cases/reviews/credentials/registries where relevant | RESERVED |
| 4 | delivery — black box | что показать о future process | Process Visibility Map | ясны stages/roles/checkpoints/change rules | российский small agency/IT/consulting context | RESERVED |
| 5 | предложение делается до понимания задачи | достаточно ли information для offer | Diagnostic Conversation Map | known/missing info явно отделены | B2C/self-employed + small B2B + buying group | RESERVED / RESEARCH BLOCKER |
| 6 | принимается плохой fit | proceed/clarify/redesign/decline | Qualification / No-Go Criteria | observable criteria дают repeatable decision | capacity risk solo/ИП/small agency | RESERVED / CONDITIONAL |
| 7 | КП не собирает decision logic | что buyer должен увидеть для решения | Offer Decision Sheet + revised proposal | decision-maker понимает situation/scope/proof/process/investment/next step | B2B КП vs B2C context | RESERVED / RESEARCH BLOCKER |
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

## 4. Next-business-day test

Каждый artifact должен быть применим к реальной продаже уже на следующий рабочий день. «Повышать ценность / доверие / качество» не считается action.

## 5. Economic significance test

Отдельная глава допустима только если её ошибка частая или дорогая и влияет на потерю сделки, unnecessary discount, bad fit, expectation conflict или wasted capacity/time.

Ch6 сохраняет **условный reservation**: если research/draft не докажут самостоятельную economic/intellectual function, она MERGE с Ch5 и книга становится 9-главной.

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

Ch1–2 practical outputs = **USED-DRAFT**.

Ch3–10 remain `RESERVED` until their own contract gates. No later chapter may create a renamed Buyer Uncertainty Map or Service Decision Definition.
