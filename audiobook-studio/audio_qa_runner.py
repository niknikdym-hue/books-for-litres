#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Offline bridge for provider-neutral Audiobook Studio audio QA/review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from audio_qa_review import AudioQAReviewService
from workspace_paths import load_workspace_paths


WORKSPACE_PATHS = load_workspace_paths()


def _service() -> AudioQAReviewService:
    return AudioQAReviewService(WORKSPACE_PATHS.qa_review_root)


def _required(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio offline audio QA bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--decide", action="store_true")
    mode.add_argument("--downstream", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--segment-id", default="")
    parser.add_argument("--audio-path", default="")
    parser.add_argument("--fingerprint", default="")
    parser.add_argument(
        "--decision",
        choices=("APPROVED", "REJECTED", "REGENERATE_REQUESTED"),
        default="",
    )
    return parser


def _identity(args: argparse.Namespace) -> dict[str, str]:
    return {
        "book_slug": _required(args.book, "--book"),
        "job_id": _required(args.job, "--job"),
        "segment_id": _required(args.segment_id, "--segment-id"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identity = _identity(args)
    service = _service()

    if args.status:
        result = service.status(**identity)
        print(json.dumps({
            "schema_version": 1,
            "record": result,
            "remote_request_sent": False,
        }, ensure_ascii=False, indent=2))
        return 0

    audio_path = Path(_required(args.audio_path, "--audio-path"))
    fingerprint = args.fingerprint or None
    if args.scan:
        result = service.scan(
            **identity,
            audio_path=audio_path,
            synthesis_fingerprint=fingerprint,
        )
    elif args.decide:
        result = service.decide(
            **identity,
            audio_path=audio_path,
            synthesis_fingerprint=fingerprint,
            decision=_required(args.decision, "--decision"),
        )
    elif args.downstream:
        result = service.downstream_audio(
            **identity,
            audio_path=audio_path,
            synthesis_fingerprint=fingerprint,
        )
        result = {
            "schema_version": 1,
            "eligible": result is not None,
            "record": result,
            "remote_request_sent": False,
        }
    else:
        raise RuntimeError("Unsupported QA bridge mode")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
