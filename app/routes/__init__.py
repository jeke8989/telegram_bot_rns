"""
Route collector — imports all domain route modules and exposes them as a list.

Usage in server.py:
    from app.routes import all_routes
    for rt in all_routes:
        app.add_routes(rt)
"""

from .static_files import routes as static_routes
from .auth import routes as auth_routes
from .proposals import routes as proposal_routes
from .clients import routes as client_routes
from .cabinet import routes as cabinet_routes
from .meetings import routes as meeting_routes
from .projects import routes as project_routes
from .employees import routes as employee_routes
from .users import routes as user_routes
from .webhooks import routes as webhook_routes
from .ai import routes as ai_routes

all_routes = [
    static_routes,
    auth_routes,
    proposal_routes,
    client_routes,
    cabinet_routes,
    meeting_routes,
    project_routes,
    employee_routes,
    user_routes,
    webhook_routes,
    ai_routes,
]
