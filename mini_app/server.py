"""
Mini App Web Server
Serves static files and API endpoints for the roulette + Zoom webhook
"""

from aiohttp import web
import aiohttp
import asyncio
import os
import sys
import json
import re
import hashlib
import hmac
import logging
import uuid
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path to import from app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import Database
from app.config import Config
from app.lark_client import LarkClient
from app.zoom_client import ZoomClient
from app.zoom_ws_listener import ZoomWSListener
from app.embeddings import embed_meeting_for_project, generate_single_embedding, reembed_all_project_meetings
from app.s3_client import S3Client
from app.kimai_client import KimaiClient
from app.proposal_calculator import ProposalCalculator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def _run_ffmpeg(*args: str, timeout: int = 300) -> tuple[int, bytes, bytes]:
    """Run ffmpeg asynchronously without blocking the event loop.
    Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"ffmpeg timed out after {timeout}s")
    return proc.returncode, stdout, stderr


# Helper functions for Lark cards
async def get_participants_with_notes(meeting_id: int) -> list[dict]:
    """Get meeting participants with their notes."""
    participants = await db.get_meeting_participants(meeting_id)
    result = []
    for p in participants:
        note = await db.get_staff_note(p['telegram_id'])
        result.append({
            'telegram_id': p['telegram_id'],
            'first_name': p.get('first_name'),
            'username': p.get('username'),
            'note': note,
        })
    return result


def format_start_time(start_time_dt) -> str | None:
    """Format start time for Lark card."""
    if not start_time_dt:
        return None
    import zoneinfo
    from datetime import datetime
    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    dt = start_time_dt.astimezone(tz) if hasattr(start_time_dt, 'astimezone') else start_time_dt
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    month_names = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{day_names[dt.weekday()]}, {dt.day} {month_names[dt.month]} в {dt.strftime('%H:%M')} МСК"


def format_end_time(start_time_dt, duration_minutes: int) -> str | None:
    """Calculate and format end time for Lark card."""
    if not start_time_dt or not duration_minutes:
        return None
    import zoneinfo
    from datetime import datetime, timedelta
    tz = zoneinfo.ZoneInfo("Europe/Moscow")
    dt = start_time_dt.astimezone(tz) if hasattr(start_time_dt, 'astimezone') else start_time_dt
    end_dt = dt + timedelta(minutes=duration_minutes)
    return end_dt.strftime('%H:%M') + " МСК"

# Get database URL from environment
database_url = os.getenv('DATABASE_URL')
if not database_url:
    raise ValueError("DATABASE_URL is not set in environment variables")

# Initialize database, config, and clients
db = Database(database_url)
config = Config()

lark_client = None
if config.lark_app_id and config.lark_app_secret:
    lark_client = LarkClient(config.lark_app_id, config.lark_app_secret, config.lark_group_chat_id)

zoom_client = None
if config.zoom_account_id and config.zoom_client_id:
    zoom_client = ZoomClient(config.zoom_account_id, config.zoom_client_id, config.zoom_client_secret)

s3_client = S3Client()

kimai_client = None
if config.kimai_url and config.kimai_api_token:
    kimai_client = KimaiClient(config.kimai_url, config.kimai_api_token)

zoom_ws_listener = None

routes = web.RouteTableDef()

# ========== Helper Functions ==========

async def send_telegram_message(telegram_id: int, text: str, reply_markup=None):
    """Send message to user via Telegram Bot API"""
    try:
        url = f"https://api.telegram.org/bot{config.telegram_token}/sendMessage"
        payload = {
            'chat_id': telegram_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Message sent to user {telegram_id}")
                    return True
                else:
                    logger.error(f"Failed to send message: {await response.text()}")
                    return False
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False

# ========== Static Files ==========

@routes.get('/')
async def index(request):
    """Serve main HTML page"""
    return web.FileResponse('./static/index.html')

@routes.get('/projects')
async def projects_page(request):
    """Serve projects listing page"""
    return web.FileResponse('./static/projects.html')

@routes.get('/employees')
async def employees_page(request):
    """Serve employees management page"""
    return web.FileResponse('./static/employees.html')

@routes.get('/employee/{uuid}')
async def employee_detail_page(request):
    """Serve employee detail page"""
    return web.FileResponse('./static/employee.html')

@routes.get('/proposals')
async def proposals_page(request):
    """Serve proposals listing page"""
    return web.FileResponse('./static/proposals.html')

@routes.get('/users')
async def users_page(request):
    """Serve users management page (admin only — enforced by middleware)"""
    return web.FileResponse('./static/users.html')

@routes.get('/seller')
async def seller_page(request):
    """Serve seller cabinet page (seller + admin)"""
    return web.FileResponse('./static/seller.html')

@routes.get('/client/{uuid}')
async def client_detail_page(request):
    """Serve client detail/card page"""
    return web.FileResponse('./static/client.html')

@routes.get('/style.css')
async def css(request):
    """Serve CSS stylesheet"""
    return web.FileResponse('./static/style.css')

@routes.get('/script.js')
async def js(request):
    """Serve JavaScript file"""
    return web.FileResponse('./static/script.js')

@routes.get('/sidebar.js')
async def sidebar_js(request):
    """Serve shared sidebar module"""
    return web.FileResponse('./static/sidebar.js')

@routes.get('/chat-widget.js')
async def chat_widget_js(request):
    """Serve reusable chat widget"""
    return web.FileResponse('./static/chat-widget.js')

@routes.get('/logo.png')
async def logo(request):
    return web.FileResponse('./static/logo.png')

@routes.get('/favicon.ico')
async def favicon(request):
    return web.FileResponse('./static/favicon.ico')

@routes.get('/apple-touch-icon.png')
async def apple_touch_icon(request):
    return web.FileResponse('./static/apple-touch-icon.png')

@routes.get('/og-image.png')
async def og_image(request):
    # Public: used by Telegram/social preview bots
    return web.FileResponse('./static/og-image.png')

@routes.get('/og-meeting.png')
async def og_meeting_image(request):
    # Public: OG image for meeting share links
    return web.FileResponse('./static/og-meeting.png')

@routes.get('/og-meeting.jpg')
async def og_meeting_image_jpg(request):
    # Public: compressed OG image for meeting share links (Telegram-compatible)
    return web.FileResponse('./static/og-meeting.jpg')

@routes.get('/og-proposal.png')
async def og_proposal_image(request):
    # Public: OG image for proposal share links
    return web.FileResponse('./static/og-proposal.png')

# ========== Commercial Proposal ==========

@routes.get('/proposal/{token}/edit')
async def proposal_edit_page(request):
    """Serve proposal editor page (auth required via middleware)."""
    return web.FileResponse('./static/proposal-edit.html')

@routes.get('/proposal/{token}')
async def proposal_page(request):
    """Serve the public proposal HTML page with dynamic OG meta tags."""
    token = request.match_info['token']
    html_path = './static/proposal.html'

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        return web.Response(status=404, text='Page not found')

    og_title = 'Коммерческое предложение — РусНейроСофт'
    og_description = 'Разработка решений на основе искусственного интеллекта для стартапов и предпринимателей'
    og_url = f'{request.scheme}://{request.host}/proposal/{token}'
    og_image = f'{request.scheme}://{request.host}/og-proposal.png'

    try:
        row = await db.get_commercial_proposal(token)
        if row:
            project_name = row.get('project_name') or ''
            client_name = row.get('client_name') or ''
            if project_name:
                og_title = f'{project_name} — РусНейроСофт'
            if client_name and project_name:
                og_description = f'Коммерческое предложение по проекту «{project_name}» для {client_name}'
            elif project_name:
                og_description = f'Коммерческое предложение по проекту «{project_name}»'
    except Exception:
        pass

    html = html.replace('{{OG_TITLE}}', og_title)
    html = html.replace('{{OG_DESCRIPTION}}', og_description)
    html = html.replace('{{OG_URL}}', og_url)
    html = html.replace('{{OG_IMAGE}}', og_image)

    return web.Response(text=html, content_type='text/html', charset='utf-8')

@routes.get('/api/proposal/{token}')
async def proposal_api(request):
    """Return proposal data as JSON (public, no auth)."""
    token = request.match_info['token']
    try:
        row = await db.get_commercial_proposal(token)
        if not row:
            return web.json_response({'error': 'not_found'}, status=404)

        estimation = row.get('estimation') or {}
        if isinstance(estimation, str):
            estimation = json.loads(estimation)
        config_data = row.get('config_data') or {}
        if isinstance(config_data, str):
            config_data = json.loads(config_data)

        # Enrich creator with calendly_url from STAFF_CONTACTS if missing
        creator = config_data.get('creator') or {}
        if 'calendly_url' not in creator:
            tg = (creator.get('telegram') or '').lstrip('@')
            staff_contact = config.STAFF_CONTACTS.get(tg, {})
            creator['calendly_url'] = staff_contact.get('calendly_url', '')
            config_data['creator'] = creator

        return web.json_response({
            'token': row['token'],
            'project_name': row.get('project_name'),
            'client_name': row.get('client_name'),
            'proposal_type': row.get('proposal_type'),
            'design_type': row.get('design_type'),
            'currency': row.get('currency', '$'),
            'hourly_rate': float(row['hourly_rate']) if row.get('hourly_rate') else 0,
            'estimation': estimation,
            'config_data': config_data,
            'created_at': row['created_at'].isoformat() if row.get('created_at') else None,
            'client_id': row.get('client_id'),
            'client_uuid': str(row['client_uuid']) if row.get('client_uuid') else None,
            'project_id': row.get('project_id'),
            'proposal_status': row.get('proposal_status', 'draft'),
        })
    except Exception as e:
        logger.error(f"Failed to get proposal {token}: {e}", exc_info=True)
        return web.json_response({'error': 'server_error'}, status=500)

@routes.get('/api/proposals')
async def proposals_list_api(request):
    """Return proposals. Sellers see only their own."""
    try:
        session = request.get('session', {})
        if session.get('role') == 'seller':
            tid = int(session.get('telegram_id', 0))
            rows = await db.get_seller_proposals(tid) if tid else []
        else:
            rows = await db.get_all_commercial_proposals()
        return web.json_response([{
            'token': r['token'],
            'project_name': r.get('project_name'),
            'client_name': r.get('client_name'),
            'proposal_type': r.get('proposal_type'),
            'design_type': r.get('design_type'),
            'currency': r.get('currency', '$'),
            'hourly_rate': float(r['hourly_rate']) if r.get('hourly_rate') else 0,
            'created_at': r['created_at'].isoformat() if r.get('created_at') else None,
            'updated_at': r['updated_at'].isoformat() if r.get('updated_at') else None,
            'client_id': r.get('client_id'),
            'client_uuid': str(r['client_uuid']) if r.get('client_uuid') else None,
            'project_id': r.get('project_id'),
            'proposal_status': r.get('proposal_status', 'draft'),
            'client_display_name': r.get('client_display_name'),
            'client_company': r.get('client_company'),
        } for r in rows])
    except Exception as e:
        logger.error(f"Failed to list proposals: {e}", exc_info=True)
        return web.json_response({'error': 'server_error'}, status=500)

@routes.patch('/api/proposal/{token}')
async def proposal_update_api(request):
    """Update proposal (auth required)."""
    token = request.match_info['token']
    try:
        data = await request.json()
        updated = await db.update_commercial_proposal(
            token,
            project_name=data.get('project_name'),
            client_name=data.get('client_name'),
            hourly_rate=data.get('hourly_rate'),
            currency=data.get('currency'),
            estimation=data.get('estimation'),
            proposal_type=data.get('proposal_type'),
            design_type=data.get('design_type'),
            client_id=data.get('client_id'),
            project_id=data.get('project_id'),
            proposal_status=data.get('proposal_status'),
        )
        if not updated:
            return web.json_response({'error': 'not_found'}, status=404)

        estimation = updated.get('estimation') or {}
        if isinstance(estimation, str):
            estimation = json.loads(estimation)

        return web.json_response({
            'token': updated['token'],
            'project_name': updated.get('project_name'),
            'client_name': updated.get('client_name'),
            'proposal_type': updated.get('proposal_type'),
            'design_type': updated.get('design_type'),
            'currency': updated.get('currency', '$'),
            'hourly_rate': float(updated['hourly_rate']) if updated.get('hourly_rate') else 0,
            'estimation': estimation,
            'updated_at': updated['updated_at'].isoformat() if updated.get('updated_at') else None,
            'client_id': updated.get('client_id'),
            'project_id': updated.get('project_id'),
            'proposal_status': updated.get('proposal_status', 'draft'),
        })
    except Exception as e:
        logger.error(f"Failed to update proposal {token}: {e}", exc_info=True)
        return web.json_response({'error': 'server_error'}, status=500)

@routes.patch('/api/proposal/{token}/discount')
async def proposal_discount_api(request):
    """Set discount percent on a proposal."""
    require_session(request)
    token = request.match_info['token']
    try:
        body = await request.json()
        discount = int(body.get('discount_percent', 0))
        if discount < 0 or discount > 100:
            return web.json_response({'error': 'discount must be 0-100'}, status=400)
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE commercial_proposals SET discount_percent = $1, updated_at = NOW() "
                "WHERE token = $2 RETURNING token, discount_percent",
                discount, token,
            )
        if not row:
            return web.json_response({'error': 'not_found'}, status=404)
        return web.json_response({'ok': True, 'discount_percent': row['discount_percent']})
    except Exception as e:
        logger.error(f"Failed to update discount for {token}: {e}")
        return web.json_response({'error': 'server_error'}, status=500)


@routes.delete('/api/proposal/{token}')
async def proposal_delete_api(request):
    """Delete proposal (auth required)."""
    token = request.match_info['token']
    try:
        deleted = await db.delete_commercial_proposal(token)
        if not deleted:
            return web.json_response({'error': 'not_found'}, status=404)
        return web.json_response({'ok': True})
    except Exception as e:
        logger.error(f"Failed to delete proposal {token}: {e}", exc_info=True)
        return web.json_response({'error': 'server_error'}, status=500)


@routes.post('/api/proposal/{token}/regenerate')
async def proposal_regenerate_api(request):
    """Regenerate proposal estimation using AI. Auth required."""
    require_session(request)
    token = request.match_info['token']
    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    description = body.get('description', '').strip()
    if not description:
        return web.json_response({'error': 'description required'}, status=400)

    proposal_type = body.get('proposal_type', 'mvp')
    design_type = body.get('design_type', 'no_design')
    hourly_rate = float(body.get('hourly_rate', 0))
    currency = body.get('currency', '$')
    budget = body.get('budget')
    budget_currency = body.get('budget_currency', currency)

    if hourly_rate <= 0:
        return web.json_response({'error': 'invalid hourly_rate'}, status=400)

    if budget is not None:
        try:
            budget = float(budget)
            if budget <= 0:
                budget = None
        except (ValueError, TypeError):
            budget = None

    openrouter_key = os.getenv('OPENROUTER_API_KEY', '')
    if not openrouter_key:
        return web.json_response({'error': 'AI service not configured'}, status=500)

    calculator = ProposalCalculator(openrouter_key)
    try:
        estimation = await calculator.calculate_proposal(
            project_description=description,
            proposal_type=proposal_type,
            budget_constraint=budget,
            budget_currency=budget_currency,
            design_type=design_type,
            hourly_rate=hourly_rate,
            currency=currency,
        )
    except Exception as e:
        logger.error(f"Proposal regeneration failed: {e}", exc_info=True)
        return web.json_response({'error': 'generation_failed'}, status=500)

    if estimation.get('error'):
        return web.json_response({'error': estimation.get('error_message', 'generation failed')}, status=500)

    try:
        await db.update_commercial_proposal(
            token,
            estimation=estimation,
            proposal_type=proposal_type,
            design_type=design_type,
            hourly_rate=hourly_rate,
            currency=currency,
            project_name=estimation.get('project_name', ''),
        )
    except Exception as e:
        logger.error(f"Failed to save regenerated proposal: {e}", exc_info=True)
        return web.json_response({'error': 'save_failed'}, status=500)

    proposal = await db.get_commercial_proposal(token)
    if not proposal:
        return web.json_response({'error': 'not_found'}, status=404)

    return web.json_response({
        'ok': True,
        'token': proposal['token'],
        'project_name': proposal['project_name'],
        'client_name': proposal.get('client_name', ''),
        'proposal_type': proposal.get('proposal_type', 'mvp'),
        'design_type': proposal.get('design_type', 'no_design'),
        'currency': proposal.get('currency', '$'),
        'hourly_rate': float(proposal.get('hourly_rate', 0)),
        'estimation': proposal.get('estimation', {}),
        'client_id': proposal.get('client_id'),
        'client_uuid': proposal.get('client_uuid'),
    })


# ========== API Endpoints ==========

import random

PRIZES = [5000, 10000, 15000, 20000, 25000, 30000]

@routes.get('/api/can-spin')
async def can_spin(request):
    """Check if user can spin the roulette"""
    try:
        telegram_id = request.query.get('telegram_id')
        
        if not telegram_id:
            return web.json_response({'error': 'telegram_id required'}, status=400)
        
        telegram_id = int(telegram_id)
        can_spin = await db.can_spin_roulette(telegram_id)
        
        # Also get prize if already spun
        prize = await db.get_user_prize(telegram_id) if not can_spin else None
        
        return web.json_response({
            'can_spin': can_spin,
            'prize': prize
        })
    except Exception as e:
        logger.error(f"Error in can-spin endpoint: {e}")
        return web.json_response({'error': str(e)}, status=500)

@routes.post('/api/spin')
async def spin_roulette(request):
    """Spin the roulette and return prize"""
    try:
        data = await request.json()
        telegram_id = data.get('telegram_id')
        
        if not telegram_id:
            return web.json_response({'error': 'telegram_id required'}, status=400)
        
        telegram_id = int(telegram_id)
        
        # Check if can spin
        if not await db.can_spin_roulette(telegram_id):
            prize = await db.get_user_prize(telegram_id)
            return web.json_response({
                'error': 'Already spun',
                'prize': prize
            }, status=400)
        
        # Select random prize with equal probability
        prize = random.choice(PRIZES)
        
        # Save to database
        await db.save_roulette_spin(telegram_id, prize)
        
        logger.info(f"User {telegram_id} won {prize} RUB")
        
        # Send notification to user
        message_text = f"""
🎉 **Поздравляем!**

Вы выиграли скидку **{prize:,} ₽** на услуги нашей компании!

💰 Эта сумма будет вычтена из стоимости разработки вашего проекта.

📞 Свяжитесь с нами, чтобы использовать скидку:
• Сайт: {config.company_website}
• Email: {config.company_email}
• Телефон: {config.company_phone}

Спасибо за участие! 🚀
        """.strip()
        
        # Send message asynchronously (don't wait for result)
        await send_telegram_message(telegram_id, message_text)
        
        return web.json_response({'prize': prize})
    
    except Exception as e:
        logger.error(f"Error in spin endpoint: {e}")
        return web.json_response({'error': str(e)}, status=500)

@routes.get('/api/health')
async def health(request):
    """Health check endpoint"""
    return web.json_response({'status': 'ok'})


# ========== Authentication ==========

BOT_USERNAME = os.getenv('BOT_USERNAME', '')

async def get_session(request) -> dict | None:
    """Read session_token cookie and return valid session or None."""
    token = request.cookies.get('session_token')
    if not token:
        return None
    return await db.get_web_session(token)


@routes.get('/login')
async def login_page(request):
    """Serve login page (no auth required)."""
    return web.FileResponse('./static/login.html')


@routes.get('/auth/callback')
async def auth_callback(request):
    """Validate session token from query param, set cookie, redirect."""
    from urllib.parse import unquote
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
    """Clear session cookie and redirect to login."""
    resp = web.HTTPFound('/login')
    resp.del_cookie('session_token', path='/')
    return resp


@routes.get('/api/auth/bot-info')
async def auth_bot_info(request):
    """Return bot username for login page (public)."""
    bot_username = os.getenv('BOT_USERNAME', '')
    return web.json_response({'bot_username': bot_username})


@routes.get('/api/auth/me')
async def auth_me(request):
    """Return current user info from session."""
    session = await get_session(request)
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
    """Redirect authenticated client to their personal cabinet."""
    session = await get_session(request)
    if not session:
        raise web.HTTPFound('/login?next=/my-cabinet')
    tg_id = session.get('telegram_id')
    if not tg_id:
        raise web.HTTPFound('/login')
    client = await db.get_client_by_telegram_id(int(tg_id))
    if client and client.get('cabinet_token'):
        raise web.HTTPFound(f"/cabinet/{client['cabinet_token']}")
    raise web.HTTPFound('/login')


def _validate_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp initData using HMAC-SHA256.
    Returns parsed params dict if valid, None if invalid.
    """
    from urllib.parse import parse_qsl
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


@routes.post('/api/auth/telegram')
async def auth_telegram(request):
    """Authenticate using Telegram WebApp initData (auto-login from Mini App)."""
    from datetime import datetime, timedelta
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

    # Auto-create user if not in DB
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

_WEBAPP_URL = os.getenv('WEBAPP_URL', '')
_IS_DEV = (
    os.getenv('APP_ENV', 'production') == 'development'
    or _WEBAPP_URL.startswith('http://localhost')
    or _WEBAPP_URL.startswith('http://127.0.0.1')
)


@routes.get('/api/auth/dev-users')
async def auth_dev_users(request):
    """Return users grouped by role. Only available in development."""
    if not _IS_DEV:
        return web.json_response({'error': 'not available'}, status=404)
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
    from datetime import datetime, timedelta
    if not _IS_DEV:
        return web.json_response({'error': 'not available'}, status=404)
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


