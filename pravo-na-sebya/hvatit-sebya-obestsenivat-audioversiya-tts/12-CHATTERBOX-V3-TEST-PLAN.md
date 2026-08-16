# Chatterbox Multilingual V3 — test gate

## Причина перехода

Silero `ru_roman` закрыт как финальный движок для книги: тембр приемлем, но после ритмической правки чтение всё равно воспринимается как автосинтез.

Основной критерий дальше: голос должен звучать как человек, а не как хорошо настроенный TTS.

## Новый кандидат

- Engine: Chatterbox Multilingual V3
- Model size: 0.5B
- Language: Russian (`ru`)
- Run mode: local only
- Billing/API: none
- Target hardware: MacBook Air M1, 8 GB
- Preferred device: Apple MPS; CPU fallback only if MPS fails

## Что тестируем

Один реальный фрагмент аудиоверсии книги в трёх режимах:

1. `01-NEUTRAL.wav` — `exaggeration=0.50`, `cfg_weight=0.50`
2. `02-MORE-HUMAN.wav` — `exaggeration=0.62`, `cfg_weight=0.35`
3. `03-RESTRAINED.wav` — `exaggeration=0.45`, `cfg_weight=0.30`

Это не три разных диктора, а три варианта манеры одного встроенного голоса/conditionals.

## PASS

PASS только если хотя бы один вариант:
- звучит естественно по-русски;
- не имеет выраженного иностранного акцента;
- не выдаёт типичную синтетическую фразовую интонацию;
- пригоден для непрерывного прослушивания как аудиокнига.

Если все три варианта остаются роботизированными, Chatterbox закрываем без строительства полного конвейера.

## Установка

Для теста создан отдельный пакет `chatterbox-v3-m1-test-kit.zip`.

Установка создаёт отдельную локальную папку:
`~/Documents/New project/audiobook-tts-m1-codex-kit/chatterbox-v3-test/`

Старые Qwen/Piper/Silero окружения до PASS Chatterbox не удаляются.

Launcher создаётся локально на Mac во время установки, чтобы не повторять Gatekeeper-проблему скачанных `.command` файлов.
