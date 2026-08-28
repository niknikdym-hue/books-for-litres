# QA runtime blocker — 2026-08-28

Observed after PR #9 was merged into main and fresh staging was rebuilt from merge commit `450caf0a8c6ad291a1d96e23b1919f8f92e88341`.

Human flow:
- Desktop fresh Audiobook Studio staging opens successfully.
- Yandex/Lera current production book/job is selected.
- `Проверка готового аудио` is present.
- Clicking `Открыть готовое аудио для проверки` fails with the generic native message: `Не удалось выполнить действие. Откройте Технические подробности, если проблема повторится.`

Known artifact remains unchanged:
- book `hvatit-sebya-obestsenivat`
- job `chapter-ch001`
- profile `yandex_lera`
- SHA-256 `2311b300ea1d1769fd9b299a7cb8e20ff218393e36e71bb6d86fb523172784b6`
- automatic QA previously PASS
- manual QA remains UNREVIEWED

No re-synthesis/provider/network request is authorized for diagnosis or fix. Reproduce through the local QA bridge/runtime and fix the root cause before human approval resumes.