# Paths that never require authentication
_PUBLIC_PREFIXES = (
    '/login', '/auth/callback', '/auth/logout', '/api/auth/bot-info', '/api/auth/telegram',
    '/api/auth/dev-users', '/api/auth/dev-login',
    '/api/health', '/api/zoom/webhook',
    '/css/', '/js/', '/style.css', '/script.js', '/sidebar.js', '/chat-widget.js',
    '/logo.png', '/img/', '/favicon.ico', '/apple-touch-icon.png',
    '/og-image.png', '/og-meeting.png', '/og-meeting.jpg', '/og-proposal.png',
    '/api/can-spin', '/api/spin',
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


@web.middleware
async def auth_middleware(request, handler):
    path = request.path
    method = request.method

    # Roulette root page — public
    if path == '/':
        return await handler(request)

    # Static/public routes
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return await handler(request)

    # Cabinet routes: public, but attach session if present (staff preview mode)
    if path.startswith('/cabinet/') or path.startswith('/api/cabinet/'):
        session = await get_session(request)
        if session:
            request['session'] = session
        return await handler(request)

    # Proposal routes: public GET for viewing, auth required for edit/list/modify
    if path.startswith('/proposal/') or path.startswith('/api/proposal/'):
        if '/edit' in path:
            pass  # requires auth — fall through
        elif method == 'GET' and path.startswith('/api/proposal/'):
            return await handler(request)
        elif method == 'GET' and path.startswith('/proposal/'):
            return await handler(request)
        # PATCH, DELETE, etc. — fall through to require auth

    # Meeting pages/API: allow if meeting is_public or user has session
    if path.startswith('/meeting/') or path.startswith('/api/meeting/'):
        session = await get_session(request)
        if session:
            request['session'] = session
            # Users can only access public meetings
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
        # No session — check if meeting is public
        parts = path.split('/')
        token_idx = 3 if path.startswith('/api/') else 2
        if len(parts) > token_idx:
            meeting_token = parts[token_idx]
            meeting = await db.get_meeting_by_public_token(meeting_token)
            if meeting and meeting.get('is_public'):
                return await handler(request)
        # Not public — redirect or 401
        if path.startswith('/api/'):
            return web.json_response({'error': 'unauthorized'}, status=401)
        raise web.HTTPFound(f'/login?next={path}')

    # All other protected routes
    session = await get_session(request)
    if not session:
        if path.startswith('/api/'):
            return web.json_response({'error': 'unauthorized'}, status=401)
        raise web.HTTPFound(f'/login?next={path}')

    request['session'] = session
    role = session.get('role', 'user')

    # Admin-only routes
    for prefix in _ADMIN_ONLY_PREFIXES:
        if path.startswith(prefix) and role != 'admin':
            if path.startswith('/api/'):
                return web.json_response({'error': 'admin only'}, status=403)
            raise web.HTTPFound('/login')

    # Redirect user/seller away from staff pages to their personal cabinets
    if role == 'user':
        for prefix in _STAFF_ONLY_PREFIXES:
            if path.startswith(prefix):
                if path.startswith('/api/'):
                    return web.json_response({'error': 'access denied'}, status=403)
                raise web.HTTPFound('/my-cabinet')
    elif role == 'seller':
        _seller_blocked_pages = (
            '/projects', '/project/', '/employees',
            '/proposals',
        )
        for prefix in _seller_blocked_pages:
            if path.startswith(prefix):
                raise web.HTTPFound('/seller')
        for prefix in _STAFF_ONLY_PREFIXES:
            if path.startswith(prefix) and not path.startswith('/seller'):
                if path.startswith('/api/'):
                    return web.json_response({'error': 'access denied'}, status=403)
                raise web.HTTPFound('/seller')

    return await handler(request)


def require_session(request):
    """Raise 401 if request has no authenticated session (public viewer)."""
    if 'session' not in request:
        raise web.HTTPUnauthorized(
            text=json.dumps({'error': 'unauthorized'}),
            content_type='application/json',
        )


def require_staff_session(request):
    """Raise 401/403 if no session or user role is 'user' (staff/admin only)."""
    require_session(request)
    if request['session'].get('role') == 'user':
        raise web.HTTPForbidden(
            text=json.dumps({'error': 'staff or admin access required'}),
            content_type='application/json',
        )


# ========== Meeting Page ==========

@routes.get('/meeting/{token}')
async def meeting_page(request):
    """Serve meeting detail page with Open Graph meta tags for social previews."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)

    og_title = 'Детали встречи'
    og_description = 'Запись встречи на портале РусНейроСофт'
    og_image = f'{config.webapp_url}/og-meeting.jpg'
    og_url = f'{config.webapp_url}/meeting/{token}'

    if meeting:
        topic = meeting.get('topic', '') or 'Встреча'
        og_title = topic
        dur = meeting.get('duration', 0)
        host = meeting.get('host_name', '')
        parts = []
        if dur:
            parts.append(f"{dur // 60} ч {dur % 60} мин" if dur >= 60 else f"{dur} мин")
        if host:
            parts.append(f"Организатор: {host}")
        summary_raw = (meeting.get('summary') or '').replace('\n', ' ').strip()
        import re as _re
        summary_clean = _re.sub(r'\[[\d:]+\]\s*', '', summary_raw)
        summary_clean = _re.sub(r'[•\-]\s*', '', summary_clean)
        summary_clean = _re.sub(r'\s{2,}', ' ', summary_clean).strip()
        if summary_clean:
            max_len = 180 - len(' · '.join(parts))
            if len(summary_clean) > max_len:
                summary_clean = summary_clean[:max_len].rsplit(' ', 1)[0] + '…'
            parts.append(summary_clean)
        og_description = ' · '.join(parts) if parts else og_description

    def _esc(s):
        return s.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

    og_tags = (
        f'<meta property="og:type" content="article">\n'
        f'    <meta property="og:site_name" content="РусНейроСофт">\n'
        f'    <meta property="og:title" content="{_esc(og_title)}">\n'
        f'    <meta property="og:description" content="{_esc(og_description)}">\n'
        f'    <meta property="og:image" content="{_esc(og_image)}">\n'
        f'    <meta property="og:image:type" content="image/jpeg">\n'
        f'    <meta property="og:image:width" content="1200">\n'
        f'    <meta property="og:image:height" content="630">\n'
        f'    <meta property="og:url" content="{_esc(og_url)}">\n'
        f'    <meta name="twitter:card" content="summary_large_image">\n'
        f'    <meta name="twitter:title" content="{_esc(og_title)}">\n'
        f'    <meta name="twitter:description" content="{_esc(og_description)}">\n'
        f'    <meta name="twitter:image" content="{_esc(og_image)}">'
    )

    html_path = os.path.join(os.path.dirname(__file__), 'static', 'meeting.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    html = html.replace('<title>Детали встречи</title>',
                         f'<title>{_esc(og_title)} — РусНейроСофт</title>\n    {og_tags}')

    return web.Response(
        text=html,
        content_type='text/html',
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache'},
    )

@routes.get('/api/meeting/{token}')
async def meeting_api(request):
    """Return meeting data by public token."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    created_at = meeting.get('created_at')
    start_time = meeting.get('start_time')
    return web.json_response({
        'id': meeting.get('id'),
        'meeting_id': meeting.get('meeting_id'),
        'topic': meeting.get('topic', ''),
        'duration': meeting.get('duration', 0),
        'status': meeting.get('status', ''),
        'recording_url': meeting.get('recording_url', ''),
        'transcript_text': meeting.get('transcript_text', ''),
        'summary': meeting.get('summary', ''),
        'structured_transcript': meeting.get('structured_transcript', ''),
        'host_name': meeting.get('host_name', ''),
        'created_at': created_at.isoformat() if created_at else None,
        'start_time': start_time.isoformat() if start_time else None,
        'join_url': meeting.get('join_url', ''),
        'video_s3_url': meeting.get('video_s3_url', ''),
        'audio_s3_url': meeting.get('audio_s3_url', ''),
        'mindmap_json': meeting.get('mindmap_json', ''),
        'is_public': bool(meeting.get('is_public', False)),
        'public_url': f"{config.webapp_url}/meeting/{token}" if meeting.get('is_public') else None,
    })


@routes.patch('/api/meeting/{token}/visibility')
async def meeting_visibility_toggle(request):
    """Toggle meeting public/private visibility."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    body = await request.json()
    is_public = bool(body.get('is_public', False))
    await db.update_meeting_visibility(meeting['meeting_id'], is_public)

    public_url = f"{config.webapp_url}/meeting/{token}" if is_public else None
    return web.json_response({'is_public': is_public, 'public_url': public_url})


@routes.delete('/api/meeting/{token}')
async def delete_meeting(request):
    """Delete meeting from database, Zoom and S3."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'Meeting not found'}, status=404)

    meeting_id = meeting.get('meeting_id')

    # Delete all files from S3
    if s3_client and meeting_id:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, s3_client.delete_meeting_files, meeting_id)
        except Exception as e:
            logger.warning(f"Failed to delete S3 files for meeting {meeting_id}: {e}")

    # Try to delete recording from Zoom
    if zoom_client and meeting_id:
        try:
            await zoom_client.delete_meeting_recordings(meeting_id)
            logger.info(f"Deleted Zoom recording for meeting {meeting_id}")
        except Exception as e:
            logger.warning(f"Failed to delete Zoom recording for meeting {meeting_id}: {e}")

    # Delete from database
    try:
        await db.delete_meeting(meeting_id)
        logger.info(f"Deleted meeting {meeting_id} from database")
        return web.json_response({'status': 'ok', 'message': 'Meeting deleted successfully'})
    except Exception as e:
        logger.error(f"Failed to delete meeting {meeting_id} from database: {e}")
        return web.json_response({'error': 'Failed to delete meeting from database'}, status=500)

@routes.patch('/api/meeting/{token}/topic')
async def update_meeting_topic(request):
    """Rename meeting topic."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'Meeting not found'}, status=404)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'Invalid JSON'}, status=400)
    topic = (body.get('topic') or '').strip()
    if not topic:
        return web.json_response({'error': 'Topic cannot be empty'}, status=400)
    if len(topic) > 200:
        return web.json_response({'error': 'Topic too long (max 200 chars)'}, status=400)
    try:
        await db.update_meeting_topic(meeting['meeting_id'], topic)
        return web.json_response({'status': 'ok', 'topic': topic})
    except Exception as e:
        logger.error(f"Failed to rename meeting {meeting['meeting_id']}: {e}")
        return web.json_response({'error': 'Failed to update topic'}, status=500)

@routes.post('/api/meeting/{token}/upload-video')
async def upload_meeting_video(request):
    """Upload a local video file, save it to S3 and link it to the meeting."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'Meeting not found'}, status=404)

    meeting_id = meeting.get('meeting_id')

    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({'error': 'Expected multipart/form-data'}, status=400)

    file_bytes = None
    fmt = 'mp4'

    async for field in reader:
        if field.name == 'video':
            filename = field.filename or 'video.mp4'
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp4'
            fmt = ext if ext in ('mp4', 'mov', 'webm', 'avi') else 'mp4'
            chunks = []
            while True:
                chunk = await field.read_chunk(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            file_bytes = b''.join(chunks)
            break

    if not file_bytes:
        return web.json_response({'error': 'No video field in request'}, status=400)

    max_bytes = 2 * 1024 * 1024 * 1024  # 2 GB
    if len(file_bytes) > max_bytes:
        return web.json_response({'error': 'File too large (max 2 GB)'}, status=413)

    try:
        url = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: s3_client.upload_video(meeting_id, file_bytes, fmt),
        )
        if not url:
            return web.json_response({'error': 'S3 upload failed'}, status=500)
        await db.update_meeting_video_url(meeting_id, url)
        logger.info(f"Meeting {meeting_id}: video uploaded via web -> {url}")
        return web.json_response({'status': 'ok', 'video_url': url})
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: upload-video error: {e}")
        return web.json_response({'error': str(e)}, status=500)


@routes.post('/api/meeting/{token}/fetch-zoom-video')
async def fetch_zoom_video(request):
    """Trigger background download of meeting video from Zoom and upload to S3."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'Meeting not found'}, status=404)

    if not zoom_client:
        return web.json_response({'status': 'no_zoom', 'message': 'Zoom не настроен'})

    if not s3_client:
        return web.json_response({'status': 'no_zoom', 'message': 'S3 не настроен'})

    meeting_id = meeting.get('meeting_id')
    asyncio.create_task(_upload_video_to_s3(meeting_id))
    logger.info(f"Meeting {meeting_id}: manual fetch-zoom-video triggered")
    return web.json_response({'status': 'started'})


@routes.post('/api/project/{token}/upload-video')
async def project_upload_video(request):
    """Upload a video file, create a manual meeting record, link to project, start processing."""
    require_session(request)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'project not found'}, status=404)

    session = request.get('session', {})

    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({'error': 'Expected multipart/form-data'}, status=400)

    file_bytes = None
    fmt = 'mp4'
    topic = ''

    async for field in reader:
        if field.name == 'topic':
            topic = (await field.read(decode=True)).decode('utf-8', errors='replace').strip()
        elif field.name == 'video':
            filename = field.filename or 'video.mp4'
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp4'
            fmt = ext if ext in ('mp4', 'mov', 'webm', 'avi', 'mkv') else 'mp4'
            if not topic:
                topic = filename.rsplit('.', 1)[0][:200]
            chunks = []
            while True:
                chunk = await field.read_chunk(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            file_bytes = b''.join(chunks)

    if not file_bytes:
        return web.json_response({'error': 'No video field in request'}, status=400)

    max_bytes = 2 * 1024 * 1024 * 1024
    if len(file_bytes) > max_bytes:
        return web.json_response({'error': 'File too large (max 2 GB)'}, status=413)

    meeting = await db.create_manual_meeting(
        topic=topic or 'Загруженное видео',
        host_telegram_id=session.get('telegram_id', 0),
        host_name=session.get('first_name') or session.get('username') or 'Unknown',
    )
    if not meeting:
        return web.json_response({'error': 'Failed to create meeting record'}, status=500)

    try:
        await db.add_meeting_to_project(project['id'], meeting['id'])
    except Exception as e:
        logger.error(f"Failed to link uploaded meeting to project: {e}")

    asyncio.create_task(_process_uploaded_video(meeting['meeting_id'], meeting['id'], file_bytes, fmt, project['id']))

    return web.json_response({
        'status': 'ok',
        'meeting_id': meeting['meeting_id'],
        'db_id': meeting['id'],
        'public_token': meeting['public_token'],
        'topic': topic or 'Загруженное видео',
    })


async def _process_uploaded_video(meeting_id: int, db_id: int, file_bytes: bytes, fmt: str, project_id: int):
    """Background: upload video to S3, extract audio, transcribe, summarise, embed."""
    import tempfile

    try:
        if s3_client:
            url = await asyncio.get_event_loop().run_in_executor(
                None, lambda: s3_client.upload_video(meeting_id, file_bytes, fmt))
            if url:
                await db.update_meeting_video_url(meeting_id, url)
                logger.info(f"Manual meeting {meeting_id}: video uploaded to S3 -> {url}")
    except Exception as e:
        logger.error(f"Manual meeting {meeting_id}: S3 video upload error: {e}")

    audio_bytes = None
    audio_fmt = "mp3"
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as src:
            src.write(file_bytes)
            src_path = src.name
        dst_path = src_path.rsplit(".", 1)[0] + ".mp3"
        rc, _, stderr = await _run_ffmpeg(
            "-y", "-i", src_path, "-vn", "-b:a", "128k", "-f", "mp3", dst_path,
            timeout=300,
        )
        os.unlink(src_path)
        del file_bytes
        if rc == 0:
            with open(dst_path, "rb") as f:
                audio_bytes = f.read()
            os.unlink(dst_path)
            logger.info(f"Manual meeting {meeting_id}: audio extracted ({len(audio_bytes)} bytes)")

            if s3_client:
                try:
                    audio_url = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: s3_client.upload_audio(meeting_id, audio_bytes, audio_fmt))
                    if audio_url:
                        await db.update_meeting_audio_url(meeting_id, audio_url)
                except Exception as e:
                    logger.error(f"Manual meeting {meeting_id}: S3 audio upload error: {e}")
        else:
            logger.error(f"Manual meeting {meeting_id}: ffmpeg audio extraction failed: {stderr.decode()[:500]}")
            if os.path.exists(src_path):
                os.unlink(src_path)
    except Exception as e:
        logger.error(f"Manual meeting {meeting_id}: audio extraction error: {e}")

    await db.update_meeting_status(meeting_id, 'recorded')

    if audio_bytes:
        await db.update_meeting_status(meeting_id, 'transcribing')
        await _auto_transcribe_audio(meeting_id, provided_audio=audio_bytes, provided_audio_fmt=audio_fmt)

    meeting_data = await db.get_zoom_meeting(meeting_id)
    if meeting_data and meeting_data.get('transcript_text'):
        await db.update_meeting_status(meeting_id, 'finished')
    elif audio_bytes:
        await db.update_meeting_status(meeting_id, 'recorded')
        try:
            dur_seconds = len(audio_bytes) / 16000 if audio_bytes else 0
            dur_minutes = max(1, int(dur_seconds / 60)) if dur_seconds else 0
            if dur_minutes:
                async with db.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE zoom_meetings SET duration = $2 WHERE meeting_id = $1",
                        meeting_id, dur_minutes)
        except Exception:
            pass

    try:
        await _embed_meeting_safe(project_id, db_id)
    except Exception as e:
        logger.error(f"Manual meeting {meeting_id}: embedding error: {e}")

    logger.info(f"Manual meeting {meeting_id}: processing complete")


@routes.post('/api/meeting/{token}/chat')
async def meeting_chat(request):
    """AI chat grounded in the meeting transcript."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    body = await request.json()
    question = body.get('question', '')
    history = body.get('history', [])
    use_power_model = body.get('model') == 'power'

    transcript = meeting.get('transcript_text', '') or ''
    summary = meeting.get('summary', '') or ''
    structured_raw = meeting.get('structured_transcript', '') or ''

    # Build structured timeline for better timecodes
    structured_timeline = ''
    if structured_raw:
        try:
            st = json.loads(structured_raw) if isinstance(structured_raw, str) else structured_raw
            if isinstance(st, dict) and 'items' in st:
                parts = []
                for item in st['items']:
                    tc = item.get('start_time', '')
                    if tc:
                        tc_short = tc.lstrip('0').lstrip(':').lstrip('0') or '0:00'
                        parts.append(f"[{tc_short}] {item.get('label', '')}: {item.get('summary', '')}")
                structured_timeline = '\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

    if not question:
        return web.json_response({'answer': 'Пожалуйста, задайте вопрос.'})

    api_key = os.getenv('OPENROUTER_API_KEY')
    _POWER_MODEL = 'anthropic/claude-opus-4-5'
    model = _POWER_MODEL if use_power_model else os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key:
        return web.json_response({'answer': 'AI-сервис временно недоступен.'})

    system_prompt = (
        "Ты — AI-ассистент, который отвечает на вопросы по содержанию встречи.\n"
        "Отвечай на русском языке. Будь максимально точен и полон.\n\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "1. К КАЖДОМУ упоминанию факта или момента ОБЯЗАТЕЛЬНО добавляй таймкод [MM:SS] из транскрипции.\n"
        "2. Если тема упоминалась НЕСКОЛЬКО РАЗ — перечисли ВСЕ упоминания с разными таймкодами.\n"
        "3. Формат таймкода: [MM:SS] — прямо в тексте рядом с фактом.\n"
        "4. Не пропускай ни одного релевантного упоминания — пользователю нужна ПОЛНАЯ картина.\n"
        "5. Структурируй ответ: если упоминаний много, используй нумерованный список.\n"
        "6. Если в транскрипции нет информации по вопросу — честно скажи об этом.\n\n"
        f"## Саммари встречи\n{summary[:4000]}\n\n"
    )
    if structured_timeline:
        system_prompt += f"## Структурированная хронология встречи\n{structured_timeline[:15000]}\n\n"
    system_prompt += f"## Полная транскрипция встречи\n{transcript[:50000]}"

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-8:]:
        if h.get('role') in ('user', 'assistant'):
            messages.append({"role": h['role'], "content": h['content'][:2000]})
    messages.append({"role": "user", "content": question[:2000]})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 4000 if use_power_model else 2000,
                    **({"provider": {"ignore": ["Google AI Studio"]}} if use_power_model else {}),
                },
            ) as resp:
                data = await resp.json()
                answer = data["choices"][0]["message"]["content"].strip()
                return web.json_response({'answer': answer, 'model_used': 'power' if use_power_model else 'default'})
    except Exception as e:
        logger.error(f"Meeting chat error: {e}")
        return web.json_response({'answer': 'Произошла ошибка при обработке запроса.'})


@routes.get('/api/meeting/{token}/brainstorm/threads')
async def brainstorm_threads_list(request):
    """List all brainstorm threads for the current user and meeting."""
    require_session(request)
    session = request.get('session', {})
    telegram_id = session.get('telegram_id')
    token = request.match_info['token']
    threads = await db.get_brainstorm_threads(token, telegram_id)
    result = []
    for t in threads:
        result.append({
            'id': t['id'],
            'title': t['title'],
            'created_at': t['created_at'].isoformat() if t.get('created_at') else None,
            'updated_at': t['updated_at'].isoformat() if t.get('updated_at') else None,
        })
    return web.json_response(result)


@routes.post('/api/meeting/{token}/brainstorm/threads')
async def brainstorm_thread_create(request):
    """Create a new brainstorm thread."""
    require_session(request)
    session = request.get('session', {})
    telegram_id = session.get('telegram_id')
    token = request.match_info['token']
    body = await request.json()
    title = (body.get('title') or 'Новая тема').strip()[:200]
    thread = await db.create_brainstorm_thread(token, telegram_id, title)
    return web.json_response({
        'id': thread['id'],
        'title': thread['title'],
        'created_at': thread['created_at'].isoformat() if thread.get('created_at') else None,
        'updated_at': thread['updated_at'].isoformat() if thread.get('updated_at') else None,
    })


@routes.patch('/api/meeting/{token}/brainstorm/threads/{thread_id}')
async def brainstorm_thread_rename(request):
    """Rename a brainstorm thread."""
    require_session(request)
    session = request.get('session', {})
    telegram_id = session.get('telegram_id')
    thread_id = int(request.match_info['thread_id'])
    body = await request.json()
    title = (body.get('title') or '').strip()[:200]
    if not title:
        return web.json_response({'error': 'title required'}, status=400)
    ok = await db.rename_brainstorm_thread(thread_id, telegram_id, title)
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True, 'title': title})


@routes.delete('/api/meeting/{token}/brainstorm/threads/{thread_id}')
async def brainstorm_thread_delete(request):
    """Delete a brainstorm thread and all its messages."""
    require_session(request)
    session = request.get('session', {})
    telegram_id = session.get('telegram_id')
    thread_id = int(request.match_info['thread_id'])
    ok = await db.delete_brainstorm_thread(thread_id, telegram_id)
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True})


@routes.get('/api/meeting/{token}/brainstorm/threads/{thread_id}/messages')
async def brainstorm_thread_messages(request):
    """Get all messages for a brainstorm thread."""
    require_session(request)
    session = request.get('session', {})
    telegram_id = session.get('telegram_id')
    thread_id = int(request.match_info['thread_id'])
    messages = await db.get_brainstorm_messages(thread_id, telegram_id)
    return web.json_response([{
        'id': m['id'],
        'role': m['role'],
        'content': m['content'],
        'created_at': m['created_at'].isoformat() if m.get('created_at') else None,
    } for m in messages])


@routes.post('/api/meeting/{token}/brainstorm')
async def meeting_brainstorm(request):
    """AI brainstorm chat — deep analysis of the full meeting transcript without timecodes."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    body = await request.json()
    question = body.get('question', '')
    history = body.get('history', [])
    use_power_model = body.get('model') == 'power'
    thread_id = body.get('thread_id')
    session = request.get('session', {})
    telegram_id = session.get('telegram_id')

    transcript = meeting.get('transcript_text', '') or ''
    summary = meeting.get('summary', '') or ''
    structured_raw = meeting.get('structured_transcript', '') or ''

    structured_text = ''
    if structured_raw:
        try:
            st = json.loads(structured_raw) if isinstance(structured_raw, str) else structured_raw
            if isinstance(st, dict) and 'items' in st:
                parts = []
                for item in st['items']:
                    parts.append(f"- {item.get('label', '')}: {item.get('summary', '')}")
                structured_text = '\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

    if not question:
        return web.json_response({'answer': 'Пожалуйста, задайте вопрос.'})

    api_key = os.getenv('OPENROUTER_API_KEY')
    _POWER_MODEL = 'anthropic/claude-opus-4-5'
    model = _POWER_MODEL if use_power_model else os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key:
        return web.json_response({'answer': 'AI-сервис временно недоступен.'})

    system_prompt = (
        "Ты — AI-партнёр для мозгового штурма. Тебе доступна полная транскрипция встречи.\n"
        "Твоя задача — помогать пользователю глубоко анализировать содержание встречи:\n\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "1. Отвечай развёрнуто, глубоко и аналитически.\n"
        "2. НЕ добавляй таймкоды — фокусируйся на содержании и смысле.\n"
        "3. Помогай находить скрытые инсайты, паттерны и связи между обсуждаемыми темами.\n"
        "4. Предлагай идеи, развивай мысли, задавай уточняющие вопросы.\n"
        "5. Если пользователь просит проанализировать проблему — структурируй ответ: проблема, причины, варианты решения, рекомендации.\n"
        "6. Если пользователь просит генерировать идеи — будь креативен, предлагай нестандартные подходы.\n"
        "7. Используй Markdown для форматирования: заголовки, списки, жирный текст.\n"
        "8. Отвечай на русском языке.\n\n"
        f"## Саммари встречи\n{summary[:6000]}\n\n"
    )
    if structured_text:
        system_prompt += f"## Структурированный обзор встречи\n{structured_text[:20000]}\n\n"
    system_prompt += f"## Полная транскрипция встречи\n{transcript[:80000]}"

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-10:]:
        if h.get('role') in ('user', 'assistant'):
            messages.append({"role": h['role'], "content": h['content'][:3000]})
    messages.append({"role": "user", "content": question[:3000]})

    try:
        async with aiohttp.ClientSession() as ai_sess:
            async with ai_sess.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 6000 if use_power_model else 3000,
                    **({"provider": {"ignore": ["Google AI Studio"]}} if use_power_model else {}),
                },
            ) as resp:
                data = await resp.json()
                answer = data["choices"][0]["message"]["content"].strip()

        # Persist to DB if thread_id provided
        if thread_id and telegram_id:
            try:
                await db.add_brainstorm_message(thread_id, 'user', question)
                await db.add_brainstorm_message(thread_id, 'assistant', answer)
                # Auto-title thread from first message if still default
                threads = await db.get_brainstorm_threads(token, telegram_id)
                thread = next((t for t in threads if t['id'] == thread_id), None)
                if thread and thread['title'] == 'Новая тема':
                    short_title = question[:60].strip()
                    if len(question) > 60:
                        short_title += '…'
                    await db.rename_brainstorm_thread(thread_id, telegram_id, short_title)
            except Exception as e:
                logger.warning(f"Failed to save brainstorm messages: {e}")

        return web.json_response({'answer': answer, 'model_used': 'power' if use_power_model else 'default'})
    except Exception as e:
        logger.error(f"Meeting brainstorm error: {e}")
        return web.json_response({'answer': 'Произошла ошибка при обработке запроса.'})


@routes.post('/api/meeting/{token}/mindmap')
async def meeting_mindmap(request):
    """Generate an AI-powered mind map (Markdown for Markmap) from meeting transcript/summary."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    api_key = os.getenv('OPENROUTER_API_KEY')
    model = 'anthropic/claude-opus-4.6'
    if not api_key:
        return web.json_response({'error': 'AI service unavailable'}, status=503)

    transcript = meeting.get('transcript_text', '') or ''
    summary = meeting.get('summary', '') or ''
    structured_raw = meeting.get('structured_transcript', '') or ''

    # Build structured text from Zoom AI Summary or AI-generated structured transcript
    structured_text = ''
    if structured_raw:
        try:
            st = json.loads(structured_raw) if isinstance(structured_raw, str) else structured_raw
            if isinstance(st, dict) and 'items' in st:
                parts = []
                if st.get('overall_summary'):
                    parts.append(f"ОБЩЕЕ РЕЗЮМЕ: {st['overall_summary']}\n")
                for item in st['items']:
                    label = (item.get('label') or '').strip()
                    item_summary = (item.get('summary') or '').strip()
                    if not label and not item_summary:
                        continue
                    ts = item.get('start_time', '')
                    te = item.get('end_time', '')
                    parts.append(f"### [{ts} — {te}] {label}\n{item_summary}")
                structured_text = '\n\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

    if not transcript and not summary and not structured_text:
        return web.json_response({'error': 'Нет данных для генерации карты'}, status=400)

    # Build the richest possible context
    context_parts = []
    if structured_text:
        context_parts.append(f"## Подробная хронология встречи (по разделам)\n{structured_text[:30000]}")
    if summary:
        context_parts.append(f"## Общее саммари\n{summary[:6000]}")
    if transcript:
        context_parts.append(f"## Полная транскрипция\n{transcript[:60000]}")
    meeting_context = '\n\n---\n\n'.join(context_parts)

    prompt = (
        "Ты — эксперт по систематизации информации и визуальному мышлению.\n"
        "Проанализируй ПОЛНОСТЬЮ все материалы деловой встречи ниже и создай МАКСИМАЛЬНО подробную "
        "и детализированную интеллектуальную карту в формате Markdown (для визуализации через Markmap).\n\n"
        "КРИТИЧЕСКИ ВАЖНО:\n"
        "- Захвати ВСЮ ценную информацию из встречи — каждое решение, инсайт, задачу, идею, цифру\n"
        "- Для каждой темы извлеки МАКСИМУМ деталей: конкретные проекты, имена, суммы, сроки, решения\n"
        "- Если участники упоминали конкретные действия ('надо сделать', 'создать задачу', 'проверить') — "
        "обязательно отрази их как **Action item: ...** (выделено жирным)\n"
        "- НЕ обобщай слишком сильно — лучше больше деталей, чем потерять информацию\n\n"
        "Структура:\n"
        "- # — тема встречи (корень карты)\n"
        "- ## — основные темы/блоки обсуждения (по хронологии + группировка)\n"
        "- ### — подтемы, если тема большая\n"
        "- Маркированный список (-) — конкретные факты, решения, цифры\n"
        "  - Вложенные уровни — детали и контекст\n"
        "- **Жирный текст** — action items, ключевые решения, задачи\n\n"
        "Правила:\n"
        "1. Количество тем (##) — столько, сколько реально было (от 3 до 15+)\n"
        "2. Под каждой темой — 3-8 конкретных пунктов с деталями\n"
        "3. Все action items и задачи — обязательно жирным **Action item: ...**\n"
        "4. Добавляй таймкоды [HH:MM:SS] к ключевым моментам\n"
        "5. Имена участников, проекты, суммы, проценты — всё фиксируй\n"
        "6. Формат ответа: ТОЛЬКО markdown. Без пояснений, без ```code fences```, без вводных фраз\n\n"
        "---\n\n"
        f"{meeting_context}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 8000,
                    "provider": {"ignore": ["Google AI Studio"]},
                },
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                data = await resp.json(content_type=None)
                choices = data.get("choices") if isinstance(data, dict) else None
                if not choices:
                    api_err = (data or {}).get("error", {})
                    if isinstance(api_err, dict):
                        err_msg = api_err.get("message", str(data))
                    else:
                        err_msg = str(api_err) or str(data)
                    logger.error(f"Mindmap API error for {model}: {err_msg}")
                    # Fallback to default model if opus fails
                    fallback_model = config.openrouter_model or 'anthropic/claude-3-5-sonnet'
                    logger.info(f"Mindmap: retrying with fallback model {fallback_model}")
                    async with aiohttp.ClientSession() as s2:
                        async with s2.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                            json={
                                "model": fallback_model,
                                "messages": [{"role": "user", "content": prompt}],
                                "max_tokens": 8000,
                            },
                            timeout=aiohttp.ClientTimeout(total=240),
                        ) as r2:
                            data = await r2.json(content_type=None)
                            choices = data.get("choices") if isinstance(data, dict) else None
                            if not choices:
                                raise ValueError(f"Fallback model also failed: {data}")
                raw = choices[0]["message"]["content"].strip()
                if '```' in raw:
                    import re
                    m = re.search(r'```(?:markdown|md)?\s*([\s\S]*?)```', raw)
                    if m:
                        raw = m.group(1).strip()
                if not raw.startswith('#'):
                    lines = raw.split('\n')
                    for i, line in enumerate(lines):
                        if line.strip().startswith('#'):
                            raw = '\n'.join(lines[i:])
                            break
                meeting_id = meeting.get('meeting_id')
                await db.update_meeting_mindmap(meeting_id, raw)
                return web.json_response({'mindmap_json': raw})
    except Exception as e:
        logger.error(f"Mindmap generation error: {e}")
        return web.json_response({'error': 'Ошибка генерации карты'}, status=500)


