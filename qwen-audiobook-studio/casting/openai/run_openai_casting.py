#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any, Callable, Mapping


MAX_CASTING_COST_USD = Decimal("1.00")
MAX_REQUESTS = 13
EXPECTED_VOICES = [
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
]
EXPECTED_ENDPOINT = "https://api.openai.com/v1/audio/speech"
EXPECTED_MODEL = "gpt-4o-mini-tts"
EXPECTED_FORMAT = "wav"


class CastingError(RuntimeError):
    pass


class ConfigError(CastingError):
    pass


class BudgetError(CastingError):
    pass


class CredentialError(CastingError):
    pass


class RetryableRequestError(CastingError):
    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


class AmbiguousRequestError(CastingError):
    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


@dataclass(frozen=True)
class Credential:
    value: str
    source_type: str


@dataclass
class AttemptLedger:
    max_attempts: int
    max_cost_usd: Decimal
    reservation_per_attempt_usd: Decimal
    attempts: int = 0

    @property
    def remaining(self) -> int:
        return self.max_attempts - self.attempts

    @property
    def reserved_cost_usd(self) -> Decimal:
        return self.reservation_per_attempt_usd * self.attempts

    def claim(self) -> int:
        next_attempt = self.attempts + 1
        if next_attempt > self.max_attempts:
            raise BudgetError(f"Network request cap reached ({self.max_attempts}).")
        next_reserved = self.reservation_per_attempt_usd * next_attempt
        if next_reserved > self.max_cost_usd:
            raise BudgetError(
                f"Casting budget cap would be exceeded: {next_reserved} > {self.max_cost_usd} USD."
            )
        self.attempts = next_attempt
        return next_attempt


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decimal_string(value: Decimal, places: str = "0.000001") -> str:
    return str(value.quantize(Decimal(places)))


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ConfigError("Casting config must be a JSON object.")
    return data


def load_and_validate(config_path: Path) -> tuple[dict[str, Any], str, Path]:
    config = load_config(config_path)
    validate_config(config)
    text_path = (config_path.parent / str(config["casting_text"])).resolve()
    text_bytes = text_path.read_bytes()
    actual_hash = sha256_bytes(text_bytes)
    if actual_hash != config["text_sha256"]:
        raise ConfigError(
            f"Casting text SHA-256 mismatch: expected {config['text_sha256']}, got {actual_hash}."
        )
    text = text_bytes.decode("utf-8")
    if not text.strip() or "\n\n" not in text:
        raise ConfigError("Casting text is empty or paragraph breaks are missing.")
    return config, text, text_path


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("provider") != "openai" or config.get("stage") != "OAI-1":
        raise ConfigError("Only the OpenAI Stage OAI-1 casting config is allowed.")
    if config.get("endpoint") != EXPECTED_ENDPOINT:
        raise ConfigError(f"Unexpected endpoint: {config.get('endpoint')!r}.")
    if config.get("model") != EXPECTED_MODEL:
        raise ConfigError(f"Unexpected model: {config.get('model')!r}.")
    if config.get("response_format") != EXPECTED_FORMAT:
        raise ConfigError("Casting output must be WAV.")
    if config.get("voices") != EXPECTED_VOICES:
        raise ConfigError("Voice list or ordering differs from the approved 13-voice casting set.")
    instructions = config.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ConfigError("A single non-empty instruction preset is required.")

    budget = config.get("budget") or {}
    retry = config.get("retry_policy") or {}
    max_cost = Decimal(str(budget.get("max_casting_cost_usd")))
    max_requests = int(budget.get("max_requests", 0))
    max_total_attempts = int(retry.get("max_total_network_attempts", 0))
    if max_cost != MAX_CASTING_COST_USD:
        raise ConfigError("MAX_CASTING_COST_USD must be exactly 1.00 USD.")
    if max_requests != MAX_REQUESTS or max_total_attempts != MAX_REQUESTS:
        raise ConfigError("Both request caps must be exactly 13.")
    if int(retry.get("max_retries_per_voice", -1)) != 1:
        raise ConfigError("Retry policy must allow at most one retry per voice.")
    if retry.get("ambiguous_requests_are_never_retried") is not True:
        raise ConfigError("Ambiguous-request protection must be enabled.")

    reservation = Decimal(str(budget.get("reservation_per_network_attempt_usd")))
    if reservation <= 0 or reservation * MAX_REQUESTS > MAX_CASTING_COST_USD:
        raise ConfigError("Request reservations exceed the casting hard cap.")


