# BOOK BRAIN — «Как продавать услуги»

**Серия:** «Секреты продвижения услуг», книга №1  
**Статус:** DEFINITION-APPROVED / ARCHITECTURE-DRAFT  
**Режим:** WRITE FROM ZERO  
**Дата старта:** 2026-09-06  
**Definition approved:** 2026-09-07  
**WRITING:** CLOSED

## 1. Обязательный authority read set

Перед любой содержательной работой по книге прочитать:

1. `../SERIES-BRAIN.md`;
2. `../SERIES-QUALITY-CONSTITUTION.md`;
3. `../WORLD-CLASS-PRACTICAL-RUSSIA-STANDARD.md`;
4. `../SERIES-CANON-REGISTRY.md`;
5. `../SERIES-PRODUCTION-PROTOCOL.md`;
6. `../CHAPTER-CONTRACT-TEMPLATE.md`;
7. `../LEGACY-SERIES-INVENTORY-2026-09-06.md`;
8. этот `BOOK-BRAIN.md`;
9. `BOOK-DEFINITION.md`;
10. `DEFINITION-APPROVAL-2026-09-07.md`;
11. `CATEGORY-COMPETITOR-MAP-2026.md`;
12. `WORLD-CLASS-BENCHMARK-2026.md`;
13. `RESEARCH-MAP.md`;
14. `PRACTICAL-VALUE-MAP.md`;
15. `RUSSIA-APPLICATION-MAP-2026.md`;
16. `UNIQUENESS-LEDGER.md`;
17. Architecture / chapter contracts после их появления;
18. Content Quality Lexicon `BOOK_PROSE`.

Обязательный общий quality gate:

- `../../audiobook-studio/contracts/content-quality-core-ru-v1.json`;
- профиль `BOOK_PROSE` из `../../audiobook-studio/content_quality_lexicon.py`.

Этот файл не заменяет Book Definition и не является Architecture.

## 2. Что подтверждено пользователем

- Название книги: **«Как продавать услуги»**.
- Это первая книга серии **«Секреты продвижения услуг»**.
- Новая версия создаётся **с нуля**, а не глубокой редактурой старого текста.
- После первой книги пользователь хочет обновить все остальные существующие книги серии и написать новые.
- Серия, правила и состояние фиксируются в `niknikdym-hue/books-for-litres`.
- Общий Content Quality Lexicon / «словарь мусорных слов» обязателен.
- Каждая книга серии должна быть уникальной; запрещены смысловые повторы, повторные аналогии и переупаковки старых механизмов.
- Книга должна иметь **очень сильное практическое значение и быть актуальной**.
- Планка — **уровень очень сильных мировых деловых книг**, не средний мировой рынок.
- При этом книга должна давать **конкретное применение для России**.
- 2026-09-07 пользователь прямо утвердил `BOOK-DEFINITION.md`: **`DEFINITION-APPROVED`**.

## 3. Четыре обязательных качества книги

Книга не может считаться сильной, если не проходит одновременно:

1. **TOP-TIER GLOBAL** — сравнение с очень сильными мировыми benchmark-книгами.
2. **ORIGINAL CONTRIBUTION** — собственная интеллектуальная модель, а не компиляция.
3. **PRACTICAL VALUE** — сильные конкретные решения и business outputs.
4. **RUSSIA APPLICATION** — применимость к российской реальности и freshness-check локальной конкретики.

Провал любого блока = `REWORK`.

## 4. Фактический legacy context

Публичная серия ЛитРес на 2026-09-06 содержит четыре содержательные книги под именем **Елена Дым**:

1. «Как продавать услуги»;
2. «Секреты продвижения услуг психолога в Яндекс Директ»;
3. «Как продвигать юридические услуги в Яндекс Директ: Практическое руководство»;
4. «Как продать онлайн-курсы».

Подробности: `../LEGACY-SERIES-INVENTORY-2026-09-06.md`. Территории legacy-книг №2–4 защищены от поглощения новой книгой №1.

