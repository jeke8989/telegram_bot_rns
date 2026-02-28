"""
Rate limiting decorator for route handlers.
Usage:
    @routes.post('/api/auth/telegram')
    @rate_limit(max_requests=5, window=60)
    async def telegram_auth(request): ...
"""

import functools
import time
from collections import defaultdict
from aiohttp import web

_buckets: dict[str, list[float]] = defaultdict(list)


def rate_limit(max_requests: int = 60, window: int = 60):
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request):
            ip = request.remote or 'unknown'
            key = f"{handler.__name__}:{ip}"

            now = time.monotonic()
            timestamps = _buckets[key]
            cutoff = now - window
            _buckets[key] = [t for t in timestamps if t > cutoff]

            if len(_buckets[key]) >= max_requests:
                return web.json_response(
                    {'error': 'Too many requests'},
                    status=429,
                    headers={'Retry-After': str(window)},
                )

            _buckets[key].append(now)
            return await handler(request)
        return wrapper
    return decorator
