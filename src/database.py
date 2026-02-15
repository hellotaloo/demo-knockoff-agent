"""
Database connection management and migrations.
"""
import asyncpg
import logging
from typing import Optional
from src.config import DATABASE_URL

logger = logging.getLogger(__name__)

# Global connection pool
_db_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global _db_pool
    if _db_pool is None:
        # Convert SQLAlchemy URL to asyncpg format
        raw_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        _db_pool = await asyncpg.create_pool(raw_url, min_size=1, max_size=10)
        logger.info("Database connection pool created")
    return _db_pool


async def close_db_pool():
    """Close the database connection pool."""
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection pool closed")


async def run_schema_migrations(pool: asyncpg.Pool):
    """Run schema migrations to ensure required columns exist."""
    try:
        # Create schemas if they don't exist
        await pool.execute("CREATE SCHEMA IF NOT EXISTS ats;")
        await pool.execute("CREATE SCHEMA IF NOT EXISTS adk;")
        logger.info("Database schemas (ats, adk) ensured")

        # Initialize Google ADK session tables
        # Check if tables exist in adk schema first (post-migration), else use public (pre-migration)
        adk_table_exists = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'adk' AND table_name = 'adk_internal_metadata'
            )
        """)

        if adk_table_exists:
            # Tables already migrated to adk schema - use adk schema
            await pool.execute("""
                INSERT INTO adk.adk_internal_metadata (key, value)
                VALUES ('schema_version', '1')
                ON CONFLICT (key) DO NOTHING;
            """)
        else:
            # Tables still in public schema (pre-migration) - create in public
            await pool.execute("""
                CREATE TABLE IF NOT EXISTS adk_internal_metadata (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT
                );
            """)
            await pool.execute("""
                INSERT INTO adk_internal_metadata (key, value)
                VALUES ('schema_version', '1')
                ON CONFLICT (key) DO NOTHING;
            """)

        # Create sessions table if it doesn't exist
        # Check if already in adk schema (post-migration)
        sessions_in_adk = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'adk' AND table_name = 'sessions'
            )
        """)

        if not sessions_in_adk:
            # Tables still in public schema (pre-migration) - create in public
            await pool.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    app_name VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    data JSONB,
                    last_update_time TIMESTAMP WITH TIME ZONE,
                    PRIMARY KEY (app_name, user_id, session_id)
                );
            """)

        logger.info("ADK session tables initialized")

        # Add 'channel' column to screening_conversations if it doesn't exist
        # Check both public and ats schemas (handles pre and post migration)
        await pool.execute("""
            DO $$
            DECLARE
                target_schema TEXT;
            BEGIN
                -- Determine which schema has the table
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'screening_conversations') THEN
                    target_schema := 'ats';
                ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'screening_conversations') THEN
                    target_schema := 'public';
                ELSE
                    RETURN; -- Table doesn't exist yet
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = target_schema
                    AND table_name = 'screening_conversations'
                    AND column_name = 'channel'
                ) THEN
                    EXECUTE format('ALTER TABLE %I.screening_conversations ADD COLUMN channel VARCHAR(20) DEFAULT ''chat''', target_schema);
                END IF;
            END $$;
        """)

        # Add 'status' column to applications if it doesn't exist
        # Check both public and ats schemas (handles pre and post migration)
        await pool.execute("""
            DO $$
            DECLARE
                target_schema TEXT;
            BEGIN
                -- Determine which schema has the table
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'applications') THEN
                    target_schema := 'ats';
                ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'applications') THEN
                    target_schema := 'public';
                ELSE
                    RETURN; -- Table doesn't exist yet
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = target_schema
                    AND table_name = 'applications'
                    AND column_name = 'status'
                ) THEN
                    EXECUTE format('ALTER TABLE %I.applications ADD COLUMN status VARCHAR(20) DEFAULT ''active''', target_schema);
                    -- Update existing completed applications to 'completed' status
                    EXECUTE format('UPDATE %I.applications SET status = ''completed'' WHERE completed = true', target_schema);
                END IF;
            END $$;
        """)

        # Ensure default is 'active' (fixes earlier migration that used 'completed' as default)
        # Check both schemas
        await pool.execute("""
            DO $$
            DECLARE
                target_schema TEXT;
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'applications') THEN
                    target_schema := 'ats';
                ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'applications') THEN
                    target_schema := 'public';
                ELSE
                    RETURN;
                END IF;
                EXECUTE format('ALTER TABLE %I.applications ALTER COLUMN status SET DEFAULT ''active''', target_schema);
            END $$;
        """)

        # Note: completed column will be removed by migration 005
        # For now, keep sync logic for backwards compatibility during transition

        # Add 'cv' to applications channel check constraint
        # Check both schemas
        await pool.execute("""
            DO $$
            DECLARE
                target_schema TEXT;
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'applications') THEN
                    target_schema := 'ats';
                ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'applications') THEN
                    target_schema := 'public';
                ELSE
                    RETURN;
                END IF;

                -- Drop the existing check constraint if it exists
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'applications_channel_check'
                ) THEN
                    EXECUTE format('ALTER TABLE %I.applications DROP CONSTRAINT applications_channel_check', target_schema);
                END IF;

                -- Add the new check constraint with 'cv' included
                EXECUTE format('ALTER TABLE %I.applications ADD CONSTRAINT applications_channel_check CHECK (channel IN (''voice'', ''whatsapp'', ''cv''))', target_schema);
            END $$;
        """)

        logger.info("Schema migrations completed")
    except Exception as e:
        logger.warning(f"Schema migration warning (may be ok if already done): {e}")
