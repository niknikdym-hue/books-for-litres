#!/usr/bin/env python3
"""Explicit local Qwen chapter segment-production runner with persistent Resume state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from qwen_chapter_execution import QwenChapterExecutionService
from qwen_chapter_manifest import QwenChapterManifestService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audiobook Studio — Qwen chapter production")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--book", default="")
    parser.add_argument("--job", default="")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--segment-id", default="")
    return parser


def _require(value: str, option: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise RuntimeError(f"{option} is required")
    return value


def _profile_id(speaker: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "_" for character in speaker).strip("_")
    if not normalized:
        raise RuntimeError("--speaker is invalid")
    return f"qwen_{normalized}"


def _runtime_facts(book_name: str, job_id: str, speaker: str) -> tuple[Any, dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    # Import the existing Qwen runtime lazily. PREPARE/STATUS use only config/book
    # facts and never load MLX or the model.
    import studio

    cfg = studio.load_config()
    book_path = studio.BOOK_LIBRARY.resolve_book_profile(book_name)
    book = studio.load_book(book_path)
    job = (book.get("jobs") or {}).get(job_id)
    if not isinstance(job, dict) or job.get("kind") != "chapter":
        raise RuntimeError("Prepared Qwen chapter job not found")
    available = {str(item.get("id")) for item in studio.load_voices() if isinstance(item, dict)}
    if speaker not in available:
        raise RuntimeError(f"Unknown Qwen speaker: {speaker}")
    generation = dict(cfg["default_generation"])
    generation.update(book.get("generation", {}))
    generation.update(job.get("generation", {}))
    instruct = str(job.get("audiobook_instruct", book["audiobook_instruct"]))
    overrides = dict(book.get("pronunciation_overrides", {}))
    base_seed = int(job.get("seed", book.get("seed", 20260816)))
    identity = {
        "studio_version": str(cfg.get("studio_version", "unknown")),
        "model": str(cfg["model"]),
        "speaker": speaker,
        "language": str(book["language"]),
        "instruct": instruct,
        "generation": generation,
        "pronunciation_overrides": overrides,
        "base_seed": base_seed,
    }
    return studio, cfg, book, str(book_path.name), identity


def _manifest_service(studio_module: Any, cfg: Mapping[str, Any]) -> QwenChapterManifestService:
    return QwenChapterManifestService(
        library=studio_module.BOOK_LIBRARY,
        output_root=Path(cfg["output_root"]),
    )


def _build_synthesizer(studio_module: Any, cfg: Mapping[str, Any], book: Mapping[str, Any], identity: Mapping[str, Any]):
    model_box: dict[str, Any] = {}

    def synthesize_segment(*, text: str, output_path: Path, seed: int, segment_id: str) -> None:
        if "model" not in model_box:
            if studio_module.platform.machine().lower() != "arm64":
                raise RuntimeError(f"Expected Apple Silicon arm64, got {studio_module.platform.machine()}")
            studio_module.configure_runtime_env(dict(cfg))
            from mlx_audio.tts.utils import load_model
            model_box["model"] = load_model(str(identity["model"]))
        studio_module.set_seed(seed)
        tts_text, _ = studio_module.apply_pronunciation_overrides(
            text,
            dict(identity["pronunciation_overrides"]),
        )
        audio, sample_rate, *_ = studio_module.generate_one(
            model_box["model"],
            text=tts_text,
            speaker=str(identity["speaker"]),
            instruct=str(identity["instruct"]),
            language=str(identity["language"]),
            gen=dict(identity["generation"]),
        )
        audio = studio_module.edge_fade(audio, sample_rate)
        studio_module.write_pcm16_wav(output_path, audio, sample_rate)
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass

    return synthesize_segment


def main(argv: Sequence[str] | None = None, *, runtime_factory=_runtime_facts) -> int:
    args = build_parser().parse_args(argv)
    book = _require(args.book, "--book")
    job = _require(args.job, "--job")
    speaker = _require(args.speaker, "--speaker")
    profile_id = _profile_id(speaker)
    studio_module, cfg, book_payload, _, identity = runtime_factory(book, job, speaker)
    manifest = _manifest_service(studio_module, cfg)
    common = {
        "book_id": book,
        "job_id": job,
        "profile_id": profile_id,
        "synthesis_identity": identity,
    }
    if args.prepare:
        result = manifest.prepare(**common)
    elif args.status:
        result = manifest.status(**common)
    elif args.retry_failed:
        result = manifest.retry_failed(
            **common,
            segment_id=_require(args.segment_id, "--segment-id"),
        )
    else:
        service = QwenChapterExecutionService(
            library=studio_module.BOOK_LIBRARY,
            manifest=manifest,
            synthesize_segment=_build_synthesizer(studio_module, cfg, book_payload, identity),
        )
        result = service.run(**common)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({
            "error": type(error).__name__,
            "message": str(error),
            "remote_request_sent": False,
        }, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
