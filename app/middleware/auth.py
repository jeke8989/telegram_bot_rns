"""
Authentication middleware and helpers.
Extracted from mini_app/server.py for reuse across route modules.
"""

import json
import functools
from aiohttp import web

_PUBLIC_PREFIXES = (
    '/login', '/auth/callback', '/auth/logout', '/api/auth/bot-info', '/api/auth/telegram',
    '/api/auth/dev-users', '/api/auth/dev-login',
    '/api/health', '/api/zoom/webhook',
    '/style.css', '/logo.png', '/img/', '/favicon.ico', '/apple-touch-icon.png',
    '/og-image.png', '/og-meeting.png', '/og-meeting.jpg', '/og-proposal.png',
    '/css/', '/js/',
    '/my-cabinet',
)

_STAFF_ONLY_PREFIXES = (
    '/projects', '/api/projects',
    '/project/', '/api/project/',
    '/employees', '/api/employees',
    '/api/kimai/',
    '/seller',
)

_ADMIN_ONLY_PREFIXES = (
    '/users', '/api/users',
)


async def get_session(request) -> dict | None:
    token = request.cookies.get('session_token')
    if not token:
        return None
    db = request.app['db']
    return await db.get_web_session(token)


@web.middleware
async def auth_middleware(request, handler):
    path = request.path
    method = request.method
    db = request.app['db']

    if path == '/':
        return await handler(request)

    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return await handler(request)

    if path.startswith('/cabinet/') or path.startswith('/api/cabinet/'):
        session = await get_session(request)
        if session:
            request['session'] = session
        return await handler(request)

    if path.startswith('/proposal/') or path.startswith('/api/proposal/'):
        if '/edit' in path:
            pass
        elif method == 'GET' and path.startswith('/api/proposal/'):
            return await handler(request)
        elif method == 'GET' and path.startswith('/proposal/'):
            return await handler(request)

    if path.startswith('/meeting/') or path.startswith('/api/meeting/'):
        session = await get_session(request)
        if session:
            request['session'] = session
            if session.get('role') == 'user':
                parts = path.split('/')
                token_idx = 3 if path.startswith('/api/') else 2
                if len(parts) > token_idx:
                    meeting_token = parts[token_idx]
                    meeting = await db.get_meeting_by_public_token(meeting_token)
                    if not meeting or not meeting.get('is_public'):
                        if path.startswith('/api/'):
                            return web.json_response({'error': 'access denied'}, status=403)
                        raise web.HTTPFound('/login')
            return await handler(request)
        parts = path.split('/')
        token_idx = 3 if path.startswith('/api/') else 2
        if len(parts) > token_idx:
            meeting_token = parts[token_idx]
            meeting = await db.get_meeting_by_public_token(meeting_token)
            if meeting and meeting.get('is_public'):
                return await handler(request)
        if path.startswith('/api/'):
            return web.json_response({'error': 'unauthorized'}, status=401)
        raise web.HTTPFound(f'/login?next={path}')

    session = await get_session(request)
    if not session:
        if path.startswith('/api/'):
            return web.json_response({'error': 'unauthorized'}, status=401)
        raise web.HTTPFound(f'/login?next={path}')

    request['session'] = session
    role = session.get('role', 'user')

    for prefix in _ADMIN_ONLY_PREFIXES:
        if path.startswith(prefix) and role != 'admin':
            if path.startswith('/api/'):
                return web.json_response({'error': 'admin only'}, status=403)
            raise web.HTTPFound('/login')

    if role == 'user':
        for prefix in _STAFF_ONLY_PREFIXES:
            if path.startswith(prefix):
                if path.startswith('/api/'):
                    return web.json_response({'error': 'access denied'}, status=403)
                raise web.HTTPFound('/my-cabinet')
    elif role == 'seller':
        for prefix in _STAFF_ONLY_PREFIXES:
            if path.startswith(prefix) and not path.startswith('/seller'):
                if path.startswith('/api/'):
                    return web.json_response({'error': 'access denied'}, status=403)
                raise web.HTTPFound('/seller')

    return await handler(request)


def require_session(request):
    if 'session' not in request:
        raise web.HTTPUnauthorized(
            text=json.dumps({'error': 'unauthorized'}),
            content_type='application/json',
        )


def require_staff_session(request):
    require_session(request)
    if request['session'].get('role') == 'user':
        raise web.HTTPForbidden(
            text=json.dumps({'error': 'staff or admin access required'}),
            content_type='application/json',
        )


def require_auth(handler):
    """Decorator: require authenticated session on a route handler."""
    @functools.wraps(handler)
    async def wrapper(request):
        require_session(request)
        return await handler(request)
    return wrapper


def require_staff(handler):
    """Decorator: require staff or admin session on a route handler."""
    @functools.wraps(handler)
    async def wrapper(request):
        require_staff_session(request)
        return await handler(request)
    return wrapper
