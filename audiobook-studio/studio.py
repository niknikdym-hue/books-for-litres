#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from workspace_paths import load_workspace_paths

STUDIO_DIR = Path(__file__).resolve().parent
CONFIG_PATH = STUDIO_DIR / "studio-config.json"
WORKSPACE_PATHS = load_workspace_paths()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^0-9a-zа-яё_-]+", "-", value, flags=re.IGNORECASE)
    return value.strip("-") or "render"


def load_config() -> dict[str, Any]:
    cfg = read_json(CONFIG_PATH)
    required = ["model", "default_generation"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"studio-config.json: missing {missing}")
    cfg["workspace_root"] = str(WORKSPACE_PATHS.root)
    cfg["engine_root"] = str(WORKSPACE_PATHS.resolve(cfg.get("engine_root"), "engines/qwen-mlx"))
    cfg["engine_python"] = str(WORKSPACE_PATHS.resolve(cfg.get("engine_python"), "engines/qwen-mlx/.venv/bin/python"))
    cfg["hf_home"] = str(WORKSPACE_PATHS.resolve(cfg.get("hf_home"), "engines/qwen-mlx/hf-cache"))
    cfg["output_root"] = str(WORKSPACE_PATHS.resolve(cfg.get("output_root"), "renders/studio"))
    return cfg


def configure_runtime_env(cfg: dict[str, Any]) -> None:
    os.environ["HF_HOME"] = cfg["hf_home"]
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(Path(cfg["hf_home"]) / "hub")


def list_book_profiles() -> list[Path]:
    books_dir = STUDIO_DIR / "books"
    return sorted(p for p in books_dir.glob("*.json") if p.name != "BOOK-TEMPLATE.json")


def load_book(path: Path) -> dict[str, Any]:
    book = read_json(path)
    if book.get("enabled", True) is not True:
        raise RuntimeError(f"Book profile disabled: {path.name}")
    for key in ["title", "author", "language", "default_speaker", "audiobook_instruct", "jobs"]:
        if key not in book:
            raise RuntimeError(f"{path.name}: missing {key}")
    if not book["jobs"]:
        raise RuntimeError(f"{path.name}: no jobs configured")
    return book


def load_voices() -> list[dict[str, Any]]:
    data = read_json(STUDIO_DIR / "voices.json")
    voices = data.get("voices", [])
    if not voices:
        raise RuntimeError("voices.json contains no voices")
    return voices


def choose(label: str, items: list[str], default_index: int = 0) -> int:
    print(f"\n{label}")
    for i, item in enumerate(items, start=1):
        marker = "  ← по умолчанию" if i - 1 == default_index else ""
        print(f"  {i}. {item}{marker}")
    while True:
        raw = input(f"Выбор [{default_index + 1}]: ").strip()
        if not raw:
            return default_index
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return int(raw) - 1
        print("Введите номер из списка.")


def confirm(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} [д/н]: ").strip().lower()
        if raw in {"д", "да", "y", "yes"}:
            return True
        if raw in {"н", "нет", "n", "no", ""}:
            return False
        print("Ответьте «д» или «н».")


def validate_profile(book: dict[str, Any], voices: list[dict[str, Any]]) -> None:
    allowed = {v["id"] for v in voices}
    if book["default_speaker"] not in allowed:
        raise RuntimeError(f"Unknown default speaker: {book['default_speaker']}")
    if not isinstance(book.get("pronunciation_overrides", {}), dict):
        raise RuntimeError("pronunciation_overrides must be an object")
    for job_id, job in book["jobs"].items():
        segments = job.get("segments", [])
        if not segments:
            raise RuntimeError(f"Job {job_id} has no segments")
        seen = set()
        for seg in segments:
            for key in ["id", "text", "pause_after_ms"]:
                if key not in seg:
                    raise RuntimeError(f"Job {job_id}: segment missing {key}")
            if seg["id"] in seen:
                raise RuntimeError(f"Duplicate segment id: {seg['id']}")
            seen.add(seg["id"])
            if not isinstance(seg["text"], str) or not seg["text"].strip():
                raise RuntimeError(f"Empty text in {seg['id']}")
            if int(seg["pause_after_ms"]) < 0:
                raise RuntimeError(f"Negative pause in {seg['id']}")


