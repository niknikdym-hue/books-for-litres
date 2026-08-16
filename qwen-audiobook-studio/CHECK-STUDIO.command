#!/bin/zsh
set -u

STUDIO_DIR="/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio"
PYTHON="/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python"

clear
echo "Qwen Audiobook Studio — безопасная проверка"
echo "==========================================="

if [[ ! -x "$PYTHON" ]]; then
  echo "ОШИБКА: не найден Python рабочей MLX-Qwen среды:"
  echo "$PYTHON"
  echo
  read "?Нажмите Enter, чтобы закрыть окно."
  exit 2
fi

cd "$STUDIO_DIR" || exit 2
"$PYTHON" "$STUDIO_DIR/studio.py" --check
STATUS=$?

echo
read "?Нажмите Enter, чтобы закрыть окно."
exit $STATUS
