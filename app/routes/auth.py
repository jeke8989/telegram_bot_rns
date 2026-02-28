"""Authentication routes — login, callback, logout, Telegram WebApp auth."""

import os
import json
import hashlib
import hmac
import uuid
import logging
from datetime import datetime, timedelta
from urllib.parse import unquote, parse_qsl
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)

_IS_DEV = os.getenv('APP_ENV', 'production') == 'development'


async def _get_session(request) -> dict | None:
    token = request.cookies.get('session_token')
    if not token:
        return None
    db = request.app['db']
    return await db.get_web_session(token)


def _validate_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = params.pop('hash', None)
    if not received_hash:
        return None
    data_check_string = '\n'.join(f'{k}={v}' for k, v in sorted(params.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None
    return params


@routes.get('/login')
async def login_page(request):
    return web.FileResponse('./static/login.html')


@routes.get('/auth/callback')
async def auth_callback(request):
    db = request.app['db']
    token = request.query.get('token', '')
    if not token:
        raise web.HTTPFound('/login')
    session = await db.get_web_session(token)
    if not session:
        raise web.HTTPFound('/login')
    raw_next = request.cookies.get('auth_next', '') or request.query.get('next', '')
    role = session.get('role', 'user')
    if role == 'seller':
        default_page = '/seller'
    elif role in ('staff', 'admin'):
        default_page = '/projects'
    else:
        default_page = '/my-cabinet'
    redirect = unquote(raw_next) if raw_next else default_page
    if not redirect.startswith('/') or redirect.startswith('/login'):
        redirect = default_page
    resp = web.HTTPFound(redirect)
    resp.set_cookie('session_token', token, max_age=10800, httponly=True, path='/', samesite='Lax')
    resp.del_cookie('auth_next', path='/')
    return resp


@routes.get('/auth/logout')
async def auth_logout(request):
    resp = web.HTTPFound('/login')
    resp.del_cookie('session_token', path='/')
    return resp


@routes.get('/api/auth/bot-info')
async def auth_bot_info(request):
    bot_username = os.getenv('BOT_USERNAME', '')
    return web.json_response({'bot_username': bot_username})


@routes.get('/api/auth/me')
async def auth_me(request):
    db = request.app['db']
    session = await _get_session(request)
    if not session:
        return web.json_response({'error': 'unauthorized'}, status=401)
    result = {
        'telegram_id': session['telegram_id'],
        'first_name': session['first_name'],
        'username': session['username'],
        'role': session['role'],
        'note': session.get('note', ''),
    }
    if session['role'] == 'user':
        client = await db.get_client_by_telegram_id(int(session['telegram_id']))
        if client and client.get('cabinet_token'):
            result['cabinet_token'] = client['cabinet_token']
    return web.json_response(result)


@routes.get('/my-cabinet')
async def my_cabinet_redirect(request):
    db = request.app['db']
    session = await _get_session(request)
    if not session:
        raise web.HTTPFound('/login?next=/my-cabinet')
    tg_id = session.get('telegram_id')
    if not tg_id:
        raise web.HTTPFound('/login')
    client = await db.get_client_by_telegram_id(int(tg_id))
    if client and client.get('cabinet_token'):
        raise web.HTTPFound(f"/cabinet/{client['cabinet_token']}")
    raise web.HTTPFound('/login')


@routes.post('/api/auth/telegram')
async def auth_telegram(request):
    db = request.app['db']
    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    init_data = body.get('initData', '')
    if not init_data:
        return web.json_response({'error': 'initData required'}, status=400)

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    params = _validate_telegram_init_data(init_data, bot_token)
    if params is None:
        return web.json_response({'error': 'invalid initData'}, status=401)

    try:
        user = json.loads(params.get('user', '{}'))
    except Exception:
        return web.json_response({'error': 'invalid user data'}, status=400)

    telegram_id = user.get('id')
    if not telegram_id:
        return web.json_response({'error': 'no user id in initData'}, status=400)

    first_name = user.get('first_name', '')
    last_name = user.get('last_name', '')
    username = user.get('username', '')

    await db.save_user(
        telegram_id=int(telegram_id),
        first_name=first_name,
        last_name=last_name,
        username=username,
    )
    role = await db.get_user_role(int(telegram_id))
    note = ''
    if role in ('staff', 'admin', 'seller'):
        note = await db.get_staff_note(int(telegram_id)) or ''

    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(hours=3)
    await db.create_web_session(
        token=token,
        telegram_id=int(telegram_id),
        first_name=first_name,
        username=username,
        role=role,
        note=note,
        expires_at=expires_at,
    )

    result = {
        'ok': True,
        'telegram_id': telegram_id,
        'first_name': first_name,
        'username': username,
        'role': role,
    }
    if role == 'user':
        client = await db.get_client_by_telegram_id(int(telegram_id))
        if client and client.get('cabinet_token'):
            result['cabinet_token'] = client['cabinet_token']
    resp = web.json_response(result)
    resp.set_cookie('session_token', token, max_age=10800, httponly=True, path='/', samesite='None', secure=True)
    return resp


# ==================== Dev-only auth ====================


@routes.get('/api/auth/dev-users')
async def auth_dev_users(request):
    """Return users grouped by role. Only available in development."""
    if not _IS_DEV:
        return web.json_response({'error': 'not available'}, status=404)
    db = request.app['db']
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT telegram_id, first_name, last_name, username, role, cabinet_token "
            "FROM users WHERE telegram_id IS NOT NULL "
            "ORDER BY role, first_name LIMIT 50"
        )
    users = []
    for r in rows:
        users.append({
            'telegram_id': r['telegram_id'],
            'first_name': r['first_name'] or '',
            'last_name': r['last_name'] or '',
            'username': r['username'] or '',
            'role': r['role'] or 'user',
            'cabinet_token': r['cabinet_token'] or '',
        })
    return web.json_response({'users': users})


@routes.post('/api/auth/dev-login')
async def auth_dev_login(request):
    """Create session for any user without Telegram validation. Dev only."""
    if not _IS_DEV:
        return web.json_response({'error': 'not available'}, status=404)
    db = request.app['db']
    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    telegram_id = body.get('telegram_id')
    if not telegram_id:
        return web.json_response({'error': 'telegram_id required'}, status=400)

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT telegram_id, first_name, username, role, cabinet_token "
            "FROM users WHERE telegram_id = $1",
            int(telegram_id),
        )
    if not row:
        return web.json_response({'error': 'user not found'}, status=404)

    first_name = row['first_name'] or ''
    username = row['username'] or ''
    role = row['role'] or 'user'

    note = ''
    if role in ('staff', 'admin', 'seller'):
        note = await db.get_staff_note(int(telegram_id)) or ''

    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(hours=24)
    await db.create_web_session(
        token=token,
        telegram_id=int(telegram_id),
        first_name=first_name,
        username=username,
        role=role,
        note=note,
        expires_at=expires_at,
    )

    result = {
        'ok': True,
        'telegram_id': telegram_id,
        'first_name': first_name,
        'username': username,
        'role': role,
    }
    if role == 'user' and row['cabinet_token']:
        result['cabinet_token'] = row['cabinet_token']

    resp = web.json_response(result)
    resp.set_cookie('session_token', token, max_age=86400, httponly=True, path='/', samesite='Lax')
    logger.info(f"[DEV AUTH] session created for {first_name} ({role}), tg_id={telegram_id}")
    return resp