def build_payload(config: Mapping[str, Any], text: str, voice: str) -> dict[str, str]:
    if voice not in EXPECTED_VOICES:
        raise ConfigError(f"Unknown casting voice: {voice}.")
    return {
        "model": str(config["model"]),
        "voice": voice,
        "input": text,
        "instructions": str(config["instructions"]),
        "response_format": str(config["response_format"]),
    }


def build_cost_plan(config: Mapping[str, Any], text: str) -> dict[str, Any]:
    pricing = config["pricing"]
    budget = config["budget"]
    voice_count = len(config["voices"])
    input_token_upper_bound = len(text) + len(str(config["instructions"]))
    audio_tokens_per_minute = Decimal(str(pricing["estimated_audio_tokens_per_minute"]))
    seconds = Decimal(str(budget["estimated_duration_seconds_per_voice"]))
    audio_token_estimate = (audio_tokens_per_minute * seconds / Decimal(60)).to_integral_value(
        rounding=ROUND_CEILING
    )
    input_per_million = Decimal(str(pricing["text_input_per_million_tokens"]))
    audio_per_million = Decimal(str(pricing["audio_output_per_million_tokens"]))
    input_cost_per_voice = Decimal(input_token_upper_bound) * input_per_million / Decimal(1_000_000)
    audio_cost_per_voice = audio_token_estimate * audio_per_million / Decimal(1_000_000)
    estimated_per_voice = input_cost_per_voice + audio_cost_per_voice
    estimated_total = estimated_per_voice * voice_count
    reservation = Decimal(str(budget["reservation_per_network_attempt_usd"]))
    reserved_total = reservation * voice_count
    hard_cap = Decimal(str(budget["max_casting_cost_usd"]))
    allowed = (
        voice_count == MAX_REQUESTS
        and estimated_total < hard_cap
        and reserved_total <= hard_cap
    )
    return {
        "planned_requests": voice_count,
        "max_network_attempts": int(config["retry_policy"]["max_total_network_attempts"]),
        "input_token_upper_bound_per_voice": input_token_upper_bound,
        "estimated_audio_tokens_per_voice": int(audio_token_estimate),
        "estimated_duration_seconds_per_voice": int(seconds),
        "estimated_cost_per_voice_usd": decimal_string(estimated_per_voice),
        "estimated_total_cost_usd": decimal_string(estimated_total),
        "reserved_total_cost_usd": decimal_string(reserved_total),
        "hard_cap_usd": decimal_string(hard_cap, "0.00"),
        "allowed_to_start": allowed,
        "actual_known_cost_usd": None,
        "actual_known_cost_note": "The audio/speech response does not provide guaranteed per-request token usage.",
    }


def validate_api_key(value: str) -> None:
    if not value or len(value) < 20:
        raise CredentialError("OpenAI API credential is absent or unexpectedly short.")
    if value != value.strip() or any(character.isspace() for character in value):
        raise CredentialError("OpenAI API credential contains whitespace.")