# ── Meeting Tasks / Action Items ───────────────────────────────

def _serialize_task(t: dict) -> dict:
    """Convert a DB task row to JSON-safe dict."""
    return {
        'id': t['id'],
        'meeting_id': t['meeting_id'],
        'title': t['title'],
        'description': t.get('description') or '',
        'priority': t.get('priority') or 'medium',
        'category': t.get('category') or 'task',
        'sent_to_lark': t.get('sent_to_lark', False),
        'created_at': t['created_at'].isoformat() if t.get('created_at') else None,
    }


@routes.get('/api/meeting/{token}/tasks')
async def meeting_tasks_list(request):
    """Return all tasks for a meeting."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)
    tasks = await db.get_meeting_tasks(meeting['meeting_id'])
    return web.json_response([_serialize_task(t) for t in tasks])


@routes.post('/api/meeting/{token}/tasks')
async def meeting_task_create(request):
    """Manually create a task."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)
    body = await request.json()
    title = (body.get('title') or '').strip()
    if not title:
        return web.json_response({'error': 'title required'}, status=400)
    task = await db.create_meeting_task(meeting['meeting_id'], title, body.get('description', ''))
    return web.json_response(_serialize_task(task))


@routes.post('/api/meeting/{token}/tasks/enhance')
async def meeting_task_enhance(request):
    """Generate a polished task title and description from a raw idea using the configured AI model."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    idea = (body.get('idea') or '').strip()
    if not idea:
        return web.json_response({'error': 'idea required'}, status=400)

    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key:
        return web.json_response({'error': 'AI service unavailable'}, status=503)

    topic = meeting.get('topic', '') or ''
    summary = meeting.get('summary', '') or ''

    system_prompt = (
        "Ты — опытный project manager. Тебе дана краткая идея задачи.\n\n"
        "Сгенерируй:\n"
        "1. Чёткое, конкретное название задачи (5–10 слов, начинается с глагола действия)\n"
        "2. Краткое описание — 2–3 предложения или маркированный список конкретных шагов\n\n"
        "ПРАВИЛА:\n"
        "- Название actionable: начинается с инфинитива (Разработать, Проверить, Настроить, …)\n"
        "- Описание объясняет ЧТО нужно сделать и ЗАЧЕМ\n"
        "- Пиши на русском языке\n\n"
        'Ответ СТРОГО в JSON: {"title": "...", "description": "..."}'
    )

    context_parts = [f"Идея задачи: {idea}"]
    if topic:
        context_parts.append(f"Тема встречи: {topic}")
    if summary:
        context_parts.append(f"Контекст встречи:\n{summary[:1500]}")
    context = '\n\n'.join(context_parts)

    try:
        async with aiohttp.ClientSession() as ai_session:
            async with ai_session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": context},
                    ],
                    "max_tokens": 400,
                    "response_format": {"type": "json_object"},
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                result = json.loads(content)
                title = result.get('title', '').strip()
                description = result.get('description', '').strip()
                if not title:
                    raise ValueError("empty title in AI response")
    except Exception as e:
        logger.error(f"Task enhance AI error: {e}")
        return web.json_response({'error': 'Ошибка AI генерации'}, status=500)

    logger.info(f"Task enhanced for meeting {token}: '{title[:40]}'")
    return web.json_response({'title': title, 'description': description})


@routes.post('/api/meeting/{token}/tasks/generate')
async def meeting_tasks_generate(request):
    """AI-generate action items from meeting transcript/summary."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    api_key = os.getenv('OPENROUTER_API_KEY')
    model = 'anthropic/claude-opus-4.6'
    if not api_key:
        return web.json_response({'error': 'AI service unavailable'}, status=503)

    transcript = meeting.get('transcript_text', '') or ''
    summary = meeting.get('summary', '') or ''
    structured_raw = meeting.get('structured_transcript', '') or ''
    if not transcript and not summary and not structured_raw:
        return web.json_response({'error': 'Нет данных для генерации задач'}, status=400)

    # Build detailed structured text from Zoom AI Summary or AI-generated structured transcript
    structured_text = ''
    if structured_raw:
        try:
            st = json.loads(structured_raw) if isinstance(structured_raw, str) else structured_raw
            if isinstance(st, dict) and 'items' in st:
                parts = []
                if st.get('overall_summary'):
                    parts.append(f"ОБЩЕЕ РЕЗЮМЕ: {st['overall_summary']}\n")
                for item in st['items']:
                    label = (item.get('label') or '').strip()
                    item_summary = (item.get('summary') or '').strip()
                    if not label and not item_summary:
                        continue
                    ts = item.get('start_time', '')
                    te = item.get('end_time', '')
                    parts.append(f"### [{ts} — {te}] {label}\n{item_summary}")
                structured_text = '\n\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

    system_prompt = (
        "Ты — AI-ассистент для управления проектами с опытом извлечения action items из деловых встреч.\n\n"
        "Проанализируй ВСЕ материалы встречи и извлеки КАЖДУЮ задачу и action item.\n\n"
        "КРИТИЧЕСКИ ВАЖНО — Типы задач для извлечения:\n"
        "1. ЯВНЫЕ задачи — участники прямо говорят: 'надо сделать', 'создать задачу', 'нужно проверить', "
        "'давай сделаем', 'запланировать', 'подготовить', 'организовать'\n"
        "2. РЕШЕНИЯ — принятые на встрече решения, которые требуют действий\n"
        "3. ПРОБЛЕМЫ — обсужденные проблемы, по которым нужно действовать\n"
        "4. ИДЕИ — предложенные идеи, которые нужно проработать\n"
        "5. FOLLOW-UP — темы, по которым нужно вернуться или проверить позже\n\n"
        "ПРАВИЛА:\n"
        "1. Извлеки ВСЕ задачи без ограничения (может быть 10, 20, 30+ — сколько реально есть)\n"
        "2. Каждая задача — КОНКРЕТНАЯ и ВЫПОЛНИМАЯ\n"
        "3. title (5-20 слов): начинается с глагола, содержит суть задачи\n"
        "4. description (2-4 предложения): контекст из встречи — кто упомянул, кто ответственный "
        "(если упоминался), дедлайн (если упоминался), связь с проектом, детали обсуждения, "
        "таймкод момента на встрече [HH:MM:SS] если известен\n"
        "5. priority: 'high' (критично, нужно срочно), 'medium' (важно, но не горит), 'low' (идея/follow-up)\n"
        "6. category: одна из — 'task' (конкретное действие), 'decision' (решение), "
        "'idea' (идея для проработки), 'problem' (проблема для решения), 'follow_up' (проверить позже)\n"
        "7. НЕ пропускай ничего — лучше больше задач, чем потерять важное\n"
        "8. НЕ дублируй одинаковые задачи\n\n"
        "Ответ СТРОГО в формате JSON массива без markdown-обёртки:\n"
        '[{"title": "...", "description": "...", "priority": "high|medium|low", '
        '"category": "task|decision|idea|problem|follow_up"}, ...]\n\n'
        "Все тексты на русском языке."
    )

    # Build the richest possible context
    context_parts = []
    if structured_text:
        context_parts.append(f"## Подробная хронология встречи (по разделам)\n{structured_text[:30000]}")
    if summary:
        context_parts.append(f"## Общее саммари\n{summary[:6000]}")
    if transcript:
        context_parts.append(f"## Полная транскрипция\n{transcript[:60000]}")
    context = '\n\n---\n\n'.join(context_parts)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": context},
                    ],
                    "max_tokens": 8000,
                    "provider": {"ignore": ["Google AI Studio"]},
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Task generation AI error: {e}")
        return web.json_response({'error': 'Ошибка генерации задач'}, status=500)

    # Parse JSON from response (strip markdown fences if present)
    if raw_text.startswith('```'):
        lines = raw_text.split('\n')
        raw_text = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])

    try:
        items = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error(f"Task generation: failed to parse JSON: {raw_text[:500]}")
        return web.json_response({'error': 'Не удалось разобрать задачи'}, status=500)

    if not isinstance(items, list):
        return web.json_response({'error': 'Неверный формат задач'}, status=500)

    meeting_id = meeting['meeting_id']
    created = []
    valid_priorities = ('high', 'medium', 'low')
    valid_categories = ('task', 'decision', 'idea', 'problem', 'follow_up')
    for item in items[:40]:
        title = (item.get('title') or '').strip()
        if not title:
            continue
        desc = (item.get('description') or '').strip()
        priority = (item.get('priority') or 'medium').strip().lower()
        if priority not in valid_priorities:
            priority = 'medium'
        category = (item.get('category') or 'task').strip().lower()
        if category not in valid_categories:
            category = 'task'
        task = await db.create_meeting_task(meeting_id, title, desc, priority, category)
        created.append(_serialize_task(task))

    logger.info(f"Meeting {meeting_id}: generated {len(created)} tasks")
    return web.json_response(created)


@routes.patch('/api/meeting/{token}/tasks/{task_id}')
async def meeting_task_update(request):
    """Edit a task's title/description."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)
    task_id = int(request.match_info['task_id'])
    body = await request.json()
    title = (body.get('title') or '').strip()
    if not title:
        return web.json_response({'error': 'title required'}, status=400)
    task = await db.update_meeting_task(task_id, title, body.get('description', ''))
    if not task:
        return web.json_response({'error': 'task not found'}, status=404)
    return web.json_response(_serialize_task(task))


@routes.delete('/api/meeting/{token}/tasks/{task_id}')
async def meeting_task_delete(request):
    """Delete a task."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)
    task_id = int(request.match_info['task_id'])
    ok = await db.delete_meeting_task(task_id)
    if not ok:
        return web.json_response({'error': 'task not found'}, status=404)
    return web.json_response({'ok': True})


@routes.post('/api/meeting/{token}/tasks/{task_id}/expand')
async def meeting_task_expand(request):
    """AI-expand a task description into detailed bullet points / sub-tasks using the meeting transcript."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    task_id = int(request.match_info['task_id'])
    tasks = await db.get_meeting_tasks(meeting['meeting_id'])
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        return web.json_response({'error': 'task not found'}, status=404)

    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key:
        return web.json_response({'error': 'AI service unavailable'}, status=503)

    transcript = meeting.get('transcript_text', '') or ''
    summary = meeting.get('summary', '') or ''
    structured_raw = meeting.get('structured_transcript', '') or ''

    structured_text = ''
    if structured_raw:
        try:
            st = json.loads(structured_raw) if isinstance(structured_raw, str) else structured_raw
            if isinstance(st, dict) and 'items' in st:
                parts = [f"[{item.get('start_time','')}] {item.get('label','')}: {item.get('summary','')}"
                         for item in st['items']]
                structured_text = '\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

    system_prompt = (
        "Ты — AI-ассистент для управления проектами. Тебе дана задача с встречи и транскрипция/саммари.\n\n"
        "Твоя цель: кратко расписать описание задачи в виде списка ключевых пунктов.\n\n"
        "ПРАВИЛА:\n"
        "1. Используй маркированный список (каждый пункт начинается с '- ').\n"
        "2. Максимум 5 пунктов — только самое важное.\n"
        "3. Каждый пункт — одно конкретное действие или ключевой факт (не более 15 слов).\n"
        "4. Если есть — укажи ответственного и дедлайн одним из пунктов.\n"
        "5. Никаких вложенных подсписков. Никаких вступлений и заключений — только список.\n"
        "6. Пиши на русском языке."
    )

    context = f"## Задача\nНазвание: {task['title']}\n"
    if task.get('description'):
        context += f"Текущее описание: {task['description']}\n\n"
    else:
        context += "\n"
    if summary:
        context += f"## Саммари встречи\n{summary[:3000]}\n\n"
    if structured_text:
        context += f"## Хронология встречи\n{structured_text[:10000]}\n\n"
    if transcript:
        context += f"## Транскрипция\n{transcript[:40000]}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": context},
                    ],
                    "max_tokens": 400,
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()
                expanded = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Task expand AI error: {e}")
        return web.json_response({'error': 'Ошибка детализации задачи'}, status=500)

    updated = await db.update_meeting_task(task_id, task['title'], expanded)
    if not updated:
        return web.json_response({'error': 'task not found'}, status=404)

    logger.info(f"Task {task_id} expanded: {len(expanded)} chars")
    return web.json_response(_serialize_task(updated))


@routes.post('/api/meeting/{token}/tasks/{task_id}/lark')
async def meeting_task_send_lark(request):
    """Send a task to the Lark group as an interactive card."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    if not lark_client:
        return web.json_response({'error': 'Lark не настроен'}, status=503)

    task_id = int(request.match_info['task_id'])
    tasks = await db.get_meeting_tasks(meeting['meeting_id'])
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        return web.json_response({'error': 'task not found'}, status=404)

    webapp_url = config.webapp_url or ''
    pt = meeting.get('public_token', token)
    meeting_url = f"{webapp_url}/meeting/{pt}" if webapp_url else None

    try:
        meeting_topic = meeting.get('topic', 'Встреча')
        task_title = task['title']
        task_description = task.get('description')

        # Create a real Lark task via Task API v2
        lark_task_id = None
        lark_task_url = None
        try:
            task_result = await lark_client.create_lark_task(
                title=task_title,
                description=task_description,
                meeting_url=meeting_url,
                meeting_topic=meeting_topic,
            )
            task_data = task_result.get('data', {}).get('task', {})
            lark_task_id = task_data.get('guid')
            lark_task_url = task_data.get('url')
            logger.info(f"Lark task created for task {task_id}: guid={lark_task_id}, url={lark_task_url}")
        except Exception as te:
            logger.warning(f"Lark Task API failed (scope missing?), falling back to card: {te}")

        # Always send notification card to the group chat
        card_result = await lark_client.send_task_card(
            meeting_topic=meeting_topic,
            task_title=task_title,
            task_description=task_description,
            meeting_url=meeting_url,
            lark_task_url=lark_task_url if lark_task_id else None,
        )
        lark_msg_id = card_result.get('data', {}).get('message_id')

        ref_id = lark_task_id or lark_msg_id
        await db.mark_task_sent_to_lark(task_id, ref_id)
        logger.info(f"Task {task_id} sent to Lark (task_guid={lark_task_id}, msg_id={lark_msg_id})")
        return web.json_response({'ok': True, 'lark_task_id': lark_task_id, 'lark_message_id': lark_msg_id})
    except Exception as e:
        logger.error(f"Task {task_id} Lark send error: {e}")
        return web.json_response({'error': 'Ошибка отправки в Lark'}, status=500)


