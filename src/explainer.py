"""API logic for legacy code explanation.

Handles streaming, prompt caching on the system prompt, and extended
thinking for complex code. Requires load_dotenv() to be called at the
entry point (main.py) before this module is imported — env vars are
read at import time to instantiate the client once.

Does not manage CLI concerns — see main.py.
"""

import logging
import os
from typing import TextIO

import anthropic

from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

COMPLEXITY_LINE_THRESHOLD = 50

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    raise ValueError("ANTHROPIC_API_KEY is not set")

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6")
THINKING_MODEL = os.getenv("THINKING_MODEL", "claude-opus-4-7")
THINKING_BUDGET = int(os.getenv("THINKING_BUDGET", "8000"))

client = anthropic.Anthropic(api_key=_api_key)


def _is_complex(code: str) -> bool:
    """Return True if code length warrants extended thinking.

    Uses line count as the primary signal. Deliberately conservative —
    extended thinking is cheap insurance on borderline cases.

    Args:
        code: Raw source code string.

    Returns:
        True if code exceeds COMPLEXITY_LINE_THRESHOLD lines.
    """
    return code.count("\n") + 1 > COMPLEXITY_LINE_THRESHOLD


def _print_usage(usage: anthropic.types.Usage) -> None:
    """Print token usage to stdout in a readable table.

    Args:
        usage: Usage object from the final API response.
    """
    print(
        f"\n--- token usage ---\n"
        f"input:       {usage.input_tokens}\n"
        f"output:      {usage.output_tokens}\n"
        f"cache read:  {usage.cache_read_input_tokens or 0}\n"
        f"cache write: {usage.cache_creation_input_tokens or 0}\n"
    )


def explain_code(
    code: str,
    filename: str,
    extra_output: TextIO | None = None,
) -> None:
    """Stream a structured explanation of legacy code to stdout.

    Selects model and enables extended thinking based on code complexity.
    Only the text response streams to the user — thinking blocks are
    consumed internally by the SDK and not printed.

    Prints token usage to stdout after the stream completes. Token usage
    is not written to extra_output — it is operational noise, not analysis.

    Args:
        code: Raw source code content to analyze.
        filename: Original filename, included in the prompt for language context.
        extra_output: Optional writable text stream to mirror streamed output
            into (e.g. an open file). Receives the same chunks as stdout.

    Raises:
        anthropic.RateLimitError: On API rate limiting — caller should back off.
        anthropic.APIError: On other unrecoverable API failures.
    """
    use_thinking = _is_complex(code)
    model = THINKING_MODEL if use_thinking else DEFAULT_MODEL

    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    messages = [
        {
            "role": "user",
            "content": f"Analyze this code from `{filename}`:\n\n```\n{code}\n```",
        }
    ]

    kwargs = {
        "model": model,
        "max_tokens": 16000 if use_thinking else 4096,
        "system": system,
        "messages": messages,
    }

    if use_thinking:
        # Claude 4 uses adaptive thinking + output_config effort instead of
        # the legacy "enabled" / budget_tokens API.
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "high"}

    logger.info(
        "Explaining %s — model: %s, extended thinking: %s",
        filename,
        model,
        use_thinking,
    )

    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
                if extra_output is not None:
                    extra_output.write(text)

            print()
            if extra_output is not None:
                extra_output.write("\n")

            final = stream.get_final_message()

        logger.info(
            "Tokens — input: %d, output: %d, cache_read: %d, cache_write: %d",
            final.usage.input_tokens,
            final.usage.output_tokens,
            final.usage.cache_read_input_tokens or 0,
            final.usage.cache_creation_input_tokens or 0,
        )
        _print_usage(final.usage)

    except anthropic.RateLimitError as e:
        logger.warning("Rate limited: %s", e)
        raise
    except anthropic.APIError as e:
        logger.error("API call failed: %s", e, exc_info=True)
        raise
