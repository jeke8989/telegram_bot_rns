"""
Role-based access control decorator.
Usage:
    @routes.get('/api/admin/users')
    @require_role('admin')
    async def list_users(request): ...

    @routes.get('/api/dashboard')
    @require_role('admin', 'staff')
    async def dashboard(request): ...
"""

import functools
from aiohttp import web

from .auth import require_session


def require_role(*roles: str):
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request):
            require_session(request)
            user_role = request['session'].get('role', 'user')
            if user_role not in roles:
                raise web.HTTPForbidden(text='Insufficient permissions')
            return await handler(request)
        return wrapper
    return decorator