@routes.post('/api/ticket-ai')
async def ticket_ai_generate(request):
    """Use AI to generate a structured ticket title, description and tags from raw text."""
    require_staff_session(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    raw_text = str(body.get('text', '')).strip()[:4000]
    if not raw_text:
        return web.json_response({'error': 'text required'}, status=400)

    system_prompt = (
        "Ты — ассистент по управлению задачами. "
        "На основе предоставленного текста сформулируй задачу для трекера. "
        "Верни ТОЛЬКО валидный JSON без markdown-блоков, без лишних пояснений. "
        'Формат: {"title": "...", "description": "...", "tags": ["...", "..."]}'
    )
    user_prompt = f"Текст:\n{raw_text}"

    headers = {
        'Authorization': f'Bearer {config.openrouter_api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://rusneurosoft.ru',
        'X-Title': 'NC Bot ticket-ai',
    }
    payload = {
        'model': config.openrouter_model or 'anthropic/claude-3-5-haiku',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'max_tokens': 400,
        'temperature': 0.4,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers=headers,
                json=payload,
            ) as resp:
                data = await resp.json(content_type=None)

        if not data.get('choices'):
            err_msg = data.get('error', {}).get('message', 'no choices') if isinstance(data.get('error'), dict) else str(data.get('error', 'no choices'))
            logger.error(f"ticket-ai OpenRouter error: {err_msg}")
            return web.json_response({'error': 'AI не вернул ответ'}, status=502)

        raw = data['choices'][0]['message']['content'].strip()
        # Extract JSON from possible markdown fences or surrounding text
        import re as _re, json as _json
        # Try to find {...} block
        json_match = _re.search(r'\{[^{}]*\}', raw, _re.DOTALL)
        if json_match:
            raw = json_match.group(0)
        elif raw.startswith('```'):
            lines = raw.split('\n')
            raw = '\n'.join(lines[1:]).rsplit('```', 1)[0].strip()

        result = _json.loads(raw)
        return web.json_response({
            'title': str(result.get('title', ''))[:120],
            'description': str(result.get('description', ''))[:2000],
            'tags': [str(t) for t in result.get('tags', []) if t][:6],
        })
    except Exception as e:
        logger.error(f"ticket-ai error: {e}")
        return web.json_response({'error': 'Ошибка генерации'}, status=500)


@routes.post('/api/lark-ticket')
async def lark_ticket_from_chat(request):
    """Create a Lark task + card from a chat message (no DB task created)."""
    require_staff_session(request)
    if not lark_client:
        return web.json_response({'error': 'Lark не настроен'}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    title = (body.get('title') or '').strip()
    description = (body.get('description') or '').strip()
    tags = [t.strip() for t in body.get('tags', []) if isinstance(t, str) and t.strip()]

    if not title:
        return web.json_response({'error': 'title required'}, status=400)

    # Append tags to description
    full_description = description
    if tags:
        tags_line = '  '.join(f'#{t}' for t in tags)
        full_description = f"{description}\n\n{tags_line}".strip() if description else tags_line

    try:
        lark_task_id = None
        lark_task_url = None
        try:
            task_result = await lark_client.create_lark_task(
                title=title,
                description=full_description or None,
            )
            task_data = task_result.get('data', {}).get('task', {})
            lark_task_id = task_data.get('guid')
            lark_task_url = task_data.get('url')
            logger.info(f"Lark ticket created from chat: guid={lark_task_id}")
        except Exception as te:
            logger.warning(f"Lark Task API failed for chat ticket: {te}")

        card_result = await lark_client.send_task_card(
            meeting_topic='Чат',
            task_title=title,
            task_description=full_description or None,
            lark_task_url=lark_task_url if lark_task_id else None,
        )
        lark_msg_id = card_result.get('data', {}).get('message_id')
        return web.json_response({'ok': True, 'lark_task_id': lark_task_id, 'lark_message_id': lark_msg_id})
    except Exception as e:
        logger.error(f"Lark ticket from chat error: {e}")
        return web.json_response({'error': 'Ошибка создания тикета'}, status=500)


@routes.post('/api/meeting/{token}/transcribe')
async def meeting_transcribe(request):
    """Kick off transcription as a background task and return 202 immediately.
    The frontend polls /api/meeting/{token}/status for progress."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    meeting_id = meeting.get('meeting_id')

    if not os.getenv('OPENROUTER_API_KEY'):
        return web.json_response({'error': 'AI service unavailable'}, status=503)

    has_audio = bool(meeting.get('audio_s3_url'))
    has_video = bool(meeting.get('video_s3_url'))
    if not zoom_client and not has_audio and not has_video:
        return web.json_response({'error': 'Нет источника аудио: нет загруженного видео и Zoom не настроен'}, status=503)

    cur_status = meeting.get('status', '')
    if cur_status == 'transcribing':
        return web.json_response({'error': 'Транскрипция уже выполняется'}, status=409)

    logger.info(f"Manual transcribe request for meeting {meeting_id} (token={token})")
    await db.update_meeting_status(meeting_id, 'transcribing')

    asyncio.ensure_future(_run_manual_transcription(meeting_id, cur_status))

    return web.json_response({'status': 'accepted'}, status=202)


async def _run_manual_transcription(meeting_id, prev_status):
    """Background worker for manual transcription triggered via the UI."""
    try:
        zoom_vtt = None
        if zoom_client:
            try:
                logger.info(f"Meeting {meeting_id}: trying Zoom VTT transcript first...")
                zoom_vtt = await zoom_client.download_meeting_transcript(meeting_id)
            except Exception as e:
                logger.warning(f"Meeting {meeting_id}: Zoom VTT download failed: {e}")

        if zoom_vtt:
            logger.info(f"Meeting {meeting_id}: Zoom VTT found ({len(zoom_vtt)} chars), using it directly")
            summary = await generate_summary(zoom_vtt)
            structured_transcript_json = None
            vtt_entries = parse_vtt(zoom_vtt)
            if vtt_entries:
                structured_transcript_json = await generate_structured_transcript(vtt_entries)
            else:
                or_api_key = os.getenv('OPENROUTER_API_KEY')
                or_model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
                if or_api_key:
                    structured_transcript_json = await _structured_transcript_single(or_api_key, or_model, zoom_vtt[:200000])
            try:
                await db.update_meeting_transcript_and_summary(
                    meeting_id=meeting_id,
                    transcript_text=zoom_vtt,
                    summary=summary or None,
                )
                if structured_transcript_json:
                    await db.update_meeting_structured_transcript(meeting_id, structured_transcript_json)
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to save Zoom VTT transcript: {e}")
        else:
            await db.update_meeting_transcript_and_summary(
                meeting_id=meeting_id,
                transcript_text=None,
                summary=None,
            )
            await _auto_transcribe_audio(meeting_id)

        refreshed = await db.get_zoom_meeting(meeting_id)
        if not refreshed or not refreshed.get('transcript_text'):
            logger.error(f"Meeting {meeting_id}: manual transcription produced no transcript")
            await db.update_meeting_status(meeting_id, prev_status or 'recorded')
            return

        await db.update_meeting_status(meeting_id, 'finished')
        logger.info(f"Meeting {meeting_id}: manual transcription completed successfully")
    except Exception as exc:
        logger.error(f"Meeting {meeting_id}: manual transcription failed: {exc}", exc_info=True)
        await db.update_meeting_status(meeting_id, prev_status or 'recorded')


@routes.get('/api/meeting/{token}/status')
async def meeting_status(request):
    """Lightweight endpoint for polling meeting processing status."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)
    has_transcript = bool(meeting.get('transcript_text') or meeting.get('structured_transcript'))
    has_summary = bool(meeting.get('summary'))
    return web.json_response({
        'status': meeting.get('status', ''),
        'has_transcript': has_transcript,
        'has_summary': has_summary,
        'has_video': bool(meeting.get('video_s3_url')),
    })


@routes.post('/api/meeting/{token}/regenerate-structured')
async def meeting_regenerate_structured(request):
    """Regenerate the structured transcript from existing transcript_text or structured_transcript."""
    require_staff_session(request)
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    meeting_id = meeting.get('meeting_id')
    transcript_text = meeting.get('transcript_text', '')
    structured_existing = meeting.get('structured_transcript', '')

    if not transcript_text and not structured_existing:
        return web.json_response({'error': 'Нет транскрипции для обработки'}, status=400)

    # Try to parse as VTT first
    vtt_entries = parse_vtt(transcript_text) if transcript_text else []

    if vtt_entries:
        logger.info(f"Meeting {meeting_id}: regenerating structured transcript from {len(vtt_entries)} VTT entries")
        structured = await generate_structured_transcript(vtt_entries)
    else:
        # Transcript is plain text or JSON — feed it directly to GPT
        source_text = transcript_text or structured_existing
        # If it's already a JSON structured transcript, extract text from it
        try:
            parsed = json.loads(source_text)
            if isinstance(parsed, dict) and 'items' in parsed:
                parts = []
                if parsed.get('overall_summary'):
                    parts.append(f"Общее описание: {parsed['overall_summary']}")
                for item in parsed['items']:
                    tc = item.get('start_time', '')
                    label = item.get('label', '')
                    summary = item.get('summary', '')
                    parts.append(f"[{tc}] {label}: {summary}")
                source_text = '\n'.join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

        logger.info(f"Meeting {meeting_id}: regenerating structured transcript from plain text ({len(source_text)} chars)")
        api_key = os.getenv('OPENROUTER_API_KEY')
        model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
        if not api_key:
            return web.json_response({'error': 'AI service unavailable'}, status=503)
        structured = await _structured_transcript_single(api_key, model, source_text[:120000])

    if not structured:
        return web.json_response({'error': 'Не удалось сгенерировать структурированную транскрипцию'}, status=500)

    try:
        await db.update_meeting_structured_transcript(meeting_id, structured)
        logger.info(f"Meeting {meeting_id}: structured transcript regenerated — {len(structured)} chars")
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: failed to save regenerated structured transcript: {e}")
        return web.json_response({'error': 'Ошибка сохранения'}, status=500)

    return web.json_response({'structured_transcript': structured})


# ========== Projects ==========

# ========== Clients CRM API ==========

def _serialize_client(c: dict, staff_tg_ids: set | None = None) -> dict:
    """Serialize a user/client DB row to a safe public dict."""
    created_at = c.get('created_at')
    updated_at = c.get('updated_at')
    tg_id = c.get('telegram_id')
    uuid_val = c.get('uuid')
    cabinet_token = c.get('cabinet_token')
    name = ' '.join(filter(None, [c.get('first_name'), c.get('last_name')])) or c.get('username') or ''
    tg_handle = f"@{c['username']}" if c.get('username') else None
    bot_username = os.getenv('BOT_USERNAME', '')
    invite_link = (
        f"https://t.me/{bot_username}?start=client_{cabinet_token}"
        if bot_username and cabinet_token else None
    )
    return {
        'id': c['id'],
        'uuid': str(uuid_val) if uuid_val else None,
        'name': name,
        'company': c.get('company'),
        'email': c.get('email'),
        'phone': c.get('phone'),
        'telegram': tg_handle,
        'position': c.get('position'),
        'website': c.get('website'),
        'address': c.get('address'),
        'notes': c.get('client_notes'),
        'status': c.get('client_status', 'lead'),
        'telegram_id': tg_id,
        'is_staff': tg_id is not None and (staff_tg_ids is not None) and tg_id in staff_tg_ids,
        'invite_link': invite_link,
        'is_registered': tg_id is not None,
        'proposals_count': c.get('proposals_count', 0),
        'projects_count': c.get('projects_count', 0),
        'created_at': created_at.isoformat() if created_at else None,
        'updated_at': updated_at.isoformat() if updated_at else None,
    }


async def _get_client_by_uuid_or_404(client_uuid_str: str) -> tuple[dict | None, web.Response | None]:
    """Look up client by UUID string; returns (client, None) or (None, error_response)."""
    import uuid as _uuid_mod
    try:
        _uuid_mod.UUID(client_uuid_str)
    except ValueError:
        return None, web.json_response({'error': 'invalid uuid'}, status=400)
    client = await db.get_client_by_uuid(client_uuid_str)
    if not client:
        return None, web.json_response({'error': 'not_found'}, status=404)
    return client, None


_client_uuids_backfilled = False

@routes.get('/api/clients')
async def list_clients(request):
    """Return all clients, optionally filtered by status."""
    global _client_uuids_backfilled
    if not _client_uuids_backfilled:
        try:
            if hasattr(db, 'backfill_client_uuids'):
                await db.backfill_client_uuids()
        except Exception as e:
            logger.warning(f"backfill_client_uuids failed: {e}")
        _client_uuids_backfilled = True

    status_filter = request.query.get('status')
    session = request.get('session', {})
    if session.get('role') == 'seller':
        tid = int(session.get('telegram_id', 0))
        clients = await db.get_seller_clients(tid, status_filter) if tid else []
    else:
        clients = await db.get_all_clients(status_filter)
    try:
        staff_tg_ids = await db.get_staff_telegram_ids()
    except Exception as e:
        logger.warning(f"Could not fetch staff telegram ids: {e}")
        staff_tg_ids = set()
    return web.json_response([_serialize_client(c, staff_tg_ids) for c in clients])

@routes.post('/api/clients')
async def create_client_api(request):
    """Create a new client."""
    body = await request.json()
    name = (body.get('name') or '').strip()
    if not name:
        return web.json_response({'error': 'name is required'}, status=400)
    client = await db.create_client(
        name=name,
        company=(body.get('company') or '').strip() or None,
        email=(body.get('email') or '').strip() or None,
        phone=(body.get('phone') or '').strip() or None,
        telegram=(body.get('telegram') or '').strip() or None,
        position=(body.get('position') or '').strip() or None,
        website=(body.get('website') or '').strip() or None,
        address=(body.get('address') or '').strip() or None,
        notes=(body.get('notes') or '').strip() or None,
        status=body.get('status', 'lead'),
    )
    created_at = client.get('created_at')
    uuid_val = client.get('uuid')
    name = ' '.join(filter(None, [client.get('first_name'), client.get('last_name')])) or ''
    cabinet_token = client.get('cabinet_token')
    bot_username = os.getenv('BOT_USERNAME', '')
    invite_link = f"https://t.me/{bot_username}?start=client_{cabinet_token}" if bot_username and cabinet_token else None
    return web.json_response({
        'id': client['id'],
        'uuid': str(uuid_val) if uuid_val else None,
        'name': name,
        'company': client.get('company'),
        'status': client.get('client_status', 'lead'),
        'cabinet_token': cabinet_token,
        'invite_link': invite_link,
        'created_at': created_at.isoformat() if created_at else None,
    })

@routes.get('/api/client/{uuid}')
async def get_client_api(request):
    """Get client details with related proposals and projects."""
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    proposals = await db.get_client_proposals(client_id)
    projects = await db.get_client_projects(client_id)
    created_at = client.get('created_at')
    updated_at = client.get('updated_at')
    uuid_val = client.get('uuid')
    name = ' '.join(filter(None, [client.get('first_name'), client.get('last_name')])) or ''
    tg_handle = f"@{client['username']}" if client.get('username') else None
    cabinet_token = client.get('cabinet_token')
    bot_username = os.getenv('BOT_USERNAME', '')
    invite_link = (
        f"https://t.me/{bot_username}?start=client_{cabinet_token}"
        if bot_username and cabinet_token else None
    )
    return web.json_response({
        'id': client['id'],
        'uuid': str(uuid_val) if uuid_val else None,
        'name': name,
        'company': client.get('company'),
        'email': client.get('email'),
        'phone': client.get('phone'),
        'telegram': tg_handle,
        'position': client.get('position'),
        'website': client.get('website'),
        'address': client.get('address'),
        'notes': client.get('client_notes'),
        'status': client.get('client_status', 'lead'),
        'is_blocked': bool(client.get('is_blocked', False)),
        'telegram_id': client.get('telegram_id'),
        'cabinet_token': cabinet_token,
        'invite_link': invite_link,
        'promo_enabled': client.get('promo_enabled', True),
        'promo_started_at': client['promo_started_at'].isoformat() if client.get('promo_started_at') else None,
        'promo_discount_percent': client.get('promo_discount_percent', 10),
        'created_at': created_at.isoformat() if created_at else None,
        'updated_at': updated_at.isoformat() if updated_at else None,
        'proposals': [{
            'token': p['token'],
            'project_name': p.get('project_name'),
            'proposal_type': p.get('proposal_type'),
            'proposal_status': p.get('proposal_status', 'draft'),
            'currency': p.get('currency', '$'),
            'hourly_rate': float(p['hourly_rate']) if p.get('hourly_rate') else 0,
            'discount_percent': p.get('discount_percent', 0) or 0,
            'created_at': p['created_at'].isoformat() if p.get('created_at') else None,
        } for p in proposals],
        'projects': [{
            'id': pr['id'],
            'name': pr['name'],
            'public_token': pr['public_token'],
            'project_type': pr.get('project_type', 'other'),
            'meeting_count': pr.get('meeting_count', 0),
            'created_at': pr['created_at'].isoformat() if pr.get('created_at') else None,
        } for pr in projects],
    })

@routes.patch('/api/client/{uuid}')
async def update_client_api(request):
    """Update client card fields."""
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    body = await request.json()
    updated = await db.update_client(
        client_id,
        name=body.get('name'),
        company=body.get('company'),
        email=body.get('email'),
        phone=body.get('phone'),
        telegram=body.get('telegram'),
        position=body.get('position'),
        website=body.get('website'),
        address=body.get('address'),
        notes=body.get('notes'),
        status=body.get('status'),
    )
    if not updated:
        return web.json_response({'error': 'not_found'}, status=404)
    updated_at = updated.get('updated_at')
    uuid_val = updated.get('uuid')
    name = ' '.join(filter(None, [updated.get('first_name'), updated.get('last_name')])) or ''
    return web.json_response({
        'id': updated['id'],
        'uuid': str(uuid_val) if uuid_val else None,
        'name': name,
        'status': updated.get('client_status', 'lead'),
        'updated_at': updated_at.isoformat() if updated_at else None,
    })

@routes.patch('/api/client/{uuid}/status')
async def update_client_status_api(request):
    """Change client pipeline status."""
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    body = await request.json()
    new_status = body.get('status')
    valid_statuses = {'lead', 'in_progress', 'client', 'archived'}
    if new_status not in valid_statuses:
        return web.json_response({'error': f'invalid status, must be one of: {", ".join(valid_statuses)}'}, status=400)
    updated = await db.update_client(client_id, status=new_status)
    if not updated:
        return web.json_response({'error': 'not_found'}, status=404)
    uuid_val = updated.get('uuid')
    return web.json_response({
        'id': updated['id'],
        'uuid': str(uuid_val) if uuid_val else None,
        'status': updated.get('client_status', new_status),
    })

@routes.patch('/api/client/{uuid}/block')
async def toggle_client_block(request):
    """Toggle is_blocked for a client."""
    require_session(request)
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    body = await request.json()
    blocked = bool(body.get('blocked', False))
    telegram_id = client.get('telegram_id')
    if telegram_id:
        if blocked:
            await db.mark_user_blocked(int(telegram_id))
        else:
            await db.mark_user_active(int(telegram_id))
    else:
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_blocked = $1 WHERE id = $2",
                blocked, client['id'],
            )
    return web.json_response({'ok': True, 'is_blocked': blocked})


@routes.get('/api/client/{uuid}/bot-status')
async def check_client_bot_status(request):
    """Check if the Telegram bot can reach this user (not blocked by user)."""
    require_session(request)
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    telegram_id = client.get('telegram_id')
    if not telegram_id:
        return web.json_response({'can_message': False, 'reason': 'no_telegram'})
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        return web.json_response({'can_message': False, 'reason': 'no_bot_token'})
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChat"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, params={'chat_id': int(telegram_id)}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get('ok'):
                    return web.json_response({'can_message': True, 'reason': 'ok'})
                description = data.get('description', '')
                if 'blocked' in description.lower() or 'bot was blocked' in description.lower():
                    return web.json_response({'can_message': False, 'reason': 'bot_blocked_by_user'})
                if 'not found' in description.lower() or 'chat not found' in description.lower():
                    return web.json_response({'can_message': False, 'reason': 'user_not_started_bot'})
                return web.json_response({'can_message': False, 'reason': 'unknown', 'detail': description})
    except Exception as e:
        logger.error(f"Bot status check failed for {telegram_id}: {e}")
        return web.json_response({'can_message': False, 'reason': 'error'})


@routes.post('/api/client/{uuid}/create-project')
async def create_project_from_client(request):
    """Create a project from a client and link all their proposals to it."""
    require_session(request)
    session = request.get('session', {})
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    body = await request.json()
    default_name = ' '.join(filter(None, [client.get('first_name'), client.get('last_name')])) or 'Project'
    project_name = (body.get('name') or default_name).strip()
    description = (body.get('description') or '').strip() or None
    project = await db.create_project(
        name=project_name,
        description=description,
        created_by=session.get('telegram_id'),
        project_type=body.get('project_type', 'client'),
        client_id=client_id,
    )
    proposals = await db.get_client_proposals(client_id)
    for p in proposals:
        if not p.get('project_id'):
            await db.link_proposal_to_project(p['token'], project['id'])
    if client.get('client_status') in ('lead', 'in_progress'):
        await db.update_client(client_id, status='client')
    created_at = project.get('created_at')
    return web.json_response({
        'id': project['id'],
        'name': project['name'],
        'public_token': project['public_token'],
        'created_at': created_at.isoformat() if created_at else None,
    })

@routes.delete('/api/client/{uuid}')
async def delete_client_api(request):
    """Delete a client."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    deleted = await db.delete_client(client['id'])
    if not deleted:
        return web.json_response({'error': 'not_found'}, status=404)
    return web.json_response({'ok': True})

# ========== Client Promo API ==========

@routes.patch('/api/client/{uuid}/promo')
async def update_client_promo_api(request):
    """Toggle promo discount for a client. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    body = await request.json()

    kwargs = {}
    if 'enabled' in body:
        kwargs['promo_enabled'] = bool(body['enabled'])
    if 'discount_percent' in body:
        kwargs['promo_discount_percent'] = int(body['discount_percent'])

    updated = await db.update_client_promo(client_id, **kwargs)
    if not updated:
        return web.json_response({'error': 'not_found'}, status=404)

    from datetime import timedelta, timezone, datetime
    started = updated.get('promo_started_at')
    now = datetime.now(timezone.utc)
    expires_at = (started + timedelta(hours=72)) if started else None
    return web.json_response({
        'promo_enabled': updated.get('promo_enabled', True),
        'promo_discount_percent': updated.get('promo_discount_percent', 10),
        'promo_started_at': started.isoformat() if started else None,
        'promo_expires_at': expires_at.isoformat() if expires_at else None,
        'promo_expired': (now > expires_at) if expires_at else False,
    })


# ========== Client Messages (Chat) API ==========

@routes.get('/api/client/{uuid}/messages')
async def get_client_messages_api(request):
    """Get chat messages for a client. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    limit = int(request.rel_url.query.get('limit', '50'))
    offset = int(request.rel_url.query.get('offset', '0'))
    messages = await db.get_client_messages(client_id, limit, offset)
    await db.mark_client_messages_read(client_id, 'in')
    result = []
    for m in messages:
        result.append({
            'id': m['id'],
            'direction': m['direction'],
            'sender_name': m['sender_name'],
            'message': m['message'],
            'created_at': m['created_at'].isoformat() if m.get('created_at') else None,
        })
    return web.json_response(result)


@routes.post('/api/client/{uuid}/messages')
async def send_client_message_api(request):
    """Send a message to client via Telegram. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    client, err = await _get_client_by_uuid_or_404(request.match_info['uuid'])
    if err:
        return err
    client_id = client['id']
    body = await request.json()
    message_text = (body.get('message') or '').strip()
    if not message_text:
        return web.json_response({'error': 'message required'}, status=400)

    telegram_id = client.get('telegram_id')
    tg_msg_id = None

    if telegram_id and config.telegram_token:
        try:
            webapp_url = config.webapp_url or ''
            cabinet_token = client.get('cabinet_token')
            payload = {
                'chat_id': telegram_id,
                'text': message_text,
                'parse_mode': 'HTML',
            }
            if webapp_url and cabinet_token:
                cabinet_chat_url = f"{webapp_url}/cabinet/{cabinet_token}#chat"
                payload['reply_markup'] = {
                    'inline_keyboard': [[{
                        'text': '💬 Открыть чат',
                        'url': cabinet_chat_url,
                    }]]
                }
            url = f"https://api.telegram.org/bot{config.telegram_token}/sendMessage"
            async with aiohttp.ClientSession() as sess:
                resp = await sess.post(url, json=payload)
                data = await resp.json()
                if data.get('ok'):
                    tg_msg_id = data['result'].get('message_id')
        except Exception as e:
            logger.error(f"Failed to send Telegram message to client {client_id}: {e}")

    sender_name = session.get('first_name', 'Менеджер')
    saved = await db.save_client_message(
        client_id=client_id,
        direction='out',
        sender_name=sender_name,
        message=message_text,
        telegram_message_id=tg_msg_id,
    )
    return web.json_response({
        'id': saved['id'],
        'direction': 'out',
        'sender_name': sender_name,
        'message': message_text,
        'created_at': saved['created_at'].isoformat() if saved.get('created_at') else None,
    })


# ========== Cabinet API (public, token-based auth) ==========

@routes.get('/cabinet/{token}')
async def cabinet_page(request):
    """Serve client cabinet page."""
    return web.FileResponse('./static/client-cabinet.html')


@routes.get('/api/cabinet/{token}')
async def get_cabinet_data(request):
    """Get cabinet data for a client. Public (token-based)."""
    token = request.match_info['token']
    client = await db.get_client_by_cabinet_token(token)
    if not client:
        return web.json_response({'error': 'not found'}, status=404)

    proposals = await db.get_client_proposals(client['id'])
    projects = await db.get_client_projects(client['id'])

    def build_proposal(full):
        est = full.get('estimation') or {}
        if isinstance(est, str):
            est = json.loads(est)
        cfg = full.get('config_data') or {}
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        hourly_rate = float(full.get('hourly_rate') or 0)
        totals = est.get('totals') or {}

        # Build payment phases from stages
        stages = est.get('stages') or []
        payment_phases = []
        for s in stages:
            tasks = s.get('tasks') or []
            phase_hours = sum(t.get('hours', 0) for t in tasks)
            phase_cost = round(phase_hours * hourly_rate, 2)
            payment_phases.append({
                'name': s.get('name', ''),
                'hours': phase_hours,
                'cost': phase_cost,
                'tasks': [{'name': t.get('name', ''), 'hours': t.get('hours', 0)} for t in tasks],
                'status': 'pending',
            })

        return {
            'project_name': full.get('project_name', ''),
            'token': full.get('token'),
            'status': full.get('proposal_status', 'draft'),
            'total_hours': est.get('total_hours') or (totals.get('total_hours') or {}),
            'total_cost': est.get('total_cost') or (totals.get('total_cost') or {}),
            'currency': full.get('currency', '$'),
            'hourly_rate': hourly_rate,
            'modules': est.get('modules', []),
            'stages': stages,
            'payment_phases': payment_phases,
            'timeline_weeks': est.get('timeline_weeks'),
            'timeline_months': est.get('timeline_months'),
            'team_size': est.get('team_size'),
            'preparation_phase': est.get('preparation_phase'),
            'perspectives': est.get('perspectives', []),
            'project_description_short': est.get('project_description_short', ''),
            'totals': totals,
            'creator': cfg.get('creator'),
        }

    proposals_by_project: dict[int, list] = {}
    standalone_proposals = []
    for p in proposals:
        full = await db.get_commercial_proposal(p['token'])
        if not full:
            continue
        pdata = build_proposal(full)
        pid = full.get('project_id')
        if pid:
            proposals_by_project.setdefault(pid, []).append(pdata)
        else:
            standalone_proposals.append(pdata)

    projects_data = []
    for pr in projects:
        pr_proposals = proposals_by_project.get(pr['id'], [])
        total_hours = sum(
            float(pp.get('total_hours') or 0) for pp in pr_proposals
        )
        total_cost = sum(
            float(pp.get('total_cost') or 0) for pp in pr_proposals
        )
        all_modules = []
        for pp in pr_proposals:
            all_modules.extend(pp.get('modules') or [])
        currency = pr_proposals[0].get('currency', '$') if pr_proposals else '$'

        created = pr.get('created_at')
        projects_data.append({
            'id': pr['id'],
            'name': pr.get('name', ''),
            'description': pr.get('description', ''),
            'public_token': pr.get('public_token', ''),
            'meeting_count': pr.get('meeting_count', 0),
            'created_at': created.isoformat() if created else None,
            'proposals': pr_proposals,
            'total_hours': total_hours,
            'total_cost': total_cost,
            'currency': currency,
            'modules': all_modules,
        })

    first_proposal = None
    if standalone_proposals:
        first_proposal = standalone_proposals[0]
    elif projects_data:
        for pd in projects_data:
            if pd['proposals']:
                first_proposal = pd['proposals'][0]
                break

    session = request.get('session')
    staff_info = None
    is_staff = False
    if session:
        is_staff = True
        staff_info = {
            'name': session.get('first_name', ''),
            'username': session.get('username', ''),
            'role': session.get('role', 'staff'),
        }

    # Promo: activate timer on first non-staff visit
    from datetime import datetime, timedelta, timezone
    promo_started = client.get('promo_started_at')
    if not is_staff and not promo_started and client.get('promo_enabled', True):
        promo_started = datetime.now(timezone.utc)
        await db.update_client_promo(client['id'], promo_started_at=promo_started)

    now = datetime.now(timezone.utc)
    promo_enabled = client.get('promo_enabled', True)
    promo_pct = client.get('promo_discount_percent', 10)
    promo_expires = (promo_started + timedelta(hours=72)) if promo_started else None
    promo_expired = (now > promo_expires) if promo_expires else False

    promo_data = {
        'enabled': promo_enabled,
        'discount_percent': promo_pct,
        'started_at': promo_started.isoformat() if promo_started else None,
        'expires_at': promo_expires.isoformat() if promo_expires else None,
        'expired': promo_expired,
    }

    client_uuid_val = client.get('uuid')
    client_name = ' '.join(filter(None, [client.get('first_name'), client.get('last_name')])) or ''
    return web.json_response({
        'client': {
            'id': client['id'],
            'uuid': str(client_uuid_val) if client_uuid_val else None,
            'name': client_name,
            'company': client.get('company', ''),
        },
        'projects': projects_data,
        'standalone_proposals': standalone_proposals,
        'proposal': first_proposal,
        'is_staff': is_staff,
        'staff': staff_info,
        'promo': promo_data,
    })


@routes.get('/api/cabinet/{token}/messages')
async def get_cabinet_messages(request):
    """Get chat messages for client cabinet. Public (token-based)."""
    token = request.match_info['token']
    client = await db.get_client_by_cabinet_token(token)
    if not client:
        return web.json_response({'error': 'not found'}, status=404)
    limit = int(request.rel_url.query.get('limit', '50'))
    offset = int(request.rel_url.query.get('offset', '0'))
    messages = await db.get_client_messages(client['id'], limit, offset)
    await db.mark_client_messages_read(client['id'], 'out')
    result = []
    for m in messages:
        result.append({
            'id': m['id'],
            'direction': m['direction'],
            'sender_name': m['sender_name'],
            'message': m['message'],
            'created_at': m['created_at'].isoformat() if m.get('created_at') else None,
        })
    return web.json_response(result)


@routes.post('/api/cabinet/{token}/messages')
async def send_cabinet_message(request):
    """Send message in cabinet chat. Staff → out, Client → in."""
    token = request.match_info['token']
    client = await db.get_client_by_cabinet_token(token)
    if not client:
        return web.json_response({'error': 'not found'}, status=404)
    body = await request.json()
    message_text = (body.get('message') or '').strip()
    if not message_text:
        return web.json_response({'error': 'message required'}, status=400)

    session = request.get('session')
    if session:
        direction = 'out'
        sender_name = session.get('first_name', 'Менеджер')
    else:
        direction = 'in'
        sender_name = ' '.join(filter(None, [client.get('first_name'), client.get('last_name')])) or 'Клиент'

    saved = await db.save_client_message(
        client_id=client['id'],
        direction=direction,
        sender_name=sender_name,
        message=message_text,
    )

    if direction == 'in':
        group_id = config.support_group_id if hasattr(config, 'support_group_id') else None
        if group_id and config.telegram_token:
            try:
                webapp_url = config.webapp_url or ''
                client_uuid = client.get('uuid')
                chat_link = f"{webapp_url}/client/{client_uuid}#chat" if webapp_url and client_uuid else ''
                link_line = f'\n\n<a href="{chat_link}">💬 Открыть чат с клиентом</a>' if chat_link else ''
                url = f"https://api.telegram.org/bot{config.telegram_token}/sendMessage"
                async with aiohttp.ClientSession() as sess:
                    await sess.post(url, json={
                        'chat_id': group_id,
                        'text': (
                            f"💬 <b>Сообщение от клиента</b>\n\n"
                            f"👤 {' '.join(filter(None, [client.get('first_name'), client.get('last_name')])) or 'Клиент'}\n"
                            f"📝 {message_text[:500]}"
                            f"{link_line}"
                        ),
                        'parse_mode': 'HTML',
                        'disable_web_page_preview': True,
                    })
            except Exception as e:
                logger.error(f"Failed to notify support group about client message: {e}")

    return web.json_response({
        'id': saved['id'],
        'direction': direction,
        'sender_name': sender_name,
        'message': message_text,
        'created_at': saved['created_at'].isoformat() if saved.get('created_at') else None,
    })


# ========== Project Proposals API ==========

@routes.get('/api/project/{token}/proposals')
async def get_project_proposals_api(request):
    """Get proposals linked to a project."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    proposals = await db.get_project_proposals(project['id'])
    return web.json_response([{
        'token': p['token'],
        'project_name': p.get('project_name'),
        'client_name': p.get('client_name'),
        'proposal_type': p.get('proposal_type'),
        'proposal_status': p.get('proposal_status', 'draft'),
        'currency': p.get('currency', '$'),
        'hourly_rate': float(p['hourly_rate']) if p.get('hourly_rate') else 0,
        'created_at': p['created_at'].isoformat() if p.get('created_at') else None,
    } for p in proposals])

@routes.post('/api/project/{token}/proposals/{proposal_token}')
async def link_proposal_to_project_api(request):
    """Link a proposal to a project."""
    token = request.match_info['token']
    proposal_token = request.match_info['proposal_token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'project not found'}, status=404)
    ok = await db.link_proposal_to_project(proposal_token, project['id'])
    if not ok:
        return web.json_response({'error': 'proposal not found'}, status=404)
    return web.json_response({'ok': True})

@routes.delete('/api/project/{token}/proposals/{proposal_token}')
async def unlink_proposal_from_project_api(request):
    """Unlink a proposal from a project."""
    proposal_token = request.match_info['proposal_token']
    ok = await db.unlink_proposal_from_project(proposal_token)
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True})

# ========== Project Pages ==========

@routes.get('/project/{token}')
async def project_page(request):
    """Serve project detail page."""
    return web.FileResponse('./static/project.html')

@routes.get('/api/projects')
async def list_projects(request):
    """Return all projects. Admin gets all; staff gets only staff-visible ones."""
    session = request.get('session', {})
    role = session.get('role', '')
    if role == 'admin':
        projects = await db.get_all_projects()
    else:
        projects = await db.get_staff_visible_projects()
    result = []
    for p in projects:
        created_at = p.get('created_at')
        result.append({
            'id': p['id'],
            'name': p['name'],
            'description': p.get('description', ''),
            'public_token': p['public_token'],
            'meeting_count': p.get('meeting_count', 0),
            'created_at': created_at.isoformat() if created_at else None,
            'is_staff_visible': p.get('is_staff_visible', True),
            'project_type': p.get('project_type', 'other'),
            'client_id': p.get('client_id'),
            'client_name': p.get('client_name'),
            'client_company': p.get('client_company'),
        })
    return web.json_response(result)


@routes.patch('/api/project/{token}/staff-visible')
async def toggle_project_staff_visibility(request):
    """Toggle is_staff_visible for a project. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    body = await request.json()
    is_visible = bool(body.get('is_staff_visible', True))
    ok = await db.update_project_staff_visibility(project['id'], is_visible)
    if not ok:
        return web.json_response({'error': 'db error'}, status=500)
    return web.json_response({'is_staff_visible': is_visible})

@routes.post('/api/projects')
async def create_project(request):
    """Create a new project."""
    body = await request.json()
    name = (body.get('name') or '').strip()
    if not name:
        return web.json_response({'error': 'name is required'}, status=400)
    description = (body.get('description') or '').strip() or None
    created_by = body.get('created_by')
    categories = await db.get_all_categories()
    valid_slugs = {c['slug'] for c in categories}
    project_type = body.get('project_type', 'other')
    if project_type not in valid_slugs:
        project_type = 'other'
    client_id = body.get('client_id')
    if client_id is not None:
        client_id = int(client_id)

    try:
        project = await db.create_project(name, description, created_by, project_type, client_id=client_id)
        created_at = project.get('created_at')
        return web.json_response({
            'id': project['id'],
            'name': project['name'],
            'description': project.get('description', ''),
            'public_token': project['public_token'],
            'created_at': created_at.isoformat() if created_at else None,
            'project_type': project.get('project_type', 'other'),
            'is_staff_visible': True,
            'meeting_count': 0,
            'client_id': project.get('client_id'),
        })
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        return web.json_response({'error': str(e)}, status=500)


@routes.patch('/api/project/{token}/type')
async def update_project_type(request):
    """Update project_type. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    body = await request.json()
    categories = await db.get_all_categories()
    valid_slugs = {c['slug'] for c in categories}
    project_type = body.get('project_type', 'other')
    if project_type not in valid_slugs:
        return web.json_response({'error': 'invalid type'}, status=400)
    ok = await db.update_project_type(token, project_type)
    if not ok:
        return web.json_response({'error': 'not found or db error'}, status=404)
    return web.json_response({'project_type': project_type})


# ── Project Categories CRUD ──────────────────────────────────────────────────

@routes.get('/api/categories')
async def get_categories(request):
    """List all project categories. Staff sees only staff_visible ones."""
    session = request.get('session', {})
    role = session.get('role', '')
    staff_only = role not in ('admin',)
    cats = await db.get_all_categories(staff_only=staff_only)
    return web.json_response(cats)


@routes.post('/api/categories')
async def create_category(request):
    """Create a new category. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    body = await request.json()
    label = (body.get('label') or '').strip()
    if not label:
        return web.json_response({'error': 'label is required'}, status=400)
    color = (body.get('color') or '#8b8fa8').strip()
    import re, uuid as _uuid
    slug = re.sub(r'[^a-z0-9_]', '', label.lower().replace(' ', '_'))[:40] or _uuid.uuid4().hex[:8]
    existing = await db.get_all_categories()
    existing_slugs = {c['slug'] for c in existing}
    if slug in existing_slugs:
        slug = slug + '_' + _uuid.uuid4().hex[:4]
    position = len(existing)
    try:
        cat = await db.create_category(slug, label, color, position)
        return web.json_response(cat, status=201)
    except Exception as e:
        logger.error(f"Failed to create category: {e}")
        return web.json_response({'error': str(e)}, status=500)


@routes.patch('/api/categories/{slug}')
async def update_category(request):
    """Rename or recolor a category. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    slug = request.match_info['slug']
    body = await request.json()
    label = (body.get('label') or '').strip()
    color = (body.get('color') or '').strip()
    if not label:
        return web.json_response({'error': 'label is required'}, status=400)
    if not color:
        return web.json_response({'error': 'color is required'}, status=400)
    cat = await db.update_category(slug, label, color)
    if not cat:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response(cat)


@routes.delete('/api/categories/{slug}')
async def delete_category(request):
    """Delete a category. Admin only. Projects are moved to 'other'."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    slug = request.match_info['slug']
    if slug == 'other':
        return web.json_response({'error': 'cannot delete default category'}, status=400)
    ok = await db.delete_category(slug)
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True})


