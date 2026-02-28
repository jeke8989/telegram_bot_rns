"""
Serverless function for spinning the roulette
Vercel Python runtime handler
"""
import os
import sys
import json
import asyncio
import random
import logging

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import Database

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PRIZES = [5000, 10000, 15000, 20000, 30000]

# Initialize database connection pool (will be reused across invocations)
_db = None

async def get_db():
    """Get or create database connection"""
    global _db
    if _db is None:
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL is not set")
        _db = Database(database_url)
        await _db.connect()
    return _db

def handler(request):
    """Vercel serverless function entry point"""
    try:
        # Get request body
        if isinstance(request, dict):
            body = request.get('body', '{}')
            if isinstance(body, str):
                data = json.loads(body)
            else:
                data = body
        else:
            data = {}
        
        telegram_id = data.get('telegram_id')
        
        if not telegram_id:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'telegram_id required'})
            }
        
        telegram_id = int(telegram_id)
        
        # Run async database operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        db = loop.run_until_complete(get_db())
        
        # Check if can spin
        can_spin = loop.run_until_complete(db.can_spin_roulette(telegram_id))
        
        if not can_spin:
            prize = loop.run_until_complete(db.get_user_prize(telegram_id))
            loop.close()
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Already spun',
                    'prize': prize
                })
            }
        
        # Select random prize
        prize = random.choice(PRIZES)
        
        # Save to database
        loop.run_until_complete(db.save_roulette_spin(telegram_id, prize))
        
        loop.close()
        
        logger.info(f"User {telegram_id} won {prize} RUB")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'prize': prize})
        }
    
    except Exception as e:
        logger.error(f"Error in spin endpoint: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }
