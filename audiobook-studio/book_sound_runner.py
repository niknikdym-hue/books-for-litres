from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from book_sound_design import (
    BookSoundDesignError,
    book_sound_status,
    import_book_sound,
    set_book_sound,
    set_sound_favorite,
)


def _workspace() -> Path:
    return Path(os.environ.get("AUDIOBOOK_STUDIO_HOME", "~/Documents/New project/Audiobook-Studio")).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audiobook Studio chapter sound preferences")
    parser.add_argument("--book", required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--set", action="store_true")
    parser.add_argument("--enabled", choices=("true", "false"))
    parser.add_argument("--sound-id")
    parser.add_argument("--clip-start-seconds", type=float)
    parser.add_argument("--clip-duration-seconds", type=float)
    parser.add_argument("--import-file")
    parser.add_argument("--label")
    parser.add_argument("--confirm-rights", action="store_true")
    parser.add_argument("--favorite", choices=("true", "false"))
    args = parser.parse_args()
    try:
        if args.status:
            result = book_sound_status(_workspace(), args.book)
        elif args.import_file:
            result = import_book_sound(
                _workspace(), args.book, Path(args.import_file), label=args.label,
                rights_confirmed=args.confirm_rights,
            )
        elif args.favorite is not None:
            if not args.sound_id:
                parser.error("--favorite requires --sound-id")
            result = set_sound_favorite(
                _workspace(), args.book, sound_id=args.sound_id, favorite=args.favorite == "true"
            )
        elif args.set:
            if args.enabled is None or not args.sound_id:
                parser.error("--set requires --enabled and --sound-id")
            result = set_book_sound(
                _workspace(),
                args.book,
                enabled=args.enabled == "true",
                sound_id=args.sound_id,
                clip_start_seconds=args.clip_start_seconds,
                clip_duration_seconds=args.clip_duration_seconds,
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