@routes.patch('/api/categories/{slug}/visibility')
async def toggle_category_visibility(request):
    """Toggle staff_visible for a category. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    slug = request.match_info['slug']
    body = await request.json()
    staff_visible = bool(body.get('staff_visible', True))
    cat = await db.update_category_staff_visible(slug, staff_visible)
    if not cat:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response(cat)


@routes.get('/api/project/{token}')
async def project_detail(request):
    """Get project details by token."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    created_at = project.get('created_at')
    return web.json_response({
        'id': project['id'],
        'name': project['name'],
        'description': project.get('description', ''),
        'public_token': project['public_token'],
        'created_at': created_at.isoformat() if created_at else None,
        'kimai_project_id': project.get('kimai_project_id'),
        'client_id': project.get('client_id'),
        'client_uuid': str(project['client_uuid']) if project.get('client_uuid') else None,
        'project_type': project.get('project_type', 'other'),
    })

@routes.patch('/api/project/{token}')
async def update_project(request):
    """Update project name/description."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)

    body = await request.json()
    name = (body.get('name') or '').strip()
    if not name:
        return web.json_response({'error': 'name is required'}, status=400)
    description = (body.get('description') or '').strip() or None

    try:
        await db.update_project(project['id'], name, description)
    except Exception as e:
        logger.error(f"Failed to update project: {e}")
        return web.json_response({'error': str(e)}, status=500)

    old_name = project.get('name', '')
    old_desc = project.get('description') or ''
    if name != old_name or (description or '') != old_desc:
        asyncio.create_task(_reembed_project_safe(project['id']))

    return web.json_response({'status': 'ok'})

@routes.delete('/api/project/{token}')
async def delete_project(request):
    """Delete project and unlink all meetings."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)

    try:
        await db.delete_project(project['id'])
        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.error(f"Failed to delete project: {e}")
        return web.json_response({'error': str(e)}, status=500)

@routes.get('/api/project/{token}/meetings')
async def project_meetings_list(request):
    """Get all meetings in a project."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    meetings = await db.get_project_meetings(project['id'])
    result = []
    for m in meetings:
        created_at = m.get('created_at')
        start_time = m.get('start_time')
        pt = m.get('public_token', '')
        is_public = bool(m.get('is_public'))
        result.append({
            'db_id': m['db_id'],
            'meeting_id': m.get('meeting_id'),
            'topic': m.get('topic', ''),
            'duration': m.get('duration', 0),
            'host_name': m.get('host_name', ''),
            'status': m.get('status', ''),
            'recording_url': m.get('recording_url', ''),
            'public_token': pt,
            'is_public': is_public,
            'public_url': f"{config.webapp_url}/meeting/{pt}" if is_public and pt else None,
            'created_at': created_at.isoformat() if created_at else None,
            'start_time': start_time.isoformat() if start_time else None,
        })
    return web.json_response(result)

@routes.post('/api/project/{token}/meetings')
async def add_meeting_to_project(request):
    """Add a meeting to a project and trigger embedding generation."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'project not found'}, status=404)

    body = await request.json()
    meeting_db_id = body.get('meeting_db_id')
    if not meeting_db_id:
        return web.json_response({'error': 'meeting_db_id is required'}, status=400)

    try:
        await db.add_meeting_to_project(project['id'], int(meeting_db_id))
    except Exception as e:
        logger.error(f"Failed to add meeting to project: {e}")
        return web.json_response({'error': str(e)}, status=500)

    asyncio.create_task(_embed_meeting_safe(project['id'], int(meeting_db_id)))
    return web.json_response({'status': 'ok'})

@routes.delete('/api/project/{token}/meetings/{meeting_db_id}')
async def remove_meeting_from_project(request):
    """Remove a meeting from a project."""
    token = request.match_info['token']
    meeting_db_id = int(request.match_info['meeting_db_id'])
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'project not found'}, status=404)

    await db.remove_meeting_from_project(project['id'], meeting_db_id)
    await db.delete_embeddings_for_meeting(project['id'], meeting_db_id)
    return web.json_response({'status': 'ok'})

@routes.get('/api/meeting/{token}/projects')
async def meeting_projects(request):
    """Get projects that a meeting belongs to."""
    token = request.match_info['token']
    meeting = await db.get_meeting_by_public_token(token)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)
    projects = await db.get_meeting_projects(meeting['id'])
    return web.json_response([
        {'id': p['id'], 'name': p['name'], 'public_token': p['public_token']}
        for p in projects
    ])

@routes.get('/api/meetings/unlinked')
async def unlinked_meetings(request):
    """Return meetings not linked to any project."""
    meetings = await db.get_unlinked_meetings()
    result = []
    for m in meetings:
        created_at = m.get('created_at')
        start_time = m.get('start_time')
        result.append({
            'db_id': m['db_id'],
            'meeting_id': m.get('meeting_id'),
            'topic': m.get('topic', ''),
            'duration': m.get('duration', 0),
            'host_name': m.get('host_name', ''),
            'status': m.get('status', ''),
            'public_token': m.get('public_token', ''),
            'created_at': created_at.isoformat() if created_at else None,
            'start_time': start_time.isoformat() if start_time else None,
        })
    return web.json_response(result)

@routes.get('/api/meetings')
async def all_meetings_short(request):
    """Return all meetings (short info) for selection UI."""
    meetings = await db.get_all_meetings_short()
    result = []
    for m in meetings:
        created_at = m.get('created_at')
        result.append({
            'db_id': m['db_id'],
            'meeting_id': m.get('meeting_id'),
            'topic': m.get('topic', ''),
            'duration': m.get('duration', 0),
            'host_name': m.get('host_name', ''),
            'status': m.get('status', ''),
            'public_token': m.get('public_token', ''),
            'created_at': created_at.isoformat() if created_at else None,
        })
    return web.json_response(result)


@routes.delete('/api/meeting/id/{meeting_db_id}')
async def delete_meeting_by_id(request):
    """Fully delete a meeting by DB id: Zoom recordings, Lark card, and all DB records."""
    try:
        meeting_db_id = int(request.match_info['meeting_db_id'])
    except (ValueError, KeyError):
        return web.json_response({'error': 'invalid meeting_db_id'}, status=400)

    meeting = await db.get_zoom_meeting_by_db_id(meeting_db_id)
    if not meeting:
        return web.json_response({'error': 'not found'}, status=404)

    zoom_meeting_id = meeting.get('meeting_id')

    # Delete all files from S3
    if s3_client and zoom_meeting_id:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, s3_client.delete_meeting_files, zoom_meeting_id)
        except Exception as e:
            logger.warning(f"Meeting {meeting_db_id}: S3 delete failed (continuing): {e}")

    # Delete recording from Zoom Cloud
    if zoom_client and zoom_meeting_id:
        try:
            await zoom_client.delete_meeting_recordings(zoom_meeting_id, action='delete')
        except Exception as e:
            logger.warning(f"Meeting {meeting_db_id}: Zoom recording delete failed (continuing): {e}")

    # Delete Lark card
    lark_msg_id = meeting.get('lark_message_id')
    if lark_client and lark_msg_id:
        try:
            await lark_client.delete_message(lark_msg_id)
        except Exception as e:
            logger.warning(f"Meeting {meeting_db_id}: Lark message delete failed (continuing): {e}")

    # Delete from DB
    try:
        await db.delete_zoom_meeting(meeting_db_id)
    except Exception as e:
        logger.error(f"Meeting {meeting_db_id}: DB delete failed: {e}")
        return web.json_response({'error': str(e)}, status=500)

    logger.info(f"Meeting db_id={meeting_db_id} fully deleted")
    return web.json_response({'status': 'ok'})


# ── Employees & Grades ──────────────────────────────────────────────────────

GRADE_RATES: dict[str, int | None] = {
    'Junior': 1500,
    'Middle': 2200,
    'Senior': 2700,
    'Lead':   3200,
    'COO':    None,   # 35% Operating Pool
    'CEO':    None,   # 30% Operating Pool
}

GRADE_COEFS: dict[str, float | None] = {
    'Junior': 1.00,
    'Middle': 1.47,
    'Senior': 1.80,
    'Lead':   2.13,
    'COO':    None,
    'CEO':    None,
}

GRADE_POOL_PCT: dict[str, int | None] = {
    'Junior': None,
    'Middle': None,
    'Senior': None,
    'Lead':   None,
    'COO':    35,
    'CEO':    30,
}


@routes.get('/api/employees')
async def get_employees(request):
    """Return all staff/admin users. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    staff = await db.get_all_staff_with_kimai()
    for emp in staff:
        if isinstance(emp.get('created_at'), object) and hasattr(emp['created_at'], 'isoformat'):
            emp['created_at'] = emp['created_at'].isoformat()
        if emp.get('uuid'):
            emp['uuid'] = str(emp['uuid'])
        g = emp.get('staff_grade') or ''
        emp['grade_rate'] = GRADE_RATES.get(g)
        emp['grade_coef'] = GRADE_COEFS.get(g)
        emp['grade_pool_pct'] = GRADE_POOL_PCT.get(g)
    return web.json_response(staff)


@routes.get('/api/employees/{uuid}')
async def get_employee_api(request):
    """Return a single employee by UUID. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    emp_uuid = request.match_info['uuid']
    emp = await db.get_employee_by_uuid(emp_uuid)
    if not emp:
        return web.json_response({'error': 'not_found'}, status=404)
    if isinstance(emp.get('created_at'), object) and hasattr(emp['created_at'], 'isoformat'):
        emp['created_at'] = emp['created_at'].isoformat()
    if emp.get('uuid'):
        emp['uuid'] = str(emp['uuid'])
    g = emp.get('staff_grade') or ''
    emp['grade_rate'] = GRADE_RATES.get(g)
    emp['grade_coef'] = GRADE_COEFS.get(g)
    emp['grade_pool_pct'] = GRADE_POOL_PCT.get(g)
    return web.json_response(emp)


@routes.patch('/api/employees/{telegram_id}')
async def update_employee(request):
    """Update employee grade/specialty/kimai_user_id. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    try:
        tid = int(request.match_info['telegram_id'])
    except ValueError:
        return web.json_response({'error': 'invalid telegram_id'}, status=400)
    body = await request.json()
    specialty = (body.get('specialty') or '').strip() or None
    grade = (body.get('grade') or '').strip() or None
    if grade and grade not in GRADE_RATES:
        return web.json_response({'error': 'invalid grade'}, status=400)
    kimai_user_id = body.get('kimai_user_id')
    if kimai_user_id is not None:
        try:
            kimai_user_id = int(kimai_user_id)
        except (TypeError, ValueError):
            kimai_user_id = None
    staff_email = (body.get('staff_email') or '').strip() or None
    staff_display_name = (body.get('staff_display_name') or '').strip() or None
    ok = await db.update_employee(
        tid, specialty, grade, kimai_user_id,
        staff_email=staff_email, staff_display_name=staff_display_name,
    )
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True, 'grade_rate': GRADE_RATES.get(grade or '', None)})


@routes.get('/api/kimai/users')
async def get_kimai_users(request):
    """Return Kimai users list for linking. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    if not kimai_client:
        return web.json_response({'error': 'Kimai not configured'}, status=503)
    try:
        users = await kimai_client.get_users_with_rates()
        result = []
        for u in users:
            result.append({
                'id': u.get('id'),
                'username': u.get('username', ''),
                'alias': u.get('alias') or u.get('username', ''),
                'hourly_rate': u.get('hourly_rate'),
                'email': u.get('email') or '',
            })
        return web.json_response(result)
    except Exception as e:
        logger.error(f"Kimai users fetch error: {e}")
        return web.json_response({'error': str(e)}, status=500)


# ========== Users Management (Admin) ==========

@routes.get('/api/users')
async def get_users(request):
    """Return all users. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    users = await db.get_all_users_admin()
    for u in users:
        for key in ('created_at', 'last_interaction'):
            if isinstance(u.get(key), object) and hasattr(u.get(key), 'isoformat'):
                u[key] = u[key].isoformat() if u[key] else None
        if u.get('uuid'):
            u['uuid'] = str(u['uuid'])
    return web.json_response(users)


@routes.patch('/api/users/{telegram_id}/role')
async def update_user_role(request):
    """Change user role. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    try:
        tid = int(request.match_info['telegram_id'])
    except ValueError:
        return web.json_response({'error': 'invalid telegram_id'}, status=400)
    body = await request.json()
    new_role = body.get('role', '').strip()
    if new_role not in ('user', 'staff', 'seller'):
        return web.json_response({'error': 'invalid role'}, status=400)
    # Prevent changing role of any admin user
    target_role = await db.get_user_role(tid)
    if target_role == 'admin':
        return web.json_response({'error': 'cannot change admin role'}, status=400)
    await db.update_user_role(tid, new_role)
    return web.json_response({'ok': True, 'role': new_role})


@routes.post('/api/users/invite')
async def create_invite_link(request):
    """Create an invite link with a target role. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)

    body = await request.json()
    target_role = (body.get('role') or '').strip()
    if target_role not in ('staff', 'seller', 'user'):
        return web.json_response({'error': 'invalid role'}, status=400)

    import uuid as _uuid
    token = _uuid.uuid4().hex[:16]
    admin_tid = session.get('telegram_id')
    await db.save_invite_link(token, admin_tid, target_role=target_role)

    bot_username = os.getenv('BOT_USERNAME', '')
    invite_url = f"https://t.me/{bot_username}?start=invite_{token}" if bot_username else None

    return web.json_response({'ok': True, 'invite_url': invite_url, 'token': token, 'role': target_role})


# ========== Project Finance ==========

@routes.get('/api/kimai/projects')
async def get_kimai_projects(request):
    """Return Kimai projects for linking dropdown. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    if not kimai_client:
        return web.json_response({'error': 'Kimai not configured'}, status=503)
    try:
        projects = await kimai_client.get_projects()
        result = []
        for p in projects:
            cust = p.get('customer')
            cust_name = cust.get('name', '') if isinstance(cust, dict) else (p.get('parentTitle') or '')
            result.append({'id': p.get('id'), 'name': p.get('name', ''), 'customer': cust_name})
        return web.json_response(result)
    except Exception as e:
        logger.error(f"Kimai projects fetch error: {e}")
        return web.json_response({'error': str(e)}, status=500)


@routes.patch('/api/project/{token}/kimai-link')
async def update_project_kimai_link(request):
    """Link NC Bot project to a Kimai project. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    body = await request.json()
    kimai_id = body.get('kimai_project_id')
    if kimai_id is not None:
        try:
            kimai_id = int(kimai_id)
        except (TypeError, ValueError):
            kimai_id = None
    ok = await db.update_project_kimai_link(project['id'], kimai_id)
    if not ok:
        return web.json_response({'error': 'update failed'}, status=500)
    return web.json_response({'ok': True})


@routes.get('/api/project/{token}/finance')
async def project_finance_summary(request):
    """Return finance summary for a project. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)

    from datetime import datetime, date, timedelta
    date_from_str = request.rel_url.query.get('from')
    date_to_str = request.rel_url.query.get('to')
    date_from = date.fromisoformat(date_from_str) if date_from_str else None
    date_to = date.fromisoformat(date_to_str) if date_to_str else None

    created = project['created_at']
    if hasattr(created, 'date'):
        created = created.date()
    days_in_work = (date.today() - created).days

    kimai_hours = 0.0
    kimai_cost = 0.0
    kimai_records = []
    by_activity: dict[int, dict] = {}
    by_user: dict[int, dict] = {}
    activities_map: dict[int, str] = {}
    users_map: dict[int, str] = {}
    kimai_project_id = project.get('kimai_project_id')
    if kimai_project_id and kimai_client:
        # When no explicit date_from, go back 2 years to capture all historical Kimai data
        default_begin = date.today().replace(year=date.today().year - 2)
        begin = (date_from or default_begin).isoformat() + 'T00:00:00'
        end = (date_to or date.today()).isoformat() + 'T23:59:59'
        try:
            records = await kimai_client.get_project_timesheets(kimai_project_id, begin, end)
            try:
                acts = await kimai_client.get_activities()
                activities_map = {a['id']: a['name'] for a in acts}
            except Exception:
                pass
            try:
                usrs = await kimai_client.get_users()
                users_map = {u['id']: u.get('alias') or u.get('username') or f"User {u['id']}" for u in usrs}
            except Exception:
                pass
            for r in records:
                dur_sec = r.get('duration', 0) or 0
                rate = r.get('rate', 0) or 0
                hours = dur_sec / 3600.0
                kimai_hours += hours
                kimai_cost += float(rate)
                rec_begin = r.get('begin', '')
                rec_date = rec_begin[:10] if rec_begin else ''
                act_id = r.get('activity', 0)
                usr_id = r.get('user', 0)
                kimai_records.append({
                    'date': rec_date,
                    'hours': round(hours, 2),
                    'cost': float(rate),
                    'user_id': usr_id,
                    'activity_id': act_id,
                    'description': r.get('description', ''),
                })
                if act_id:
                    entry = by_activity.setdefault(act_id, {'hours': 0.0, 'cost': 0.0})
                    entry['hours'] += hours
                    entry['cost'] += float(rate)
                if usr_id:
                    entry = by_user.setdefault(usr_id, {'hours': 0.0, 'cost': 0.0})
                    entry['hours'] += hours
                    entry['cost'] += float(rate)
        except Exception as e:
            logger.error(f"Kimai timesheets error for project {token}: {e}")

    expenses = await db.get_project_expenses(project['id'], date_from, date_to)
    custom_total = sum(float(ex.get('amount', 0)) for ex in expenses)
    income_list = await db.get_project_income(project['id'], date_from, date_to)
    income_total = sum(float(inc.get('amount', 0)) for inc in income_list)

    total_expenses = kimai_cost + custom_total
    profit = income_total - total_expenses

    monthly: dict[str, dict] = {}
    for r in kimai_records:
        m = r['date'][:7]
        if m:
            monthly.setdefault(m, {'expenses': 0.0, 'income': 0.0})
            monthly[m]['expenses'] += r['cost']
    for ex in expenses:
        d = ex.get('expense_date')
        m = d.isoformat()[:7] if d else ''
        if m:
            monthly.setdefault(m, {'expenses': 0.0, 'income': 0.0})
            monthly[m]['expenses'] += float(ex.get('amount', 0))
    for inc in income_list:
        d = inc.get('income_date')
        m = d.isoformat()[:7] if d else ''
        if m:
            monthly.setdefault(m, {'expenses': 0.0, 'income': 0.0})
            monthly[m]['income'] += float(inc.get('amount', 0))

    monthly_data = [{'month': k, **v} for k, v in sorted(monthly.items())]

    activity_breakdown = [
        {'name': activities_map.get(aid, f'Activity {aid}'), 'hours': round(v['hours'], 2), 'cost': round(v['cost'], 2)}
        for aid, v in sorted(by_activity.items(), key=lambda x: x[1]['cost'], reverse=True)
    ]
    user_breakdown = [
        {'name': users_map.get(uid, f'User {uid}'), 'hours': round(v['hours'], 2), 'cost': round(v['cost'], 2)}
        for uid, v in sorted(by_user.items(), key=lambda x: x[1]['cost'], reverse=True)
    ]

    return web.json_response({
        'days_in_work': days_in_work,
        'kimai_hours': round(kimai_hours, 2),
        'kimai_cost': round(kimai_cost, 2),
        'custom_expenses_total': round(custom_total, 2),
        'total_expenses': round(total_expenses, 2),
        'income_total': round(income_total, 2),
        'profit': round(profit, 2),
        'kimai_project_id': kimai_project_id,
        'monthly_data': monthly_data,
        'activity_breakdown': activity_breakdown,
        'user_breakdown': user_breakdown,
    })


