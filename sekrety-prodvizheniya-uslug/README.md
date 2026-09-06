# «Секреты продвижения услуг» — series workspace

Это отдельный рабочий контур серии практического делового нон-фикшена в `niknikdym-hue/books-for-litres`.

## Source of truth

GitHub — source of truth. Новый чат/исполнитель сначала проверяет актуальный `main` и рабочий PR/branch. Не восстанавливать производственное состояние по памяти, если его можно проверить в репозитории.

## Обязательный read order перед написанием

1. `SERIES-BRAIN.md` — мозг, границы и канон серии.
2. `SERIES-QUALITY-CONSTITUTION.md` — жёсткие законы качества и zero-overlap.
3. `SERIES-CANON-REGISTRY.md` — что уже использовано/зарезервировано и больше нельзя повторять.
4. `SERIES-PRODUCTION-PROTOCOL.md` — последовательность производства каждой книги.
5. `audiobook-studio/contracts/content-quality-core-ru-v1.json` — системный русский Content Quality Lexicon core.
6. Book-level authority текущей книги.
7. Полные принятые Literary Masters всех предыдущих книг серии.

Без этого read set не начинать новое написание.

## Текущая книга

1. `kak-prodavat-uslugi/` — **«Как продавать услуги»**, книга №1, режим WRITE FROM ZERO.

Внутри книги обязательны:

- `BOOK-BRAIN.md`;
- `UNIQUENESS-LEDGER.md`;
- позже: Book Definition / Research Map / Architecture / chapter contracts / Literary Master.

## Главный закон

**Каждая книга серии уникальна.**

Не допускаются смысловые повторы предыдущих книг и повторные версии уже использованных:

- механизмов;
- причинных схем;
- сцен и типов кейсов;
- аналогий и метафор;
- исследовательских функций;
- фреймворков и практических инструментов;
- классификаций;
- композиционных решений;
- риторических ходов.

Та же проверка действует внутри одной книги между её главами.

## Status discipline

`DRAFT` ≠ `APPROVED`.  
`LITERARY MASTER` ≠ `ACCEPTED/LOCKED` без прямого принятия пользователем.

После принятия книги полный master становится exclusion corpus для всех следующих книг серии, а `SERIES-CANON-REGISTRY.md` обновляется фактическими использованными активами.
