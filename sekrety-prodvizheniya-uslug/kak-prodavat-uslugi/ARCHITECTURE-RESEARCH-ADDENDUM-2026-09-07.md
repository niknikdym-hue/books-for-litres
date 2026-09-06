# ARCHITECTURE RESEARCH ADDENDUM — «Как продавать услуги»

**Дата:** 2026-09-07  
**Статус:** ARCHITECTURE-DRAFT SUPPORTING EVIDENCE  
**Назначение:** проверить самые рискованные границы Architecture v1 до пользовательского Architecture gate.

## 1. Chapter 6 — fit / qualification имеет самостоятельную функцию

### Evidence A — customer compatibility

Buell, Campbell & Frei, `The Customer May Not Always Be Right: Customer Compatibility and Service Performance`, Management Science 67(3), 2021 (published online 2020).  
https://pubsonline.informs.org/doi/10.1287/mnsc.2020.3596

Исследование определяет customer compatibility как степень соответствия потребностей клиентов возможностям обслуживающей operation и связывает различия в compatibility с customer experience и firm performance.

**Architecture implication:** у chapter 6 есть отдельный предмет: не «лучше расспросить клиента», а проверить fit между потребностью/условиями клиента и способностью service system качественно выполнить работу.

**Boundary:** это не research validation универсальной sales qualification scorecard. Практический tool остаётся авторским synthesis.

### Evidence B — client participation in professional services

Fu et al., `When are clients helpful? Capitalising on client involvement in professional service delivery`, PLOS ONE 18(2), 2023.  
https://journals.plos.org/plosone/doi?id=10.1371/journal.pone.0280738

Study of professional-service project teams finds client involvement can contribute to performance/creativity, with effect depending on team conditions.

**Architecture implication:** participation is a real delivery variable; Ch6 may legitimately ask whether roles/participation conditions support good delivery.

**Decision:** Ch6 remains separate in Architecture v1, but fail-closed merge test stays active if chapter-level practical criteria collapse into Ch5.

## 2. Chapter 8 — price must remain risk-aware, not value-pricing folklore

Alavi et al., `Price negotiating for services: elucidating the ambivalent effects on customers’ negotiation aspirations`, Journal of the Academy of Marketing Science 48, 2020.  
https://link.springer.com/article/10.1007/s11747-019-00676-4

Across five studies, service heterogeneity and perceived product risk can increase negotiation aspirations, while service inseparability/integration can produce countervailing negotiation risk.

**Architecture implication:** price negotiation in services can be connected to uncertainty/risk and service design. This supports Ch8's decision to integrate price with scope/risk rather than teach generic «raise value» rhetoric.

**Boundary:** the paper does not validate every proposed payment/staging/guarantee tactic. Russia-specific transaction designs remain a high-freshness research blocker.

## 3. Chapter 10 — lost-deal learning needs buyer evidence, not seller attribution

Friend et al., `Why are you really losing sales opportunities? A buyers' perspective on the determinants of key account sales failures`, Industrial Marketing Management 43(7), 2014.  
https://www.sciencedirect.com/science/article/pii/S001985011400100X

The study uses 35 post-mortem interviews with buying decision makers after failed key-account proposals and explicitly addresses attribution bias from seller-side explanations.

**Architecture implication:** Ch10 has a legitimate independent function: separate seller inference from buyer-side evidence and learn from outcomes.

**Boundary:** key-account B2B evidence is not generalized to all Russian solo/B2C services. The book's practical method must stay lightweight and scope-aware.

## 4. Remaining blockers before WRITING

Architecture itself may be approved with these blockers visible, but no affected chapter gets `WRITING_ALLOWED=YES` until resolved:

- **Ch5:** sales-specific evidence for diagnosis before proposal; avoid SPIN-copy.
- **Ch7:** proposal-specific evidence; much guidance may remain expert synthesis and must be labelled honestly.
- **Ch8:** guarantees/staged commitments/fee models + Russian legal/payment context.
- **Ch9:** exact uncertainty/objection taxonomy and status-quo mechanisms; likely author synthesis unless stronger research supports categories.

## 5. Audit conclusion

Evidence found after Architecture draft **strengthens rather than invalidates** the proposed causal spine.

No evidence justifies relaxing anti-overlap rules or turning author-created tools into claimed validated methodologies.

Current recommendation: Architecture v1 is fit to be shown to the user for `ARCHITECTURE-APPROVED / REWORK`, with Ch6 standalone but still subject to final merge test and Ch5/7/8/9 research blockers explicit.
