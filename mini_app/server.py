"""
Mini App Web Server
Serves static files and API endpoints for the roulette
"""

from aiohttp import web
import aiohttp
import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path to import from app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import Database
from app.config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get database URL from environment
database_url = os.getenv('DATABASE_URL')
if not database_url:
    raise ValueError("DATABASE_URL is not set in environment variables")

# Initialize database and config
db = Database(database_url)
config = Config()

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

@routes.get('/style.css')
async def css(request):
    """Serve CSS stylesheet"""
    return web.FileResponse('./static/style.css')

@routes.get('/script.js')
async def js(request):
    """Serve JavaScript file"""
    return web.FileResponse('./static/script.js')

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

# ========== Application Setup ==========

async def init_db(app):
    """Initialize database connection on startup"""
    logger.info("Connecting to database...")
    await db.connect()
    logger.info("Database connected successfully")

async def close_db(app):
    """Close database connection on shutdown"""
    logger.info("Closing database connection...")
    await db.disconnect()
    logger.info("Database connection closed")

def create_app():
    """Create and configure the application"""
    app = web.Application()
    app.add_routes(routes)
    
    # Setup startup/cleanup hooks
    app.on_startup.append(init_db)
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
