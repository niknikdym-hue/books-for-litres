#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent


def load_studio_module():
    path = STUDIO_DIR / "studio.py"
    spec = importlib.util.spec_from_file_location("qwen_audiobook_studio_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def notify(title: str, text: str) -> None:
    script = f'display notification {json.dumps(text)} with title {json.dumps(title)}'
    subprocess.run(["/usr/bin/osascript", "-e", script], check=False)


def main() -> int:
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-books", action="store_true")
    mode.add_argument("--list-jobs", action="store_true")
    mode.add_argument("--list-voices", action="store_true")
    mode.add_argument("--default-speaker", action="store_true")
    mode.add_argument("--run", action="store_true")
    p.add_argument("--book", default="")
    p.add_argument("--job", default="")
    p.add_argument("--speaker", default="")
    args = p.parse_args()

    studio = load_studio_module()

    if args.list_books:
        for path in studio.list_book_profiles():
            book = studio.load_book(path)
            print(f"{path.name}\t{book['title']} — {book['author']}")
        return 0

    if args.list_voices:
        for voice in studio.load_voices():
            note = voice.get("note_ru", "")
            print(f"{voice['id']}\t{voice['id']}{' — ' + note if note else ''}")
        return 0

    if not args.book:
        raise RuntimeError("--book is required")

    book_path = studio.BOOK_LIBRARY.resolve_book_profile(args.book)
    book = studio.load_book(args.book)

    if args.list_jobs:
        for job_id, job in book["jobs"].items():
            print(f"{job_id}\t{job.get('label', job_id)}")
        return 0

    if args.default_speaker:
        print(book["default_speaker"])
        return 0

    if args.run:
        if not args.job or not args.speaker:
            raise RuntimeError("--job and --speaker are required for --run")
        if args.job not in book["jobs"]:
            raise RuntimeError("Prepared job not found. Generation was not started.")
        cfg = studio.load_config()
        title = book["title"]
        try:
            out = studio.run_generation(cfg, book_path, book, args.job, args.speaker)
        except Exception as e:
            notify("Audiobook Studio — Qwen — ошибка", f"{title}: {type(e).__name__}: {e}")
            raise
        notify("Audiobook Studio — Qwen", f"Готово: {title}, диктор {args.speaker}")
        print(out)
        return 0

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(2)
