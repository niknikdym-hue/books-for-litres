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


QA_BRIDGE_SCHEMA_VERSION = 1
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
    parser.add_argument("--provider", default="")
    parser.add_argument("--profile-id", default="")
    parser.add_argument("--segment-id", default="")
    parser.add_argument("--audio-path", default="")
    parser.add_argument("--fingerprint", default="")
    parser.add_argument("--expected-sample-rate-hz", type=int, default=0)
    parser.add_argument("--text-characters", type=int, default=-1)
    parser.add_argument("--reviewed-audio-sha256", default="")
    parser.add_argument("--reviewed-path-identity", default="")
    parser.add_argument("--reviewed-fingerprint", default="")
    parser.add_argument(
        "--decision",
        choices=("APPROVED", "REJECTED", "REGENERATE_REQUESTED"),
        default="",
    )
    return parser


def _identity(args: argparse.Namespace) -> dict[str, str]:
    return {
        "provider": _required(args.provider, "--provider"),
        "profile_id": _required(args.profile_id, "--profile-id"),
        "book_slug": _required(args.book, "--book"),
        "job_id": _required(args.job, "--job"),
        "segment_id": _required(args.segment_id, "--segment-id"),
    }


def _current_facts(args: argparse.Namespace) -> dict:
    if args.expected_sample_rate_hz <= 0:
        raise RuntimeError("--expected-sample-rate-hz is required")
    if args.text_characters < 0:
        raise RuntimeError("--text-characters is required")
    return {
        "audio_path": Path(_required(args.audio_path, "--audio-path")),
        "synthesis_fingerprint": _required(args.fingerprint, "--fingerprint"),
        "expected_sample_rate_hz": args.expected_sample_rate_hz,
        "text_characters": args.text_characters,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identity = _identity(args)
    service = _service()
    current = _current_facts(args)

    if args.status:
        result = service.scan(**identity, **current)
        print(json.dumps({
            "schema_version": QA_BRIDGE_SCHEMA_VERSION,
            "record": result,
            "remote_request_sent": False,
        }, ensure_ascii=False, indent=2))
        return 0

    if args.scan:
        result = service.scan(**identity, **current)
    elif args.decide:
        result = service.decide(
            **identity,
            **current,
            decision=_required(args.decision, "--decision"),
            reviewed_identity={
                "audio_sha256": _required(args.reviewed_audio_sha256, "--reviewed-audio-sha256"),
                "path_identity": _required(args.reviewed_path_identity, "--reviewed-path-identity"),
                "synthesis_fingerprint": _required(args.reviewed_fingerprint, "--reviewed-fingerprint"),
            },
        )
    elif args.downstream:
        result = service.downstream_audio(**identity, **current)
        result = {
            "schema_version": QA_BRIDGE_SCHEMA_VERSION,
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
