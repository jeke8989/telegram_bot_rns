"""
User management routes — list users, change roles (admin only).
Source: mini_app/server.py lines 3601-3637
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)