def run_check(cfg: dict[str, Any]) -> int:
    print("Audiobook Studio — Qwen backend — проверка")
    print(f"Studio: {STUDIO_DIR}")
    print(f"Workspace: {cfg['workspace_root']}")
    print(f"Machine: {platform.machine()}")
    engine_root = Path(cfg["engine_root"])
    engine_python = Path(cfg["engine_python"])
    hf_home = Path(cfg["hf_home"])
    print(f"Engine root: {'OK' if engine_root.exists() else 'MISSING'} — {engine_root}")
    print(f"Engine Python: {'OK' if engine_python.exists() else 'MISSING'} — {engine_python}")
    print(f"HF cache: {'OK' if hf_home.exists() else 'MISSING'} — {hf_home}")
    print(f"Model: {cfg['model']}")
    profiles = list_book_profiles()
    print(f"Book profiles: {len(profiles)}")
    voices = load_voices()
    for p in profiles:
        try:
            b = load_book(p)
            validate_profile(b, voices)
            print(f"  OK — {b['title']} ({p.name})")
        except Exception as e:
            print(f"  FAIL — {p.name}: {e}")
            return 2
    if platform.machine().lower() != "arm64":
        print("FAIL: expected Apple Silicon arm64")
        return 2
    if not engine_root.exists() or not engine_python.exists() or not hf_home.exists():
        return 2
    print("\nCHECK PASS. Модель не загружалась, генерация не запускалась.")
    return 0


def set_seed(seed: int) -> None:
    import mlx.core as mx
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


