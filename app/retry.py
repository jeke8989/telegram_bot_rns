"""Tiny retry helpers for flaky external API calls.

No new dependencies — pure asyncio + functools.

Usage:

    from app.retry import retry_async

    @retry_async(attempts=3, base_delay=0.5)
    async def fetch_token(...):
        ...

The decorator retries on any Exception except those listed in `dont_retry`
(default: nothing). Backoff is exponential with jitter, capped at `max_delay`.
On the final attempt it re-raises the original exception.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
from typing import Awaitable, Callable, Iterable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_async(
    attempts: int = 3,
    base_delay: float = 0.5,
    factor: float = 2.0,
    max_delay: float = 10.0,
    jitter: float = 0.25,
    dont_retry: Iterable[type[BaseException]] = (),
):
    """Decorator: retry an async callable on exception with exponential backoff.

    `attempts` includes the first call. `dont_retry` lists exception types that
    should propagate immediately (e.g. asyncio.CancelledError, KeyboardInterrupt).
    """
    dont_retry = tuple(dont_retry) + (asyncio.CancelledError, KeyboardInterrupt)

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            delay = base_delay
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except dont_retry:
                    raise
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if attempt >= attempts:
                        break
                    sleep_for = min(max_delay, delay) * (1 + random.uniform(-jitter, jitter))
                    logger.warning(
                        "%s attempt %d/%d failed: %s — retrying in %.2fs",
                        fn.__qualname__, attempt, attempts, e, sleep_for,
                    )
                    await asyncio.sleep(max(0, sleep_for))
                    delay *= factor
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
