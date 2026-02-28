"""
Data serializers — convert DB rows to API response dicts.
Source: mini_app/server.py lines 1633, 2372, 2410

Contains:
- serialize_task(task_row) -> dict
- serialize_client(client_row) -> dict
- get_client_by_uuid_or_404(uuid_str, db) -> dict

TODO: Extract implementations from server.py
"""

import logging
from aiohttp import web

logger = logging.getLogger(__name__)
