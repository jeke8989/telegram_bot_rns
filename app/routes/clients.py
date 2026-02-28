"""
Client routes — CRUD, messages, status, promo.
Source: mini_app/server.py lines 2372-2776
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)
