"""
Webhook routes — Zoom webhook handler.
Source: mini_app/server.py lines 4504-4920
TODO: Migrate handler from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)
