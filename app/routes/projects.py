"""
Project routes — CRUD, categories, finance, expenses, income, meeting linking.
Source: mini_app/server.py lines 3027-3070, 3075-3400, 3660-3970
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)


@routes.get('/project/{token}')
async def project_page(request):
    return web.FileResponse('./static/project.html')
