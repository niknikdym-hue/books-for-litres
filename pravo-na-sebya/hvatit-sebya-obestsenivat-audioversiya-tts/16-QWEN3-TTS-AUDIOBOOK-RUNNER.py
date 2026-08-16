#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Production-oriented short audiobook audition for Qwen3-TTS 0.6B CustomVoice.

Qwen receives ONLY the clean Russian text from the JSON script.
All pauses, joins and bookkeeping are handled outside the model.
No SSML. No voice cloning. No unsupported stress markup. No style instruct for 0.6B.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from qwen_tts import Qwen3TTSModel


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--script", type=Path, required=True)
    p.add_argument(
        "--stage",
        choices=["stage_a_all_voices", "stage_b_finalists"],
        default="stage_a_all_voices",
    )
    p.add_argument(
        "--speakers",
        default="",
        help="Comma-separated speaker names. Required for stage_b_finalists; optional for stage_a_all_voices.",
    )
    p.add_argument("--output-dir", type=Path, required=True)
    return p.parse_args()


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if hasattr(torch, "mps"):
        try:
            torch.mps.manual_seed(seed)
        except Exception:
            pass


def apply_edge_fade(wav: np.ndarray, sr: int, fade_ms: float = 8.0) -> np.ndarray:
    """Tiny linear edge fade to prevent clicks when joining independently generated segments."""
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    if wav.ndim != 1:
        raise ValueError(f"Expected mono waveform, got shape={wav.shape}")
    n = int(sr * fade_ms / 1000.0)
    n = min(n, max(0, len(wav) // 4))
    if n <= 1:
        return wav
    out = wav.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def digital_silence(sr: int, ms: int) -> np.ndarray:
    n = int(round(sr * max(ms, 0) / 1000.0))
    return np.zeros(n, dtype=np.float32)


def safe_name(name: str) -> str:
    return name.replace("/", "_").replace(" ", "_")


def load_script(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("rules", {}).get("tts_receives_only_text") is not True:
        raise RuntimeError("Script safety rule missing: tts_receives_only_text=true")
    if cfg.get("rules", {}).get("voice_cloning") is not False:
        raise RuntimeError("This runner forbids voice cloning")
    if cfg.get("rules", {}).get("ssml") is not False:
        raise RuntimeError("This runner forbids SSML")
    if cfg.get("rules", {}).get("instruct", "NOT_NULL") is not None:
        raise RuntimeError("0.6B CustomVoice must run with instruct=None")
    return cfg


def resolve_speakers(cfg: dict, stage: str, raw: str) -> list[str]:
    supported = list(cfg["speakers"])
    requested = [x.strip() for x in raw.split(",") if x.strip()]

    if stage == "stage_b_finalists":
        if not requested:
            raise SystemExit("stage_b_finalists requires --speakers with 1 or 2 selected finalists")
        if len(requested) > 2:
            raise SystemExit("stage_b_finalists accepts at most 2 speakers")
        speakers = requested
    elif requested:
        speakers = requested
    else:
        # Serena first = technical smoke. If it fails, do not waste time on the other eight.
        speakers = ["Serena"] + [s for s in supported if s != "Serena"]

    bad = [s for s in speakers if s not in supported]
    if bad:
        raise SystemExit(f"Unknown speakers in script: {bad}")
    return speakers


def main() -> None:
    args = parse_args()
    cfg = load_script(args.script)
    stage_cfg = cfg[args.stage]
    segments = stage_cfg["segments"]
    speakers = resolve_speakers(cfg, args.stage, args.speakers)

    if not (torch.backends.mps.is_built() and torch.backends.mps.is_available()):
        raise SystemExit("STOP: Apple MPS is not available. Do not silently fall back to CPU.")

    args.output_dir.mkdir(parents=True, exist_ok=False)

    model_id = cfg["model"]
    language = cfg["language"]

    print(f"MODEL={model_id}")
    print("DEVICE=mps")
    print("DTYPE=float16")
    print(f"STAGE={args.stage}")
    print(f"SPEAKERS={speakers}")

    load_t0 = time.perf_counter()
    tts = Qwen3TTSModel.from_pretrained(
        model_id,
        device_map="mps",
        dtype=torch.float16,
        attn_implementation=None,
    )
    load_seconds = time.perf_counter() - load_t0
    print(f"MODEL_LOAD_SECONDS={load_seconds:.2f}")

    actual_speakers = tts.get_supported_speakers()
    actual_languages = tts.get_supported_languages()
    print(f"MODEL_SUPPORTED_SPEAKERS={actual_speakers}")
    print(f"MODEL_SUPPORTED_LANGUAGES={actual_languages}")

    report = {
        "model": model_id,
        "stage": args.stage,
        "language": language,
        "device": "mps",
        "dtype": "float16",
        "model_load_seconds": load_seconds,
        "generation_policy": "official model defaults; no manual temperature/top-k/top-p tuning",
        "instruct": None,
        "voice_cloning": False,
        "ssml": False,
        "speakers": {},
    }

    base_seed = int(stage_cfg["seed"])

    for speaker_index, speaker in enumerate(speakers):
        spk_dir = args.output_dir / safe_name(speaker)
        spk_dir.mkdir(parents=True, exist_ok=False)
        assembled: list[np.ndarray] = []
        sample_rate: int | None = None
        spk_report = {"segments": [], "joined_wav": None}
        speaker_t0 = time.perf_counter()

        print(f"\n=== SPEAKER {speaker} ===")

        for segment_index, seg in enumerate(segments):
            seg_id = seg["id"]
            text = seg["text"]
            pause_ms = int(seg["pause_after_ms"])

            # Same segment gets the same sampling seed for every speaker.
            segment_seed = base_seed + segment_index
            set_seed(segment_seed)

            t0 = time.perf_counter()
            wavs, sr = tts.generate_custom_voice(
                text=text,
                language=language,
                speaker=speaker,
                instruct=None,
            )
            elapsed = time.perf_counter() - t0

            if len(wavs) != 1:
                raise RuntimeError(f"{speaker}/{seg_id}: expected one waveform, got {len(wavs)}")

            wav = np.asarray(wavs[0], dtype=np.float32).squeeze()
            if wav.ndim != 1 or len(wav) == 0:
                raise RuntimeError(f"{speaker}/{seg_id}: invalid waveform shape={wav.shape}")
            if not np.isfinite(wav).all():
                raise RuntimeError(f"{speaker}/{seg_id}: waveform contains NaN/Inf")

            sr = int(sr)
            if sample_rate is None:
                sample_rate = sr
            elif sr != sample_rate:
                raise RuntimeError(f"{speaker}: sample rate changed {sample_rate} -> {sr}")

            wav = apply_edge_fade(wav, sr, fade_ms=8.0)
            seg_path = spk_dir / f"{seg_id}.wav"
            sf.write(seg_path, wav, sr, subtype="PCM_16")

            assembled.append(wav)
            if pause_ms > 0:
                assembled.append(digital_silence(sr, pause_ms))

            duration = len(wav) / sr
            spk_report["segments"].append(
                {
                    "id": seg_id,
                    "seed": segment_seed,
                    "pause_after_ms": pause_ms,
                    "generation_seconds": elapsed,
                    "audio_seconds": duration,
                    "wav": str(seg_path.name),
                }
            )
            print(
                f"{seg_id}: gen={elapsed:.2f}s audio={duration:.2f}s pause={pause_ms}ms"
            )

        if sample_rate is None:
            raise RuntimeError(f"{speaker}: no audio generated")

        joined = np.concatenate(assembled).astype(np.float32, copy=False)
        joined_path = args.output_dir / f"BOOK-AUDITION-{safe_name(speaker)}.wav"
        sf.write(joined_path, joined, sample_rate, subtype="PCM_16")

        total_elapsed = time.perf_counter() - speaker_t0
        spk_report["joined_wav"] = joined_path.name
        spk_report["joined_audio_seconds"] = len(joined) / sample_rate
        spk_report["total_generation_seconds"] = total_elapsed
        report["speakers"][speaker] = spk_report

        print(
            f"JOINED={joined_path.name} audio={len(joined)/sample_rate:.2f}s total_gen={total_elapsed:.2f}s"
        )

        del joined, assembled
        gc.collect()
        try:
            torch.mps.empty_cache()
        except Exception:
            pass

        # Stage A smoke gate: if Serena itself failed, execution would already have stopped.

    report_path = args.output_dir / "RUN-REPORT.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nDONE. REPORT={report_path}")


if __name__ == "__main__":
    main()
