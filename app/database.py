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
            
            # Zoom meetings table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS zoom_meetings (
                    id SERIAL PRIMARY KEY,
                    meeting_id BIGINT UNIQUE NOT NULL,
                    topic VARCHAR(500),
                    duration INTEGER,
                    join_url TEXT,
                    start_url TEXT,
                    host_telegram_id BIGINT,
                    host_name VARCHAR(255),
                    start_time TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(50) DEFAULT 'scheduled',
                    recording_url TEXT,
                    transcript_text TEXT,
                    summary TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # Add role column to users table if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='users' AND column_name='role') THEN
                        ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'user';
                    END IF;
                END $$;
            """)

            # Add staff_specialty and staff_grade columns to users if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='users' AND column_name='staff_specialty') THEN
                        ALTER TABLE users ADD COLUMN staff_specialty VARCHAR(50);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='users' AND column_name='staff_grade') THEN
                        ALTER TABLE users ADD COLUMN staff_grade VARCHAR(60);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='users' AND column_name='kimai_user_id') THEN
                        ALTER TABLE users ADD COLUMN kimai_user_id INTEGER;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='users' AND column_name='staff_email') THEN
                        ALTER TABLE users ADD COLUMN staff_email VARCHAR(255);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='users' AND column_name='staff_display_name') THEN
                        ALTER TABLE users ADD COLUMN staff_display_name VARCHAR(255);
                    END IF;
                END $$;
            """)

            # Add lark_message_id column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='lark_message_id') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN lark_message_id VARCHAR(255);
                    END IF;
                END $$;
            """)

            # Meeting participants table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS meeting_participants (
                    id SERIAL PRIMARY KEY,
                    meeting_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    status VARCHAR(50) DEFAULT 'invited',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(meeting_id, telegram_id)
                )
            """)

            # Staff invite links table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS staff_invite_links (
                    id SERIAL PRIMARY KEY,
                    token VARCHAR(64) UNIQUE NOT NULL,
                    created_by BIGINT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            await conn.execute("""
                ALTER TABLE staff_invite_links
                ADD COLUMN IF NOT EXISTS target_role VARCHAR(50) DEFAULT 'staff'
            """)

            # Add public_token column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='public_token') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN public_token VARCHAR(32) UNIQUE;
                    END IF;
                END $$;
            """)

            # Backfill public_token for existing meetings that don't have one
            rows_without_token = await conn.fetch(
                "SELECT id FROM zoom_meetings WHERE public_token IS NULL"
            )
            if rows_without_token:
                import uuid
                for row in rows_without_token:
                    token = uuid.uuid4().hex[:16]
                    await conn.execute(
                        "UPDATE zoom_meetings SET public_token = $1 WHERE id = $2",
                        token, row['id'],
                    )
                logger.info(f"Backfilled public_token for {len(rows_without_token)} meetings")

            # Add video_s3_url column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='video_s3_url') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN video_s3_url TEXT;
                    END IF;
                END $$;
            """)

            # Add audio_s3_url column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='audio_s3_url') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN audio_s3_url TEXT;
                    END IF;
                END $$;
            """)

            # Add mindmap_json column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='mindmap_json') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN mindmap_json TEXT;
                    END IF;
                END $$;
            """)

            # Add structured_transcript column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='structured_transcript') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN structured_transcript TEXT;
                    END IF;
                END $$;
            """)

            # Staff notes table (admin notes about staff members)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS staff_notes (
                    id SERIAL PRIMARY KEY,
                    staff_telegram_id BIGINT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    updated_by BIGINT NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(staff_telegram_id)
                )
            """)

            # Brainstorm threads and messages
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS brainstorm_threads (
                    id SERIAL PRIMARY KEY,
                    meeting_token VARCHAR(64) NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    title VARCHAR(200) NOT NULL DEFAULT 'Новая тема',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS brainstorm_messages (
                    id SERIAL PRIMARY KEY,
                    thread_id INTEGER NOT NULL REFERENCES brainstorm_threads(id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bs_threads_meeting
                ON brainstorm_threads(meeting_token, telegram_id)
            """)

            # pgvector extension for embedding similarity search
            has_pgvector = False
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                has_pgvector = True
            except Exception as e:
                logger.warning(f"pgvector extension not available, RAG features disabled: {e}")

            # Projects table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(500) NOT NULL,
                    description TEXT,
                    public_token VARCHAR(32) UNIQUE NOT NULL,
                    created_by BIGINT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            # Migrate: add is_staff_visible column if missing
            await conn.execute("""
                ALTER TABLE projects
                ADD COLUMN IF NOT EXISTS is_staff_visible BOOLEAN NOT NULL DEFAULT TRUE
            """)
            # Migrate: add project_type column if missing
            await conn.execute("""
                ALTER TABLE projects
                ADD COLUMN IF NOT EXISTS project_type VARCHAR(60) NOT NULL DEFAULT 'other'
            """)

            # Project categories (dynamic, user-managed)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS project_categories (
                    id SERIAL PRIMARY KEY,
                    slug VARCHAR(60) UNIQUE NOT NULL,
                    label VARCHAR(120) NOT NULL,
                    color VARCHAR(20) NOT NULL DEFAULT '#8b8fa8',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            # Migrate: add staff_visible to categories
            await conn.execute("""
                ALTER TABLE project_categories
                ADD COLUMN IF NOT EXISTS staff_visible BOOLEAN NOT NULL DEFAULT TRUE
            """)
            # Seed default categories if table is empty
            await conn.execute("""
                INSERT INTO project_categories (slug, label, color, position)
                VALUES
                    ('client',   'Клиентские', '#6c5ce7', 0),
                    ('internal', 'Внутренние', '#00cec9', 1),
                    ('training', 'Обучение',   '#fdcb6e', 2),
                    ('other',    'Другие',     '#8b8fa8', 3)
                ON CONFLICT (slug) DO NOTHING
            """)

            # Many-to-many: projects <-> zoom_meetings
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS project_meetings (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    zoom_meeting_db_id INTEGER NOT NULL REFERENCES zoom_meetings(id) ON DELETE CASCADE,
                    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(project_id, zoom_meeting_db_id)
                )
            """)

            # Meeting tasks / action items
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS meeting_tasks (
                    id SERIAL PRIMARY KEY,
                    meeting_id BIGINT NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    sent_to_lark BOOLEAN DEFAULT FALSE,
                    lark_message_id VARCHAR(255),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

            # Migrate: add priority/category columns to meeting_tasks
            await conn.execute("""
                ALTER TABLE meeting_tasks
                ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'medium'
            """)
            await conn.execute("""
                ALTER TABLE meeting_tasks
                ADD COLUMN IF NOT EXISTS category VARCHAR(30) DEFAULT 'task'
            """)

            # Embeddings for project-level RAG chat (requires pgvector)
            if has_pgvector:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS project_embeddings (
                        id SERIAL PRIMARY KEY,
                        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        zoom_meeting_db_id INTEGER NOT NULL REFERENCES zoom_meetings(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        chunk_text TEXT NOT NULL,
                        embedding vector(1536) NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)

                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_project_embeddings_project
                    ON project_embeddings(project_id)
                """)

            # Web sessions for web app authentication
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS web_sessions (
                    id SERIAL PRIMARY KEY,
                    token VARCHAR(64) UNIQUE NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    first_name VARCHAR(255),
                    username VARCHAR(255),
                    role VARCHAR(50) NOT NULL,
                    note TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)

            # Add is_public column to zoom_meetings if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_name='zoom_meetings' AND column_name='is_public') THEN
                        ALTER TABLE zoom_meetings ADD COLUMN is_public BOOLEAN DEFAULT FALSE;
                    END IF;
                END $$;
            """)

            # Migrate: add kimai_project_id to projects
            await conn.execute("""
                ALTER TABLE projects
                ADD COLUMN IF NOT EXISTS kimai_project_id INTEGER
            """)

            # Project expenses (custom costs added by admin)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS project_expenses (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title VARCHAR(300) NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    category VARCHAR(100),
                    expense_date DATE NOT NULL,
                    created_by BIGINT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

            # Project income (payments received)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS project_income (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title VARCHAR(300) NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    income_date DATE NOT NULL,
                    created_by BIGINT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

            # Commercial proposals table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS commercial_proposals (
                    id SERIAL PRIMARY KEY,
                    token VARCHAR(32) UNIQUE NOT NULL,
                    project_name TEXT,
                    client_name TEXT,
                    proposal_type VARCHAR(10),
                    design_type VARCHAR(20),
                    currency VARCHAR(5) DEFAULT '$',
                    hourly_rate NUMERIC,
                    estimation JSONB NOT NULL,
                    config_data JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            await conn.execute("ALTER TABLE commercial_proposals ADD COLUMN IF NOT EXISTS client_id INTEGER")
            await conn.execute("""
                ALTER TABLE commercial_proposals
                ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL
            """)
            await conn.execute("""
                ALTER TABLE commercial_proposals
                ADD COLUMN IF NOT EXISTS proposal_status VARCHAR(50) DEFAULT 'draft'
            """)
            await conn.execute("""
                ALTER TABLE commercial_proposals
                ADD COLUMN IF NOT EXISTS created_by_telegram_id BIGINT
            """)
            await conn.execute("""
                ALTER TABLE commercial_proposals
                ADD COLUMN IF NOT EXISTS discount_percent INTEGER DEFAULT 0
            """)

            # Add client_id to projects (FK re-pointed to users after migration)
            await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS client_id INTEGER")

            # Client messages table (two-way chat, client_id references users)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS client_messages (
                    id SERIAL PRIMARY KEY,
                    client_id INTEGER NOT NULL,
                    direction VARCHAR(3) NOT NULL,
                    sender_name VARCHAR(255),
                    message TEXT NOT NULL,
                    telegram_message_id BIGINT,
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_client_messages_client
                ON client_messages(client_id, created_at DESC)
            """)

            # ── Migration: merge clients into users table ──
            await self._migrate_clients_to_users(conn)

            logger.info("Database tables initialized")
    
    async def _migrate_clients_to_users(self, conn):
        """One-time migration: merge clients table data into users, then drop clients."""
        # Step 1: Add client-profile columns to users (idempotent)
        for stmt in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS uuid UUID DEFAULT gen_random_uuid() UNIQUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS company VARCHAR(500)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS website VARCHAR(500)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS client_notes TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS client_status VARCHAR(50)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS cabinet_token VARCHAR(32) UNIQUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_enabled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_started_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_discount_percent INTEGER DEFAULT 10",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        ]:
            await conn.execute(stmt)

        # Backfill uuid for existing users that got NULL
        await conn.execute("UPDATE users SET uuid = gen_random_uuid() WHERE uuid IS NULL")

        # Make telegram_id nullable (for clients without Telegram)
        await conn.execute("""
            ALTER TABLE users ALTER COLUMN telegram_id DROP NOT NULL
        """)

        # Step 2: Check if clients table exists and has rows
        has_clients = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'clients'
            )
        """)
        if not has_clients:
            return

        client_count = await conn.fetchval("SELECT COUNT(*) FROM clients")
        if client_count == 0:
            logger.info("clients table is empty, skipping data migration")
            await self._drop_clients_table(conn)
            return

        logger.info(f"Migrating {client_count} clients into users table...")

        # Step 3: Migrate data
        clients = await conn.fetch("SELECT * FROM clients")
        id_map = {}  # old clients.id -> new users.id

        for c in clients:
            old_id = c['id']
            tg_id = c.get('telegram_id')

            if tg_id:
                existing = await conn.fetchrow(
                    "SELECT id FROM users WHERE telegram_id = $1", tg_id
                )
                if existing:
                    await conn.execute("""
                        UPDATE users SET
                            company = COALESCE($2, company),
                            email = COALESCE($3, email),
                            phone = COALESCE($4, phone),
                            position = COALESCE($5, position),
                            website = COALESCE($6, website),
                            address = COALESCE($7, address),
                            client_notes = COALESCE($8, client_notes),
                            client_status = COALESCE($9, client_status),
                            cabinet_token = COALESCE($10, cabinet_token),
                            promo_enabled = $11,
                            promo_started_at = COALESCE($12, promo_started_at),
                            promo_discount_percent = COALESCE($13, promo_discount_percent),
                            updated_at = NOW()
                        WHERE telegram_id = $1
                    """,
                        tg_id,
                        c.get('company'), c.get('email'), c.get('phone'),
                        c.get('position'), c.get('website'), c.get('address'),
                        c.get('notes'), c.get('status'),
                        c.get('cabinet_token'),
                        c.get('promo_enabled', False),
                        c.get('promo_started_at'),
                        c.get('promo_discount_percent', 10),
                    )
                    id_map[old_id] = existing['id']
                    continue

            # Create new user from client data (idempotent — skip if already migrated)
            import secrets as _secrets
            name = c.get('name', '') or ''
            parts = name.split(' ', 1)
            first = parts[0] if parts else ''
            last = parts[1] if len(parts) > 1 else ''
            tg_username = (c.get('telegram') or '').lstrip('@') or None

            # Skip if a row with this username already exists as a client
            if tg_username:
                already = await conn.fetchrow(
                    "SELECT id FROM users WHERE username = $1 AND client_status IS NOT NULL",
                    tg_username,
                )
                if already:
                    id_map[old_id] = already['id']
                    continue

            # If the cabinet_token already exists in users, generate a fresh one
            cab_token = c.get('cabinet_token')
            if cab_token:
                conflict = await conn.fetchval(
                    "SELECT id FROM users WHERE cabinet_token = $1", cab_token
                )
                if conflict:
                    cab_token = _secrets.token_hex(16)

            new_row = await conn.fetchrow("""
                INSERT INTO users (
                    telegram_id, first_name, last_name, username, role,
                    company, email, phone, position, website, address,
                    client_notes, client_status, cabinet_token,
                    promo_enabled, promo_started_at, promo_discount_percent,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, 'user',
                    $5, $6, $7, $8, $9, $10,
                    $11, $12, $13,
                    $14, $15, $16,
                    COALESCE($17, NOW()), NOW()
                ) RETURNING id
            """,
                tg_id, first, last, tg_username,
                c.get('company'), c.get('email'), c.get('phone'),
                c.get('position'), c.get('website'), c.get('address'),
                c.get('notes'), c.get('status'), cab_token,
                c.get('promo_enabled', False), c.get('promo_started_at'),
                c.get('promo_discount_percent', 10),
                c.get('created_at'),
            )
            id_map[old_id] = new_row['id']

        # Step 4: Drop old FK constraints BEFORE re-pointing data
        for table, col in [
            ('projects', 'client_id'),
            ('commercial_proposals', 'client_id'),
            ('client_messages', 'client_id'),
        ]:
            constraints = await conn.fetch("""
                SELECT conname FROM pg_constraint
                WHERE conrelid = $1::regclass AND contype = 'f'
                AND array_to_string(conkey, ',') = (
                    SELECT attnum::text FROM pg_attribute
                    WHERE attrelid = $1::regclass AND attname = $2
                )
            """, table, col)
            for fk in constraints:
                await conn.execute(
                    f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {fk['conname']}"
                )

        # Step 5: Re-point data references
        for old_cid, new_uid in id_map.items():
            await conn.execute(
                "UPDATE projects SET client_id = $2 WHERE client_id = $1",
                old_cid, new_uid,
            )
            await conn.execute(
                "UPDATE commercial_proposals SET client_id = $2 WHERE client_id = $1",
                old_cid, new_uid,
            )
            await conn.execute(
                "UPDATE client_messages SET client_id = $2 WHERE client_id = $1",
                old_cid, new_uid,
            )

        logger.info(f"Migrated {len(id_map)} clients -> users. Dropping clients table.")
        await self._drop_clients_table(conn)

    async def _drop_clients_table(self, conn):
        """Drop clients table and re-point FK constraints to users."""
        # Drop old FK constraints that reference clients
        for table, col in [
            ('projects', 'client_id'),
            ('commercial_proposals', 'client_id'),
            ('client_messages', 'client_id'),
        ]:
            constraints = await conn.fetch("""
                SELECT conname FROM pg_constraint
                WHERE conrelid = $1::regclass AND contype = 'f'
                AND array_to_string(conkey, ',') = (
                    SELECT attnum::text FROM pg_attribute
                    WHERE attrelid = $1::regclass AND attname = $2
                )
            """, table, col)
            for c in constraints:
                await conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {c['conname']}")

        # Add new FK constraints pointing to users
        for table in ('projects', 'commercial_proposals', 'client_messages'):
            await conn.execute(f"""
                DO $$ BEGIN
                    ALTER TABLE {table}
                    ADD CONSTRAINT {table}_client_id_users_fk
                    FOREIGN KEY (client_id) REFERENCES users(id) ON DELETE SET NULL;
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$
            """)

        await conn.execute("DROP TABLE IF EXISTS clients CASCADE")
        logger.info("clients table dropped, FK constraints re-pointed to users")

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

    # ---- Users management (admin panel) ----

    async def get_all_users_admin(self) -> list[dict]:
        """Return all real bot users (telegram_id IS NOT NULL) for admin panel."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT telegram_id, first_name, last_name, username,
                           role, is_blocked, created_at, last_interaction,
                           client_status, company, uuid
                    FROM users
                    WHERE telegram_id IS NOT NULL
                    ORDER BY last_interaction DESC NULLS LAST
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get all users admin: {e}")
                return []

    # ---- Staff / Zoom helpers ----

    async def update_user_role(self, telegram_id: int, role: str):
        """Update user role (e.g. 'staff')"""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE users SET role = $2 WHERE telegram_id = $1",
                    telegram_id, role,
                )
                logger.info(f"User {telegram_id} role updated to '{role}'")
            except Exception as e:
                logger.error(f"Failed to update user role: {e}")

    async def get_user_role(self, telegram_id: int) -> str:
        async with self.pool.acquire() as conn:
            try:
                role = await conn.fetchval(
                    "SELECT role FROM users WHERE telegram_id = $1",
                    telegram_id,
                )
                return role or "user"
            except Exception as e:
                logger.error(f"Failed to get user role: {e}")
                return "user"

    async def save_zoom_meeting(
        self,
        meeting_id: int,
        topic: str,
        duration: int,
        join_url: str,
        start_url: str,
        host_telegram_id: int,
        host_name: str,
        start_time=None,
    ):
        import uuid
        public_token = uuid.uuid4().hex[:16]
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO zoom_meetings
                        (meeting_id, topic, duration, join_url, start_url,
                         host_telegram_id, host_name, start_time, public_token)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (meeting_id) DO NOTHING
                """, meeting_id, topic, duration, join_url, start_url,
                     host_telegram_id, host_name, start_time, public_token)
                logger.info(f"Zoom meeting {meeting_id} saved to database (token={public_token})")
            except Exception as e:
                logger.error(f"Failed to save zoom meeting: {e}")

    async def create_manual_meeting(
        self,
        topic: str,
        host_telegram_id: int,
        host_name: str,
    ) -> dict | None:
        """Create a meeting record for a manually uploaded video (not from Zoom)."""
        import uuid
        manual_id = -abs(hash(uuid.uuid4())) % (2**31)
        public_token = uuid.uuid4().hex[:32]
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    INSERT INTO zoom_meetings
                        (meeting_id, topic, duration, join_url, start_url,
                         host_telegram_id, host_name, status, public_token)
                    VALUES ($1, $2, 0, '', '', $3, $4, 'uploading', $5)
                    RETURNING id, meeting_id, public_token
                """, manual_id, topic, host_telegram_id, host_name, public_token)
                logger.info(f"Manual meeting created: id={row['id']}, meeting_id={manual_id}")
                return dict(row)
            except Exception as e:
                logger.error(f"Failed to create manual meeting: {e}")
                return None

    async def get_zoom_meeting(self, meeting_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM zoom_meetings WHERE meeting_id = $1",
                    meeting_id,
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get zoom meeting: {e}")
                return None

    async def get_zoom_meeting_by_db_id(self, db_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM zoom_meetings WHERE id = $1",
                    db_id,
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get zoom meeting by db_id: {e}")
                return None

    async def get_meeting_by_zoom_id(self, zoom_meeting_id: int) -> dict | None:
        """Get meeting DB record by Zoom meeting ID."""
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM zoom_meetings WHERE meeting_id = $1",
                    int(zoom_meeting_id),
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get meeting by zoom_id: {e}")
                return None

    async def delete_zoom_meeting(self, db_id: int):
        """Fully delete a meeting: embeddings, project links, then the meeting itself."""
        async with self.pool.acquire() as conn:
            try:
                try:
                    if await self._has_embeddings_table(conn):
                        await conn.execute(
                            "DELETE FROM project_embeddings WHERE zoom_meeting_db_id = $1",
                            db_id,
                        )
                except Exception as emb_err:
                    logger.warning(f"Skipping embeddings delete (table may not exist): {emb_err}")
                await conn.execute(
                    "DELETE FROM project_meetings WHERE zoom_meeting_db_id = $1",
                    db_id,
                )
                await conn.execute(
                    "DELETE FROM meeting_participants WHERE meeting_id = "
                    "(SELECT meeting_id FROM zoom_meetings WHERE id = $1)",
                    db_id,
                )
                await conn.execute(
                    "DELETE FROM zoom_meetings WHERE id = $1",
                    db_id,
                )
                logger.info(f"Zoom meeting db_id={db_id} fully deleted from DB")
            except Exception as e:
                logger.error(f"Failed to delete zoom meeting db_id={db_id}: {e}")
                raise

    async def update_meeting_recording(
        self,
        meeting_id: int,
        recording_url: str | None,
        transcript_text: str | None,
        summary: str | None,
        status: str = "recorded",
        topic: str | None = None,
        duration: int | None = None,
        start_time: str | None = None,
    ):
        async with self.pool.acquire() as conn:
            try:
                # Upsert: create record if not exists, update if exists
                await conn.execute("""
                    INSERT INTO zoom_meetings
                        (meeting_id, recording_url, transcript_text, summary, status, topic, duration, start_time)
                    VALUES ($1, $2, $3, $4, $5, $6, $7,
                        CASE WHEN $8::text IS NOT NULL
                             THEN $8::timestamptz ELSE NULL END)
                    ON CONFLICT (meeting_id) DO UPDATE
                        SET recording_url   = EXCLUDED.recording_url,
                            transcript_text = EXCLUDED.transcript_text,
                            summary         = EXCLUDED.summary,
                            status          = EXCLUDED.status,
                            topic           = COALESCE(EXCLUDED.topic, zoom_meetings.topic),
                            duration        = COALESCE(EXCLUDED.duration, zoom_meetings.duration),
                            start_time      = COALESCE(EXCLUDED.start_time, zoom_meetings.start_time)
                """, meeting_id, recording_url, transcript_text, summary, status,
                     topic, duration, start_time)
                logger.info(f"Zoom meeting {meeting_id} recording upserted")
            except Exception as e:
                logger.error(f"Failed to upsert meeting recording: {e}")

    async def update_meeting_public_token(self, meeting_id: int, public_token: str):
        async with self.pool.acquire() as conn:
            try:
                # Upsert: create minimal record if not exists, just update public_token if exists
                await conn.execute("""
                    INSERT INTO zoom_meetings (meeting_id, public_token)
                    VALUES ($1, $2)
                    ON CONFLICT (meeting_id) DO UPDATE
                        SET public_token = EXCLUDED.public_token
                """, meeting_id, public_token)
                logger.info(f"Zoom meeting {meeting_id} public_token saved")
            except Exception as e:
                logger.error(f"Failed to update meeting public_token: {e}")

    async def update_meeting_transcript_and_summary(
        self,
        meeting_id: int,
        transcript_text: str | None,
        summary: str | None,
    ):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE zoom_meetings
                    SET transcript_text = $2, summary = $3
                    WHERE meeting_id = $1
                """, meeting_id, transcript_text, summary)
                logger.info(f"Zoom meeting {meeting_id} transcript/summary updated")
            except Exception as e:
                logger.error(f"Failed to update meeting transcript/summary: {e}")

    async def update_meeting_structured_transcript(
        self,
        meeting_id: int,
        structured_transcript: str | None,
    ):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE zoom_meetings
                    SET structured_transcript = $2
                    WHERE meeting_id = $1
                """, meeting_id, structured_transcript)
                logger.info(f"Zoom meeting {meeting_id} structured_transcript updated")
            except Exception as e:
                logger.error(f"Failed to update structured_transcript: {e}")

    async def get_meeting_by_public_token(self, public_token: str) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM zoom_meetings WHERE public_token = $1",
                    public_token,
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get meeting by public_token: {e}")
                return None

    async def get_host_upcoming_meetings(self, host_telegram_id: int) -> list[dict]:
        """Return scheduled (not yet ended) meetings created by this host, newest first."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT id, meeting_id, topic, duration, join_url, start_url, "
                    "start_time, status, lark_message_id "
                    "FROM zoom_meetings "
                    "WHERE host_telegram_id = $1 "
                    "AND status = 'scheduled' "
                    "ORDER BY COALESCE(start_time, created_at) ASC "
                    "LIMIT 10",
                    host_telegram_id,
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get host upcoming meetings: {e}")
                return []

    async def update_meeting_status(self, meeting_id: int, status: str):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET status = $2 WHERE meeting_id = $1",
                    meeting_id, status,
                )
                logger.info(f"Zoom meeting {meeting_id} status updated to: {status}")
            except Exception as e:
                logger.error(f"Failed to update meeting status: {e}")

    async def update_meeting_lark_message_id(self, meeting_id: int, lark_message_id: str):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET lark_message_id = $2 WHERE meeting_id = $1",
                    meeting_id, lark_message_id,
                )
                logger.info(f"Zoom meeting {meeting_id} lark_message_id saved: {lark_message_id}")
            except Exception as e:
                logger.error(f"Failed to update lark_message_id: {e}")

    async def update_meeting_video_url(self, meeting_id: int, video_s3_url: str):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET video_s3_url = $2 WHERE meeting_id = $1",
                    meeting_id, video_s3_url,
                )
                logger.info(f"Zoom meeting {meeting_id} video_s3_url saved: {video_s3_url}")
            except Exception as e:
                logger.error(f"Failed to update video_s3_url: {e}")

    async def update_meeting_audio_url(self, meeting_id: int, audio_s3_url: str):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET audio_s3_url = $2 WHERE meeting_id = $1",
                    meeting_id, audio_s3_url,
                )
                logger.info(f"Zoom meeting {meeting_id} audio_s3_url saved: {audio_s3_url}")
            except Exception as e:
                logger.error(f"Failed to update audio_s3_url: {e}")

    async def update_meeting_mindmap(self, meeting_id: int, mindmap_json: str):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET mindmap_json = $2 WHERE meeting_id = $1",
                    meeting_id, mindmap_json,
                )
                logger.info(f"Zoom meeting {meeting_id} mindmap_json saved ({len(mindmap_json)} chars)")
            except Exception as e:
                logger.error(f"Failed to update mindmap_json: {e}")

    async def update_meeting_topic(self, meeting_id: int, topic: str):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET topic = $2 WHERE meeting_id = $1",
                    meeting_id, topic,
                )
                logger.info(f"Zoom meeting {meeting_id} topic updated: {topic}")
            except Exception as e:
                logger.error(f"Failed to update meeting topic: {e}")
                raise

    async def update_meeting_duration(self, meeting_id: int, duration: int):
        """Update the actual duration of a meeting (in minutes)."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE zoom_meetings SET duration = $2 WHERE meeting_id = $1",
                    meeting_id, duration,
                )
                logger.info(f"Zoom meeting {meeting_id} duration updated to {duration} min")
            except Exception as e:
                logger.error(f"Failed to update meeting duration: {e}")

    async def update_meeting_schedule(self, meeting_id: int, start_time, duration: int):
        """Update scheduled start time and duration for a meeting."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    UPDATE zoom_meetings
                    SET start_time = $2,
                        duration = $3,
                        status = 'scheduled'
                    WHERE meeting_id = $1
                    """,
                    meeting_id,
                    start_time,
                    duration,
                )
                logger.info(
                    f"Zoom meeting {meeting_id} schedule updated: start_time={start_time}, duration={duration}"
                )
            except Exception as e:
                logger.error(f"Failed to update meeting schedule: {e}")
                raise

    async def get_staff_users(self, exclude_telegram_id: int) -> list:
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT telegram_id, first_name, last_name, username "
                    "FROM users WHERE role IN ('staff', 'admin') AND telegram_id != $1 "
                    "ORDER BY first_name",
                    exclude_telegram_id,
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get staff users: {e}")
                return []

    async def save_meeting_participants(self, meeting_id: int, telegram_ids: list):
        if not telegram_ids:
            return
        async with self.pool.acquire() as conn:
            try:
                await conn.executemany(
                    "INSERT INTO meeting_participants (meeting_id, telegram_id) "
                    "VALUES ($1, $2) ON CONFLICT (meeting_id, telegram_id) DO NOTHING",
                    [(meeting_id, tid) for tid in telegram_ids],
                )
                logger.info(f"Saved {len(telegram_ids)} participants for meeting {meeting_id}")
            except Exception as e:
                logger.error(f"Failed to save meeting participants: {e}")

    async def get_participant_upcoming_meetings(self, telegram_id: int) -> list[dict]:
        """Return scheduled meetings where this user is a participant (not host)."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT zm.id, zm.meeting_id, zm.topic, zm.duration, zm.join_url, "
                    "zm.start_time, zm.status, zm.host_name "
                    "FROM zoom_meetings zm "
                    "JOIN meeting_participants mp ON mp.meeting_id = zm.meeting_id "
                    "WHERE mp.telegram_id = $1 "
                    "AND zm.host_telegram_id != $1 "
                    "AND zm.status = 'scheduled' "
                    "ORDER BY COALESCE(zm.start_time, zm.created_at) ASC "
                    "LIMIT 10",
                    telegram_id,
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get participant upcoming meetings: {e}")
                return []

    async def get_meeting_participants(self, meeting_id: int) -> list:
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT mp.telegram_id, u.first_name, u.last_name, u.username "
                    "FROM meeting_participants mp "
                    "LEFT JOIN users u ON mp.telegram_id = u.telegram_id "
                    "WHERE mp.meeting_id = $1",
                    meeting_id,
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get meeting participants: {e}")
                return []

    async def get_upcoming_meetings(self) -> list:
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT zm.meeting_id, zm.topic, zm.duration, zm.join_url, "
                    "zm.start_url, zm.start_time, zm.host_name, zm.host_telegram_id "
                    "FROM zoom_meetings zm "
                    "WHERE zm.status = 'scheduled' AND zm.start_time > NOW() "
                    "ORDER BY zm.start_time",
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get upcoming meetings: {e}")
                return []

    async def get_overdue_scheduled_meetings(self) -> list[dict]:
        """Return 'scheduled' meetings whose expected end time has already passed (missed ended event)."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT id, meeting_id, topic, duration, join_url, "
                    "start_time, host_name, host_telegram_id, lark_message_id, "
                    "recording_url, transcript_text, summary, public_token, "
                    "video_s3_url, audio_s3_url, status "
                    "FROM zoom_meetings "
                    "WHERE status = 'scheduled' "
                    "AND start_time IS NOT NULL "
                    "AND start_time + (COALESCE(duration, 30) * INTERVAL '1 minute') < NOW() - INTERVAL '10 minutes' "
                    "AND created_at > NOW() - INTERVAL '7 days' "
                    "ORDER BY created_at DESC "
                    "LIMIT 20",
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get overdue scheduled meetings: {e}")
                return []

    async def get_scheduled_meetings(self) -> list[dict]:
        """Return all meetings still in 'scheduled' status (may have ended while server was down)."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT id, meeting_id, topic, duration, join_url, "
                    "start_time, host_name, host_telegram_id, lark_message_id, "
                    "recording_url, transcript_text, summary, public_token, "
                    "video_s3_url, audio_s3_url "
                    "FROM zoom_meetings "
                    "WHERE status = 'scheduled' "
                    "ORDER BY created_at",
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get scheduled meetings: {e}")
                return []

    async def get_meetings_needing_transcript(self) -> list[dict]:
        """Return meetings with recordings but missing transcript/summary, Lark card, S3 video, or S3 audio."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT id, meeting_id, topic, duration, join_url, "
                    "start_time, host_name, host_telegram_id, lark_message_id, "
                    "recording_url, transcript_text, summary, public_token, "
                    "video_s3_url, audio_s3_url "
                    "FROM zoom_meetings "
                    "WHERE status = 'recorded' "
                    "AND recording_url IS NOT NULL "
                    "AND ("
                    "  transcript_text IS NULL OR transcript_text = '' "
                    "  OR summary IS NULL OR summary = '' "
                    "  OR lark_message_id IS NULL OR lark_message_id = ''"
                    "  OR video_s3_url IS NULL OR video_s3_url = ''"
                    "  OR audio_s3_url IS NULL OR audio_s3_url = ''"
                    ") "
                    "ORDER BY created_at DESC "
                    "LIMIT 20",
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get meetings needing transcript: {e}")
                return []

    async def delete_meeting(self, meeting_id: int):
        """Delete meeting and all related data from database."""
        async with self.pool.acquire() as conn:
            try:
                # Delete from project_meetings (if linked to any projects)
                await conn.execute(
                    "DELETE FROM project_meetings WHERE zoom_meeting_db_id = "
                    "(SELECT id FROM zoom_meetings WHERE meeting_id = $1)",
                    meeting_id,
                )
                
                # Delete from meeting_participants
                await conn.execute(
                    "DELETE FROM meeting_participants WHERE meeting_id = $1",
                    meeting_id,
                )
                
                # Delete the meeting itself
                await conn.execute(
                    "DELETE FROM zoom_meetings WHERE meeting_id = $1",
                    meeting_id,
                )
                
                logger.info(f"Meeting {meeting_id} deleted from database")
            except Exception as e:
                logger.error(f"Failed to delete meeting {meeting_id}: {e}")
                raise

    # ---- Web sessions (web app auth) ----

    async def create_web_session(self, token: str, telegram_id: int, first_name: str,
                                  username: str, role: str, note: str, expires_at) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO web_sessions (token, telegram_id, first_name, username, role, note, expires_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                token, telegram_id, first_name, username, role, note, expires_at,
            )

    async def get_web_session(self, token: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM web_sessions WHERE token = $1 AND expires_at > NOW()",
                token,
            )
            return dict(row) if row else None

    async def delete_expired_sessions(self) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM web_sessions WHERE expires_at < NOW()")
            return int(result.split()[-1])

    async def update_meeting_visibility(self, meeting_id: int, is_public: bool):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE zoom_meetings SET is_public = $2 WHERE meeting_id = $1",
                meeting_id, is_public,
            )

    # ---- Invite links helpers ----

    async def save_invite_link(self, token: str, created_by: int, target_role: str = 'staff'):
        """Save a new invite link token with target role."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO staff_invite_links (token, created_by, target_role) "
                    "VALUES ($1, $2, $3) ON CONFLICT (token) DO NOTHING",
                    token, created_by, target_role,
                )
                logger.info(f"Invite link saved by {created_by}, role={target_role}")
            except Exception as e:
                logger.error(f"Failed to save invite link: {e}")

    async def get_invite_link_by_token(self, token: str) -> dict | None:
        """Return invite link row if token exists and is active."""
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM staff_invite_links WHERE token = $1 AND is_active = TRUE",
                    token,
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get invite link: {e}")
                return None

    # ---- Staff notes + admin helpers ----

    async def get_admin_users(self) -> list[dict]:
        """Return all users with role='admin'."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT telegram_id, first_name, last_name, username "
                    "FROM users WHERE role = 'admin' ORDER BY first_name",
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get admin users: {e}")
                return []

    async def get_all_staff(self) -> list[dict]:
        """Return all staff/admin users with their notes and grade info."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT u.telegram_id, u.first_name, u.last_name, u.username,
                           u.role, u.created_at, u.staff_specialty, u.staff_grade,
                           sn.note
                    FROM users u
                    LEFT JOIN staff_notes sn ON u.telegram_id = sn.staff_telegram_id
                    WHERE u.role IN ('staff', 'admin')
                    ORDER BY u.role DESC, u.first_name
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get all staff: {e}")
                return []

    async def update_staff_grade_info(self, telegram_id: int, specialty: str, grade: str) -> None:
        """Update staff specialty and grade."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE users SET staff_specialty = $2, staff_grade = $3 WHERE telegram_id = $1",
                    telegram_id, specialty, grade,
                )
                logger.info(f"Staff {telegram_id} grade updated: specialty={specialty}, grade={grade}")
            except Exception as e:
                logger.error(f"Failed to update staff grade: {e}")

    async def update_employee(
        self,
        telegram_id: int,
        specialty: str | None,
        grade: str | None,
        kimai_user_id: int | None,
        staff_email: str | None = None,
        staff_display_name: str | None = None,
    ) -> bool:
        """Update employee specialty, grade, Kimai user link, email and display name."""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    """UPDATE users
                       SET staff_specialty = $2, staff_grade = $3, kimai_user_id = $4,
                           staff_email = $5, staff_display_name = $6
                       WHERE telegram_id = $1 AND role IN ('staff', 'admin')""",
                    telegram_id, specialty, grade, kimai_user_id,
                    staff_email, staff_display_name,
                )
                logger.info(f"Employee {telegram_id} updated: specialty={specialty}, grade={grade}, kimai_user_id={kimai_user_id}, email={staff_email}, display_name={staff_display_name}")
                return result == "UPDATE 1"
            except Exception as e:
                logger.error(f"Failed to update employee {telegram_id}: {e}")
                return False

    async def get_all_staff_with_kimai(self) -> list[dict]:
        """Return all staff/admin users including kimai_user_id, email and display name."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT u.telegram_id, u.uuid, u.first_name, u.last_name, u.username,
                           u.role, u.created_at, u.staff_specialty, u.staff_grade,
                           u.kimai_user_id, u.staff_email, u.staff_display_name, sn.note
                    FROM users u
                    LEFT JOIN staff_notes sn ON u.telegram_id = sn.staff_telegram_id
                    WHERE u.role IN ('staff', 'admin')
                    ORDER BY u.role DESC, u.first_name
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get staff with kimai: {e}")
                return []

    async def get_employee_by_uuid(self, emp_uuid: str) -> dict | None:
        """Get a single employee by UUID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT u.telegram_id, u.uuid, u.first_name, u.last_name, u.username,
                       u.role, u.created_at, u.staff_specialty, u.staff_grade,
                       u.kimai_user_id, u.staff_email, u.staff_display_name, sn.note
                FROM users u
                LEFT JOIN staff_notes sn ON u.telegram_id = sn.staff_telegram_id
                WHERE u.uuid = $1::uuid AND u.role IN ('staff', 'admin')
            """, emp_uuid)
            return dict(row) if row else None

    async def get_staff_note(self, staff_telegram_id: int) -> str:
        """Get note for a specific staff member."""
        async with self.pool.acquire() as conn:
            try:
                val = await conn.fetchval(
                    "SELECT note FROM staff_notes WHERE staff_telegram_id = $1",
                    staff_telegram_id,
                )
                return val or ""
            except Exception as e:
                logger.error(f"Failed to get staff note: {e}")
                return ""

    async def save_staff_note(self, staff_telegram_id: int, note: str, updated_by: int):
        """Save or update a note for a staff member."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO staff_notes (staff_telegram_id, note, updated_by, updated_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (staff_telegram_id) DO UPDATE
                    SET note = $2, updated_by = $3, updated_at = NOW()
                """, staff_telegram_id, note, updated_by)
                logger.info(f"Staff note saved for {staff_telegram_id}")
            except Exception as e:
                logger.error(f"Failed to save staff note: {e}")

    async def get_staff_notes_bulk(self, telegram_ids: list[int]) -> dict[int, str]:
        """Get notes for multiple staff members at once."""
        if not telegram_ids:
            return {}
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT staff_telegram_id, note FROM staff_notes "
                    "WHERE staff_telegram_id = ANY($1::bigint[])",
                    telegram_ids,
                )
                return {row['staff_telegram_id']: row['note'] for row in rows}
            except Exception as e:
                logger.error(f"Failed to get staff notes bulk: {e}")
                return {}

    # ---- Project Categories ----

    async def get_all_categories(self, staff_only: bool = False) -> list[dict]:
        async with self.pool.acquire() as conn:
            if staff_only:
                rows = await conn.fetch(
                    "SELECT id, slug, label, color, position, staff_visible "
                    "FROM project_categories WHERE staff_visible = TRUE ORDER BY position, id"
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, slug, label, color, position, staff_visible "
                    "FROM project_categories ORDER BY position, id"
                )
            return [dict(r) for r in rows]

    async def create_category(self, slug: str, label: str, color: str, position: int) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO project_categories (slug, label, color, position)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id, slug, label, color, position, staff_visible""",
                slug, label, color, position
            )
            return dict(row)

    async def update_category(self, slug: str, label: str, color: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE project_categories SET label = $1, color = $2
                   WHERE slug = $3
                   RETURNING id, slug, label, color, position, staff_visible""",
                label, color, slug
            )
            return dict(row) if row else None

    async def update_category_staff_visible(self, slug: str, staff_visible: bool) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE project_categories SET staff_visible = $1
                   WHERE slug = $2
                   RETURNING id, slug, label, color, position, staff_visible""",
                staff_visible, slug
            )
            return dict(row) if row else None

    async def delete_category(self, slug: str) -> bool:
        """Delete category and reset its projects to 'other'."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE projects SET project_type = 'other' WHERE project_type = $1",
                    slug
                )
                result = await conn.execute(
                    "DELETE FROM project_categories WHERE slug = $1", slug
                )
            return result.split()[-1] != '0'

    async def reorder_categories(self, slugs: list[str]) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for i, slug in enumerate(slugs):
                    await conn.execute(
                        "UPDATE project_categories SET position = $1 WHERE slug = $2", i, slug
                    )

    # ---- Projects ----

    async def create_project(self, name: str, description: str | None, created_by: int | None,
                              project_type: str = 'other', client_id: int | None = None) -> dict:
        async with self.pool.acquire() as conn:
            try:
                import uuid
                public_token = uuid.uuid4().hex[:16]
                row = await conn.fetchrow("""
                    INSERT INTO projects (name, description, public_token, created_by, project_type, client_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, name, description, public_token, created_by, created_at, project_type, client_id
                """, name, description, public_token, created_by, project_type, client_id)
                logger.info(f"Project created: {name} (token={public_token}, type={project_type})")
                return dict(row)
            except Exception as e:
                logger.error(f"Failed to create project: {e}")
                raise

    async def update_project_type(self, public_token: str, project_type: str) -> bool:
        """Update project_type for a project."""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    "UPDATE projects SET project_type = $1 WHERE public_token = $2",
                    project_type, public_token,
                )
                return result.split()[-1] != '0'
            except Exception as e:
                logger.error(f"Failed to update project type: {e}")
                return False

    async def get_all_projects(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT p.*, COUNT(pm.id) AS meeting_count,
                           CONCAT_WS(' ', cl.first_name, cl.last_name) AS client_name,
                           cl.company AS client_company
                    FROM projects p
                    LEFT JOIN project_meetings pm ON p.id = pm.project_id
                    LEFT JOIN users cl ON p.client_id = cl.id
                    GROUP BY p.id, cl.first_name, cl.last_name, cl.company
                    ORDER BY p.created_at DESC
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get all projects: {e}")
                return []

    async def get_staff_visible_projects(self) -> list[dict]:
        """Return only projects visible to staff (is_staff_visible = TRUE and category staff_visible = TRUE)."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT p.*, COUNT(pm.id) AS meeting_count,
                           CONCAT_WS(' ', cl.first_name, cl.last_name) AS client_name,
                           cl.company AS client_company
                    FROM projects p
                    LEFT JOIN project_meetings pm ON p.id = pm.project_id
                    LEFT JOIN users cl ON p.client_id = cl.id
                    LEFT JOIN project_categories pc ON p.project_type = pc.slug
                    WHERE p.is_staff_visible = TRUE
                      AND (pc.staff_visible IS NULL OR pc.staff_visible = TRUE)
                    GROUP BY p.id, cl.first_name, cl.last_name, cl.company
                    ORDER BY p.created_at DESC
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get staff-visible projects: {e}")
                return []

    async def update_project_staff_visibility(self, project_id: int, is_visible: bool) -> bool:
        """Set is_staff_visible for a project. Returns True on success."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE projects SET is_staff_visible = $2 WHERE id = $1",
                    project_id, is_visible,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to update project staff visibility: {e}")
                return False

    async def get_project_by_token(self, public_token: str) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT p.*, cl.uuid AS client_uuid "
                    "FROM projects p "
                    "LEFT JOIN users cl ON p.client_id = cl.id "
                    "WHERE p.public_token = $1",
                    public_token,
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get project by token: {e}")
                return None

    async def get_project_by_id(self, project_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM projects WHERE id = $1",
                    project_id,
                )
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get project by id: {e}")
                return None

    async def update_project(self, project_id: int, name: str, description: str | None):
        """Update project name and description."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE projects
                    SET name = $2, description = $3
                    WHERE id = $1
                """, project_id, name, description)
                logger.info(f"Project {project_id} updated")
            except Exception as e:
                logger.error(f"Failed to update project: {e}")
                raise

    async def delete_project(self, project_id: int):
        """Delete project (CASCADE will remove project_meetings and project_embeddings)."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("DELETE FROM projects WHERE id = $1", project_id)
                logger.info(f"Project {project_id} deleted")
            except Exception as e:
                logger.error(f"Failed to delete project: {e}")
                raise

    async def update_project_kimai_link(self, project_id: int, kimai_project_id: int | None) -> bool:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "UPDATE projects SET kimai_project_id = $2 WHERE id = $1",
                    project_id, kimai_project_id,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to update kimai link for project {project_id}: {e}")
                return False

    # ---- Project Expenses ----

    async def add_project_expense(self, project_id: int, title: str, amount: float,
                                   category: str | None, expense_date, created_by: int | None) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    INSERT INTO project_expenses (project_id, title, amount, category, expense_date, created_by)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                """, project_id, title, amount, category, expense_date, created_by)
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to add project expense: {e}")
                return None

    async def get_project_expenses(self, project_id: int, date_from=None, date_to=None) -> list[dict]:
        async with self.pool.acquire() as conn:
            try:
                sql = "SELECT * FROM project_expenses WHERE project_id = $1"
                params: list = [project_id]
                if date_from:
                    params.append(date_from)
                    sql += f" AND expense_date >= ${len(params)}"
                if date_to:
                    params.append(date_to)
                    sql += f" AND expense_date <= ${len(params)}"
                sql += " ORDER BY expense_date DESC, id DESC"
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]
            except Exception as e:
                logger.error(f"Failed to get project expenses: {e}")
                return []

    async def delete_project_expense(self, expense_id: int) -> bool:
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute("DELETE FROM project_expenses WHERE id = $1", expense_id)
                return result == "DELETE 1"
            except Exception as e:
                logger.error(f"Failed to delete expense {expense_id}: {e}")
                return False

    # ---- Project Income ----

    async def add_project_income(self, project_id: int, title: str, amount: float,
                                  income_date, created_by: int | None) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    INSERT INTO project_income (project_id, title, amount, income_date, created_by)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                """, project_id, title, amount, income_date, created_by)
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to add project income: {e}")
                return None

    async def get_project_income(self, project_id: int, date_from=None, date_to=None) -> list[dict]:
        async with self.pool.acquire() as conn:
            try:
                sql = "SELECT * FROM project_income WHERE project_id = $1"
                params: list = [project_id]
                if date_from:
                    params.append(date_from)
                    sql += f" AND income_date >= ${len(params)}"
                if date_to:
                    params.append(date_to)
                    sql += f" AND income_date <= ${len(params)}"
                sql += " ORDER BY income_date DESC, id DESC"
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]
            except Exception as e:
                logger.error(f"Failed to get project income: {e}")
                return []

    async def delete_project_income(self, income_id: int) -> bool:
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute("DELETE FROM project_income WHERE id = $1", income_id)
                return result == "DELETE 1"
            except Exception as e:
                logger.error(f"Failed to delete income {income_id}: {e}")
                return False

    async def add_meeting_to_project(self, project_id: int, zoom_meeting_db_id: int):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO project_meetings (project_id, zoom_meeting_db_id)
                    VALUES ($1, $2)
                    ON CONFLICT (project_id, zoom_meeting_db_id) DO NOTHING
                """, project_id, zoom_meeting_db_id)
                logger.info(f"Meeting {zoom_meeting_db_id} added to project {project_id}")
            except Exception as e:
                logger.error(f"Failed to add meeting to project: {e}")
                raise

    async def remove_meeting_from_project(self, project_id: int, zoom_meeting_db_id: int):
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "DELETE FROM project_meetings WHERE project_id = $1 AND zoom_meeting_db_id = $2",
                    project_id, zoom_meeting_db_id,
                )
                logger.info(f"Meeting {zoom_meeting_db_id} removed from project {project_id}")
            except Exception as e:
                logger.error(f"Failed to remove meeting from project: {e}")

    async def get_project_meetings(self, project_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT zm.id AS db_id, zm.meeting_id, zm.topic, zm.duration,
                           zm.host_name, zm.status, zm.recording_url, zm.public_token,
                           zm.is_public, zm.created_at, zm.start_time
                    FROM project_meetings pm
                    JOIN zoom_meetings zm ON pm.zoom_meeting_db_id = zm.id
                    WHERE pm.project_id = $1
                    ORDER BY zm.created_at DESC
                """, project_id)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get project meetings: {e}")
                return []

    async def get_meeting_projects(self, zoom_meeting_db_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT p.id, p.name, p.public_token
                    FROM project_meetings pm
                    JOIN projects p ON pm.project_id = p.id
                    WHERE pm.zoom_meeting_db_id = $1
                    ORDER BY p.name
                """, zoom_meeting_db_id)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get meeting projects: {e}")
                return []

    async def get_all_meetings_short(self) -> list[dict]:
        """Return all meetings (short info) for selection lists."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT id AS db_id, meeting_id, topic, duration, host_name,
                           status, public_token, created_at
                    FROM zoom_meetings
                    ORDER BY created_at DESC
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get all meetings short: {e}")
                return []

    async def get_unlinked_meetings(self) -> list[dict]:
        """Return meetings not linked to any project."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT zm.id AS db_id, zm.meeting_id, zm.topic, zm.duration,
                           zm.host_name, zm.status, zm.public_token, zm.created_at,
                           zm.start_time
                    FROM zoom_meetings zm
                    WHERE zm.id NOT IN (
                        SELECT DISTINCT zoom_meeting_db_id FROM project_meetings
                    )
                    ORDER BY zm.created_at DESC
                """)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get unlinked meetings: {e}")
                return []

    async def get_zoom_meeting_by_db_id(self, db_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow("SELECT * FROM zoom_meetings WHERE id = $1", db_id)
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Failed to get zoom meeting by db_id: {e}")
                return None

    async def get_projects_for_meeting_by_meeting_id(self, meeting_id: int) -> list[dict]:
        """Get projects linked to a zoom meeting by its zoom meeting_id (not db id)."""
        async with self.pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT p.id, p.name, p.public_token
                    FROM project_meetings pm
                    JOIN projects p ON pm.project_id = p.id
                    JOIN zoom_meetings zm ON pm.zoom_meeting_db_id = zm.id
                    WHERE zm.meeting_id = $1
                    ORDER BY p.name
                """, meeting_id)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get projects for meeting: {e}")
                return []

    # ---- Project Embeddings ----

    async def _has_embeddings_table(self, conn) -> bool:
        return await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'project_embeddings')"
        )

    async def save_embeddings(self, project_id: int, zoom_meeting_db_id: int, chunks: list[dict]):
        """Save embedding chunks. Each chunk: {chunk_index, chunk_text, embedding}."""
        async with self.pool.acquire() as conn:
            try:
                if not await self._has_embeddings_table(conn):
                    logger.warning("project_embeddings table does not exist, skipping save")
                    return
                await conn.execute(
                    "DELETE FROM project_embeddings WHERE project_id = $1 AND zoom_meeting_db_id = $2",
                    project_id, zoom_meeting_db_id,
                )
                for chunk in chunks:
                    embedding_str = "[" + ",".join(str(v) for v in chunk["embedding"]) + "]"
                    await conn.execute("""
                        INSERT INTO project_embeddings
                            (project_id, zoom_meeting_db_id, chunk_index, chunk_text, embedding)
                        VALUES ($1, $2, $3, $4, $5::vector)
                    """, project_id, zoom_meeting_db_id, chunk["chunk_index"],
                         chunk["chunk_text"], embedding_str)
                logger.info(f"Saved {len(chunks)} embeddings for project {project_id}, meeting {zoom_meeting_db_id}")
            except Exception as e:
                logger.error(f"Failed to save embeddings: {e}")
                raise

    async def search_similar_chunks(self, project_id: int, query_embedding: list[float], limit: int = 10) -> list[dict]:
        async with self.pool.acquire() as conn:
            try:
                if not await self._has_embeddings_table(conn):
                    return []
                embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
                rows = await conn.fetch("""
                    SELECT pe.chunk_text, pe.chunk_index, pe.zoom_meeting_db_id,
                           zm.topic AS meeting_topic,
                           zm.public_token AS meeting_token,
                           pe.embedding <=> $1::vector AS distance
                    FROM project_embeddings pe
                    JOIN zoom_meetings zm ON pe.zoom_meeting_db_id = zm.id
                    WHERE pe.project_id = $2
                    ORDER BY pe.embedding <=> $1::vector
                    LIMIT $3
                """, embedding_str, project_id, limit)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to search similar chunks: {e}")
                return []

    async def delete_embeddings_for_meeting(self, project_id: int, zoom_meeting_db_id: int):
        async with self.pool.acquire() as conn:
            try:
                if not await self._has_embeddings_table(conn):
                    return
                await conn.execute(
                    "DELETE FROM project_embeddings WHERE project_id = $1 AND zoom_meeting_db_id = $2",
                    project_id, zoom_meeting_db_id,
                )
                logger.info(f"Embeddings deleted for project {project_id}, meeting {zoom_meeting_db_id}")
            except Exception as e:
                logger.error(f"Failed to delete embeddings: {e}")

    # ── Meeting Tasks ──────────────────────────────────────────────

    async def get_meeting_tasks(self, meeting_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM meeting_tasks WHERE meeting_id = $1 ORDER BY created_at",
                meeting_id,
            )
            return [dict(r) for r in rows]

    async def create_meeting_task(
        self,
        meeting_id: int,
        title: str,
        description: str | None = None,
        priority: str = 'medium',
        category: str = 'task',
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO meeting_tasks (meeting_id, title, description, priority, category)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
            """, meeting_id, title, description, priority, category)
            return dict(row)

    async def update_meeting_task(self, task_id: int, title: str, description: str | None = None) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE meeting_tasks
                SET title = $2, description = $3, updated_at = NOW()
                WHERE id = $1
                RETURNING *
            """, task_id, title, description)
            return dict(row) if row else None

    async def delete_meeting_task(self, task_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM meeting_tasks WHERE id = $1", task_id)
            return result == "DELETE 1"

    async def mark_task_sent_to_lark(self, task_id: int, lark_message_id: str | None = None) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE meeting_tasks
                SET sent_to_lark = TRUE, lark_message_id = $2, updated_at = NOW()
                WHERE id = $1
                RETURNING *
            """, task_id, lark_message_id)
            return dict(row) if row else None

    # ── Clients (CRM) ──────────────────────────────────────────

    async def create_client(self, name: str, company: str | None = None,
                            email: str | None = None, phone: str | None = None,
                            telegram: str | None = None, position: str | None = None,
                            website: str | None = None, address: str | None = None,
                            notes: str | None = None, status: str = 'lead') -> dict:
        import secrets
        parts = name.split(' ', 1)
        first = parts[0] if parts else name
        last = parts[1] if len(parts) > 1 else ''
        tg_username = (telegram or '').lstrip('@') or None
        cabinet_token = secrets.token_hex(16)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO users (first_name, last_name, username, role,
                                   company, email, phone, position, website,
                                   address, client_notes, client_status,
                                   cabinet_token, updated_at)
                VALUES ($1,$2,$3,'user',$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
                RETURNING *
            """, first, last, tg_username, company, email, phone,
                position, website, address, notes, status, cabinet_token)
            logger.info(f"Client created: {name} (id={row['id']}, cabinet_token={cabinet_token})")
            return dict(row)

    async def link_telegram_to_client(
        self, cabinet_token: str, telegram_id: int,
        first_name: str, last_name: str | None, username: str | None,
    ) -> dict | None:
        """Link a Telegram account to an existing client record by cabinet_token.
        Handles the case where save_user() already created a row with this telegram_id
        by merging client fields into the existing user row."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                client_row = await conn.fetchrow(
                    "SELECT * FROM users WHERE cabinet_token = $1", cabinet_token
                )
                if not client_row:
                    return None

                if client_row['telegram_id'] == telegram_id:
                    return dict(client_row)

                if client_row['telegram_id'] is not None and client_row['telegram_id'] != telegram_id:
                    return None

                existing_user = await conn.fetchrow(
                    "SELECT * FROM users WHERE telegram_id = $1", telegram_id
                )

                if existing_user and existing_user['id'] != client_row['id']:
                    row = await conn.fetchrow("""
                        UPDATE users SET
                            client_status = COALESCE($2, client_status),
                            cabinet_token = $3,
                            company = COALESCE($4, company),
                            email = COALESCE($5, email),
                            phone = COALESCE($6, phone),
                            position = COALESCE($7, position),
                            website = COALESCE($8, website),
                            address = COALESCE($9, address),
                            client_notes = COALESCE($10, client_notes),
                            updated_at = NOW()
                        WHERE id = $1
                        RETURNING *
                    """,
                        existing_user['id'],
                        client_row.get('client_status') or 'lead',
                        client_row['cabinet_token'],
                        client_row.get('company'),
                        client_row.get('email'),
                        client_row.get('phone'),
                        client_row.get('position'),
                        client_row.get('website'),
                        client_row.get('address'),
                        client_row.get('client_notes'),
                    )
                    await conn.execute(
                        "UPDATE commercial_proposals SET client_id = $1 WHERE client_id = $2",
                        existing_user['id'], client_row['id'],
                    )
                    await conn.execute(
                        "UPDATE projects SET client_id = $1 WHERE client_id = $2",
                        existing_user['id'], client_row['id'],
                    )
                    await conn.execute(
                        "UPDATE client_messages SET client_id = $1 WHERE client_id = $2",
                        existing_user['id'], client_row['id'],
                    )
                    await conn.execute(
                        "DELETE FROM users WHERE id = $1", client_row['id']
                    )
                    logger.info(
                        f"Merged client id={client_row['id']} into user id={existing_user['id']} "
                        f"(tg={telegram_id})"
                    )
                    return dict(row) if row else None
                else:
                    row = await conn.fetchrow("""
                        UPDATE users SET
                            telegram_id = $2,
                            first_name = COALESCE(NULLIF($3, ''), first_name),
                            last_name = COALESCE(NULLIF($4, ''), last_name),
                            username = COALESCE($5, username),
                            client_status = COALESCE(client_status, 'lead'),
                            updated_at = NOW()
                        WHERE cabinet_token = $1
                        RETURNING *
                    """, cabinet_token, telegram_id, first_name or '', last_name or '', username)
                    if row:
                        logger.info(
                            f"Telegram {telegram_id} linked to client id={row['id']} "
                            f"via cabinet_token"
                        )
                    return dict(row) if row else None

    async def get_client(self, client_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", client_id)
            return dict(row) if row else None

    async def get_all_clients(self, status_filter: str | None = None) -> list[dict]:
        """Return all CRM-visible users: clients (client_status IS NOT NULL) + staff + admin."""
        async with self.pool.acquire() as conn:
            base = (
                "SELECT u.*, "
                "(SELECT COUNT(*) FROM commercial_proposals cp WHERE cp.client_id = u.id) AS proposals_count, "
                "(SELECT COUNT(*) FROM projects p WHERE p.client_id = u.id) AS projects_count "
                "FROM users u "
                "WHERE (u.client_status IS NOT NULL OR u.role IN ('staff', 'admin', 'seller')) "
                "AND u.telegram_id IS NOT NULL "
            )
            if status_filter:
                rows = await conn.fetch(
                    base + "AND u.client_status = $1 ORDER BY u.updated_at DESC NULLS LAST",
                    status_filter,
                )
            else:
                rows = await conn.fetch(
                    base + "ORDER BY u.updated_at DESC NULLS LAST"
                )
            return [dict(r) for r in rows]

    async def update_client(self, client_id: int, **kwargs) -> dict | None:
        field_map = {
            'name': None,  # handled specially
            'company': 'company', 'email': 'email', 'phone': 'phone',
            'telegram': 'username', 'position': 'position',
            'website': 'website', 'address': 'address',
            'notes': 'client_notes', 'status': 'client_status',
        }
        fields = {}
        for k, v in kwargs.items():
            if k == 'name' and v:
                parts = v.split(' ', 1)
                fields['first_name'] = parts[0]
                fields['last_name'] = parts[1] if len(parts) > 1 else ''
                continue
            col = field_map.get(k)
            if not col:
                continue
            if v is None:
                continue
            if k == 'telegram' and isinstance(v, str):
                v = v.lstrip('@') or None
            if isinstance(v, str) and v == '' and k not in ('status',):
                fields[col] = None
            else:
                fields[col] = v
        if not fields:
            return await self.get_client(client_id)
        async with self.pool.acquire() as conn:
            sets = []
            vals = [client_id]
            idx = 2
            for k, v in fields.items():
                sets.append(f"{k} = ${idx}")
                vals.append(v)
                idx += 1
            sets.append("updated_at = NOW()")
            query = f"UPDATE users SET {', '.join(sets)} WHERE id = $1 RETURNING *"
            row = await conn.fetchrow(query, *vals)
            if row:
                logger.info(f"Client {client_id} updated")
            return dict(row) if row else None

    async def delete_client(self, client_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET client_status = NULL WHERE id = $1", client_id
            )
            deleted = result.split()[-1] != '0'
            if deleted:
                logger.info(f"Client {client_id} removed from clients")
            return deleted

    async def get_client_proposals(self, client_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, token, project_name, client_name, proposal_type,
                       currency, hourly_rate, proposal_status, project_id,
                       discount_percent,
                       created_at, updated_at
                FROM commercial_proposals WHERE client_id = $1
                ORDER BY created_at DESC
            """, client_id)
            return [dict(r) for r in rows]

    async def get_client_projects(self, client_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT p.*, COUNT(pm.id) AS meeting_count
                FROM projects p
                LEFT JOIN project_meetings pm ON p.id = pm.project_id
                WHERE p.client_id = $1
                GROUP BY p.id
                ORDER BY p.created_at DESC
            """, client_id)
            return [dict(r) for r in rows]

    async def get_staff_telegram_ids(self) -> set:
        """Return set of telegram_ids that are staff or admin users."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT telegram_id FROM users WHERE role IN ('staff', 'admin')"
            )
            return {r['telegram_id'] for r in rows}

    async def backfill_client_uuids(self) -> int:
        """Assign gen_random_uuid() to any users that have uuid IS NULL."""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    "UPDATE users SET uuid = gen_random_uuid() WHERE uuid IS NULL"
                )
                count = int(result.split()[-1])
                if count > 0:
                    logger.info(f"backfill_client_uuids: assigned UUID to {count} users")
                return count
            except Exception as e:
                logger.error(f"backfill_client_uuids error: {e}")
                return 0

    async def get_client_by_uuid(self, client_uuid: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE uuid = $1::uuid", client_uuid
            )
            return dict(row) if row else None

    async def get_client_by_telegram_id(self, telegram_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1 AND client_status IS NOT NULL",
                telegram_id,
            )
            return dict(row) if row else None

    async def get_client_by_cabinet_token(self, cabinet_token: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE cabinet_token = $1", cabinet_token
            )
            return dict(row) if row else None

    async def create_client_from_telegram(
        self, telegram_id: int, first_name: str,
        last_name: str | None, username: str | None,
        proposal_token: str | None = None,
    ) -> dict:
        import secrets
        cabinet_token = secrets.token_hex(16)
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1", telegram_id
            )
            if existing:
                row = await conn.fetchrow("""
                    UPDATE users SET
                        client_status = COALESCE(client_status, 'lead'),
                        cabinet_token = COALESCE(cabinet_token, $2),
                        updated_at = NOW()
                    WHERE telegram_id = $1 RETURNING *
                """, telegram_id, cabinet_token)
            else:
                row = await conn.fetchrow("""
                    INSERT INTO users (telegram_id, first_name, last_name, username,
                                       role, client_status, cabinet_token)
                    VALUES ($1, $2, $3, $4, 'user', 'lead', $5)
                    RETURNING *
                """, telegram_id, first_name or '', last_name or '', username, cabinet_token)
            client = dict(row)
            if proposal_token:
                await conn.execute("""
                    UPDATE commercial_proposals
                    SET client_id = $1, updated_at = NOW()
                    WHERE token = $2 AND client_id IS NULL
                """, client['id'], proposal_token)
            logger.info(f"Client from Telegram: {first_name} (id={client['id']}, tg={telegram_id})")
            return client

    async def save_client_message(
        self, client_id: int, direction: str,
        sender_name: str | None, message: str,
        telegram_message_id: int | None = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO client_messages
                    (client_id, direction, sender_name, message, telegram_message_id)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
            """, client_id, direction, sender_name, message, telegram_message_id)
            return dict(row)

    async def get_client_messages(
        self, client_id: int, limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM client_messages
                WHERE client_id = $1
                ORDER BY created_at ASC
                LIMIT $2 OFFSET $3
            """, client_id, limit, offset)
            return [dict(r) for r in rows]

    async def mark_client_messages_read(self, client_id: int, direction: str = 'in') -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE client_messages SET is_read = TRUE
                WHERE client_id = $1 AND direction = $2 AND is_read = FALSE
            """, client_id, direction)

    async def get_client_unread_count(self, client_id: int) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as cnt FROM client_messages
                WHERE client_id = $1 AND direction = 'in' AND is_read = FALSE
            """, client_id)
            return row['cnt'] if row else 0

    async def update_client_promo(self, client_id: int, **kwargs) -> dict | None:
        """Update promo fields on a user/client record."""
        sets = []
        vals = []
        idx = 1
        for key in ('promo_enabled', 'promo_started_at', 'promo_discount_percent'):
            if key in kwargs:
                sets.append(f"{key} = ${idx}")
                vals.append(kwargs[key])
                idx += 1
        if not sets:
            return await self.get_client(client_id)
        vals.append(client_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE users SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
                *vals,
            )
            return dict(row) if row else None

    async def get_project_proposals(self, project_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, token, project_name, client_name, proposal_type,
                       currency, hourly_rate, proposal_status, client_id,
                       created_at, updated_at
                FROM commercial_proposals WHERE project_id = $1
                ORDER BY created_at DESC
            """, project_id)
            return [dict(r) for r in rows]

    async def link_proposal_to_project(self, proposal_token: str, project_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE commercial_proposals SET project_id = $2, updated_at = NOW() WHERE token = $1",
                proposal_token, project_id,
            )
            return result.split()[-1] != '0'

    async def unlink_proposal_from_project(self, proposal_token: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE commercial_proposals SET project_id = NULL, updated_at = NOW() WHERE token = $1",
                proposal_token,
            )
            return result.split()[-1] != '0'

    # ── Commercial Proposals ─────────────────────────────────────

    async def save_commercial_proposal(
        self,
        token: str,
        project_name: str,
        client_name: str,
        proposal_type: str,
        design_type: str,
        currency: str,
        hourly_rate: float,
        estimation: dict,
        config_data: dict | None = None,
        created_by_telegram_id: int | None = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO commercial_proposals
                    (token, project_name, client_name, proposal_type, design_type,
                     currency, hourly_rate, estimation, config_data, created_by_telegram_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10)
                RETURNING id, token, project_name, created_at
            """, token, project_name, client_name, proposal_type, design_type,
                 currency, hourly_rate, json.dumps(estimation), json.dumps(config_data or {}),
                 created_by_telegram_id)
            logger.info(f"Commercial proposal saved: token={token}, project={project_name}")
            return dict(row)

    async def get_commercial_proposal(self, token: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT cp.*, cl.uuid AS client_uuid "
                "FROM commercial_proposals cp "
                "LEFT JOIN users cl ON cp.client_id = cl.id "
                "WHERE cp.token = $1",
                token,
            )
            return dict(row) if row else None

    async def get_all_commercial_proposals(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT cp.id, cp.token, cp.project_name, cp.client_name, cp.proposal_type,
                       cp.design_type, cp.currency, cp.hourly_rate, cp.created_at, cp.updated_at,
                       cp.client_id, cp.project_id, cp.proposal_status,
                       cp.created_by_telegram_id,
                       CONCAT_WS(' ', cl.first_name, cl.last_name) AS client_display_name,
                       cl.company AS client_company,
                       cl.uuid AS client_uuid
                FROM commercial_proposals cp
                LEFT JOIN users cl ON cp.client_id = cl.id
                ORDER BY cp.created_at DESC
            """)
            return [dict(r) for r in rows]

    async def get_seller_proposals(self, telegram_id: int) -> list[dict]:
        """Return proposals created by a specific seller."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT cp.id, cp.token, cp.project_name, cp.client_name, cp.proposal_type,
                       cp.design_type, cp.currency, cp.hourly_rate, cp.created_at, cp.updated_at,
                       cp.client_id, cp.project_id, cp.proposal_status,
                       cp.created_by_telegram_id,
                       CONCAT_WS(' ', cl.first_name, cl.last_name) AS client_display_name,
                       cl.company AS client_company,
                       cl.uuid AS client_uuid
                FROM commercial_proposals cp
                LEFT JOIN users cl ON cp.client_id = cl.id
                WHERE cp.created_by_telegram_id = $1
                ORDER BY cp.created_at DESC
            """, telegram_id)
            return [dict(r) for r in rows]

    async def get_seller_clients(self, telegram_id: int, status_filter: str | None = None) -> list[dict]:
        """Return clients linked to proposals created by a specific seller."""
        async with self.pool.acquire() as conn:
            base = (
                "SELECT u.*, "
                "(SELECT COUNT(*) FROM commercial_proposals cp WHERE cp.client_id = u.id AND cp.created_by_telegram_id = $1) AS proposals_count, "
                "(SELECT COUNT(*) FROM projects p WHERE p.client_id = u.id) AS projects_count "
                "FROM users u "
                "WHERE u.id IN ("
                "  SELECT DISTINCT cp2.client_id FROM commercial_proposals cp2 "
                "  WHERE cp2.created_by_telegram_id = $1 AND cp2.client_id IS NOT NULL"
                ") "
            )
            if status_filter:
                rows = await conn.fetch(
                    base + "AND u.client_status = $2 ORDER BY u.updated_at DESC NULLS LAST",
                    telegram_id, status_filter,
                )
            else:
                rows = await conn.fetch(
                    base + "ORDER BY u.updated_at DESC NULLS LAST",
                    telegram_id,
                )
            return [dict(r) for r in rows]

    async def update_commercial_proposal(self, token: str, **kwargs) -> dict | None:
        allowed = {'project_name', 'client_name', 'hourly_rate', 'currency', 'estimation',
                    'proposal_type', 'design_type', 'client_id', 'project_id', 'proposal_status'}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return await self.get_commercial_proposal(token)
        async with self.pool.acquire() as conn:
            sets = []
            vals = [token]
            idx = 2
            for k, v in fields.items():
                if k == 'estimation':
                    sets.append(f"{k} = ${idx}::jsonb")
                    vals.append(json.dumps(v))
                else:
                    sets.append(f"{k} = ${idx}")
                    vals.append(v)
                idx += 1
            sets.append("updated_at = NOW()")
            query = f"UPDATE commercial_proposals SET {', '.join(sets)} WHERE token = $1 RETURNING *"
            row = await conn.fetchrow(query, *vals)
            if row:
                logger.info(f"Commercial proposal updated: token={token}")
            return dict(row) if row else None

    async def delete_commercial_proposal(self, token: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM commercial_proposals WHERE token = $1", token
            )
            deleted = result.split()[-1] != '0'
            if deleted:
                logger.info(f"Commercial proposal deleted: token={token}")
            return deleted

    # ---- Brainstorm threads ----

    async def create_brainstorm_thread(self, meeting_token: str, telegram_id: int, title: str = 'Новая тема') -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO brainstorm_threads (meeting_token, telegram_id, title) VALUES ($1, $2, $3) RETURNING *",
                meeting_token, telegram_id, title,
            )
            return dict(row)

    async def get_brainstorm_threads(self, meeting_token: str, telegram_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM brainstorm_threads WHERE meeting_token=$1 AND telegram_id=$2 ORDER BY updated_at DESC",
                meeting_token, telegram_id,
            )
            return [dict(r) for r in rows]

    async def rename_brainstorm_thread(self, thread_id: int, telegram_id: int, title: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE brainstorm_threads SET title=$1, updated_at=NOW() WHERE id=$2 AND telegram_id=$3",
                title, thread_id, telegram_id,
            )
            return result.split()[-1] != '0'

    async def delete_brainstorm_thread(self, thread_id: int, telegram_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM brainstorm_threads WHERE id=$1 AND telegram_id=$2",
                thread_id, telegram_id,
            )
            return result.split()[-1] != '0'

    async def add_brainstorm_message(self, thread_id: int, role: str, content: str) -> dict:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE brainstorm_threads SET updated_at=NOW() WHERE id=$1", thread_id
            )
            row = await conn.fetchrow(
                "INSERT INTO brainstorm_messages (thread_id, role, content) VALUES ($1, $2, $3) RETURNING *",
                thread_id, role, content,
            )
            return dict(row)

    async def get_brainstorm_messages(self, thread_id: int, telegram_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT m.* FROM brainstorm_messages m
                JOIN brainstorm_threads t ON t.id = m.thread_id
                WHERE m.thread_id=$1 AND t.telegram_id=$2
                ORDER BY m.created_at ASC
            """, thread_id, telegram_id)
            return [dict(r) for r in rows]