@routes.get('/api/project/{token}/expenses')
async def get_project_expenses(request):
    """List custom expenses. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    from datetime import date
    date_from_str = request.rel_url.query.get('from')
    date_to_str = request.rel_url.query.get('to')
    date_from = date.fromisoformat(date_from_str) if date_from_str else None
    date_to = date.fromisoformat(date_to_str) if date_to_str else None
    rows = await db.get_project_expenses(project['id'], date_from, date_to)
    result = []
    for r in rows:
        d = dict(r)
        for k in ('expense_date', 'created_at'):
            v = d.get(k)
            if v and hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
        d['amount'] = float(d.get('amount', 0))
        result.append(d)
    return web.json_response(result)


@routes.post('/api/project/{token}/expenses')
async def add_project_expense(request):
    """Add custom expense. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    body = await request.json()
    title = (body.get('title') or '').strip()
    if not title:
        return web.json_response({'error': 'title required'}, status=400)
    try:
        amount = float(body['amount'])
    except (KeyError, ValueError, TypeError):
        return web.json_response({'error': 'invalid amount'}, status=400)
    category = (body.get('category') or '').strip() or None
    from datetime import date
    try:
        expense_date = date.fromisoformat(body['date'])
    except (KeyError, ValueError, TypeError):
        expense_date = date.today()
    row = await db.add_project_expense(
        project['id'], title, amount, category, expense_date, session.get('telegram_id'))
    if not row:
        return web.json_response({'error': 'failed'}, status=500)
    r = dict(row)
    for k in ('expense_date', 'created_at'):
        v = r.get(k)
        if v and hasattr(v, 'isoformat'):
            r[k] = v.isoformat()
    r['amount'] = float(r.get('amount', 0))
    return web.json_response(r, status=201)


@routes.delete('/api/project/{token}/expenses/{expense_id}')
async def delete_project_expense(request):
    """Delete custom expense. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    try:
        eid = int(request.match_info['expense_id'])
    except ValueError:
        return web.json_response({'error': 'invalid id'}, status=400)
    ok = await db.delete_project_expense(eid)
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True})


@routes.get('/api/project/{token}/income')
async def get_project_income(request):
    """List income entries. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    from datetime import date
    date_from_str = request.rel_url.query.get('from')
    date_to_str = request.rel_url.query.get('to')
    date_from = date.fromisoformat(date_from_str) if date_from_str else None
    date_to = date.fromisoformat(date_to_str) if date_to_str else None
    rows = await db.get_project_income(project['id'], date_from, date_to)
    result = []
    for r in rows:
        d = dict(r)
        for k in ('income_date', 'created_at'):
            v = d.get(k)
            if v and hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
        d['amount'] = float(d.get('amount', 0))
        result.append(d)
    return web.json_response(result)


@routes.post('/api/project/{token}/income')
async def add_project_income(request):
    """Add income entry. Admin only."""
    require_session(request)
    session = request.get('session', {})
    if session.get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)
    body = await request.json()
    title = (body.get('title') or '').strip()
    if not title:
        return web.json_response({'error': 'title required'}, status=400)
    try:
        amount = float(body['amount'])
    except (KeyError, ValueError, TypeError):
        return web.json_response({'error': 'invalid amount'}, status=400)
    from datetime import date
    try:
        income_date = date.fromisoformat(body['date'])
    except (KeyError, ValueError, TypeError):
        income_date = date.today()
    row = await db.add_project_income(
        project['id'], title, amount, income_date, session.get('telegram_id'))
    if not row:
        return web.json_response({'error': 'failed'}, status=500)
    r = dict(row)
    for k in ('income_date', 'created_at'):
        v = r.get(k)
        if v and hasattr(v, 'isoformat'):
            r[k] = v.isoformat()
    r['amount'] = float(r.get('amount', 0))
    return web.json_response(r, status=201)


@routes.delete('/api/project/{token}/income/{income_id}')
async def delete_project_income(request):
    """Delete income entry. Admin only."""
    require_session(request)
    if request.get('session', {}).get('role') != 'admin':
        return web.json_response({'error': 'forbidden'}, status=403)
    try:
        iid = int(request.match_info['income_id'])
    except ValueError:
        return web.json_response({'error': 'invalid id'}, status=400)
    ok = await db.delete_project_income(iid)
    if not ok:
        return web.json_response({'error': 'not found'}, status=404)
    return web.json_response({'ok': True})


# ========== Project Chat ==========

@routes.post('/api/project/{token}/chat')
async def project_chat(request):
    """AI chat grounded in all meeting transcripts within a project (RAG via pgvector)."""
    token = request.match_info['token']
    project = await db.get_project_by_token(token)
    if not project:
        return web.json_response({'error': 'not found'}, status=404)

    body = await request.json()
    question = body.get('question', '')
    history = body.get('history', [])
    use_power_model = body.get('model') == 'power'

    if not question:
        return web.json_response({'answer': 'Пожалуйста, задайте вопрос.', 'sources': []})

    api_key = os.getenv('OPENROUTER_API_KEY')
    _POWER_MODEL = 'anthropic/claude-opus-4-5'
    model = _POWER_MODEL if use_power_model else os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    openai_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        return web.json_response({'answer': 'AI-сервис временно недоступен.', 'sources': []})

    context_chunks = []
    sources_map: dict[int, dict] = {}

    if openai_key:
        try:
            query_embedding = await generate_single_embedding(question)
            context_chunks = await db.search_similar_chunks(project['id'], query_embedding, limit=10)
        except Exception as e:
            logger.error(f"Project chat vector search error: {e}")

    if context_chunks:
        for c in context_chunks:
            db_id = c.get('zoom_meeting_db_id')
            if db_id and db_id not in sources_map:
                sources_map[db_id] = {
                    'topic': c.get('meeting_topic', ''),
                    'token': c.get('meeting_token', ''),
                }
        context_text = "\n\n".join(
            f"[Встреча: {c.get('meeting_topic', '?')}]\n{c['chunk_text']}"
            for c in context_chunks
        )
    else:
        meetings = await db.get_project_meetings(project['id'])
        parts = []
        for m in meetings:
            full = await db.get_zoom_meeting_by_db_id(m['db_id'])
            if full:
                s = full.get('summary') or ''
                t = full.get('transcript_text') or ''
                parts.append(f"[Встреча: {m.get('topic', '?')}]\n{s[:1500]}\n{t[:3000]}")
                sources_map[m['db_id']] = {
                    'topic': m.get('topic', ''),
                    'token': full.get('public_token', ''),
                }
        context_text = "\n\n".join(parts)[:12000]

    timelines_text = ''
    for db_id, src in sources_map.items():
        try:
            full = await db.get_zoom_meeting_by_db_id(db_id)
            if not full:
                continue
            raw = full.get('structured_transcript') or ''
            if not raw:
                continue
            st = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(st, dict) and 'items' in st:
                parts_tl = []
                for item in st['items']:
                    tc = item.get('start_time', '')
                    if tc:
                        tc_short = tc.lstrip('0').lstrip(':').lstrip('0') or '0:00'
                        parts_tl.append(f"[{tc_short}] {item.get('label', '')}: {item.get('summary', '')}")
                if parts_tl:
                    timelines_text += f"\n### Хронология встречи «{src['topic']}»\n" + "\n".join(parts_tl) + "\n"
        except (json.JSONDecodeError, TypeError, Exception) as e:
            logger.debug(f"Failed to parse structured_transcript for meeting {db_id}: {e}")

    system_prompt = (
        "Ты — AI-ассистент, который отвечает на вопросы по материалам проекта.\n"
        f"Проект: {project['name']}\n"
        f"Описание: {project.get('description') or 'нет описания'}\n\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "1. Отвечай на русском языке.\n"
        "2. К КАЖДОМУ упоминанию факта ОБЯЗАТЕЛЬНО добавляй таймкод [MM:SS] из хронологии встречи.\n"
        "3. После таймкода указывай название встречи в скобках, например: [05:30] (Встреча по дизайну).\n"
        "4. Если тема упоминалась в НЕСКОЛЬКИХ встречах — перечисли ВСЕ упоминания с разными таймкодами.\n"
        "5. Структурируй ответ: используй нумерованный или маркированный список.\n"
        "6. Если в контексте нет информации по вопросу — честно скажи об этом.\n\n"
        f"## Контекст из встреч проекта\n{context_text[:12000]}"
    )
    if timelines_text:
        system_prompt += f"\n\n## Хронология встреч (таймкоды){timelines_text[:8000]}"

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-8:]:
        if h.get('role') in ('user', 'assistant'):
            messages.append({"role": h['role'], "content": h['content'][:1000]})
    messages.append({"role": "user", "content": question[:2000]})

    sources_list = [{'topic': s['topic'], 'token': s['token']} for s in sources_map.values() if s.get('token')]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 4000 if use_power_model else 2000,
                    **({"provider": {"ignore": ["Google AI Studio"]}} if use_power_model else {}),
                },
            ) as resp:
                data = await resp.json()
                answer = data["choices"][0]["message"]["content"].strip()
                return web.json_response({'answer': answer, 'sources': sources_list, 'model_used': 'power' if use_power_model else 'default'})
    except Exception as e:
        logger.error(f"Project chat error: {e}")
        return web.json_response({'answer': 'Произошла ошибка при обработке запроса.', 'sources': []})


async def _embed_meeting_safe(project_id: int, zoom_meeting_db_id: int):
    """Background task wrapper for embedding generation."""
    try:
        await embed_meeting_for_project(db, project_id, zoom_meeting_db_id)
    except Exception as e:
        logger.error(f"Background embedding failed for project {project_id}, meeting {zoom_meeting_db_id}: {e}")


async def _reembed_project_safe(project_id: int):
    """Re-embed all meetings in a project (e.g. after project name/description change)."""
    try:
        await reembed_all_project_meetings(db, project_id)
    except Exception as e:
        logger.error(f"Background re-embedding failed for project {project_id}: {e}")

# ========== Zoom Webhook ==========

async def generate_summary(transcript: str) -> str:
    """Use OpenRouter to create a detailed meeting summary with timestamps."""
    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key or not transcript:
        return ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Ты — ассистент для анализа встреч. Создай подробное саммари встречи на русском языке.\n\n"
                                "Правила:\n"
                                "1. Создай 8-15 детальных пунктов, охватывающих ВСЕ ключевые моменты встречи.\n"
                                "2. Каждый пункт ОБЯЗАТЕЛЬНО начинается с таймкода начала момента в формате [MM:SS] или [H:MM:SS].\n"
                                "3. Используй таймкоды из транскрипции. Указывай только НАЧАЛО момента, не диапазон.\n"
                                "4. Включай максимум деталей: имена участников, конкретные решения, цифры, названия инструментов, ключевые идеи.\n"
                                "5. Пункты должны идти в хронологическом порядке.\n"
                                "6. Отвечай ТОЛЬКО списком пунктов, без заголовков и вступлений.\n\n"
                                "Пример формата:\n"
                                "• [00:00] Обсудили необходимость централизованной организации коммуникаций через Telegram и интеграцию с Lark.\n"
                                "• [03:15] Рассмотрели маркетинговые стратегии с акцентом на создание делового аккаунта в Instagram.\n"
                                "• [12:40] Приняли решение о внедрении автоматизированной системы управления проектами."
                            ),
                        },
                        {"role": "user", "content": f"Транскрипция встречи:\n\n{transcript[:60000]}"},
                    ],
                    "max_tokens": 2000,
                    "temperature": 0.3,
                },
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        return ""


async def generate_short_summary(full_summary: str) -> str:
    """Generate a 3-sentence summary from full summary using OpenRouter."""
    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key or not full_summary:
        return ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Ты — ассистент. Сократи саммари встречи до 3 предложений на русском языке. "
                                "Выдели только самое важное. Отвечай только текстом саммари, без вступлений."
                            ),
                        },
                        {"role": "user", "content": f"Саммари встречи:\n\n{full_summary[:3000]}"},
                    ],
                    "max_tokens": 200,
                },
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        return ""


def parse_vtt(vtt_text: str) -> list[dict]:
    """Parse Zoom VTT transcript into timestamped utterances.

    Returns a list of dicts: {start_time, end_time, speaker, text}.
    """
    if not vtt_text or not vtt_text.strip():
        return []

    entries: list[dict] = []
    timestamp_re = re.compile(
        r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
    )

    blocks = re.split(r"\n\s*\n", vtt_text.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue

        ts_match = None
        ts_line_idx = -1
        for i, line in enumerate(lines):
            ts_match = timestamp_re.search(line)
            if ts_match:
                ts_line_idx = i
                break

        if not ts_match:
            continue

        start_time = ts_match.group(1)
        end_time = ts_match.group(2)

        text_lines = [l.strip() for l in lines[ts_line_idx + 1:] if l.strip()]
        if not text_lines:
            continue

        raw_text = " ".join(text_lines)

        speaker = ""
        colon_match = re.match(r"^(.+?):\s*(.+)$", raw_text)
        if colon_match:
            speaker = colon_match.group(1).strip()
            raw_text = colon_match.group(2).strip()

        entries.append({
            "start_time": start_time,
            "end_time": end_time,
            "speaker": speaker,
            "text": raw_text,
        })

    return entries


def _format_vtt_for_llm(entries: list[dict]) -> str:
    """Format parsed VTT entries into a compact timestamped transcript for the LLM."""
    lines = []
    for e in entries:
        prefix = f"[{e['start_time']}]"
        if e.get("speaker"):
            prefix += f" {e['speaker']}:"
        lines.append(f"{prefix} {e['text']}")
    return "\n".join(lines)


_STRUCTURED_TRANSCRIPT_SYSTEM_PROMPT = """\
Ты — профессиональный ассистент для детального анализа деловых встреч. \
Тебе дана транскрипция встречи с таймкодами.

Твоя задача — создать МАКСИМАЛЬНО ДЕТАЛЬНУЮ разбивку встречи на смысловые сегменты.

ПРАВИЛА:
1. Разбей транскрипцию на мелкие тематические сегменты по 1-3 минуты каждый.
   - Каждая смена темы, нового вопроса или спикера = новый сегмент.
   - Если одна тема обсуждается дольше 3 минут — обязательно разбей на подтемы.
   - Стремись к 10-20+ сегментам для 30-минутной встречи.
2. Для каждого сегмента укажи:
   - label: точное и конкретное название темы (5-12 слов), отражающее СУТЬ обсуждения
   - start_time: таймкод начала в формате HH:MM:SS.mmm
   - end_time: таймкод конца в формате HH:MM:SS.mmm
   - summary: ПОДРОБНОЕ описание на 4-7 предложений, включая:
     • Конкретные цифры, даты, названия, имена участников
     • Принятые решения и action items (выделяй их)
     • Ключевые аргументы и мнения разных сторон
     • Упомянутые инструменты, технологии, компании
3. Напиши overall_summary: развёрнутое описание всей встречи (5-8 предложений) с основными выводами.

Отвечай ТОЛЬКО валидным JSON без markdown-обёртки. Формат:
{
  "overall_summary": "...",
  "items": [
    {
      "start_time": "HH:MM:SS.mmm",
      "end_time": "HH:MM:SS.mmm",
      "label": "...",
      "summary": "..."
    }
  ]
}

Все тексты на русском языке. Сегменты должны покрывать ВСЮ встречу без пропусков. \
Чем больше деталей и конкретики — тем лучше."""


async def generate_structured_transcript(vtt_entries: list[dict]) -> str | None:
    """Use GPT-4o to segment a parsed VTT transcript into topic chapters.

    Returns a JSON string matching the structured transcript schema,
    or None on failure.
    """
    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    if not api_key or not vtt_entries:
        return None

    formatted = _format_vtt_for_llm(vtt_entries)
    if not formatted.strip():
        return None

    max_chars = 120_000
    if len(formatted) <= max_chars:
        return await _structured_transcript_single(api_key, model, formatted)
    else:
        return await _structured_transcript_chunked(api_key, model, vtt_entries, max_chars)


async def _structured_transcript_single(
    api_key: str, model: str, formatted_transcript: str
) -> str | None:
    """Single-pass structured transcript generation for transcripts that fit in context."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _STRUCTURED_TRANSCRIPT_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Транскрипция встречи:\n\n{formatted_transcript}"},
                    ],
                    "max_tokens": 8000,
                    "temperature": 0.2,
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                json.loads(raw)
                return raw
    except Exception as e:
        logger.error(f"Structured transcript generation error: {e}")
        return None


def _timecode_to_seconds(tc: str) -> float:
    """Convert HH:MM:SS.mmm to seconds."""
    parts = tc.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


async def _structured_transcript_chunked(
    api_key: str, model: str, vtt_entries: list[dict], max_chars: int
) -> str | None:
    """Chunked processing for very long transcripts.

    Splits entries into ~15-minute overlapping windows, generates per-chunk
    topics, then merges results.
    """
    chunk_duration_s = 900  # 15 minutes
    overlap_s = 60  # 1 minute overlap

    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    chunk_start_s = 0.0

    for entry in vtt_entries:
        entry_start_s = _timecode_to_seconds(entry["start_time"])
        if entry_start_s >= chunk_start_s + chunk_duration_s and current_chunk:
            chunks.append(current_chunk)
            rewind_s = entry_start_s - overlap_s
            current_chunk = [e for e in current_chunk
                            if _timecode_to_seconds(e["start_time"]) >= rewind_s]
            current_chunk.append(entry)
            chunk_start_s = entry_start_s - overlap_s
        else:
            current_chunk.append(entry)
    if current_chunk:
        chunks.append(current_chunk)

    all_items: list[dict] = []
    for chunk in chunks:
        formatted = _format_vtt_for_llm(chunk)
        result_json = await _structured_transcript_single(api_key, model, formatted[:max_chars])
        if result_json:
            try:
                parsed = json.loads(result_json)
                all_items.extend(parsed.get("items", []))
            except json.JSONDecodeError:
                pass

    if not all_items:
        return None

    seen_starts: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        key = item.get("start_time", "")
        if key not in seen_starts:
            seen_starts.add(key)
            deduped.append(item)

    deduped.sort(key=lambda x: _timecode_to_seconds(x.get("start_time", "00:00:00.000")))

    overall = await _generate_overall_from_items(api_key, model, deduped)

    result = {
        "overall_summary": overall or "",
        "items": deduped,
    }
    return json.dumps(result, ensure_ascii=False)


async def _generate_overall_from_items(
    api_key: str, model: str, items: list[dict]
) -> str:
    """Generate an overall_summary from already-segmented items."""
    summaries = "\n".join(
        f"- {it.get('label', '')}: {it.get('summary', '')}" for it in items
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Ты — ассистент. Напиши общее описание встречи на русском "
                                "(3-5 предложений) на основе списка обсуждённых тем. "
                                "Отвечай только текстом описания."
                            ),
                        },
                        {"role": "user", "content": f"Темы встречи:\n\n{summaries[:6000]}"},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Overall summary generation error: {e}")
        return ""


async def _send_telegram_notification(chat_id: str, text: str) -> bool:
    """Send an HTML message to a Telegram chat via Bot API (no library needed)."""
    token = config.telegram_token
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Telegram sendMessage failed ({resp.status}): {body}")
                    return False
                return True
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")
        return False


@routes.post('/api/zoom/webhook')
async def zoom_webhook(request):
    """Handle Zoom webhook events (URL validation, recording.completed, etc.)."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    event = body.get("event", "")
    logger.info(f"Zoom webhook event: {event}")

    # --- URL validation challenge ---
    if event == "endpoint.url_validation":
        plain_token = body.get("payload", {}).get("plainToken", "")
        secret = config.zoom_webhook_secret_token or ""
        hash_obj = hmac.new(secret.encode(), plain_token.encode(), hashlib.sha256)
        encrypted_token = hash_obj.hexdigest()
        return web.json_response({
            "plainToken": plain_token,
            "encryptedToken": encrypted_token,
        })

    # --- Meeting created (e.g. Calendly bookings) ---
    if event == "meeting.created":
        payload = body.get("payload", {}).get("object", {})
        meeting_id = payload.get("id")
        topic = payload.get("topic", "Встреча")
        duration = payload.get("duration", 30)
        join_url = payload.get("join_url", "")
        start_url = payload.get("start_url", "") or join_url
        start_time_raw = payload.get("start_time", "")
        host_email = payload.get("host_email", "")

        logger.info(f"Meeting {meeting_id}: meeting.created — topic={topic}")

        start_time_dt = None
        if start_time_raw:
            from datetime import datetime
            try:
                start_time_dt = datetime.fromisoformat(start_time_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        start_time_str = format_start_time(start_time_dt)
        end_time_str = format_end_time(start_time_dt, duration) if start_time_dt else None

        db_meeting = await db.get_zoom_meeting(meeting_id) if meeting_id else None
        host_name = None
        if db_meeting:
            host_name = db_meeting.get("host_name")

        if not host_name and host_email:
            host_name = host_email.split("@")[0]

        if lark_client:
            try:
                result = await lark_client.send_meeting_card(
                    topic=topic,
                    duration=duration,
                    join_url=join_url,
                    start_url=start_url,
                    host_name=host_name or "Calendly",
                    start_time=start_time_str,
                    end_time=end_time_str,
                    card_title="📅 Новая встреча забронирована",
                )
                new_msg_id = result.get("data", {}).get("message_id")
                logger.info(f"Meeting {meeting_id}: Lark 'created' card sent (msg_id={new_msg_id})")

                if db_meeting and new_msg_id:
                    await db.update_meeting_lark_message_id(meeting_id, new_msg_id)
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to send Lark created card: {e}")

        notify_chat = config.calendly_notify_chat_id
        if notify_chat:
            tg_text = (
                "📅 <b>Новая встреча забронирована!</b>\n\n"
                f"📌 <b>Тема:</b> {topic}\n"
                f"🕐 <b>Начало:</b> {start_time_str or '—'}\n"
                f"⏱ <b>Длительность:</b> {duration} мин\n"
                f"👤 <b>Организатор:</b> {host_name or host_email or '—'}\n"
                f"🔗 <b>Ссылка (гость):</b> {join_url}\n"
                f"🎬 <b>Ссылка (хост):</b> {start_url}"
            )
            ok = await _send_telegram_notification(notify_chat, tg_text)
            if ok:
                logger.info(f"Meeting {meeting_id}: Telegram notification sent to {notify_chat}")

        return web.json_response({"status": "ok"})

    # --- Recording completed ---
    if event == "recording.completed":
        payload = body.get("payload", {}).get("object", {})
        meeting_id = payload.get("id")
        try:
            meeting_id = int(meeting_id)
        except (TypeError, ValueError):
            logger.error(f"Invalid meeting_id in recording.completed: {meeting_id}")
            return web.json_response({"error": "invalid meeting_id"}, status=400)

        topic = payload.get("topic", "Встреча")
        duration = payload.get("duration", 0)
        recording_files = payload.get("recording_files", [])

        file_types = [rf.get("file_type") for rf in recording_files]
        logger.info(f"Meeting {meeting_id}: recording.completed — file types: {file_types}")

        share_url = payload.get("share_url", "")
        recording_password = payload.get("recording_play_passcode") or payload.get("password", "")
        
        # Use share_url as primary recording URL (it's embeddable)
        recording_url = share_url
        transcript_download_url = None
        summary_download_url = None

        for rf in recording_files:
            if rf.get("file_type") == "TRANSCRIPT":
                transcript_download_url = rf.get("download_url")
            elif rf.get("file_type") == "SUMMARY" and rf.get("recording_type") == "summary":
                summary_download_url = rf.get("download_url")

        # Add password to recording URL if present
        if recording_password and recording_url and "?pwd=" not in recording_url:
            recording_url = f"{recording_url}?pwd={recording_password}"

        transcript_text = ""
        
        # Try to download TRANSCRIPT first
        if transcript_download_url and zoom_client:
            logger.info(f"Meeting {meeting_id}: downloading Zoom VTT transcript...")
            try:
                token = await zoom_client.get_access_token()
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        transcript_download_url,
                        headers={"Authorization": f"Bearer {token}"},
                    ) as resp:
                        if resp.status == 200:
                            transcript_text = await resp.text()
                            logger.info(f"Meeting {meeting_id}: VTT transcript downloaded — {len(transcript_text)} chars")
                        else:
                            logger.error(f"Meeting {meeting_id}: VTT transcript download returned status {resp.status}")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to download VTT transcript: {e}")
        
        # If no TRANSCRIPT, try to download SUMMARY from Zoom
        if not transcript_text and summary_download_url and zoom_client:
            logger.info(f"Meeting {meeting_id}: no TRANSCRIPT, downloading Zoom SUMMARY instead...")
            try:
                token = await zoom_client.get_access_token()
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        summary_download_url,
                        headers={"Authorization": f"Bearer {token}"},
                    ) as resp:
                        if resp.status == 200:
                            transcript_text = await resp.text()
                            logger.info(f"Meeting {meeting_id}: Zoom SUMMARY downloaded — {len(transcript_text)} chars")
                        else:
                            logger.error(f"Meeting {meeting_id}: SUMMARY download returned status {resp.status}")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to download SUMMARY: {e}")

        summary = ""
        structured_transcript_json = None
        if transcript_text:
            summary = await generate_summary(transcript_text)
            vtt_entries = parse_vtt(transcript_text)
            if vtt_entries:
                logger.info(f"Meeting {meeting_id}: parsed {len(vtt_entries)} VTT entries, generating structured transcript...")
                structured_transcript_json = await generate_structured_transcript(vtt_entries)
                if structured_transcript_json:
                    logger.info(f"Meeting {meeting_id}: structured transcript generated — {len(structured_transcript_json)} chars")

        public_token = uuid.uuid4().hex[:16]

        try:
            await db.update_meeting_recording(
                meeting_id=meeting_id,
                recording_url=recording_url,
                transcript_text=transcript_text[:500000] if transcript_text else None,
                summary=summary or None,
                status="recorded",
            )
            await db.update_meeting_public_token(meeting_id, public_token)
            if structured_transcript_json:
                await db.update_meeting_structured_transcript(meeting_id, structured_transcript_json)
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to update recording in DB: {e}")

        # Download video and audio from Zoom and upload to S3
        asyncio.create_task(_upload_video_to_s3(meeting_id))
        asyncio.create_task(_upload_audio_to_s3(meeting_id))

        webapp_url = config.webapp_url or ''
        public_page_url = f"{webapp_url}/meeting/{public_token}" if webapp_url else None

        # Only send Lark card if we have a summary
        if lark_client and summary:
            try:
                # Get meeting details for Lark card
                db_meeting = await db.get_zoom_meeting(meeting_id)
                host_name = db_meeting.get('host_name') if db_meeting else None
                start_time_str = format_start_time(db_meeting.get('start_time')) if db_meeting else None
                end_time_str = format_end_time(db_meeting.get('start_time'), duration) if db_meeting and db_meeting.get('start_time') else None
                participants = await get_participants_with_notes(meeting_id)
                
                # Generate short summary (3 sentences) for Lark card
                short_summary = await generate_short_summary(summary)

                await lark_client.send_recording_card(
                    topic=topic,
                    recording_url=recording_url,
                    transcript_text=transcript_text[:3000] if transcript_text else None,
                    summary=summary,
                    duration=duration,
                    public_page_url=public_page_url,
                    host_name=host_name,
                    start_time=start_time_str,
                    end_time=end_time_str,
                    participants=participants if participants else None,
                    short_summary=short_summary or None,
                )
                logger.info(f"Meeting {meeting_id}: recording card sent to Lark (with summary)")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to send Lark recording card: {e}")
        elif lark_client and not summary:
            logger.info(f"Meeting {meeting_id}: Lark card — sending recording card without summary (transcription pending)")
            asyncio.create_task(_send_lark_recording_card_no_summary(meeting_id))

        if not transcript_text:
            logger.warning(
                f"Meeting {meeting_id}: no TRANSCRIPT file from Zoom. "
                "Starting audio-based auto-transcription and polling as fallback."
            )
            asyncio.create_task(_poll_transcript_later(meeting_id, topic, duration, recording_url, public_token))
            asyncio.create_task(_safe_auto_transcribe(meeting_id))

        # Trigger embedding generation for any projects this meeting belongs to
        asyncio.create_task(_embed_projects_for_meeting(meeting_id))

        return web.json_response({"status": "ok"})

    # --- Recording transcript completed ---
    if event == "recording.transcript.completed":
        payload = body.get("payload", {}).get("object", {})
        meeting_id = payload.get("id")
        try:
            meeting_id = int(meeting_id)
        except (TypeError, ValueError):
            logger.error(f"Invalid meeting_id in transcript.completed: {meeting_id}")
            return web.json_response({"error": "invalid meeting_id"}, status=400)

        topic = payload.get("topic", "Встреча")
        recording_files = payload.get("recording_files", [])
        logger.info(f"Meeting {meeting_id}: recording.transcript.completed — processing")

        transcript_download_url = None
        for rf in recording_files:
            if rf.get("file_type") == "TRANSCRIPT":
                transcript_download_url = rf.get("download_url")

        if not transcript_download_url:
            logger.warning(f"Meeting {meeting_id}: no transcript download URL in transcript.completed event")
            return web.json_response({"status": "ok"})

        transcript_text = ""
        if zoom_client:
            try:
                token = await zoom_client.get_access_token()
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        transcript_download_url,
                        headers={"Authorization": f"Bearer {token}"},
                    ) as resp:
                        if resp.status == 200:
                            transcript_text = await resp.text()
                            logger.info(f"Meeting {meeting_id}: VTT transcript downloaded via transcript.completed — {len(transcript_text)} chars")
                        else:
                            logger.error(f"Meeting {meeting_id}: transcript download returned status {resp.status}")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to download transcript: {e}")

        if not transcript_text:
            return web.json_response({"status": "ok"})

        summary = await generate_summary(transcript_text)

        structured_transcript_json = None
        vtt_entries = parse_vtt(transcript_text)
        if vtt_entries:
            logger.info(f"Meeting {meeting_id}: parsed {len(vtt_entries)} VTT entries (transcript.completed)")
            structured_transcript_json = await generate_structured_transcript(vtt_entries)

        try:
            await db.update_meeting_transcript_and_summary(
                meeting_id=meeting_id,
                transcript_text=transcript_text[:500000],
                summary=summary or None,
            )
            if structured_transcript_json:
                await db.update_meeting_structured_transcript(meeting_id, structured_transcript_json)
            logger.info(f"Meeting {meeting_id}: transcript/summary updated via transcript.completed")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to update transcript/summary in DB: {e}")

        # Only send Lark card if we have a summary
        if lark_client and summary:
            db_meeting = await db.get_zoom_meeting(meeting_id)
            if db_meeting and db_meeting.get("lark_message_id"):
                try:
                    await lark_client.delete_message(db_meeting["lark_message_id"])
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to delete old Lark card: {e}")

            if db_meeting:
                recording_url = db_meeting.get("recording_url", "")
                duration = db_meeting.get("duration", 0)
                pt = db_meeting.get("public_token", "")
                webapp_url = config.webapp_url or ''
                public_page_url = f"{webapp_url}/meeting/{pt}" if webapp_url and pt else None

                # Get meeting details for Lark card
                host_name = db_meeting.get('host_name')
                start_time_str = format_start_time(db_meeting.get('start_time'))
                end_time_str = format_end_time(db_meeting.get('start_time'), duration)
                participants = await get_participants_with_notes(meeting_id)
                
                # Generate short summary (3 sentences) for Lark card
                short_summary = await generate_short_summary(summary)

                try:
                    result = await lark_client.send_recording_card(
                        topic=topic,
                        recording_url=recording_url,
                        transcript_text=transcript_text[:3000],
                        summary=summary,
                        duration=duration,
                        public_page_url=public_page_url,
                        host_name=host_name,
                        start_time=start_time_str,
                        end_time=end_time_str,
                        participants=participants if participants else None,
                        short_summary=short_summary or None,
                    )
                    new_msg_id = result.get("data", {}).get("message_id")
                    if new_msg_id:
                        await db.update_meeting_lark_message_id(meeting_id, new_msg_id)
                    logger.info(f"Meeting {meeting_id}: Lark card updated via transcript.completed (with summary)")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to send Lark recording card: {e}")
        elif lark_client and not summary:
            logger.info(f"Meeting {meeting_id}: Lark card NOT sent via transcript.completed — no summary yet")

        asyncio.create_task(_embed_projects_for_meeting(meeting_id))

        return web.json_response({"status": "ok"})

    # --- Meeting ended ---
    if event == "meeting.ended":
        payload = body.get("payload", {}).get("object", {})
        meeting_id = payload.get("id")
        try:
            meeting_id = int(meeting_id)
        except (TypeError, ValueError):
            logger.error(f"Invalid meeting_id in meeting.ended: {meeting_id}")
            return web.json_response({"error": "invalid meeting_id"}, status=400)

        topic = payload.get("topic", "Встреча")
        duration = payload.get("duration", 0)
        logger.info(f"Meeting {meeting_id}: meeting.ended — updating Lark card")

        if zoom_client:
            try:
                past = await zoom_client.get_past_meeting(meeting_id)
                if past and past.get("duration"):
                    duration = past["duration"]
                    await db.update_meeting_duration(meeting_id, duration)
            except Exception as e:
                logger.warning(f"Meeting {meeting_id}: could not fetch actual duration: {e}")

        db_meeting = await db.get_zoom_meeting(meeting_id)

        await db.update_meeting_status(meeting_id, "ended")

        if lark_client and db_meeting:
            if db_meeting.get("lark_message_id"):
                try:
                    await lark_client.delete_message(db_meeting["lark_message_id"])
                except Exception as e:
                    logger.warning(f"Meeting {meeting_id}: failed to delete old Lark card: {e}")

            host_name = db_meeting.get('host_name')
            start_time_str = format_start_time(db_meeting.get('start_time'))
            participants = await get_participants_with_notes(meeting_id)

            try:
                result = await lark_client.send_meeting_ended_card(
                    topic=topic,
                    host_name=host_name,
                    start_time=start_time_str,
                    duration=duration or db_meeting.get('duration', 0),
                    participants=participants if participants else None,
                )
                new_msg_id = result.get("data", {}).get("message_id")
                if new_msg_id:
                    await db.update_meeting_lark_message_id(meeting_id, new_msg_id)
                logger.info(f"Meeting {meeting_id}: Lark 'ended' card sent")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to send Lark ended card: {e}")

        return web.json_response({"status": "ok"})

    return web.json_response({"status": "ignored"})


