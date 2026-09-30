"""Secret redaction for V0.7 LLM provider parity (W4).

A user-supplied API key must never reach a persisted log line, an HTTP error
body, or a fallback-reason string. ``redact_secrets`` scrubs the common key
formats used by the providers in this package (OpenAI, OpenRouter, Google
Gemini, Anthropic Claude) plus generic bearer tokens and ``key=``/``api_key=``
query parameters, without disturbing ordinary prose.
"""

from __future__ import annotations

import re

_REDACTED = "***REDACTED***"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenRouter keys, e.g. sk-or-v1-<hex>. Must run before the generic sk- pattern.
    (re.compile(r"\bsk-or-[A-Za-z0-9\-_]{6,}"), f"sk-or-{_REDACTED}"),
    # Anthropic keys, e.g. sk-ant-api03-<...>. Must run before the generic sk- pattern.
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{6,}"), f"sk-ant-{_REDACTED}"),
    # Generic OpenAI-style secret keys, e.g. sk-<hex> or sk-proj-<hyphenated tail>.
    (re.compile(r"\bsk-(?!or-|ant-)[A-Za-z0-9_-]{10,}"), f"sk-{_REDACTED}"),
    # Google / Gemini API keys.
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{10,}"), f"AIza{_REDACTED}"),
    # Generic bearer tokens (Authorization headers echoed into error text).
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"), f"Bearer {_REDACTED}"),
    # `key=` / `api_key=` query-string parameter values.
    (re.compile(r"(?i)\b(api_key|key)=[^&\s\"']+"), rf"\1={_REDACTED}"),
]


def redact_secrets(text: str | None) -> str:
    """Scrub API keys, tokens and key-bearing query parameters out of ``text``.

    Safe to call on arbitrary provider error strings, URLs or log lines. Text
    with no recognizable secret pattern is returned unchanged.
    """
    if not text:
        return text or ""

    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