def read_credential(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> Credential:
    env = os.environ if env is None else env
    credential_config = config["credential"]
    variable = str(credential_config["environment_variable"])
    environment_value = env.get(variable, "")
    if environment_value:
        validate_api_key(environment_value)
        return Credential(environment_value, "environment")

    service = str(credential_config["keychain_service"])
    account = str(credential_config.get("keychain_account") or "")
    if not account:
        try:
            account = subprocess.check_output(["/usr/bin/id", "-un"], text=True).strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise CredentialError("Unable to determine the macOS Keychain account.") from error
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", account, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise CredentialError("macOS Keychain utility is unavailable.") from error
    if result.returncode != 0 or not result.stdout.strip():
        raise CredentialError(
            f"No OpenAI credential found in {variable} or macOS Keychain service {service}."
        )
    key = result.stdout.strip()
    validate_api_key(key)
    return Credential(key, "macos_keychain")


def request_id_from_headers(headers: Any) -> str | None:
    for name in ("x-request-id", "request-id", "openai-request-id"):
        value = headers.get(name) if headers is not None else None
        if value:
            return str(value)
    return None


def perform_speech_request(
    endpoint: str,
    payload: Mapping[str, str],
    api_key: str,
    timeout_seconds: int,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[bytes, str | None]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        },
    )
    try:
        response = opener(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
        request_id = request_id_from_headers(error.headers)
        if error.code == 429 or 500 <= error.code <= 599:
            raise RetryableRequestError(f"Retryable HTTP {error.code}.", request_id=request_id) from error
        raise CastingError(f"Non-retryable HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, (socket.gaierror, ConnectionRefusedError)):
            raise RetryableRequestError("Pre-connect transport failure; no response was received.") from error
        raise AmbiguousRequestError("Transport state is ambiguous; automatic retry is forbidden.") from error
    except (TimeoutError, socket.timeout) as error:
        raise AmbiguousRequestError("Request timed out in an ambiguous state; retry is forbidden.") from error

    request_id = request_id_from_headers(getattr(response, "headers", None))
    try:
        status = int(getattr(response, "status", 200))
        if status < 200 or status >= 300:
            raise CastingError(f"Unexpected HTTP status {status}.")
        audio = response.read()
    except (TimeoutError, socket.timeout, OSError) as error:
        raise AmbiguousRequestError(
            "The server accepted the request but the audio response was interrupted; retry is forbidden.",
            request_id=request_id,
        ) from error
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return audio, request_id


def validate_wav_bytes(data: bytes, duration_config: Mapping[str, Any]) -> dict[str, Any]:
    if len(data) <= 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise CastingError("Response is not a non-empty RIFF/WAVE file.")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            compression_type = wav.getcomptype()
    except (wave.Error, EOFError) as error:
        raise CastingError("WAV parser rejected the response.") from error
    if sample_rate <= 0 or channels <= 0 or sample_width <= 0 or frames <= 0:
        raise CastingError("WAV contains invalid or empty audio properties.")
    duration = frames / sample_rate
    if duration <= 0:
        raise CastingError("WAV duration is zero.")
    needs_review = (
        duration < float(duration_config["needs_review_below_seconds"])
        or duration > float(duration_config["needs_review_above_seconds"])
    )
    return {
        "valid": True,
        "parser": "python-wave",
        "container": "RIFF/WAVE",
        "duration_seconds": round(duration, 3),
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "compression_type": compression_type,
        "expected_duration_seconds": [
            duration_config["expected_min_seconds"],
            duration_config["expected_max_seconds"],
        ],
        "needs_review": needs_review,
    }


def write_validated_wav(
    output_path: Path,
    data: bytes,
    duration_config: Mapping[str, Any],
) -> dict[str, Any]:
    validation = validate_wav_bytes(data, duration_config)
    part_path = output_path.with_suffix(output_path.suffix + ".part")
    try:
        part_path.write_bytes(data)
        os.replace(part_path, output_path)
    finally:
        if part_path.exists():
            part_path.unlink()
    validation["size_bytes"] = output_path.stat().st_size
    validation["sha256"] = sha256_bytes(data)
    return validation


def can_retry(
    error: BaseException,
    *,
    retries_used: int,
    max_retries_per_voice: int,
    ledger_remaining: int,
    unattempted_voices: int,
) -> bool:
    if isinstance(error, AmbiguousRequestError):
        return False
    return (
        isinstance(error, RetryableRequestError)
        and retries_used < max_retries_per_voice
        and ledger_remaining > unattempted_voices
    )


def initial_manifest(
    config: Mapping[str, Any],
    text_path: Path,
    output_dir: Path,
    credential_source_type: str,
    cost_plan: Mapping[str, Any],
) -> dict[str, Any]:
    samples = []
    for index, voice in enumerate(config["voices"], start=1):
        samples.append(
            {
                "ordinal": index,
                "voice": voice,
                "status": "PENDING",
                "success": False,
                "output_filename": f"{index:02d}-{voice}.wav",
                "attempts": [],
                "retry_count": 0,
                "request_started_at": None,
                "request_completed_at": None,
                "request_id": None,
                "size_bytes": None,
                "wav_validation": None,
                "sha256": None,
                "usage_metadata": None,
                "estimated_cost_usd": None,
                "error": None,
            }
        )
    return {
        "schema_version": 1,
        "stage": config["stage"],
        "provider": config["provider"],
        "model": config["model"],
        "endpoint": config["endpoint"],
        "voices": list(config["voices"]),
        "instructions": config["instructions"],
        "response_format": config["response_format"],
        "text_path": str(text_path),
        "text_sha256": config["text_sha256"],
        "pricing": dict(config["pricing"]),
        "budget": dict(config["budget"]),
        "cost_plan": dict(cost_plan),
        "credential_source_type": credential_source_type,
        "credential_value_stored": False,
        "output_folder": str(output_dir),
        "created_at": utc_now_iso(),
        "completed_at": None,
        "network_attempts": 0,
        "retry_count": 0,
        "actual_known_cost_usd": None,
        "actual_estimated_cost_usd": "0.000000",
        "samples": samples,
    }


def estimated_sample_cost(config: Mapping[str, Any], text: str, duration_seconds: float) -> Decimal:
    pricing = config["pricing"]
    input_tokens_upper = len(text) + len(str(config["instructions"]))
    input_cost = (
        Decimal(input_tokens_upper)
        * Decimal(str(pricing["text_input_per_million_tokens"]))
        / Decimal(1_000_000)
    )
    audio_tokens = (
        Decimal(str(pricing["estimated_audio_tokens_per_minute"]))
        * Decimal(str(duration_seconds))
        / Decimal(60)
    )
    audio_cost = audio_tokens * Decimal(str(pricing["audio_output_per_million_tokens"])) / Decimal(1_000_000)
    return input_cost + audio_cost


def write_readme_summary(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    lines = [
        "OpenAI Russian voice casting — Stage OAI-1",
        "",
        f"Model: {manifest['model']}",
        f"Text SHA-256: {manifest['text_sha256']}",
        f"Network attempts: {manifest['network_attempts']}",
        f"Estimated cost from returned durations: USD {manifest['actual_estimated_cost_usd']}",
        "Actual provider-billed cost: unavailable per response; inspect the OpenAI usage dashboard.",
        "",
        "voice | file | status | duration | sample rate | channels | sample width",
    ]
    for sample in manifest["samples"]:
        validation = sample.get("wav_validation") or {}
        lines.append(
            " | ".join(
                [
                    sample["voice"],
                    sample["output_filename"] if sample["success"] else "-",
                    sample["status"],
                    str(validation.get("duration_seconds", "-")),
                    str(validation.get("sample_rate_hz", "-")),
                    str(validation.get("channels", "-")),
                    str(validation.get("sample_width_bytes", "-")),
                ]
            )
        )
    lines.extend(
        [
            "",
            "These samples are AI-generated voices. No winner is selected by this runner.",
        ]
    )
    (output_dir / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_casting(config: dict[str, Any], text: str, text_path: Path, credential: Credential) -> Path:
    cost_plan = build_cost_plan(config, text)
    if not cost_plan["allowed_to_start"]:
        raise BudgetError("Casting cost plan did not pass the local hard cap.")

    output_root = Path(str(config["output_root"])).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = output_root / timestamp_slug()
    output_dir.mkdir(parents=False, exist_ok=False)
    manifest_path = output_dir / "CASTING-MANIFEST.json"
    manifest = initial_manifest(config, text_path, output_dir, credential.source_type, cost_plan)
    atomic_write_json(manifest_path, manifest)

    budget = config["budget"]
    retry_policy = config["retry_policy"]
    ledger = AttemptLedger(
        max_attempts=int(retry_policy["max_total_network_attempts"]),
        max_cost_usd=Decimal(str(budget["max_casting_cost_usd"])),
        reservation_per_attempt_usd=Decimal(str(budget["reservation_per_network_attempt_usd"])),
    )
    total_estimated_cost = Decimal("0")

    for voice_index, sample in enumerate(manifest["samples"]):
        retries_used = 0
        while True:
            attempt_number = ledger.claim()
            started_at = utc_now_iso()
            sample["status"] = "IN_FLIGHT"
            sample["request_started_at"] = started_at
            sample["attempts"].append(
                {
                    "global_attempt": attempt_number,
                    "voice_attempt": retries_used + 1,
                    "started_at": started_at,
                    "completed_at": None,
                    "result": "IN_FLIGHT",
                }
            )
            manifest["network_attempts"] = ledger.attempts
            atomic_write_json(manifest_path, manifest)

            payload = build_payload(config, text, sample["voice"])
            try:
                audio, request_id = perform_speech_request(
                    str(config["endpoint"]),
                    payload,
                    credential.value,
                    int(config["request_timeout_seconds"]),
                )
                output_path = output_dir / sample["output_filename"]
                validation = write_validated_wav(output_path, audio, config["duration_review"])
                sample_cost = estimated_sample_cost(config, text, float(validation["duration_seconds"]))
                total_estimated_cost += sample_cost
                sample["status"] = "NEEDS_REVIEW" if validation["needs_review"] else "DONE"
                sample["success"] = True
                sample["request_id"] = request_id
                sample["size_bytes"] = validation["size_bytes"]
                sample["wav_validation"] = validation
                sample["sha256"] = validation["sha256"]
                sample["estimated_cost_usd"] = decimal_string(sample_cost)
                sample["error"] = None
                sample["attempts"][-1]["result"] = "SUCCESS"
                sample["attempts"][-1]["request_id"] = request_id
                break
            except AmbiguousRequestError as error:
                sample["status"] = "AMBIGUOUS"
                sample["error"] = {
                    "category": "ambiguous",
                    "message": str(error),
                    "retryable": False,
                }
                sample["request_id"] = error.request_id
                sample["attempts"][-1]["result"] = "AMBIGUOUS"
                break
            except RetryableRequestError as error:
                sample["error"] = {
                    "category": "retryable_transport_or_service",
                    "message": str(error),
                    "retryable": True,
                }
                sample["request_id"] = error.request_id
                sample["attempts"][-1]["result"] = "RETRYABLE_FAILURE"
                unattempted_voices = len(manifest["samples"]) - voice_index - 1
                if can_retry(
                    error,
                    retries_used=retries_used,
                    max_retries_per_voice=int(retry_policy["max_retries_per_voice"]),
                    ledger_remaining=ledger.remaining,
                    unattempted_voices=unattempted_voices,
                ):
                    retries_used += 1
                    sample["retry_count"] = retries_used
                    manifest["retry_count"] += 1
                    continue
                sample["status"] = "FAILED"
                sample["error"]["retry_suppressed_reason"] = (
                    "global_request_cap_preserves_unattempted_voices"
                    if ledger.remaining <= unattempted_voices
                    else "per_voice_retry_limit"
                )
                break
            except CastingError as error:
                sample["status"] = "FAILED"
                sample["error"] = {
                    "category": "non_retryable_or_audio_validation",
                    "message": str(error),
                    "retryable": False,
                }
                sample["attempts"][-1]["result"] = "FAILED"
                break
            finally:
                completed_at = utc_now_iso()
                sample["request_completed_at"] = completed_at
                sample["attempts"][-1]["completed_at"] = completed_at
                manifest["actual_estimated_cost_usd"] = decimal_string(total_estimated_cost)
                atomic_write_json(manifest_path, manifest)

    manifest["completed_at"] = utc_now_iso()
    manifest["actual_estimated_cost_usd"] = decimal_string(total_estimated_cost)
    atomic_write_json(manifest_path, manifest)
    write_readme_summary(output_dir, manifest)
    return output_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded OpenAI Stage OAI-1 voice casting runner.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("openai-casting-config.json"),
    )
    parser.add_argument("--check", action="store_true", help="Run offline config/text/budget checks only.")
    parser.add_argument(
        "--credential-status",
        action="store_true",
        help="Report only the credential source type; never print the credential.",
    )
    parser.add_argument("--run", action="store_true", help="Perform the bounded paid casting round.")
    parser.add_argument(
        "--confirm-paid-casting",
        action="store_true",
        help="Required together with --run to prevent accidental paid requests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config, text, text_path = load_and_validate(args.config.resolve())
        plan = build_cost_plan(config, text)
        if not plan["allowed_to_start"]:
            raise BudgetError("Offline budget gate failed.")

        if args.credential_status:
            credential = read_credential(config)
            print(json.dumps({"credential_present": True, "source_type": credential.source_type}))
            return 0

        if args.run:
            if not args.confirm_paid_casting:
                raise CastingError("--run requires --confirm-paid-casting.")
            credential = read_credential(config)
            print(
                json.dumps(
                    {
                        "gate": "PASS",
                        "planned_requests": plan["planned_requests"],
                        "estimated_total_cost_usd": plan["estimated_total_cost_usd"],
                        "reserved_total_cost_usd": plan["reserved_total_cost_usd"],
                        "hard_cap_usd": plan["hard_cap_usd"],
                        "credential_source_type": credential.source_type,
                    }
                )
            )
            output_dir = run_casting(config, text, text_path, credential)
            print(json.dumps({"casting_complete": True, "output_folder": str(output_dir)}))
            return 0

        summary = {
            "offline_check": "PASS",
            "model": config["model"],
            "voices": config["voices"],
            "text_path": str(text_path),
            "text_sha256": config["text_sha256"],
            "response_format": config["response_format"],
            "cost_plan": plan,
            "network_requests_made": 0,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except CastingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
