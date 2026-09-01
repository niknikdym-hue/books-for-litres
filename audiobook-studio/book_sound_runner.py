from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from book_sound_design import BookSoundDesignError, book_sound_status, set_book_sound


def _workspace() -> Path:
    return Path(os.environ.get("AUDIOBOOK_STUDIO_HOME", "~/Documents/New project/Audiobook-Studio")).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audiobook Studio chapter sound preferences")
    parser.add_argument("--book", required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--set", action="store_true")
    parser.add_argument("--enabled", choices=("true", "false"))
    parser.add_argument("--sound-id")
    args = parser.parse_args()
    try:
        if args.status:
            result = book_sound_status(_workspace(), args.book)
        elif args.set:
            if args.enabled is None or not args.sound_id:
                parser.error("--set requires --enabled and --sound-id")
            result = set_book_sound(
                _workspace(),
                args.book,
                enabled=args.enabled == "true",
                sound_id=args.sound_id,
            )
        else:
            parser.error("choose --status or --set")
            return 2
    except BookSoundDesignError as error:
        print(json.dumps({"state": "BLOCKED", "code": error.code, "message": error.message}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
