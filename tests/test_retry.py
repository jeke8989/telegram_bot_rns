"""Tests for app.retry.retry_async."""
import asyncio
import pytest

from app.retry import retry_async


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt():
    calls = 0

    @retry_async(attempts=3, base_delay=0)
    async def ok():
        nonlocal calls
        calls += 1
        return "fine"

    assert await ok() == "fine"
    assert calls == 1


@pytest.mark.asyncio
async def test_retries_until_success():
    calls = 0

    @retry_async(attempts=4, base_delay=0)
    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("transient")
        return "recovered"

    assert await flaky() == "recovered"
    assert calls == 3


@pytest.mark.asyncio
async def test_raises_after_exhaustion():
    calls = 0

    @retry_async(attempts=2, base_delay=0)
    async def always_fails():
        nonlocal calls
        calls += 1
        raise ValueError(f"boom {calls}")

    with pytest.raises(ValueError, match="boom 2"):
        await always_fails()
    assert calls == 2


@pytest.mark.asyncio
async def test_dont_retry_propagates_immediately():
    calls = 0

    class Fatal(Exception):
        pass

    @retry_async(attempts=5, base_delay=0, dont_retry=(Fatal,))
    async def raises_fatal():
        nonlocal calls
        calls += 1
        raise Fatal()

    with pytest.raises(Fatal):
        await raises_fatal()
    assert calls == 1  # no retries


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry():
    calls = 0

    @retry_async(attempts=5, base_delay=0)
    async def cancelled():
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await cancelled()
    assert calls == 1


@pytest.mark.asyncio
async def test_preserves_function_signature_and_args():
    @retry_async(attempts=2, base_delay=0)
    async def add(a: int, b: int = 0) -> int:
        return a + b

    assert await add(2, b=3) == 5
    assert add.__name__ == "add"
