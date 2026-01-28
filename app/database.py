"""
Database module for Neuro-Connector Bot
"""

import asyncpg
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    """Database handler"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None
    
    async def connect(self):
        """Create connection pool"""
        try:
            self.pool = await asyncpg.create_pool(self.database_url)
            await self.init_tables()
            logger.info("Database connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def disconnect(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database disconnected")
    
    async def init_tables(self):
        """Initialize database tables"""
        async with self.pool.acquire() as conn:
            # Create users table - для всех пользователей бота (для рассылок)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    username VARCHAR(255),
                    is_bot BOOLEAN DEFAULT FALSE,
                    language_code VARCHAR(10),
                    is_blocked BOOLEAN DEFAULT FALSE,
                    last_interaction TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # Create contacts table - для пользователей, прошедших опрос
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    username VARCHAR(255),
                    phone_number VARCHAR(50),
                    email VARCHAR(255),
                    role VARCHAR(50),
                    company VARCHAR(500),
                    position VARCHAR(500),
                    website VARCHAR(500),
                    address TEXT,
                    business_card_data JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # Add new columns if they don't exist (for existing databases)
            await conn.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                  WHERE table_name='contacts' AND column_name='company') THEN
                        ALTER TABLE contacts ADD COLUMN company VARCHAR(500);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                  WHERE table_name='contacts' AND column_name='position') THEN
                        ALTER TABLE contacts ADD COLUMN position VARCHAR(500);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                  WHERE table_name='contacts' AND column_name='website') THEN
                        ALTER TABLE contacts ADD COLUMN website VARCHAR(500);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                  WHERE table_name='contacts' AND column_name='address') THEN
                        ALTER TABLE contacts ADD COLUMN address TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                  WHERE table_name='contacts' AND column_name='business_card_data') THEN
                        ALTER TABLE contacts ADD COLUMN business_card_data JSONB;
                    END IF;
                END $$;
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id SERIAL PRIMARY KEY,
                    contact_id INTEGER UNIQUE NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                    process_pain TEXT NOT NULL,
                    time_lost VARCHAR(255) NOT NULL,
                    department_affected TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS startup_ideas (
                    id SERIAL PRIMARY KEY,
                    contact_id INTEGER UNIQUE NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                    problem_solved TEXT NOT NULL,
                    current_stage VARCHAR(255) NOT NULL,
                    main_barrier TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS specialist_profiles (
                    id SERIAL PRIMARY KEY,
                    contact_id INTEGER UNIQUE NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                    main_skill TEXT NOT NULL,
                    project_interests TEXT NOT NULL,
                    work_format VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS roulette_spins (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL UNIQUE,
                    prize_amount INTEGER NOT NULL,
                    spun_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # Create index for faster lookups
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_roulette_telegram_id 
                ON roulette_spins(telegram_id)
            """)
            
            logger.info("Database tables initialized")
    
    async def save_user(self, telegram_id: int, first_name: str, last_name: str, username: str, language_code: str = None):
        """Save user to database (users table for broadcasts)"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO users (telegram_id, first_name, last_name, username, language_code, last_interaction)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET first_name = $2, last_name = $3, username = $4, language_code = $5, last_interaction = NOW()
                """, telegram_id, first_name, last_name, username, language_code)
                logger.info(f"User {telegram_id} saved to database")
            except Exception as e:
                logger.error(f"Failed to save user: {e}")
    
    async def save_entrepreneur_profile(self, user_id: int, process_pain: str, time_lost: str, 
                                       department_affected: str, phone: str, email: str):
        """Save entrepreneur profile"""
        async with self.pool.acquire() as conn:
            try:
                # Get or create contact
                contact_id = await conn.fetchval(
                    "SELECT id FROM contacts WHERE telegram_id = $1",
                    user_id
                )
                
                if not contact_id:
                    # Create new contact
                    contact_id = await conn.fetchval("""
                        INSERT INTO contacts (telegram_id, role, phone_number, email)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id
                    """, user_id, 'entrepreneur', phone, email)
                else:
                    # Update existing contact
                    await conn.execute(
                        "UPDATE contacts SET role = $1, phone_number = $2, email = $3 WHERE id = $4",
                        'entrepreneur', phone, email, contact_id
                    )
                
                # Insert business profile
                await conn.execute("""
                    INSERT INTO business_profiles (contact_id, process_pain, time_lost, department_affected)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (contact_id) DO UPDATE
                    SET process_pain = $2, time_lost = $3, department_affected = $4
                """, contact_id, process_pain, time_lost, department_affected)
                
                logger.info(f"Entrepreneur profile for user {user_id} saved")
            except Exception as e:
                logger.error(f"Failed to save entrepreneur profile: {e}")
    
    async def save_startup_profile(self, user_id: int, problem_solved: str, current_stage: str, main_barrier: str, phone: str = None):
        """Save startup profile"""
        async with self.pool.acquire() as conn:
            try:
                # Get or create contact
                contact_id = await conn.fetchval(
                    "SELECT id FROM contacts WHERE telegram_id = $1",
                    user_id
                )
                
                if not contact_id:
                    # Create new contact
                    contact_id = await conn.fetchval("""
                        INSERT INTO contacts (telegram_id, role, phone_number)
                        VALUES ($1, $2, $3)
                        RETURNING id
                    """, user_id, 'startupper', phone)
                else:
                    # Update existing contact
                    if phone:
                        await conn.execute(
                            "UPDATE contacts SET role = $1, phone_number = $2 WHERE id = $3",
                            'startupper', phone, contact_id
                        )
                    else:
                        await conn.execute(
                            "UPDATE contacts SET role = $1 WHERE id = $2",
                            'startupper', contact_id
                        )
                
                # Insert startup idea
                await conn.execute("""
                    INSERT INTO startup_ideas (contact_id, problem_solved, current_stage, main_barrier)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (contact_id) DO UPDATE
                    SET problem_solved = $2, current_stage = $3, main_barrier = $4
                """, contact_id, problem_solved, current_stage, main_barrier)
                
                logger.info(f"Startup profile for user {user_id} saved")
            except Exception as e:
                logger.error(f"Failed to save startup profile: {e}")
    
    async def save_specialist_profile(self, user_id: int, main_skill: str, project_interests: str, work_format: str, phone: str = None):
        """Save specialist profile"""
        async with self.pool.acquire() as conn:
            try:
                # Get or create contact
                contact_id = await conn.fetchval(
                    "SELECT id FROM contacts WHERE telegram_id = $1",
                    user_id
                )
                
                if not contact_id:
                    # Create new contact
                    contact_id = await conn.fetchval("""
                        INSERT INTO contacts (telegram_id, role, phone_number)
                        VALUES ($1, $2, $3)
                        RETURNING id
                    """, user_id, 'specialist', phone)
                else:
                    # Update existing contact
                    if phone:
                        await conn.execute(
                            "UPDATE contacts SET role = $1, phone_number = $2 WHERE id = $3",
                            'specialist', phone, contact_id
                        )
                    else:
                        await conn.execute(
                            "UPDATE contacts SET role = $1 WHERE id = $2",
                            'specialist', contact_id
                        )
                
                # Insert specialist profile
                await conn.execute("""
                    INSERT INTO specialist_profiles (contact_id, main_skill, project_interests, work_format)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (contact_id) DO UPDATE
                    SET main_skill = $2, project_interests = $3, work_format = $4
                """, contact_id, main_skill, project_interests, work_format)
                
                logger.info(f"Specialist profile for user {user_id} saved")
            except Exception as e:
                logger.error(f"Failed to save specialist profile: {e}")
    
    async def update_business_card_data(self, user_id: int, card_data: dict):
        """Update business card data for a user"""
        async with self.pool.acquire() as conn:
            try:
                # Update contact with business card data
                await conn.execute("""
                    UPDATE contacts 
                    SET company = $2,
                        position = $3,
                        website = $4,
                        address = $5,
                        business_card_data = $6,
                        phone_number = COALESCE(phone_number, $7),
                        email = COALESCE(email, $8)
                    WHERE telegram_id = $1
                """, 
                    user_id,
                    card_data.get('company'),
                    card_data.get('position'),
                    card_data.get('website'),
                    card_data.get('address'),
                    card_data,  # Store full JSON
                    card_data.get('phone'),
                    card_data.get('email')
                )
                
                logger.info(f"Business card data for user {user_id} updated")
            except Exception as e:
                logger.error(f"Failed to update business card data: {e}")
    
    async def can_spin_roulette(self, telegram_id: int) -> bool:
        """Check if user can spin the roulette (hasn't spun before)"""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.fetchval(
                    "SELECT COUNT(*) FROM roulette_spins WHERE telegram_id = $1",
                    telegram_id
                )
                return result == 0
            except Exception as e:
                logger.error(f"Failed to check roulette spin status: {e}")
                return False
    
    async def save_roulette_spin(self, telegram_id: int, prize_amount: int):
        """Save roulette spin result"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO roulette_spins (telegram_id, prize_amount)
                    VALUES ($1, $2)
                    ON CONFLICT (telegram_id) DO NOTHING
                """, telegram_id, prize_amount)
                logger.info(f"Roulette spin saved for user {telegram_id}: {prize_amount} RUB")
            except Exception as e:
                logger.error(f"Failed to save roulette spin: {e}")
    
    async def get_user_prize(self, telegram_id: int) -> int:
        """Get user's prize amount (if they have spun)"""
        async with self.pool.acquire() as conn:
            try:
                prize = await conn.fetchval(
                    "SELECT prize_amount FROM roulette_spins WHERE telegram_id = $1",
                    telegram_id
                )
                return prize if prize else 0
            except Exception as e:
                logger.error(f"Failed to get user prize: {e}")
                return 0
    
    # === Methods for user management (broadcasts) ===
    
    async def get_all_users(self, exclude_blocked: bool = True):
        """Get all users for broadcast"""
        async with self.pool.acquire() as conn:
            try:
                if exclude_blocked:
                    query = "SELECT telegram_id, first_name, username FROM users WHERE is_blocked = FALSE ORDER BY created_at DESC"
                else:
                    query = "SELECT telegram_id, first_name, username FROM users ORDER BY created_at DESC"
                
                rows = await conn.fetch(query)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get all users: {e}")
                return []
    
    async def get_users_count(self) -> dict:
        """Get statistics about users"""
        async with self.pool.acquire() as conn:
            try:
                total = await conn.fetchval("SELECT COUNT(*) FROM users")
                active = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE")
                blocked = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
                
                return {
                    'total': total,
                    'active': active,
                    'blocked': blocked
                }
            except Exception as e:
                logger.error(f"Failed to get users count: {e}")
                return {'total': 0, 'active': 0, 'blocked': 0}
    
    async def mark_user_blocked(self, telegram_id: int):
        """Mark user as blocked (can't receive messages)"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE users SET is_blocked = TRUE WHERE telegram_id = $1",
                    telegram_id
                )
                logger.info(f"User {telegram_id} marked as blocked")
            except Exception as e:
                logger.error(f"Failed to mark user as blocked: {e}")
    
    async def mark_user_active(self, telegram_id: int):
        """Mark user as active (unblocked)"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE users SET is_blocked = FALSE WHERE telegram_id = $1",
                    telegram_id
                )
                logger.info(f"User {telegram_id} marked as active")
            except Exception as e:
                logger.error(f"Failed to mark user as active: {e}")
    
    async def get_user_full_info(self, telegram_id: int) -> dict:
        """Get full user information from contacts table including profile data"""
        async with self.pool.acquire() as conn:
            try:
                # Get basic contact info
                row = await conn.fetchrow("""
                    SELECT 
                        c.telegram_id,
                        c.first_name,
                        c.last_name,
                        c.username,
                        c.phone_number,
                        c.email,
                        c.role,
                        c.company,
                        c.position,
                        c.website,
                        c.address,
                        c.business_card_data,
                        c.id as contact_id
                    FROM contacts c
                    WHERE c.telegram_id = $1
                """, telegram_id)
                
                if not row:
                    return None
                
                user_info = dict(row)
                
                # Get role-specific profile data based on user's role
                if user_info['role'] == 'entrepreneur':
                    profile = await conn.fetchrow("""
                        SELECT process_pain, time_lost, department_affected
                        FROM business_profiles
                        WHERE contact_id = $1
                    """, user_info['contact_id'])
                    if profile:
                        user_info['profile_data'] = dict(profile)
                
                elif user_info['role'] == 'startupper':
                    profile = await conn.fetchrow("""
                        SELECT problem_solved, current_stage, main_barrier
                        FROM startup_ideas
                        WHERE contact_id = $1
                    """, user_info['contact_id'])
                    if profile:
                        user_info['profile_data'] = dict(profile)
                
                elif user_info['role'] == 'specialist':
                    profile = await conn.fetchrow("""
                        SELECT main_skill, project_interests, work_format
                        FROM specialist_profiles
                        WHERE contact_id = $1
                    """, user_info['contact_id'])
                    if profile:
                        user_info['profile_data'] = dict(profile)
                
                return user_info
                
            except Exception as e:
                logger.error(f"Failed to get user full info: {e}")
                return None
