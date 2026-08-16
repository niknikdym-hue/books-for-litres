#!/bin/zsh
set -u

STUDIO_DIR="/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio"
PYTHON="/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python"

clear
echo "Qwen Audiobook Studio"
echo "======================"

if [[ ! -d "$STUDIO_DIR" ]]; then
  echo "ОШИБКА: не найдена папка студии:"
  echo "$STUDIO_DIR"
  echo
  read "?Нажмите Enter, чтобы закрыть окно."
  exit 2
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ОШИБКА: не найдено рабочее MLX-Qwen окружение:"
  echo "$PYTHON"
  echo
  read "?Нажмите Enter, чтобы закрыть окно."
  exit 2
fi

cd "$STUDIO_DIR" || exit 2
"$PYTHON" "$STUDIO_DIR/studio.py"
STATUS=$?

echo
if [[ $STATUS -eq 0 ]]; then
  echo "Студия завершила работу."
else
  echo "Студия завершилась с кодом ошибки: $STATUS"
fi
read "?Нажмите Enter, чтобы закрыть окно."
exit $STATUS
