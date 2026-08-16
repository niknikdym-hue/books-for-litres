#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Book-oriented Qwen3-TTS 0.6B CustomVoice audition through mlx-audio.

The model receives only the clean Russian `text` field plus a separate control
`instruct`. It never sees pause metadata, JSON keys, SSML or stress markup.
Pauses and joins are rendered outside the model.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import time
import wave
from pathlib import Path

import mlx.core as mx
import numpy as np

from mlx_audio.tts.utils import load_model


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--script", type=Path, required=True)
    p.add_argument(
        "--stage",
        choices=["stage_a_all_voices", "stage_b_finalists"],
        default="stage_a_all_voices",
    )
    p.add_argument("--speakers", default="")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Generate only a01 with Serena. Must pass before full Stage A.",
    )
    return p.parse_args()


def load_script(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    rules = cfg.get("rules", {})
    if rules.get("tts_receives_only_text_field_as_spoken_text") is not True:
        raise RuntimeError("Safety rule missing: only text field may be spoken")
    if rules.get("instruct_is_control_only_not_spoken") is not True:
        raise RuntimeError("Safety rule missing: instruct must remain control-only")
    if rules.get("voice_cloning") is not False:
        raise RuntimeError("Voice cloning is forbidden")
    if rules.get("ssml") is not False:
        raise RuntimeError("SSML is forbidden")
    return cfg


def resolve_speakers(cfg: dict, stage: str, raw: str, smoke: bool) -> list[str]:
    allowed = list(cfg["speakers"])
    if smoke:
        return ["Serena"]
    requested = [x.strip() for x in raw.split(",") if x.strip()]
    if stage == "stage_b_finalists":
        if not requested or len(requested) > 2:
            raise SystemExit("Stage B requires exactly 1 or 2 --speakers finalists")
        speakers = requested
    else:
        speakers = requested or allowed
    bad = [s for s in speakers if s not in allowed]
    if bad:
        raise SystemExit(f"Unknown speaker(s): {bad}")
    return speakers


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    mx.random.seed(seed)


def edge_fade(audio: np.ndarray, sr: int, fade_ms: float = 8.0) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).squeeze()
    if audio.ndim != 1 or audio.size == 0:
        raise ValueError(f"Invalid mono waveform shape={audio.shape}")
    n = min(int(round(sr * fade_ms / 1000.0)), audio.size // 4)
    if n <= 1:
        return audio
    out = audio.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def silence(sr: int, ms: int) -> np.ndarray:
    return np.zeros(int(round(sr * max(ms, 0) / 1000.0)), dtype=np.float32)


def write_pcm16_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    audio = np.asarray(audio, dtype=np.float32).squeeze()
    if audio.ndim != 1 or audio.size == 0:
        raise ValueError(f"Cannot write invalid waveform shape={audio.shape}")
    if not np.isfinite(audio).all():
        raise ValueError("Waveform contains NaN/Inf")
    pcm = np.round(np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())


def safe_name(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


def generate_one(model, *, text: str, speaker: str, instruct: str, language: str, gen: dict):
    results = list(
        model.generate(
            text=text,
            voice=speaker,
            instruct=instruct,
            lang_code=language,
            temperature=float(gen["temperature"]),
            top_k=int(gen["top_k"]),
            top_p=float(gen["top_p"]),
            repetition_penalty=float(gen["repetition_penalty"]),
            max_tokens=int(gen["max_tokens"]),
            stream=False,
            verbose=False,
        )
    )
    if not results:
        raise RuntimeError("mlx-audio returned no GenerationResult")

    sr = int(results[0].sample_rate)
    chunks: list[np.ndarray] = []
    peak_memory_gb = 0.0
    processing_seconds = 0.0
    token_count = 0

    for result in results:
        if int(result.sample_rate) != sr:
            raise RuntimeError("Sample rate changed within one segment")
        arr = np.asarray(result.audio, dtype=np.float32).squeeze()
        if arr.ndim != 1 or arr.size == 0 or not np.isfinite(arr).all():
            raise RuntimeError(f"Invalid generated audio shape={arr.shape}")
        chunks.append(arr)
        peak_memory_gb = max(peak_memory_gb, float(getattr(result, "peak_memory_usage", 0.0) or 0.0))
        processing_seconds += float(getattr(result, "processing_time_seconds", 0.0) or 0.0)
        token_count += int(getattr(result, "token_count", 0) or 0)

    return np.concatenate(chunks).astype(np.float32, copy=False), sr, peak_memory_gb, processing_seconds, token_count


def main() -> None:
    args = parse_args()
    cfg = load_script(args.script)

    if platform.machine().lower() != "arm64":
        raise SystemExit(f"STOP: expected Apple Silicon arm64, got {platform.machine()}")
    if args.output_dir.exists():
        raise SystemExit(f"STOP: output directory already exists: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    stage = cfg[args.stage]
    segments = stage["segments"][:1] if args.smoke else stage["segments"]
    speakers = resolve_speakers(cfg, args.stage, args.speakers, args.smoke)
    instruct = cfg["audiobook_instruct"]
    generation = cfg["generation"]

    print(f"MODEL={cfg['model']}")
    print(f"BACKEND={cfg['backend']}")
    print(f"MACHINE={platform.machine()}")
    print(f"STAGE={'SMOKE' if args.smoke else args.stage}")
    print(f"SPEAKERS={speakers}")
    print("VOICE_CLONING=NO")
    print("SSML=NO")
    print("INSTRUCT_CONTROL=YES")

    load_t0 = time.perf_counter()
    model = load_model(cfg["model"])
    load_seconds = time.perf_counter() - load_t0

    try:
        mlx_audio_version = importlib.metadata.version("mlx-audio")
    except Exception:
        mlx_audio_version = "unknown"

    model_type = getattr(getattr(model, "config", None), "tts_model_type", None)
    model_size = getattr(getattr(model, "config", None), "tts_model_size", None)
    if model_type not in (None, "custom_voice"):
        raise RuntimeError(f"Wrong model type loaded: {model_type}")

    print(f"MLX_AUDIO_VERSION={mlx_audio_version}")
    print(f"MODEL_LOAD_SECONDS={load_seconds:.2f}")
    print(f"MODEL_TYPE={model_type}")
    print(f"MODEL_SIZE={model_size}")

    report = {
        "model": cfg["model"],
        "backend": cfg["backend"],
        "mlx_audio_version": mlx_audio_version,
        "machine": platform.machine(),
        "stage": "smoke" if args.smoke else args.stage,
        "language": cfg["language"],
        "instruct": instruct,
        "generation": generation,
        "model_load_seconds": load_seconds,
        "voice_cloning": False,
        "ssml": False,
        "speakers": {},
    }

    base_seed = int(stage["seed"])

    for speaker in speakers:
        speaker_dir = args.output_dir / safe_name(speaker)
        speaker_dir.mkdir(parents=True, exist_ok=False)
        assembled: list[np.ndarray] = []
        sr_final: int | None = None
        speaker_report = {"segments": []}
        speaker_t0 = time.perf_counter()

        print(f"\n=== {speaker} ===")
        for idx, seg in enumerate(segments):
            seg_id = seg["id"]
            seed = base_seed + idx
            set_seed(seed)
            t0 = time.perf_counter()

            audio, sr, peak_gb, model_processing_s, token_count = generate_one(
                model,
                text=seg["text"],
                speaker=speaker,
                instruct=instruct,
                language=cfg["language"],
                gen=generation,
            )
            wall_seconds = time.perf_counter() - t0

            if sr_final is None:
                sr_final = sr
            elif sr_final != sr:
                raise RuntimeError(f"{speaker}: sample rate changed {sr_final} -> {sr}")

            audio = edge_fade(audio, sr)
            segment_path = speaker_dir / f"{seg_id}.wav"
            write_pcm16_wav(segment_path, audio, sr)

            assembled.append(audio)
            pause_ms = int(seg["pause_after_ms"])
            if pause_ms > 0:
                assembled.append(silence(sr, pause_ms))

            speaker_report["segments"].append(
                {
                    "id": seg_id,
                    "seed": seed,
                    "pause_after_ms": pause_ms,
                    "wall_generation_seconds": wall_seconds,
                    "model_processing_seconds": model_processing_s,
                    "audio_seconds": float(audio.size / sr),
                    "peak_memory_gb_reported_by_mlx": peak_gb,
                    "token_count": token_count,
                    "wav": segment_path.name,
                }
            )
            print(
                f"{seg_id}: wall={wall_seconds:.2f}s audio={audio.size/sr:.2f}s "
                f"peak_mlx={peak_gb:.3f}GB pause={pause_ms}ms"
            )
            mx.clear_cache()

        if sr_final is None or not assembled:
            raise RuntimeError(f"{speaker}: no audio produced")

        joined = np.concatenate(assembled).astype(np.float32, copy=False)
        joined_path = args.output_dir / f"BOOK-AUDITION-MLX-{safe_name(speaker)}.wav"
        write_pcm16_wav(joined_path, joined, sr_final)

        speaker_report["joined_wav"] = joined_path.name
        speaker_report["joined_audio_seconds"] = float(joined.size / sr_final)
        speaker_report["total_wall_seconds"] = time.perf_counter() - speaker_t0
        report["speakers"][speaker] = speaker_report
        print(f"JOINED={joined_path.name} duration={joined.size/sr_final:.2f}s")
        mx.clear_cache()

    report_path = args.output_dir / "RUN-REPORT.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nDONE REPORT={report_path}")


if __name__ == "__main__":
    main()
