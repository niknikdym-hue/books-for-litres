# UNIQUENESS LEDGER — «Как продавать услуги»

**Серия:** «Секреты продвижения услуг»  
**Книга:** №1  
**Статус:** DRAFT / PRE-ARCHITECTURE  
**Назначение:** защита от повторов внутри первой книги и подготовка её будущего exclusion corpus для всей серии.

## 1. Правило

До написания каждой главы её интеллектуальные активы резервируются здесь. После написания запись сверяется с фактическим текстом.

Нельзя начинать следующую главу, не проверив её против всех предыдущих записей этого ledger.

После принятия всей книги финальные активы переносятся/агрегируются в `../SERIES-CANON-REGISTRY.md` и становятся межкнижным exclusion corpus.

До `DEFINITION-APPROVED` и `ARCHITECTURE-APPROVED` book-wide идеи могут иметь только статус `PLANNED`; глава не получает `RESERVED` автоматически.

## 2. Статусы

- `PLANNED` — предложено, но пользователь ещё не утвердил Definition/Architecture;
- `RESERVED` — закреплено принятой архитектурой;
- `USED-DRAFT` — вошло в рабочий текст;
- `REMOVED` — удалено и не присутствует в финальном тексте;
- `USED-ACCEPTED` — вошло в принятый master.

## 3. Book-wide proposed territory

| Объект | Предложенная функция | Статус |
|---|---|---|
| Central promise | сделать профессиональную услугу понятной и достаточно безопасной для решения о покупке | PLANNED / `BOOK-DEFINITION.md` |
| Central mechanism | трудно оценить услугу → buyer uncertainty/perceived risk → покупатель ищет signals → ясность/evidence/process уменьшают часть uncertainty | PLANNED / not reserved |
| Main diagnostic direction | различать виды неопределённости вместо общего «нет доверия / дорого» | PLANNED / requires research+architecture |

Эти записи не являются chapter contracts и не разрешают писать главы.

## 4. Chapter territory matrix

| Глава | Уникальный вопрос | Уникальный механизм | Результат читателя | NOT THIS CHAPTER | Статус |
|---|---|---|---|---|---|
| TBD | TBD | TBD | TBD | TBD | PRE-ARCHITECTURE |

## 5. Causal mechanisms

| ID | Глава | Причинная схема | Что объясняет | Запрещено повторять где | Статус |
|---|---|---|---|---|---|
| — | — | Chapter-level механизмы не резервируются до Architecture | — | — | — |

## 6. Scenes / cases

| ID | Глава | Тип сцены | Конфликт | Функция в аргументе | Статус |
|---|---|---|---|---|---|
| — | — | Сцены не резервируются до Architecture | — | — | — |

## 7. Analogies / metaphors

| ID | Глава | Аналогия / образ | Какой механизм объясняет | Статус |
|---|---|---|---|---|
| — | — | Никакие аналогии не зарезервированы | — | — |

**Правило:** использованная аналогия не повторяется в другой главе даже в новой декорации, если объяснительная функция та же.

До Architecture не придумывать «фирменные» метафоры заранее: это создаёт риск строить главу вокруг украшения, а не механизма.

## 8. Research functions

| ID | Глава | Источник / тип evidence | Что доказывает | Статус |
|---|---|---|---|---|
| — | — | `RESEARCH-MAP.md` содержит source pool; конкретные functions ещё не распределены | — | PRE-ARCHITECTURE |

Новое исследование не разрешает заново доказывать уже закрытый вывод.

## 9. Frameworks / practical tools

| ID | Глава | Инструмент | Новое действие читателя | Статус |
|---|---|---|---|---|
| — | — | Пока не создано | — | — |

## 10. Distinctions / classifications

| ID | Глава | Различение / классификация | Зачем нужна | Статус |
|---|---|---|---|---|
| — | — | Candidate taxonomy buyer uncertainty остаётся research hypothesis | — | PLANNED |

## 11. Composition map

| Глава | Тип открытия | Основной ход | Поворот / усложнение | Тип финала | Статус |
|---|---|---|---|---|---|
| TBD | TBD | TBD | TBD | TBD | PRE-ARCHITECTURE |

Цель — не допустить, чтобы главы повторяли одну производственную формулу.

## 12. Repetition audit log

| Дата | Объекты сравнения | Найденный риск | Решение | Результат |
|---|---|---|---|---|
| 2026-09-06 | инициализация книги | Architecture отсутствует | не резервировать chapter assets | CLOSED |
| 2026-09-06 | Definition vs legacy books №2–4 | книга №1 может поглотить Яндекс Директ/онлайн-курс как «полезные темы» | внести legacy territories в `NOT THIS BOOK` и series registry | PASS / PROTECTED |
| 2026-09-06 | Definition vs old 2024 public fragment | риск повторить generic «ценность / доверие / потребности / УТП» | заменить broad advice на proposed buyer-uncertainty mechanism; старую структуру не использовать | PASS FOR DEFINITION-DRAFT |
| 2026-09-06 | Definition vs competitor category | риск стать ещё одной книгой из советов/скриптов | требовать causal model + diagnostics + evidence + decision tools | PASS FOR DEFINITION-DRAFT |
| 2026-09-06 | Research Map | один и тот же perceived-risk evidence может расползтись по нескольким главам | после Architecture закреплять один research function за конкретной главой и не повторять вывод | OPEN UNTIL ARCHITECTURE |

## 13. Future-book leakage

Сильные идеи, которые не относятся к центральному обещанию «Как продавать услуги», не расширяют книгу автоматически.

| Идея | Почему не здесь | Куда вынесена | Статус |
|---|---|---|---|
| Яндекс Директ для психолога | отдельная platform+niche system | legacy book №2 | LEGACY-PROTECTED |
| Яндекс Директ для юриста | отдельная platform+niche system | legacy book №3 | LEGACY-PROTECTED |
| полноценная система продаж онлайн-курса | отдельная product/funnel territory | legacy book №4 | LEGACY-PROTECTED |
| SEO/GEO, SMM, email, personal brand | acquisition/visibility systems, а не центральная mechanics of purchase decision | `../SERIES-CANON-REGISTRY.md` future parking lot | PARKED |

## 14. Gate перед каждой главой

Глава получает допуск к написанию только если можно ответить `YES` на всё:

- её вопрос не решён предыдущей главой;
- механизм новый;
- причинная схема новая;
- тип сцены не воспроизводит прежнюю функцию;
- аналогия новая, не повторяет series registry и действительно нужна;
- evidence доказывает новый вывод;
- практический инструмент создаёт новое действие;
- композиция не копирует соседнюю главу;
- материал не принадлежит другой главе/будущей книге;
- Content Quality и research constraints известны заранее.

## 15. Current gate

Сейчас допустимы только Definition/research/category work и подготовка к Architecture.

`WRITING=CLOSED` до прямого пользовательского `ARCHITECTURE-APPROVED`.
