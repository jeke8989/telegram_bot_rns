"""Tests for app.log_filter.SecretMaskingFilter."""
import logging

import pytest

from app.log_filter import SecretMaskingFilter, _mask


def _make_record(msg, *args, name="test"):
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_mask_telegram_bot_token_in_url():
    # Synthetic token (NOT real). Format must match what Telegram issues:
    # <bot_id>:<35+ char secret>. Using only `A` characters in the secret
    # so the test fixture cannot accidentally match a real revoked token.
    raw = "POST https://api.telegram.org/bot1234567890:" + "A" * 35 + "/setMyCommands"
    out = _mask(raw)
    assert "A" * 35 not in out
    assert "1234567890:***" in out


def test_mask_openrouter_key():
    out = _mask("loaded sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaa")
    assert "aaaaa" not in out
    assert "sk-or-v1-***" in out


def test_mask_generic_sk_key():
    out = _mask("sk-1234567890abcdefghij12345 in config")
    assert "1234567890abcdefghij" not in out
    assert "sk-***" in out


def test_mask_authorization_bearer():
    out = _mask("Authorization: Bearer eyJhbGc.payload.signature")
    assert "eyJhbGc" not in out
    assert "Authorization: Bearer ***" in out


def test_does_not_mask_short_digit_colon_pair():
    raw = "duration 1:30 elapsed"
    assert _mask(raw) == raw


def test_does_not_mask_plain_text():
    raw = "Старт сессии для пользователя 42"
    assert _mask(raw) == raw


def test_filter_mutates_record_in_place():
    f = SecretMaskingFilter()
    rec = _make_record("token sk-or-v1-secrettokensecrettoken123")
    assert f.filter(rec) is True
    assert "sk-or-v1-***" in rec.getMessage()
    assert "secrettoken" not in rec.getMessage()


def test_filter_handles_args_interpolation():
    """printf-style args should be formatted before masking, then cleared."""
    f = SecretMaskingFilter()
    rec = _make_record("user %s sent token %s", "alice", "sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaa")
    assert f.filter(rec) is True
    msg = rec.getMessage()
    assert "alice" in msg
    assert "sk-or-v1-***" in msg
    assert rec.args == ()


def test_filter_never_raises():
    """Even if msg is unusual, filter must not break logging."""
    f = SecretMaskingFilter()
    rec = _make_record(object())  # non-string msg
    assert f.filter(rec) is True
