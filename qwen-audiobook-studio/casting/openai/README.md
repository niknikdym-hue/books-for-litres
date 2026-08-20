# OpenAI Russian voice casting — Stage OAI-1

This directory contains the isolated, bounded first-round casting tools for the 13 built-in `gpt-4o-mini-tts` voices. It is not a production OpenAI backend and is not connected to the Audiobook Studio UI.

The same artificial Russian control text and the same instruction preset are sent once for every voice. The runner never assigns gender or selects winners.

## Safety properties

- Default execution is offline and sends no API request.
- `--run` additionally requires `--confirm-paid-casting`.
- Both `MAX_REQUESTS` and the total network-attempt cap are 13; a 14th call is rejected locally.
- The hard budget cap is USD 1.00. Thirteen calls reserve USD 0.65 and the normal duration-based estimate is much lower.
- A voice may have at most one retry in the generic policy, but the 13-attempt global cap preserves one first attempt for every voice. With the current 13-voice plan there is no spare attempt for an automatic retry.
- Ambiguous timeouts or interrupted responses are never retried.
- Audio is retained only after RIFF/WAVE parsing succeeds.
- API credentials are read from `OPENAI_API_KEY` or macOS Keychain service `AudiobookStudio-OpenAI`; their values are never written to output.
- Generated WAV, manifest, summary, and logs stay outside the repository under `/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio/casting/openai/<timestamp>/`.

## Safe local checks

Run the complete offline gate:

```bash
python3 qwen-audiobook-studio/casting/openai/run_openai_casting.py --check
```

Check only whether an approved credential source exists (the value is not printed):

```bash
python3 qwen-audiobook-studio/casting/openai/run_openai_casting.py --credential-status
```

If no credential exists, store it in the macOS Keychain using the Keychain Access application with service name `AudiobookStudio-OpenAI` and the current macOS username as the account, or provide `OPENAI_API_KEY` only in the local process environment. Do not put the key in this repository or send it in chat.

The paid run is deliberately explicit:

```bash
python3 qwen-audiobook-studio/casting/openai/run_openai_casting.py --run --confirm-paid-casting
```

Official references:

- <https://developers.openai.com/api/docs/guides/text-to-speech>
- <https://developers.openai.com/api/docs/models/gpt-4o-mini-tts>

The manifest reports a duration-based cost estimate and leaves `actual_known_cost_usd` null because the binary Speech response does not guarantee per-request token usage. Provider-billed totals must be checked in the OpenAI usage dashboard.
