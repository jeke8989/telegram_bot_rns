"""
Proposal routes — CRUD for commercial proposals.
Source: mini_app/server.py lines 243-415
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


@routes.get('/proposal/{token}/edit')
async def proposal_edit_page(request):
    return web.FileResponse('./static/proposal-edit.html')


@routes.get('/proposal/{token}')
async def proposal_page(request):
    return web.FileResponse('./static/proposal.html')