def _build_transcription_prompt(participant_names: list[str], offset_seconds: int = 0) -> str:
    """Build the transcription prompt, optionally including known participant names and time offset."""
    if offset_seconds > 0:
        h = offset_seconds // 3600
        m = (offset_seconds % 3600) // 60
        s = offset_seconds % 60
        if h > 0:
            offset_str = f"{h}:{m:02d}:{s:02d}"
            ts_fmt = "[H:MM:SS]"
        else:
            offset_str = f"{m:02d}:{s:02d}"
            ts_fmt = "[MM:SS]"
        base = (
            "Transcribe this audio file in full detail. "
            f"IMPORTANT: This is a segment from a longer recording. This segment starts at {offset_str} in the full recording. "
            f"All timestamps MUST reflect the actual position in the full recording, starting from [{offset_str}]. "
            f"Include timestamps in format {ts_fmt} at the beginning of each logical segment or speaker change. "
            "Capture every word spoken, including filler words and hesitations. "
        )
    else:
        base = (
            "Transcribe this audio file in full detail. "
            "Include timestamps in format [MM:SS] or [H:MM:SS] at the beginning of each logical segment or speaker change. "
            "Capture every word spoken, including filler words and hesitations. "
        )
    if participant_names:
        names_str = ", ".join(participant_names)
        base += (
            f"The following people participated in this meeting: {names_str}. "
            "Try to identify each speaker by their real name based on voice, context, "
            "how they address each other, and who is introduced as the organizer. "
            "Use their actual names (e.g. \"Иван:\", \"Malik:\") instead of generic labels like Speaker 1. "
            "If you cannot confidently identify a speaker, use \"Неизвестный\" with a number. "
        )
    else:
        base += "Identify different speakers where possible (Speaker 1, Speaker 2, etc). "

    base += (
        "Preserve the original language of the audio. "
        "Output ONLY the transcription text itself. "
        "Do NOT include any preamble, introduction, commentary, or explanation — "
        "start directly with the first timestamp and spoken words."
    )
    return base


async def _gather_participant_names(meeting_id: int, db_meeting: dict | None) -> list[str]:
    """Collect participant names from Zoom API and local DB for speaker identification."""
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: str, role: str = ""):
        clean = name.strip() if name else ""
        if not clean or clean.lower() in seen:
            return
        seen.add(clean.lower())
        names.append(f"{clean} ({role})" if role else clean)

    if db_meeting:
        _add(db_meeting.get("host_name", ""), "организатор")

    if zoom_client and meeting_id > 0:
        try:
            zoom_parts = await zoom_client.get_past_meeting_participants(meeting_id)
            for zp in zoom_parts:
                _add(zp.get("name", ""), "")
        except Exception as e:
            logger.warning(f"Meeting {meeting_id}: failed to fetch Zoom participants: {e}")

    try:
        db_parts = await db.get_meeting_participants(meeting_id)
        for p in db_parts:
            first = p.get("first_name") or ""
            last = p.get("last_name") or ""
            full = f"{first} {last}".strip()
            if full:
                _add(full, "")
            elif p.get("username"):
                _add(p["username"], "")
    except Exception as e:
        logger.warning(f"Meeting {meeting_id}: failed to fetch DB participants: {e}")

    logger.info(f"Meeting {meeting_id}: gathered {len(names)} participant names: {names}")
    return names


async def _safe_auto_transcribe(meeting_id: int):
    """Wrapper for background auto-transcribe that catches all exceptions and logs them."""
    try:
        await _auto_transcribe_audio(meeting_id)
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: background auto-transcribe crashed: {e}")
        await _send_lark_recording_card_no_summary(meeting_id)


async def _send_lark_recording_card_no_summary(meeting_id: int):
    """Send a Lark recording card without summary (used when transcription fails but recording exists)."""
    if not lark_client:
        return
    try:
        db_meeting = await db.get_zoom_meeting(meeting_id)
        if not db_meeting:
            return

        if db_meeting.get("lark_message_id"):
            try:
                await lark_client.delete_message(db_meeting["lark_message_id"])
            except Exception:
                pass

        topic = db_meeting.get("topic", "Встреча")
        recording_url = db_meeting.get("recording_url", "")
        duration = db_meeting.get("duration", 0)
        pt = db_meeting.get("public_token", "")
        webapp_url = config.webapp_url or ''
        public_page_url = f"{webapp_url}/meeting/{pt}" if webapp_url and pt else None
        host_name = db_meeting.get('host_name')
        start_time_str = format_start_time(db_meeting.get('start_time')) if db_meeting.get('start_time') else None
        end_time_str = format_end_time(db_meeting.get('start_time'), duration) if db_meeting.get('start_time') else None
        participants = await get_participants_with_notes(meeting_id)

        result = await lark_client.send_recording_card(
            topic=topic,
            recording_url=recording_url,
            transcript_text=None,
            summary=None,
            duration=duration,
            public_page_url=public_page_url,
            host_name=host_name,
            start_time=start_time_str,
            end_time=end_time_str,
            participants=participants if participants else None,
            short_summary="⏳ Транскрипция обрабатывается...",
        )
        new_msg_id = result.get("data", {}).get("message_id")
        if new_msg_id:
            await db.update_meeting_lark_message_id(meeting_id, new_msg_id)
        logger.info(f"Meeting {meeting_id}: Lark recording card sent (without summary, transcription pending)")
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: failed to send Lark recording card (no summary): {e}")


