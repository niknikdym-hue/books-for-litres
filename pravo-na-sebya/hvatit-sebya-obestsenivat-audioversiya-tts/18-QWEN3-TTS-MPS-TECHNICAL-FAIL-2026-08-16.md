# Qwen3-TTS 0.6B CustomVoice — MPS TECHNICAL FAIL

Дата: 2026-08-16

Источник статуса: фактический локальный запуск Codex на MacBook Air M1 / 8 GB, результат передан пользователем после выполнения обязательного STOP-условия.

## Проверенная конфигурация

- Qwen upstream PR #345 head: `26a5dacbc1644772df13f34966838e601a59c03c`
- модель: `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`
- backend: PyTorch MPS
- device: `mps`
- dtype: `float16`
- speaker первого smoke: `Serena`

## Фактический результат

- MPS был доступен;
- модель загрузилась;
- загрузка модели: `282.01 s`;
- до первого WAV генерация упала с:
  `torch.AcceleratorError: probability tensor contains either inf, nan or element < 0`;
- WAV получено: `0`;
- остальные 8 speaker не запускались;
- `RUN-REPORT.json` не создан, потому что runner остановился до завершения первого сегмента;
- system swap вырос примерно с `1211.69 MB` до `2431.75 MB`;
- OOM/process kill не было;
- никаких исправлений, альтернативных моделей, Stage B или полной книги не запускалось;
- старые TTS, мастер, сценарий и runner не изменялись.

## Интерпретация

Это **не HUMAN READING FAIL самой Qwen3-TTS 0.6B CustomVoice**: ни одного аудиосэмпла не было получено и художественное качество не проверялось.

Это технический FAIL конкретного пути:

`Qwen3-TTS PR #345 + PyTorch MPS + float16 + sampling + MacBook Air M1/8GB`.

Ошибка возникает на этапе sampling probability tensor до первого WAV. Дополнительно путь уже показал заметный swap на 8 GB unified memory.

## Решение

`PYTORCH/MPS PR #345 PATH: CLOSED FOR THIS PROJECT`

Не делать на этом пути:
- повторные запуски с другими speaker;
- перебор temperature/top-k/top-p;
- monkey patches sampling;
- CPU fallback;
- float32 fallback;
- отключение sampling ради получения технического WAV;
- многочасовой ремонт PR #345.

Причина: цель проекта — получить естественную аудиокнигу, а не довести экспериментальный MPS backend до состояния demo.

## Следующий разрешённый путь

Та же модель/концепция CustomVoice, но нативный Apple-Silicon runtime:

- runtime: `Blaizzy/mlx-audio`;
- pinned release: `v0.4.5`;
- commit: `04151c6abb74b886f879a4457ccdc96761f10102`;
- MLX model: `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16`;
- voice cloning: NO;
- 9 preset speaker: YES;
- Russian: YES;
- audiobook instruct: YES, передаётся отдельным control argument, не как произносимый текст.

Следующее точное задание: `19-QWEN3-TTS-MLX-AUDIO-M1-CODEX-TASK.md`.
