"""
Client cabinet routes — public-facing client dashboard.
Source: mini_app/server.py lines 2778-3025
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


@routes.get('/cabinet/{token}')
async def cabinet_page(request):
    return web.FileResponse('./static/client-cabinet.html')