async def _auto_transcribe_audio(meeting_id: int, provided_audio: bytes = None, provided_audio_fmt: str = None):
    """Background: transcribe audio via OpenRouter, save transcript/summary, send Lark card.
    If provided_audio is given, uses it directly; otherwise downloads from Zoom."""
    import base64
    import tempfile
    import glob as glob_module

    db_meeting = await db.get_zoom_meeting(meeting_id)
    if db_meeting and db_meeting.get("transcript_text"):
        logger.info(f"Meeting {meeting_id}: auto-transcribe skipped — transcript already in DB")
        return

    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        logger.warning(f"Meeting {meeting_id}: auto-transcribe skipped — missing API key")
        return

    # Gather participant names for speaker identification
    participant_names = await _gather_participant_names(meeting_id, db_meeting)

    if provided_audio:
        audio_bytes = provided_audio
        audio_fmt = provided_audio_fmt or "mp3"
        logger.info(f"Meeting {meeting_id}: auto-transcribe starting (provided audio, {audio_fmt}, {len(audio_bytes)} bytes)")
    else:
        audio_bytes = None
        audio_fmt = "mp3"

        if db_meeting and db_meeting.get('audio_s3_url'):
            try:
                logger.info(f"Meeting {meeting_id}: downloading audio from S3")
                async with aiohttp.ClientSession() as session:
                    async with session.get(db_meeting['audio_s3_url'], timeout=aiohttp.ClientTimeout(total=300)) as resp:
                        if resp.status == 200:
                            audio_bytes = await resp.read()
                            audio_fmt = db_meeting['audio_s3_url'].rsplit('.', 1)[-1] or 'mp3'
                            logger.info(f"Meeting {meeting_id}: audio from S3 ({audio_fmt}, {len(audio_bytes)} bytes)")
                        else:
                            logger.warning(f"Meeting {meeting_id}: S3 audio download failed (status {resp.status})")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: error downloading audio from S3: {e}")

        if not audio_bytes and db_meeting and db_meeting.get('video_s3_url'):
            try:
                logger.info(f"Meeting {meeting_id}: downloading video from S3 to extract audio")
                async with aiohttp.ClientSession() as session:
                    async with session.get(db_meeting['video_s3_url'], timeout=aiohttp.ClientTimeout(total=600)) as resp:
                        if resp.status == 200:
                            video_bytes = await resp.read()
                            video_ext = db_meeting['video_s3_url'].rsplit('.', 1)[-1] or 'mp4'
                            logger.info(f"Meeting {meeting_id}: video from S3 ({len(video_bytes)} bytes), extracting audio")
                            with tempfile.NamedTemporaryFile(suffix=f".{video_ext}", delete=False) as src:
                                src.write(video_bytes)
                                src_path = src.name
                            del video_bytes
                            dst_path = src_path.rsplit(".", 1)[0] + ".mp3"
                            rc, _, stderr = await _run_ffmpeg(
                                "-y", "-i", src_path, "-vn", "-b:a", "128k", "-f", "mp3", dst_path,
                                timeout=300,
                            )
                            os.unlink(src_path)
                            if rc == 0:
                                with open(dst_path, "rb") as f:
                                    audio_bytes = f.read()
                                os.unlink(dst_path)
                                audio_fmt = "mp3"
                                logger.info(f"Meeting {meeting_id}: audio extracted from video ({len(audio_bytes)} bytes)")
                                if s3_client:
                                    asyncio.create_task(_upload_audio_to_s3(meeting_id, audio_bytes, audio_fmt))
                            else:
                                logger.error(f"Meeting {meeting_id}: ffmpeg extraction failed: {stderr.decode()[:500]}")
                                if os.path.exists(dst_path):
                                    os.unlink(dst_path)
                        else:
                            logger.warning(f"Meeting {meeting_id}: S3 video download failed (status {resp.status})")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: error extracting audio from S3 video: {e}")

        if not audio_bytes:
            if not zoom_client:
                logger.warning(f"Meeting {meeting_id}: auto-transcribe skipped — no audio source available")
                return
            logger.info(f"Meeting {meeting_id}: auto-transcribe starting (audio from Zoom)")
            audio_result = await zoom_client.download_meeting_audio(meeting_id)
            if not audio_result:
                logger.warning(f"Meeting {meeting_id}: auto-transcribe — no audio available from any source")
                return
            audio_bytes, audio_fmt = audio_result
            logger.info(f"Meeting {meeting_id}: audio downloaded from Zoom ({audio_fmt}, {len(audio_bytes)} bytes)")

    if not db_meeting or not db_meeting.get('audio_s3_url'):
        asyncio.create_task(_upload_audio_to_s3(meeting_id, audio_bytes, audio_fmt))

    # Convert to mp3 if needed
    if audio_fmt not in ("mp3", "wav"):
        try:
            logger.info(f"Meeting {meeting_id}: converting {audio_fmt} -> mp3 via ffmpeg")
            with tempfile.NamedTemporaryFile(suffix=f".{audio_fmt}", delete=False) as src:
                src.write(audio_bytes)
                src_path = src.name
            dst_path = src_path.rsplit(".", 1)[0] + ".mp3"
            rc, _, stderr = await _run_ffmpeg(
                "-y", "-i", src_path, "-b:a", "128k", "-f", "mp3", dst_path,
                timeout=600,
            )
            os.unlink(src_path)
            if rc != 0:
                logger.error(f"Meeting {meeting_id}: ffmpeg conversion failed: {stderr.decode()[:500]}")
                return
            with open(dst_path, "rb") as f:
                audio_bytes = f.read()
            os.unlink(dst_path)
            audio_fmt = "mp3"
            logger.info(f"Meeting {meeting_id}: converted to mp3 — {len(audio_bytes)} bytes")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: audio conversion error: {e}")
            return

    MAX_CHUNK_BYTES = 9 * 1024 * 1024  # 9MB — ~10 min per chunk at 128kbps, avoids AI token truncation
    chunks = []

    if len(audio_bytes) > MAX_CHUNK_BYTES:
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{audio_fmt}", delete=False) as src:
                src.write(audio_bytes)
                src_path = src.name
            chunk_dir = tempfile.mkdtemp()
            pattern = os.path.join(chunk_dir, "chunk_%03d.mp3")
            rc, _, stderr = await _run_ffmpeg(
                "-y", "-i", src_path, "-f", "segment", "-segment_time", "600",
                "-b:a", "128k", pattern,
                timeout=600,
            )
            os.unlink(src_path)
            if rc != 0:
                logger.error(f"Meeting {meeting_id}: ffmpeg split failed: {stderr.decode()[:500]}")
                return
            for chunk_file in sorted(glob_module.glob(os.path.join(chunk_dir, "chunk_*.mp3"))):
                with open(chunk_file, "rb") as f:
                    chunks.append(("mp3", f.read()))
                os.unlink(chunk_file)
            os.rmdir(chunk_dir)
            logger.info(f"Meeting {meeting_id}: split into {len(chunks)} chunks")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to split audio: {e}")
            return
    else:
        chunks = [(audio_fmt, audio_bytes)]

    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 15, 30]

    SEGMENT_DURATION = 600

    full_transcript = []
    for idx, (fmt, chunk_bytes) in enumerate(chunks):
        b64 = base64.b64encode(chunk_bytes).decode('utf-8')
        chunk_text = None
        chunk_offset_seconds = idx * SEGMENT_DURATION if len(chunks) > 1 else 0

        for attempt in range(MAX_RETRIES):
            attempt_suffix = f" (attempt {attempt+1}/{MAX_RETRIES})" if attempt > 0 else ""
            logger.info(f"Meeting {meeting_id}: transcribing chunk {idx+1}/{len(chunks)} ({len(chunk_bytes)} bytes, offset={chunk_offset_seconds}s){attempt_suffix}")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "google/gemini-3-flash-preview",
                            "provider": {
                                "ignore": ["Google AI Studio"],
                            },
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": _build_transcription_prompt(participant_names, offset_seconds=chunk_offset_seconds),
                                        },
                                        {
                                            "type": "input_audio",
                                            "input_audio": {"data": b64, "format": fmt},
                                        },
                                    ],
                                }
                            ],
                        },
                        timeout=aiohttp.ClientTimeout(total=600),
                    ) as resp:
                        data = await resp.json()
                        if resp.status != 200 or "error" in data:
                            logger.warning(f"Meeting {meeting_id}: OpenRouter error on chunk {idx+1}{attempt_suffix}: {str(data)[:500]}")
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAYS[attempt])
                                continue
                            break
                        if "choices" in data:
                            chunk_text = data["choices"][0]["message"]["content"].strip()
                        elif "text" in data:
                            chunk_text = data["text"].strip()
                        else:
                            logger.warning(f"Meeting {meeting_id}: unexpected OpenRouter response on chunk {idx+1}{attempt_suffix}: {str(data)[:300]}")
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAYS[attempt])
                                continue
                            break
                        logger.info(f"Meeting {meeting_id}: chunk {idx+1} transcribed — {len(chunk_text)} chars")
                        break
            except asyncio.TimeoutError:
                logger.warning(f"Meeting {meeting_id}: transcription timeout on chunk {idx+1}{attempt_suffix}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
                break
            except Exception as e:
                logger.warning(f"Meeting {meeting_id}: transcription error on chunk {idx+1}{attempt_suffix}: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
                break

        if chunk_text is None:
            logger.error(f"Meeting {meeting_id}: chunk {idx+1} failed after {MAX_RETRIES} attempts, aborting transcription")
            await db.update_meeting_status(meeting_id, 'recorded')
            await _send_lark_recording_card_no_summary(meeting_id)
            return
        full_transcript.append(chunk_text)

    transcript_text = "\n\n".join(full_transcript)
    logger.info(f"Meeting {meeting_id}: auto-transcription complete — {len(transcript_text)} chars")

    # Re-check: another path might have saved transcript while we were transcribing
    fresh = await db.get_zoom_meeting(meeting_id)
    if fresh and fresh.get("transcript_text"):
        logger.info(f"Meeting {meeting_id}: auto-transcribe — transcript arrived via other path, skipping save")
        return

    summary = await generate_summary(transcript_text)

    structured_transcript_json = None
    vtt_entries = parse_vtt(transcript_text)
    if vtt_entries:
        structured_transcript_json = await generate_structured_transcript(vtt_entries)
    else:
        model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
        if transcript_text:
            structured_transcript_json = await _structured_transcript_single(api_key, model, transcript_text[:200000])

    try:
        await db.update_meeting_transcript_and_summary(
            meeting_id=meeting_id,
            transcript_text=transcript_text[:500000],
            summary=summary or None,
        )
        if structured_transcript_json:
            await db.update_meeting_structured_transcript(meeting_id, structured_transcript_json)
        logger.info(f"Meeting {meeting_id}: auto-transcribe — transcript + summary saved")
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: auto-transcribe — failed to save to DB: {e}")
        return

    if lark_client and summary:
        db_meeting = await db.get_zoom_meeting(meeting_id)
        if db_meeting and db_meeting.get("lark_message_id"):
            try:
                await lark_client.delete_message(db_meeting["lark_message_id"])
            except Exception:
                pass

        topic = db_meeting.get("topic", "Встреча") if db_meeting else "Встреча"
        recording_url = db_meeting.get("recording_url", "") if db_meeting else ""
        duration = db_meeting.get("duration", 0) if db_meeting else 0
        pt = db_meeting.get("public_token", "") if db_meeting else ""
        webapp_url = config.webapp_url or ''
        public_page_url = f"{webapp_url}/meeting/{pt}" if webapp_url and pt else None
        host_name = db_meeting.get('host_name') if db_meeting else None
        start_time_str = format_start_time(db_meeting.get('start_time')) if db_meeting else None
        end_time_str = format_end_time(db_meeting.get('start_time'), duration) if db_meeting and db_meeting.get('start_time') else None
        participants = await get_participants_with_notes(meeting_id)
        short_summary = await generate_short_summary(summary)

        try:
            result = await lark_client.send_recording_card(
                topic=topic,
                recording_url=recording_url,
                transcript_text=transcript_text[:3000],
                summary=summary,
                duration=duration,
                public_page_url=public_page_url,
                host_name=host_name,
                start_time=start_time_str,
                end_time=end_time_str,
                participants=participants if participants else None,
                short_summary=short_summary or None,
            )
            new_msg_id = result.get("data", {}).get("message_id")
            if new_msg_id:
                await db.update_meeting_lark_message_id(meeting_id, new_msg_id)
            logger.info(f"Meeting {meeting_id}: Lark recording card sent after auto-transcription")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to send Lark card after auto-transcription: {e}")

    asyncio.create_task(_embed_projects_for_meeting(meeting_id))


async def _upload_video_to_s3(meeting_id: int):
    """Download MP4 from Zoom and upload to S3 in the background."""
    try:
        if not zoom_client or not s3_client:
            return
        video_result = await zoom_client.download_meeting_video(meeting_id)
        if not video_result:
            logger.info(f"Meeting {meeting_id}: no video available for S3 upload")
            return
        video_bytes, fmt = video_result
        url = s3_client.upload_video(meeting_id, video_bytes, fmt)
        if url:
            await db.update_meeting_video_url(meeting_id, url)
            logger.info(f"Meeting {meeting_id}: video uploaded to S3 -> {url}")
        else:
            logger.error(f"Meeting {meeting_id}: S3 upload returned None")
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: _upload_video_to_s3 error: {e}")


async def _upload_audio_to_s3(meeting_id: int, audio_bytes: bytes | None = None, audio_fmt: str | None = None):
    """Download audio from Zoom (or use provided bytes) and upload to S3."""
    try:
        if not s3_client:
            return
        if audio_bytes is None:
            if not zoom_client:
                return
            audio_result = await zoom_client.download_meeting_audio(meeting_id)
            if not audio_result:
                logger.info(f"Meeting {meeting_id}: no audio available for S3 upload")
                return
            audio_bytes, audio_fmt = audio_result
        url = s3_client.upload_audio(meeting_id, audio_bytes, audio_fmt or "m4a")
        if url:
            await db.update_meeting_audio_url(meeting_id, url)
            logger.info(f"Meeting {meeting_id}: audio uploaded to S3 -> {url}")
        else:
            logger.error(f"Meeting {meeting_id}: S3 audio upload returned None")
    except Exception as e:
        logger.error(f"Meeting {meeting_id}: _upload_audio_to_s3 error: {e}")


async def _embed_projects_for_meeting(meeting_id: int):
    """Re-generate embeddings for every project that contains this meeting."""
    try:
        db_meeting = await db.get_zoom_meeting(meeting_id)
        if not db_meeting:
            return
        projects = await db.get_meeting_projects(db_meeting['id'])
        for p in projects:
            await _embed_meeting_safe(p['id'], db_meeting['id'])
    except Exception as e:
        logger.error(f"_embed_projects_for_meeting error for {meeting_id}: {e}")


POLL_DELAYS = [600, 600, 600]  # 10 min, 20 min, 30 min total

async def _poll_transcript_later(meeting_id: int, topic: str, duration: int,
                                 recording_url: str, public_token: str):
    """Background: poll Zoom API for transcript at increasing intervals."""
    if not zoom_client:
        return

    for attempt, delay in enumerate(POLL_DELAYS, 1):
        await asyncio.sleep(delay)

        # Check if transcript already arrived via webhook/WS
        db_meeting = await db.get_zoom_meeting(meeting_id)
        if db_meeting and db_meeting.get("transcript_text"):
            logger.info(f"Meeting {meeting_id}: transcript already in DB (poll attempt {attempt} — skipping)")
            return

        logger.info(f"Meeting {meeting_id}: polling Zoom API for transcript (attempt {attempt}/{len(POLL_DELAYS)})")

        try:
            transcript_text = await zoom_client.download_meeting_transcript(meeting_id)
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: poll attempt {attempt} failed: {e}")
            continue

        if not transcript_text:
            continue

        summary = await generate_summary(transcript_text)

        structured_transcript_json = None
        vtt_entries = parse_vtt(transcript_text)
        if vtt_entries:
            logger.info(f"Meeting {meeting_id}: parsed {len(vtt_entries)} VTT entries (poll attempt {attempt})")
            structured_transcript_json = await generate_structured_transcript(vtt_entries)

        try:
            await db.update_meeting_transcript_and_summary(
                meeting_id=meeting_id,
                transcript_text=transcript_text[:500000],
                summary=summary or None,
            )
            if structured_transcript_json:
                await db.update_meeting_structured_transcript(meeting_id, structured_transcript_json)
            logger.info(f"Meeting {meeting_id}: transcript + summary saved via API poll (attempt {attempt})")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to save polled transcript: {e}")
            continue

        # Only send Lark card if we have a summary
        if lark_client and summary:
            if db_meeting and db_meeting.get("lark_message_id"):
                try:
                    await lark_client.delete_message(db_meeting["lark_message_id"])
                except Exception:
                    pass

            webapp_url = config.webapp_url or ''
            pt = public_token or (db_meeting or {}).get("public_token", "")
            page_url = f"{webapp_url}/meeting/{pt}" if webapp_url and pt else None

            # Get meeting details for Lark card
            host_name = db_meeting.get('host_name') if db_meeting else None
            start_time_str = format_start_time(db_meeting.get('start_time')) if db_meeting else None
            end_time_str = format_end_time(db_meeting.get('start_time'), duration) if db_meeting and db_meeting.get('start_time') else None
            participants = await get_participants_with_notes(meeting_id)
            
            # Generate short summary (3 sentences) for Lark card
            short_summary = await generate_short_summary(summary)

            try:
                result = await lark_client.send_recording_card(
                    topic=topic,
                    recording_url=recording_url,
                    transcript_text=transcript_text[:3000],
                    summary=summary,
                    duration=duration,
                    public_page_url=page_url,
                    host_name=host_name,
                    start_time=start_time_str,
                    end_time=end_time_str,
                    participants=participants if participants else None,
                    short_summary=short_summary or None,
                )
                new_msg_id = result.get("data", {}).get("message_id")
                if new_msg_id:
                    await db.update_meeting_lark_message_id(meeting_id, new_msg_id)
                logger.info(f"Meeting {meeting_id}: Lark card sent after poll (with summary)")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to update Lark card after poll: {e}")
        elif lark_client and not summary:
            logger.info(f"Meeting {meeting_id}: Lark card NOT sent after poll — no summary yet")

        asyncio.create_task(_embed_projects_for_meeting(meeting_id))
        return

    logger.warning(f"Meeting {meeting_id}: transcript not available after {len(POLL_DELAYS)} poll attempts")


# ========== Startup Sync: catch up on missed recordings ==========

async def _sync_single_meeting(meeting: dict):
    """Check a single 'scheduled' meeting via Zoom API; update if it has ended and has recordings."""
    mid = meeting['meeting_id']

    try:
        recordings = await zoom_client.get_meeting_recordings(mid)
    except Exception as e:
        logger.error(f"Startup sync: failed to fetch recordings for {mid}: {e}")
        return

    if not recordings:
        past = await zoom_client.get_past_meeting(mid)
        if past and past.get("status") == "ended":
            logger.info(f"Startup sync: meeting {mid} ended but no recordings yet — skipping")
        return

    recording_files = recordings.get("recording_files", [])
    if not recording_files:
        return

    share_url = recordings.get("share_url", "")
    recording_password = recordings.get("recording_play_passcode") or recordings.get("password", "")
    
    # Use share_url as primary recording URL (it's embeddable)
    recording_url = share_url
    transcript_download_url = None
    summary_download_url = None

    for rf in recording_files:
        if rf.get("file_type") == "TRANSCRIPT":
            transcript_download_url = rf.get("download_url")
        elif rf.get("file_type") == "SUMMARY" and rf.get("recording_type") == "summary":
            summary_download_url = rf.get("download_url")

    # Add password to recording URL if present
    if recording_password and recording_url and "?pwd=" not in recording_url:
        recording_url = f"{recording_url}?pwd={recording_password}"

    if not recording_url and not transcript_download_url and not summary_download_url:
        return

    logger.info(f"Startup sync: meeting {mid} has recordings, processing...")

    # Check if meeting already has transcript/summary
    has_existing_transcript = meeting.get('transcript_text') and len(meeting.get('transcript_text', '')) > 0
    has_existing_summary = meeting.get('summary') and len(meeting.get('summary', '')) > 0
    
    transcript_text = ""
    
    # Try to download TRANSCRIPT first (only if not already present)
    if transcript_download_url and not has_existing_transcript:
        try:
            token = await zoom_client.get_access_token()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    transcript_download_url,
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    if resp.status == 200:
                        transcript_text = await resp.text()
                        logger.info(f"Startup sync: meeting {mid} transcript downloaded — {len(transcript_text)} chars")
        except Exception as e:
            logger.error(f"Startup sync: meeting {mid} transcript download error: {e}")
    
    # If no TRANSCRIPT, try to download SUMMARY from Zoom (only if not already present)
    if not transcript_text and summary_download_url and not has_existing_transcript:
        logger.info(f"Startup sync: meeting {mid} no TRANSCRIPT, downloading Zoom SUMMARY...")
        try:
            token = await zoom_client.get_access_token()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    summary_download_url,
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    if resp.status == 200:
                        transcript_text = await resp.text()
                        logger.info(f"Startup sync: meeting {mid} SUMMARY downloaded — {len(transcript_text)} chars")
        except Exception as e:
            logger.error(f"Startup sync: meeting {mid} SUMMARY download error: {e}")

    # If no new transcript was downloaded and meeting already has data, check if Lark card still needs sending
    has_s3_video = bool(meeting.get('video_s3_url'))
    has_s3_audio = bool(meeting.get('audio_s3_url'))
    if not transcript_text and has_existing_transcript and has_existing_summary:
        needs_s3 = not has_s3_video or not has_s3_audio
        if meeting.get('lark_message_id') and not needs_s3:
            logger.info(f"Startup sync: meeting {mid} already has transcript/summary, Lark card, and S3 video, skipping")
            return
        elif meeting.get('lark_message_id') and needs_s3:
            logger.info(f"Startup sync: meeting {mid} has all data but missing S3 video — uploading")
            if not has_s3_video:
                asyncio.create_task(_upload_video_to_s3(mid))
            if not has_s3_audio:
                asyncio.create_task(_upload_audio_to_s3(mid))
            return
        else:
            logger.info(f"Startup sync: meeting {mid} has transcript/summary but no Lark card — will send")
            # Use existing data to build the Lark card
            transcript_text = None  # signal to skip DB update
            summary = meeting.get('summary', '')

    # transcript_text can be: non-empty string (new data), empty string (nothing downloaded), or None (skip DB update)
    # summary may already be set above (from existing DB data) if transcript_text is None
    structured_transcript_json = None
    if transcript_text is None:
        pass  # summary already set from meeting data
    else:
        summary = ""
        if transcript_text:
            try:
                summary = await generate_summary(transcript_text)
                logger.info(f"Startup sync: meeting {mid} summary generated — {len(summary)} chars")
            except Exception as e:
                logger.error(f"Startup sync: meeting {mid} summary error: {e}")

            vtt_entries = parse_vtt(transcript_text)
            if vtt_entries:
                try:
                    structured_transcript_json = await generate_structured_transcript(vtt_entries)
                    if structured_transcript_json:
                        logger.info(f"Startup sync: meeting {mid} structured transcript generated")
                except Exception as e:
                    logger.error(f"Startup sync: meeting {mid} structured transcript error: {e}")

    # transcript_text is None means we're only here to send Lark card — skip DB update
    # transcript_text is "" means nothing downloaded at all — nothing to do
    if transcript_text == "":
        if not summary:
            logger.info(f"Startup sync: meeting {mid} no new data to update")
            return

    public_token = meeting.get('public_token')
    if not public_token:
        import uuid
        public_token = uuid.uuid4().hex[:16]

    if transcript_text is not None:
        try:
            await db.update_meeting_recording(
                meeting_id=mid,
                recording_url=recording_url,
                transcript_text=transcript_text[:500000] if transcript_text else None,
                summary=summary or None,
                status="recorded",
            )
            if structured_transcript_json:
                await db.update_meeting_structured_transcript(mid, structured_transcript_json)
            if not meeting.get('public_token'):
                await db.update_meeting_public_token(mid, public_token)
        except Exception as e:
            logger.error(f"Startup sync: meeting {mid} DB update error: {e}")
            return
    else:
        # Already recorded, only sending Lark card — ensure public_token is set
        if not meeting.get('public_token'):
            import uuid
            public_token = uuid.uuid4().hex[:16]
            await db.update_meeting_public_token(mid, public_token)

    # Only send Lark card if we have a summary
    if lark_client and summary:
        old_lark_id = meeting.get('lark_message_id')
        if old_lark_id:
            try:
                await lark_client.delete_message(old_lark_id)
            except Exception:
                pass

        webapp_url = config.webapp_url or ''
        page_url = f"{webapp_url}/meeting/{public_token}" if webapp_url else None

        # Get meeting details for Lark card
        host_name = meeting.get('host_name')
        start_time_str = format_start_time(meeting.get('start_time'))
        duration = meeting.get('duration', 0)
        end_time_str = format_end_time(meeting.get('start_time'), duration)
        participants = await get_participants_with_notes(mid)
        
        # Generate short summary (3 sentences) for Lark card
        short_summary = await generate_short_summary(summary)

        try:
            topic = meeting.get('topic', 'Встреча')
            result = await lark_client.send_recording_card(
                topic=topic,
                recording_url=recording_url,
                transcript_text=transcript_text[:3000] if transcript_text else None,
                summary=summary,
                duration=duration,
                public_page_url=page_url,
                host_name=host_name,
                start_time=start_time_str,
                end_time=end_time_str,
                participants=participants if participants else None,
                short_summary=short_summary or None,
            )
            new_msg_id = result.get("data", {}).get("message_id")
            if new_msg_id:
                await db.update_meeting_lark_message_id(mid, new_msg_id)
            logger.info(f"Startup sync: meeting {mid} Lark card sent (with summary)")
        except Exception as e:
            logger.error(f"Startup sync: meeting {mid} Lark card error: {e}")
    elif lark_client and not summary:
        logger.info(f"Startup sync: meeting {mid} Lark card NOT sent — no summary yet")

    asyncio.create_task(_embed_projects_for_meeting(mid))

    # Upload video and audio to S3 if not already done
    if not meeting.get('video_s3_url'):
        asyncio.create_task(_upload_video_to_s3(mid))
    if not meeting.get('audio_s3_url'):
        asyncio.create_task(_upload_audio_to_s3(mid))

    logger.info(f"Startup sync: meeting {mid} fully processed")


async def _reconcile_overdue_meetings():
    """
    Check meetings that should have ended (start_time + duration < now - 10 min)
    but are still 'scheduled' in DB — means we missed the meeting.ended WS event.

    For each overdue meeting:
    - If Zoom past API confirms it ended → mark as 'ended' + send Lark ended card.
    - If recordings are already available → hand off to _sync_single_meeting.
    """
    if not zoom_client:
        return

    overdue = await db.get_overdue_scheduled_meetings()
    if not overdue:
        return

    logger.info(f"Reconciliation: found {len(overdue)} overdue scheduled meetings to check")

    for meeting in overdue:
        mid = meeting['meeting_id']
        try:
            # First check if there are already recordings (highest priority)
            recordings = await zoom_client.get_meeting_recordings(mid)
            if recordings and recordings.get("recording_files"):
                logger.info(f"Reconciliation: meeting {mid} has recordings — running full sync")
                await _sync_single_meeting(meeting)
                continue

            # No recordings yet — check if meeting actually ended via past_meetings API
            past = await zoom_client.get_past_meeting(mid)
            if not past:
                logger.info(f"Reconciliation: meeting {mid} not found in past meetings — skipping")
                continue

            logger.info(f"Reconciliation: meeting {mid} confirmed ended via Zoom past API — updating")

            await db.update_meeting_status(mid, "ended")

            # Send Lark "ended" card if lark_client is configured
            if lark_client:
                old_lark_id = meeting.get('lark_message_id')
                if old_lark_id:
                    try:
                        await lark_client.delete_message(old_lark_id)
                    except Exception:
                        pass

                topic = meeting.get('topic', 'Встреча')
                host_name = meeting.get('host_name')
                start_time_str = format_start_time(meeting.get('start_time'))
                duration = meeting.get('duration', 0)
                participants = await get_participants_with_notes(mid)

                try:
                    result = await lark_client.send_meeting_ended_card(
                        topic=topic,
                        host_name=host_name,
                        start_time=start_time_str,
                        duration=duration,
                        participants=participants if participants else None,
                    )
                    new_msg_id = result.get("data", {}).get("message_id")
                    if new_msg_id:
                        await db.update_meeting_lark_message_id(mid, new_msg_id)
                    logger.info(f"Reconciliation: meeting {mid} Lark 'ended' card sent")
                except Exception as e:
                    logger.error(f"Reconciliation: meeting {mid} failed to send Lark ended card: {e}")

        except Exception as e:
            logger.error(f"Reconciliation: error processing meeting {mid}: {e}", exc_info=True)


async def _periodic_meeting_reconciliation_loop():
    """Background loop: every 5 minutes reconcile meetings with missed ended events."""
    # Initial delay so DB and Zoom client are ready
    await asyncio.sleep(60)
    while True:
        try:
            await _reconcile_overdue_meetings()
        except Exception as e:
            logger.error(f"Periodic reconciliation error: {e}", exc_info=True)
        await asyncio.sleep(300)  # 5 minutes


async def sync_meetings_on_startup():
    """
    Check all 'scheduled' meetings against Zoom API and process any that completed while offline.
    Also check 'recorded' meetings that are missing transcript/summary.
    """
    if not zoom_client:
        logger.info("Startup sync: Zoom client not configured — skipped")
        return

    # Process scheduled meetings that may have ended
    scheduled = await db.get_scheduled_meetings()
    if scheduled:
        logger.info(f"Startup sync: checking {len(scheduled)} scheduled meetings...")
        for m in scheduled:
            try:
                await _sync_single_meeting(m)
            except Exception as e:
                logger.error(f"Startup sync: error processing meeting {m['meeting_id']}: {e}", exc_info=True)
    else:
        logger.info("Startup sync: no scheduled meetings to check")

    # Fix meetings stuck in 'transcribing' state from a previous crashed/restarted process
    async with db.pool.acquire() as _conn:
        stuck = await _conn.fetch(
            "SELECT meeting_id, transcript_text IS NOT NULL as has_transcript "
            "FROM zoom_meetings WHERE status = 'transcribing'"
        )
    for row in stuck:
        if row['has_transcript']:
            await db.update_meeting_status(row['meeting_id'], 'finished')
            logger.info(f"Startup sync: meeting {row['meeting_id']} had transcript but was stuck 'transcribing' — set to 'finished'")
        else:
            await db.update_meeting_status(row['meeting_id'], 'recorded')
            logger.info(f"Startup sync: meeting {row['meeting_id']} stuck 'transcribing' without transcript — reset to 'recorded'")

    # Process recorded meetings missing transcript/summary
    needing_transcript = await db.get_meetings_needing_transcript()
    if needing_transcript:
        logger.info(f"Startup sync: checking {len(needing_transcript)} meetings needing transcript...")
        for m in needing_transcript:
            try:
                await _sync_single_meeting(m)
            except Exception as e:
                logger.error(f"Startup sync: error processing meeting {m['meeting_id']}: {e}", exc_info=True)
    else:
        logger.info("Startup sync: no meetings needing transcript")

    logger.info("Startup sync: complete")

    if zoom_client:
        asyncio.ensure_future(_fix_meeting_durations())


async def _fix_meeting_durations():
    """One-time task: update actual durations from Zoom API for finished meetings."""
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT meeting_id, duration FROM zoom_meetings WHERE status IN ('finished', 'recorded', 'ended') AND meeting_id IS NOT NULL"
            )
        if not rows:
            return
        logger.info(f"Duration fix: checking {len(rows)} meetings")
        updated = 0
        for row in rows:
            mid = row['meeting_id']
            try:
                past = await zoom_client.get_past_meeting(mid)
                if past and past.get('duration') and past['duration'] != row['duration']:
                    await db.update_meeting_duration(mid, past['duration'])
                    updated += 1
            except Exception:
                pass
            await asyncio.sleep(0.3)
        logger.info(f"Duration fix: updated {updated}/{len(rows)} meetings")
    except Exception as e:
        logger.error(f"Duration fix failed: {e}")


# ========== Application Setup ==========

async def init_db(app):
    """Initialize database connection on startup"""
    logger.info("Connecting to database...")
    await db.connect()
    logger.info("Database connected successfully")

async def start_zoom_ws(app):
    """Start Zoom WebSocket listener after DB is ready."""
    global zoom_ws_listener
    if zoom_client and config.zoom_ws_subscription_id:
        zoom_ws_listener = ZoomWSListener(
            zoom_client=zoom_client,
            lark_client=lark_client,
            db=db,
            config=config,
            generate_summary_fn=generate_summary,
            generate_structured_fn=generate_structured_transcript,
            parse_vtt_fn=parse_vtt,
            s3_client=s3_client,
            auto_transcribe_fn=_auto_transcribe_audio,
        )
        await zoom_ws_listener.start()
        logger.info("Zoom WebSocket listener started")
    else:
        logger.info("Zoom WebSocket listener not configured — skipped")

async def startup_sync(app):
    """Run meeting sync after all services are ready and start periodic reconciliation."""
    asyncio.create_task(sync_meetings_on_startup())
    asyncio.create_task(_periodic_meeting_reconciliation_loop())
    logger.info("Periodic meeting reconciliation loop started")

async def close_db(app):
    """Close database connection on shutdown"""
    global zoom_ws_listener
    if zoom_ws_listener:
        await zoom_ws_listener.stop()
        logger.info("Zoom WebSocket listener stopped")
    logger.info("Closing database connection...")
    await db.disconnect()
    logger.info("Database connection closed")

def create_app():
    """Create and configure the application"""
    app = web.Application(middlewares=[auth_middleware], client_max_size=2 * 1024 * 1024 * 1024)

    # Store shared dependencies in app context for route modules
    app['db'] = db
    app['config'] = config
    app['lark_client'] = lark_client
    app['zoom_client'] = zoom_client
    app['s3_client'] = s3_client
    app['kimai_client'] = kimai_client

    app.add_routes(routes)
    app.router.add_static('/img/', './static/img/', name='static_img')
    app.router.add_static('/css/', './static/css/', name='static_css')
    app.router.add_static('/js/', './static/js/', name='static_js')

    # Setup startup/cleanup hooks
    app.on_startup.append(init_db)
    app.on_startup.append(start_zoom_ws)
    app.on_startup.append(startup_sync)
    app.on_cleanup.append(close_db)

    # Enable CORS for Telegram
    from aiohttp_cors import setup as cors_setup, ResourceOptions
    cors = cors_setup(app, defaults={
        "*": ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })

    # Configure CORS on all routes
    for route in list(app.router.routes()):
        cors.add(route)

    return app

if __name__ == '__main__':
    logger.info("Starting Mini App Web Server...")
    logger.info("Server will be available at http://0.0.0.0:8080")
    
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=8080)
