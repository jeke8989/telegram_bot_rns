#!/usr/bin/env python3
"""
Main entry point for Neuro-Connector Bot
"""

import asyncio
import logging
from database import Database
from config import Config

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def init_db():
    """Initialize database connection and tables"""
    try:
        logger.info("Initializing Neuro-Connector Bot...")
        
        # Load configuration
        config = Config()
        logger.info(f"Configuration loaded. Environment: {config.app_env}")
        
        # Initialize database
        db = Database(config.database_url)
        await db.connect()
        
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    # Initialize database first
    asyncio.run(init_db())
    
    # Import and run bot main function (after DB is initialized)
    from bot import main as bot_main
    bot_main()
