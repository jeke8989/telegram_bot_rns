"""
Request logging middleware.
Logs method, path, status, and duration for every request.
"""

import time
import logging
from aiohttp import web

logger = logging.getLogger('request')


@web.middleware
async def request_logging_middleware(request, handler):
    start = time.monotonic()
    try:
        response = await handler(request)
        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %d %.0fms",
            request.method, request.path, response.status, elapsed,
        )
        return response
    except web.HTTPException as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %d %.0fms",
            request.method, request.path, exc.status_code, elapsed,
        )
        raise
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        logger.error(
            "%s %s 500 %.0fms (unhandled)",
            request.method, request.path, elapsed,
        )
        raise
