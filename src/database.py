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
        # Disable statement cache for Supabase pooler compatibility (transaction-level pooling)
        _db_pool = await asyncpg.create_pool(raw_url, min_size=1, max_size=10, statement_cache_size=0)
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
        # Initialize Google ADK session tables
        # The ADK library expects these tables to exist with proper schema
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS adk_internal_metadata (
                key VARCHAR(255) PRIMARY KEY,
                value TEXT
            );
        """)

        # Insert the schema version if it doesn't exist
        await pool.execute("""
            INSERT INTO adk_internal_metadata (key, value)
            VALUES ('schema_version', '1')
            ON CONFLICT (key) DO NOTHING;
        """)

        # Create sessions table if it doesn't exist
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
        await pool.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'screening_conversations'
                    AND column_name = 'channel'
                ) THEN
                    ALTER TABLE screening_conversations
                    ADD COLUMN channel VARCHAR(20) DEFAULT 'chat';
                END IF;
            END $$;
        """)

        # Add 'status' column to applications if it doesn't exist
        await pool.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'applications'
                    AND column_name = 'status'
                ) THEN
                    ALTER TABLE applications
                    ADD COLUMN status VARCHAR(20) DEFAULT 'active';

                    -- Update existing completed applications to 'completed' status
                    UPDATE applications SET status = 'completed' WHERE completed = true;
                END IF;
            END $$;
        """)

        # Ensure default is 'active' (fixes earlier migration that used 'completed' as default)
        await pool.execute("""
            ALTER TABLE applications ALTER COLUMN status SET DEFAULT 'active';
        """)

        # Note: completed column will be removed by migration 005
        # For now, keep sync logic for backwards compatibility during transition

        # Add 'cv' to applications channel check constraint
        await pool.execute("""
            DO $$
            BEGIN
                -- Drop the existing check constraint if it exists
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'applications_channel_check'
                ) THEN
                    ALTER TABLE applications DROP CONSTRAINT applications_channel_check;
                END IF;

                -- Add the new check constraint with 'cv' included
                ALTER TABLE applications
                ADD CONSTRAINT applications_channel_check
                CHECK (channel IN ('voice', 'whatsapp', 'cv'));
            END $$;
        """)

        logger.info("Schema migrations completed")
    except Exception as e:
        logger.warning(f"Schema migration warning (may be ok if already done): {e}")
