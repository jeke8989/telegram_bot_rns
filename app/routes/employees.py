"""
Employee routes — employee management, grade system, Kimai integration.
Source: mini_app/server.py lines 3497-3655
TODO: Migrate remaining handlers from server.py
"""

import json
import logging
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)

GRADE_RATES = {
    'Junior': 1500,
    'Middle': 2200,
    'Senior': 2700,
    'Lead': 3200,
}

GRADE_COEFS = {
    'Junior': 1.00,
    'Middle': 1.47,
    'Senior': 1.80,
    'Lead': 2.13,
}

GRADE_POOL_PCT = {
    'Junior': 0,
    'Middle': 0,
    'Senior': 0,
    'Lead': 0,
    'Partner': 10,
    'Owner': 30,
}
