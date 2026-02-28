"""
Meeting routes — CRUD, chat, brainstorm, tasks, mindmap, transcription, video.
Source: mini_app/server.py lines 820-2370, 3393-3470
This is the largest route module (~25 endpoints).
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)