def apply_pronunciation_overrides(text: str, overrides: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
    working = text
    applied: list[dict[str, str]] = []
    for source, replacement in overrides.items():
        if source and replacement and source in working:
            working = working.replace(source, replacement)
            applied.append({"source": source, "replacement": replacement})
    return working, applied


def generate_one(model, *, text: str, speaker: str, instruct: str, language: str, gen: dict[str, Any]):
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


def create_unique_output(cfg: dict[str, Any], book: dict[str, Any], job_id: str, speaker: str) -> Path:
    root = Path(cfg["output_root"]).expanduser()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = root / safe_slug(book.get("slug") or book["title"])
    name = f"{stamp}__{safe_slug(job_id)}__{safe_slug(speaker)}"
    out = base / name
    suffix = 2
    while out.exists():
        out = base / f"{name}__{suffix}"
        suffix += 1
    out.mkdir(parents=True, exist_ok=False)
    return out


def run_generation(cfg: dict[str, Any], book_path: Path, book: dict[str, Any], job_id: str, speaker: str) -> Path:
    if platform.machine().lower() != "arm64":
        raise RuntimeError(f"Expected Apple Silicon arm64, got {platform.machine()}")

    configure_runtime_env(cfg)

    import mlx.core as mx
    from mlx_audio.tts.utils import load_model

    job = book["jobs"][job_id]
    generation = dict(cfg["default_generation"])
    generation.update(book.get("generation", {}))
    generation.update(job.get("generation", {}))
    instruct = job.get("audiobook_instruct", book["audiobook_instruct"])
    overrides = dict(book.get("pronunciation_overrides", {}))
    output_dir = create_unique_output(cfg, book, job_id, speaker)
    segment_dir = output_dir / "segments"
    segment_dir.mkdir(exist_ok=False)

    metadata = {
        "studio_version": cfg.get("studio_version", "unknown"),
        "studio_dir": str(STUDIO_DIR),
        "book_profile": str(book_path),
        "book_profile_sha256": sha256_file(book_path),
        "book_title": book["title"],
        "author": book["author"],
        "job": job_id,
        "job_label": job.get("label", job_id),
        "speaker": speaker,
        "model": cfg["model"],
        "language": book["language"],
        "audiobook_instruct": instruct,
        "generation": generation,
        "pronunciation_overrides": overrides,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "segments": [],
    }

    print("\nЗагрузка модели…")
    load_t0 = time.perf_counter()
    model = load_model(cfg["model"])
    metadata["model_load_seconds"] = time.perf_counter() - load_t0
    try:
        metadata["mlx_audio_version"] = importlib.metadata.version("mlx-audio")
    except Exception:
        metadata["mlx_audio_version"] = "unknown"

    assembled: list[np.ndarray] = []
    sr_final: int | None = None
    base_seed = int(job.get("seed", book.get("seed", 20260816)))
    all_t0 = time.perf_counter()

    for idx, seg in enumerate(job["segments"]):
        seg_id = str(seg["id"])
        source_text = seg["text"]
        tts_text, applied = apply_pronunciation_overrides(source_text, overrides)
        seed = base_seed + idx
        set_seed(seed)
        print(f"[{idx + 1}/{len(job['segments'])}] {seg_id}")
        t0 = time.perf_counter()
        audio, sr, peak_gb, model_s, token_count = generate_one(
            model,
            text=tts_text,
            speaker=speaker,
            instruct=instruct,
            language=book["language"],
            gen=generation,
        )
        wall_s = time.perf_counter() - t0
        if sr_final is None:
            sr_final = sr
        elif sr_final != sr:
            raise RuntimeError(f"Sample rate changed {sr_final} -> {sr}")

        audio = edge_fade(audio, sr)
        segment_path = segment_dir / f"{seg_id}.wav"
        write_pcm16_wav(segment_path, audio, sr)
        assembled.append(audio)
        pause_ms = int(seg["pause_after_ms"])
        if pause_ms:
            assembled.append(silence(sr, pause_ms))

        metadata["segments"].append({
            "id": seg_id,
            "seed": seed,
            "pause_after_ms": pause_ms,
            "wall_generation_seconds": wall_s,
            "model_processing_seconds": model_s,
            "audio_seconds": float(audio.size / sr),
            "peak_memory_gb_reported_by_mlx": peak_gb,
            "token_count": token_count,
            "pronunciation_overrides_applied": applied,
            "wav": str(segment_path.name),
        })
        mx.clear_cache()

    if sr_final is None or not assembled:
        raise RuntimeError("No audio produced")

    joined = np.concatenate(assembled).astype(np.float32, copy=False)
    joined_name = f"{safe_slug(book.get('slug') or book['title'])}__{safe_slug(job_id)}__{safe_slug(speaker)}.wav"
    joined_path = output_dir / joined_name
    write_pcm16_wav(joined_path, joined, sr_final)

    metadata["finished_at"] = datetime.now().isoformat(timespec="seconds")
    metadata["total_wall_seconds"] = time.perf_counter() - all_t0
    metadata["sample_rate"] = sr_final
    metadata["joined_audio_seconds"] = float(joined.size / sr_final)
    metadata["joined_wav"] = str(joined_path.name)
    metadata["segment_count"] = len(job["segments"])

    with (output_dir / "RUN-REPORT.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print("\nГОТОВО")
    print(f"WAV: {joined_path}")
    print(f"Отчёт: {output_dir / 'RUN-REPORT.json'}")
    subprocess.run(["open", str(output_dir)], check=False)
    return output_dir


def interactive(cfg: dict[str, Any]) -> int:
    profiles = list_book_profiles()
    if not profiles:
        print("Нет профилей книг в папке books/")
        return 2

    voices = load_voices()
    voice_ids = [v["id"] for v in voices]

    while True:
        books = [load_book(p) for p in profiles]
        labels = [f"{b['title']} — {b['author']}" for b in books] + ["Выход"]
        book_idx = choose("Книга:", labels, 0)
        if book_idx == len(books):
            return 0

        book_path = profiles[book_idx]
        book = books[book_idx]
        validate_profile(book, voices)

        job_ids = list(book["jobs"].keys())
        job_labels = [book["jobs"][j].get("label", j) for j in job_ids]
        job_idx = choose("Что генерировать:", job_labels, 0)
        job_id = job_ids[job_idx]

        default_idx = voice_ids.index(book["default_speaker"])
        voice_labels = [v["id"] + (f" — {v.get('note_ru')}" if v.get("note_ru") else "") for v in voices]
        voice_idx = choose("Диктор:", voice_labels, default_idx)
        speaker = voice_ids[voice_idx]

        job = book["jobs"][job_id]
        print("\nПроверка запуска")
        print(f"  Книга:     {book['title']}")
        print(f"  Режим:     {job.get('label', job_id)}")
        print(f"  Диктор:    {speaker}")
        print(f"  Сегментов: {len(job['segments'])}")
        print("  Старые рендеры: не перезаписываются")
        print("  Мастер книги: не изменяется")
        if not confirm("Запустить генерацию?"):
            continue

        try:
            run_generation(cfg, book_path, book, job_id, speaker)
        except KeyboardInterrupt:
            print("\nОстановлено пользователем.")
        except Exception as e:
            print(f"\nОШИБКА: {type(e).__name__}: {e}")
            print("Существующие рендеры не удалялись.")
        print()
        if not confirm("Вернуться в меню студии?"):
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audiobook Studio — Qwen backend")
    parser.add_argument("--check", action="store_true", help="Проверить студию без загрузки модели")
    args = parser.parse_args()

    try:
        cfg = load_config()
    except Exception as e:
        print(f"CONFIG ERROR: {e}")
        return 2

    if args.check:
        return run_check(cfg)
    return interactive(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
