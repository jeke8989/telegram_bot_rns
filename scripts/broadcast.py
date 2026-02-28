#!/usr/bin/env python3
"""
Broadcast script - рассылка сообщений всем пользователям бота
Usage: python broadcast.py "Текст сообщения"
"""

import asyncio
import sys
from database import Database
from config import Config
import aiohttp
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def send_message(session, bot_token: str, chat_id: int, text: str) -> bool:
    """Send message to user"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    
    try:
        async with session.post(url, json=data) as response:
            result = await response.json()
            if result.get('ok'):
                return True
            else:
                # Check if user blocked the bot
                error_description = result.get('description', '')
                if 'blocked' in error_description.lower() or 'user is deactivated' in error_description.lower():
                    logger.warning(f"User {chat_id} has blocked the bot")
                    return False
                else:
                    logger.error(f"Failed to send message to {chat_id}: {error_description}")
                    return False
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
        return False


async def broadcast_message(message_text: str):
    """Broadcast message to all users"""
    config = Config()
    db = Database(config.database_url)
    
    try:
        # Connect to database
        await db.connect()
        
        # Get all active users
        users = await db.get_all_users(exclude_blocked=True)
        total_users = len(users)
        
        logger.info(f"Starting broadcast to {total_users} users...")
        
        # Statistics
        sent = 0
        failed = 0
        blocked = 0
        
        async with aiohttp.ClientSession() as session:
            for i, user in enumerate(users, 1):
                telegram_id = user['telegram_id']
                first_name = user['first_name'] or 'User'
                
                logger.info(f"[{i}/{total_users}] Sending to {first_name} (ID: {telegram_id})")
                
                success = await send_message(session, config.telegram_token, telegram_id, message_text)
                
                if success:
                    sent += 1
                else:
                    failed += 1
                    # Mark user as blocked
                    await db.mark_user_blocked(telegram_id)
                    blocked += 1
                
                # Sleep to avoid rate limits (30 messages per second)
                await asyncio.sleep(0.05)
        
        # Print statistics
        logger.info("=" * 50)
        logger.info("Broadcast completed!")
        logger.info(f"Total users: {total_users}")
        logger.info(f"✅ Successfully sent: {sent}")
        logger.info(f"❌ Failed: {failed}")
        logger.info(f"🚫 Blocked: {blocked}")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")
    finally:
        await db.disconnect()


async def get_stats():
    """Get user statistics"""
    config = Config()
    db = Database(config.database_url)
    
    try:
        await db.connect()
        stats = await db.get_users_count()
        
        print("=" * 50)
        print("📊 USER STATISTICS")
        print("=" * 50)
        print(f"Total users: {stats['total']}")
        print(f"Active users: {stats['active']}")
        print(f"Blocked users: {stats['blocked']}")
        print("=" * 50)
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
    finally:
        await db.disconnect()


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Broadcast message: python broadcast.py \"Your message here\"")
        print("  Get statistics:    python broadcast.py --stats")
        sys.exit(1)
    
    if sys.argv[1] == '--stats':
        asyncio.run(get_stats())
    else:
        message = ' '.join(sys.argv[1:])
        
        print("=" * 50)
        print("BROADCAST MESSAGE:")
        print(message)
        print("=" * 50)
        
        confirm = input("Are you sure you want to send this message to all users? (yes/no): ")
        if confirm.lower() == 'yes':
            asyncio.run(broadcast_message(message))
        else:
            print("Broadcast cancelled.")


if __name__ == "__main__":
    main()
