# Yandex Russian male voice casting — round 1

This directory contains a separate bounded casting layer over the existing SpeechKit v3 backend. It does not replace or modify the frozen production profile `Lera / neutral / 1.04`.

Profiles:

- `filipp` — default/no role
- `ermil` — `neutral`
- `zahar` — `neutral`
- `alexander` — `neutral`
- `kirill` — `neutral`
- `anton` — `neutral`
- `madi_ru` — default/no role

Every profile uses speed `1.0` and the unchanged OpenAI-round Russian control text. The task-scoped hard limit is `10.00 RUB`; the production pricing file is read but never modified. The existing safe segmenter creates six paid segments per voice, or 42 planned billing units.

Offline check:

```bash
python3 qwen-audiobook-studio/casting/yandex-male/run_yandex_male_casting.py --check
```

Paid run requires both explicit flags:

```bash
python3 qwen-audiobook-studio/casting/yandex-male/run_yandex_male_casting.py --run --confirm-paid-casting
```

Generated WAV, manifests, working segments, and summaries stay outside the repository under `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/casting/yandex-male/<timestamp>/`.

Official voice reference: <https://yandex.cloud/ru-kz/docs/speechkit/tts/voices>