## 5. Утверждённый Definition

Source: `BOOK-DEFINITION.md` + `DEFINITION-APPROVAL-2026-09-07.md`.

Утверждённый стратегический центр:

> продажа профессиональной услуги — работа с неопределённостью покупки: результат, поставщик, доказательства, процесс, цена, границы и следующий шаг должны стать достаточно ясными, чтобы подходящий клиент мог принять решение.

Статус: **DEFINITION-APPROVED**.

Definition закрепляет top-tier global benchmark, original contribution, сильную практическую систему и конкретный российский application layer. Изменение центрального обещания/механизма требует нового явного пользовательского решения.

## 6. Практический результат всей книги

Финальная книга должна позволить читателю **перестроить собственную систему продажи** и оставить компактный набор реальных business artifacts. Candidate pool хранится в `PRACTICAL-VALUE-MAP.md`; Architecture обязана объединить его до минимального числа неповторяющихся outputs.

## 7. World-class benchmark state

`WORLD-CLASS-BENCHMARK-2026.md` задаёт benchmark против сильных сторон `Selling the Invisible`, `The Trusted Advisor`, `SPIN Selling`, `Book Yourself Solid`, `The Challenger Sale` без копирования их frameworks/архитектуры.

## 8. Russia application state

`RUSSIA-APPLICATION-MAP-2026.md` задаёт маршрут:

`мировой mechanism → international evidence → границы применимости → российская ситуация → конкретное действие российского читателя`.

Локальная конкретика проходит freshness audit и не превращает книгу в юридический/платформенный справочник.

## 9. Что пока НЕ зафиксировано

До отдельного решения пользователя не считать окончательно установленными:

- подзаголовок;
- byline нового издания, если пользователь захочет изменить legacy-псевдоним Елена Дым;
- целевой объём;
- число глав;
- Architecture;
- chapter contracts;
- окончательный набор practical artifacts/frameworks;
- оформление ссылок/примечаний.

## 10. Роль старого издания

Старое издание «Как продавать услуги» — **legacy source**, не draft новой книги. Оно может давать вопросы для повторной проверки, но не диктует новую Architecture, стиль или актуальные факты.

## 11. Уникальность первой книги

До accepted master действуют внутрикнижный zero-overlap, protected legacy territories, future-book leakage control, practical-output uniqueness и world-class anti-copy benchmark. Всё резервируется через `UNIQUENESS-LEDGER.md`; аналогии по умолчанию не резервируются и допускаются только при реальной объяснительной необходимости.

## 12. Research state

`RESEARCH-MAP.md` даёт достаточную опору для Architecture по perceived risk/uncertainty, information asymmetry, ex-ante quality signals, process visibility, customer participation/co-production и AI-era context. Открытые вопросы остаются chapter-level blockers до получения достаточного evidence.

## 13. Category state

`CATEGORY-COMPETITOR-MAP-2026.md` и `WORLD-CLASS-BENCHMARK-2026.md` фиксируют gap: цельная decision-oriented система продажи услуги через buyer uncertainty, а не список советов.

## 14. Следующий производственный gate

Definition принят. Следующий разрешённый этап:

1. `ARCHITECTURE-V1.md`;
2. chapter contracts;
3. `PLANNED` intra-book uniqueness entries;
4. practical-output allocation;
5. research blockers per chapter;
6. Russia application allocation;
7. world-class benchmark/deletion audit;
8. прямое пользовательское решение `ARCHITECTURE-APPROVED / REWORK`.

Только после `ARCHITECTURE-APPROVED` переходить к WRITING.

## 15. Quality target

`top-tier global quality + original contribution + доказательная честность + очень сильная practical value + российская применимость + уникальность → скорость`.

## 16. Current next stage

Текущий разрешённый этап: **DEFINITION-APPROVED / ARCHITECTURE-DRAFT**.

Следующий user gate: **ARCHITECTURE-APPROVED / REWORK**. До него WRITING остаётся `CLOSED`.
