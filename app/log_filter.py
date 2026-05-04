"""Logging filter that masks known secret formats in log records.

What gets masked:
- Telegram bot tokens (`<digits>:<35+ token chars>`) — including when
  they appear in URLs like `api.telegram.org/bot<TOKEN>/...`
- OpenRouter / OpenAI keys (`sk-...` and `sk-or-v1-...`)
- Bearer tokens in Authorization headers (`Authorization: Bearer ...`)

Why a Filter and not a Formatter: filters run on every record across every
handler, including third-party libraries like httpx that log request URLs
with tokens embedded.
"""
from __future__ import annotations

import logging
import re

# (pattern, replacement) — replacement keeps a short prefix so it's still
# possible to tell *which* key leaked without exposing the value.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Telegram bot token, also inside URLs (api.telegram.org/bot<TOKEN>/method).
    # The second group has to be 35+ chars to keep this specific to real tokens.
    (re.compile(r"(\d{8,12}):([A-Za-z0-9_-]{35,})"), r"\1:***"),
    # OpenRouter v1 keys
    (re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,}"), "sk-or-v1-***"),
    # Generic OpenAI / sk- keys (must be at least 20 chars to avoid false positives)
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "sk-***"),
    # Authorization: Bearer <token>
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.IGNORECASE), r"\1***"),
]


def _mask(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class SecretMaskingFilter(logging.Filter):
    """Mutates the LogRecord in-place so masking applies in every handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Format the message once with current args, then store as msg
            # with no args, so downstream formatters don't reintroduce them.
            if record.args:
                rendered = record.getMessage()
                record.msg = _mask(rendered)
                record.args = ()
            elif isinstance(record.msg, str):
                record.msg = _mask(record.msg)
        except Exception:  # noqa: BLE001
            # Never let masking break logging itself.
            pass
        return True


def install(level: int | None = None) -> None:
    """Attach the filter to the root logger so every record is scrubbed.

    Call this once after logging.basicConfig().
    """
    root = logging.getLogger()
    f = SecretMaskingFilter()
    # On both the root logger (catches direct .log calls) and each handler
    # (handlers have their own filter chain when added via basicConfig).
    root.addFilter(f)
    for h in root.handlers:
        h.addFilter(f)
    if level is not None:
        root.setLevel(level)
