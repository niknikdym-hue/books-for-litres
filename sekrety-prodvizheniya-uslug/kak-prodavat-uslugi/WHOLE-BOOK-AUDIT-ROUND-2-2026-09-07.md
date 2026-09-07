# WHOLE-BOOK AUDIT — ROUND 2 — «Как продавать услуги»

**Дата:** 2026-09-07  
**Definition:** APPROVED  
**Architecture v1:** APPROVED  
**Manuscript:** 10 chapters = USED-DRAFT  
**ACCEPTED / LOCKED / LITERARY MASTER:** NO  
**Round-2 verdict:** **PASS STRUCTURE + PASS BOOK_PROSE; FINAL CONTENT GATES STILL OPEN**

## 1. What Round 1 required

Round 1 returned `REWORK` for three P0 defects and several P1 defects:

1. formulaic chapter composition;
2. Ch1 ↔ Ch9 repeated `same surface phrase → different causes` function;
3. Ch7 re-taught Ch2–6 instead of acting as integration layer;
4. production anglicisms in literary prose;
5. course-like navigation / negative-rhetoric residue;
6. risk that ten practical tools read as ten mandatory workbook forms.

All six were actually edited before this audit.

## 2. P0 re-audit

### P0-1. Formulaic composition — PASS-DRAFT

Opening forms now materially differ:

- Ch1 — direct commercial thesis + three microcases;
- Ch2 — conceptual distinction between production description and buyer-readable obligation;
- Ch3 — contrast scene around impressive vs relevant proof;
- Ch4 — direct thesis about the invisible post-payment part of service;
- Ch5 — named-solution dialogue;
- Ch6 — economic thesis: payment does not prove deal quality;
- Ch7 — practical stress-test of a proposal sent to a person absent from the meeting;
- Ch8 — price negotiation dialogue;
- Ch9 — post-offer message and hypothesis test;
- Ch10 — direct CRM attribution thesis.

The previous uniform `scene → mechanism → research → tool → next chapter` rhythm is no longer the book's dominant repeated form.

### P0-2. Ch1 ↔ Ch9 overlap — PASS

Ch1 no longer owns `я подумаю` as its opening or main scene function.

Ch1 owns ex-ante evaluability and the book-wide Buyer Uncertainty Map.

Ch9 begins only after a concrete proposal and owns:

`observed post-offer signal → 2–3 deal-specific competing hypotheses → discriminating fact → one relevant action → stop condition`.

The old second full taxonomy was removed from Ch9.

### P0-3. Ch7 reteaching Ch2–6 — PASS-DRAFT

Ch7 was substantially compressed/rebuilt.

Its unique function is now proposal portability / decision reconstruction when the seller is absent.

Prior chapter outputs are inputs, not lessons retaught inside Ch7. The practical stress-test asks whether an absent decision-maker can reconstruct the purchase decision.

## 3. Other overlap re-audit

- Ch2 ↔ Ch4: PASS — Ch2 owns service obligation/client-role boundary; Ch4 owns sequential observability, intermediate outputs, checkpoints and change rules.
- Ch3 ↔ Ch4: PASS — past/observable provider evidence vs future-delivery observability.
- Ch5 ↔ Ch6: PASS — information sufficiency vs transaction compatibility; Ch6 hard merge-test remains passed on actual drafts.
- Ch6 ↔ Ch8: PASS — feasibility/configuration vs economic/risk allocation.
- Ch7 ↔ Ch8: PASS — visibility of price/terms inside decision document vs redesign of economics.
- Ch8 ↔ Ch9: PASS — Ch8 acts only when economic cause is established; Ch9 establishes which cause is supported.
- Ch9 ↔ Ch10: PASS — live unfinished decision vs after-outcome learning.
- Ch10 ↔ Ch1–9: PASS-DRAFT — final synthesis grouped into four usage phases and does not introduce T11.

## 4. Practical-value re-audit — PASS-DRAFT

Ten tools remain distinct, but the manuscript now explicitly rejects a ten-form ritual.

Four operational phases:

1. make the purchase evaluable — Ch1–4;
2. understand the task and test feasibility — Ch5–6;
3. assemble the transaction — Ch7–8;
4. handle the outcome and learn — Ch9–10.

An instrument is used only when its problem is present.

The book therefore remains strongly practical without becoming a workbook/checklist product in disguise.

## 5. Content Quality Lexicon — EXACT-HEAD PASS

A permanent dedicated CI gate now exists:

`.github/workflows/kak-prodavat-uslugi-book-prose-gate.yml`

Runner:

`sekrety-prodvizheniya-uslug/kak-prodavat-uslugi/quality/book_prose_gate.py`

Properties:

- offline;
- no model/provider/paid calls;
- uses canonical repository Content Quality Lexicon;
- profile `BOOK_PROSE`;
- validates exact ten-chapter inventory;
- fails on BLOCK;
- reports WARN as GitHub annotations;
- deterministic empty CI user lexicon store.

### Round-1 automated result

Initial exact-head run:

- chapters: 10;
- BLOCK: 0;
- WARN: 19.

All 19 warnings were manually reviewed and could be rewritten more directly without loss of meaning.

A one-time fail-closed exact replacement migration was run. It required every source fragment to occur exactly once and required `0 BLOCK / 0 WARN` before it could commit. Temporary migration script/workflow then removed themselves from the branch.

### Independent permanent-gate result

Exact branch HEAD at independent revalidation:

`065d6e584437512ce8ee190a39ff9052d9f00e24`

GitHub Actions:

- workflow: `How to Sell Services BOOK_PROSE Gate`;
- run: `34093093175`;
- conclusion: **SUCCESS**;
- chapters: **10/10 PASS**;
- BLOCK: **0**;
- WARN: **0**;
- canonical lexicon core sha256: `9047773b06c0ae0b9728805baddb120c800cfe9533f8861bdad03c3538adc52d`;
- lexicon fingerprint: `8f178c0cb7de665067dc2dfe32477ba164ddf679e060a92f692697e4a328dc2d`.

This closes the previously open automated `BOOK_PROSE` gate.

## 6. Language / anti-AI re-audit — PASS-DRAFT

Major production anglicisms were removed from literary prose, including research/production terms previously leaking from contracts/source notes.

The 19 lexicon warnings were also removed through reviewed direct rewrites rather than exemptions or weakening the lexicon.

Structural analogies: **NONE USED** across Ch1–10. This remains intentional; no forced metaphor-per-chapter rhythm was introduced.

## 7. What is still NOT closed

### 7.1. Russia freshness audit — OPEN

Before Literary Master, verify every materially time-sensitive Russian claim, especially:

- consumer pre-contract/service information;
- NPD/self-employed receipt language;
- any payment/document claim;
- any regulated-service status/license/registry example;
- any claim whose legal wording could have changed by 2026-09-07.

Do not expand the book into a legal handbook. Correct or narrow only claims already materially used in the manuscript.

### 7.2. Global world-class adversarial review — OPEN

Run a separate whole-book review against top-tier global business nonfiction criteria:

- original contribution vs benchmark books;
- density of non-obvious insight;
- argument quality and counterexamples;
- readability / narrative pull;
- absence of consultant/course voice;
- whether any chapter is merely competent rather than category-level;
- whether Russian applicability weakens or strengthens universality;
- whether any practical tool feels manufactured.

### 7.3. Final literary rhythm / transition pass — OPEN

Even with composition diversity PASS-DRAFT, the full sequential read still needs a final rhythm pass after Russia/adversarial corrections, because those corrections can reintroduce repetition or explanatory clutter.

## 8. Current verdict

**The manuscript has passed the first full structural rework and exact automated BOOK_PROSE quality gate.**

It is materially stronger than the ten initial chapter drafts and the largest overlap/formularity defects are closed.

It is still **NOT ACCEPTED, NOT LOCKED and NOT Literary Master**.

Next allowed work:

1. Russia freshness audit and only necessary corrections;
2. independent world-class adversarial review;
3. whole-book literary/rhythm re-audit after those corrections;
4. Final Review candidate only if all three pass.
