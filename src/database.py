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
    """Get or create the database connection pool.

    Pool configuration optimized for Supabase Session Mode Pooler:
    - setup callback validates connections on acquire (like SQLAlchemy pool_pre_ping)
    - max_inactive_connection_lifetime matches Supabase pooler timeout (~5 min)
    - min_size=2 pre-warms connections to avoid cold start latency
    """
    global _db_pool
    if _db_pool is None:
        # Convert SQLAlchemy URL to asyncpg format
        raw_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

        async def setup_connection(conn):
            """Validate connection on acquire - equivalent to pool_pre_ping.

            This prevents stale connections from being returned to callers
            when Supabase's pooler has terminated them due to inactivity.
            """
            await conn.execute("SELECT 1")

        _db_pool = await asyncpg.create_pool(
            raw_url,
            min_size=2,                              # Pre-warm connections
            max_size=10,                             # Reduced to stay within Supabase Session pooler limits
            command_timeout=60,                      # Query timeout (seconds)
            max_inactive_connection_lifetime=300.0,  # Match Supabase pooler timeout (~5 min)
            setup=setup_connection,                  # Validate on each acquire
        )
        logger.info("Database connection pool created (min=2, max=10, idle_lifetime=300s)")
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

        # Rename pre-screening tables to consistent prefix
        # screening_conversations → pre_screening_conversations
        # conversation_messages → pre_screening_messages
        await pool.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'screening_conversations') THEN
                    ALTER TABLE ats.screening_conversations RENAME TO pre_screening_conversations;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'conversation_messages') THEN
                    ALTER TABLE ats.conversation_messages RENAME TO pre_screening_messages;
                END IF;
            END $$;
        """)

        # Add 'channel' column to pre_screening_conversations if it doesn't exist
        await pool.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'pre_screening_conversations') THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'ats'
                        AND table_name = 'pre_screening_conversations'
                        AND column_name = 'channel'
                    ) THEN
                        ALTER TABLE agents.pre_screening_sessions ADD COLUMN channel VARCHAR(20) DEFAULT 'chat';
                    END IF;
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

        # =====================================================================
        # Office locations table
        # =====================================================================
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.office_locations (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES system.workspaces(id) ON DELETE CASCADE,
                name        VARCHAR(200) NOT NULL,
                address     VARCHAR(500) NOT NULL,
                is_default  BOOLEAN NOT NULL DEFAULT false,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_office_locations_workspace
            ON ats.office_locations(workspace_id);
        """)

        # Add office_location_id FK to vacancies (nullable — not all vacancies have a location yet)
        await pool.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'ats' AND table_name = 'vacancies'
                    AND column_name = 'office_location_id'
                ) THEN
                    ALTER TABLE ats.vacancies
                    ADD COLUMN office_location_id UUID REFERENCES ats.office_locations(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """)

        logger.info("Office locations table and vacancy FK ensured")

        # Add analysis_result JSONB column to pre_screenings (for interview analysis cache)
        await pool.execute("""
            ALTER TABLE agents.pre_screenings
            ADD COLUMN IF NOT EXISTS analysis_result JSONB DEFAULT NULL;
        """)

        # =====================================================================
        # Document Collection v2 tables
        # =====================================================================

        # Drop old/duplicate document collection tables (replaced by v2 tables below)
        await pool.execute("""
            DROP TABLE IF EXISTS ats.document_collection_upl CASCADE;
            DROP TABLE IF EXISTS ats.document_collection_msg CASCADE;
            DROP TABLE IF EXISTS ats.document_collection_conv CASCADE;
            DROP TABLE IF EXISTS ats.document_collection_conversations CASCADE;
        """)

        # 1. Document types reference table
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.document_types (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id    UUID NOT NULL REFERENCES system.workspaces(id) ON DELETE CASCADE,
                slug            VARCHAR(50) NOT NULL,
                name            VARCHAR(200) NOT NULL,
                description     TEXT,
                category        VARCHAR(50) NOT NULL DEFAULT 'identity',
                requires_front_back BOOLEAN NOT NULL DEFAULT false,
                is_verifiable   BOOLEAN NOT NULL DEFAULT false,
                icon            VARCHAR(50),
                is_default      BOOLEAN NOT NULL DEFAULT false,
                is_active       BOOLEAN NOT NULL DEFAULT true,
                sort_order      INTEGER NOT NULL DEFAULT 0,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_document_type_workspace_slug UNIQUE (workspace_id, slug)
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_types_workspace
            ON ats.document_types(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_document_types_workspace_active
            ON ats.document_types(workspace_id) WHERE is_active = true;
        """)

        # 2. Document collection configs
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS agents.document_collection_configs (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id    UUID NOT NULL REFERENCES system.workspaces(id) ON DELETE CASCADE,
                vacancy_id      UUID REFERENCES ats.vacancies(id) ON DELETE CASCADE,
                name            VARCHAR(200),
                intro_message   TEXT,
                status          VARCHAR(20) NOT NULL DEFAULT 'draft',
                is_online       BOOLEAN NOT NULL DEFAULT false,
                whatsapp_enabled BOOLEAN NOT NULL DEFAULT true,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_dc_config_vacancy UNIQUE (vacancy_id)
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_dc_configs_workspace
            ON agents.document_collection_configs(workspace_id);
        """)
        # Partial unique index: one default per workspace (vacancy_id IS NULL)
        await pool.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_dc_config_workspace_default
            ON agents.document_collection_configs(workspace_id)
            WHERE vacancy_id IS NULL;
        """)

        # 3. Document collection requirements
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS agents.document_collection_requirements (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                config_id           UUID NOT NULL REFERENCES agents.document_collection_configs(id) ON DELETE CASCADE,
                document_type_id    UUID NOT NULL REFERENCES ats.document_types(id) ON DELETE CASCADE,
                position            INTEGER NOT NULL DEFAULT 0,
                is_required         BOOLEAN NOT NULL DEFAULT true,
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_dc_requirement UNIQUE (config_id, document_type_id)
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_dc_requirements_config
            ON agents.document_collection_requirements(config_id);
        """)

        # 4. Document collections (main entry table)
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS agents.document_collections (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                config_id           UUID NOT NULL REFERENCES agents.document_collection_configs(id) ON DELETE CASCADE,
                workspace_id        UUID NOT NULL REFERENCES system.workspaces(id) ON DELETE CASCADE,
                vacancy_id          UUID REFERENCES ats.vacancies(id) ON DELETE SET NULL,
                application_id      UUID REFERENCES ats.applications(id) ON DELETE SET NULL,
                candidate_id        UUID REFERENCES ats.candidates(id) ON DELETE SET NULL,
                session_id          VARCHAR(255),
                candidate_name      VARCHAR(200) NOT NULL,
                candidate_phone     VARCHAR(20),
                status              VARCHAR(20) NOT NULL DEFAULT 'active',
                channel             VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
                retry_count         INTEGER NOT NULL DEFAULT 0,
                message_count       INTEGER NOT NULL DEFAULT 0,
                documents_required  JSONB,
                started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at        TIMESTAMPTZ,
                CONSTRAINT chk_dc_status CHECK (status IN ('active', 'completed', 'needs_review', 'abandoned'))
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_dc_workspace ON agents.document_collections(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_dc_phone ON agents.document_collections(candidate_phone);
            CREATE INDEX IF NOT EXISTS idx_dc_status ON agents.document_collections(status) WHERE status = 'active';
        """)

        # 5. Document collection messages
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS agents.document_collection_session_turns (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                collection_id       UUID NOT NULL REFERENCES agents.document_collections(id) ON DELETE CASCADE,
                role                VARCHAR(20) NOT NULL,
                message             TEXT NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_dc_msg_collection
            ON agents.document_collection_session_turns(collection_id);
        """)

        # 6. Document collection uploads
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS agents.document_collection_uploads (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                collection_id       UUID NOT NULL REFERENCES agents.document_collections(id) ON DELETE CASCADE,
                application_id      UUID REFERENCES ats.applications(id) ON DELETE SET NULL,
                document_type_id    UUID REFERENCES ats.document_types(id) ON DELETE SET NULL,
                document_side       VARCHAR(20) NOT NULL DEFAULT 'single',
                image_hash          VARCHAR(64),
                storage_path        VARCHAR(500),
                verification_result JSONB,
                verification_passed BOOLEAN,
                status              VARCHAR(20) NOT NULL DEFAULT 'pending',
                uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                verified_at         TIMESTAMPTZ
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_dc_upl_collection
            ON agents.document_collection_uploads(collection_id);
        """)

        # 7. Candidate documents (portfolio)
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.candidate_documents (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                candidate_id        UUID NOT NULL REFERENCES ats.candidates(id) ON DELETE CASCADE,
                document_type_id    UUID NOT NULL REFERENCES ats.document_types(id) ON DELETE CASCADE,
                workspace_id        UUID NOT NULL REFERENCES system.workspaces(id) ON DELETE CASCADE,
                document_number     VARCHAR(100),
                metadata            JSONB DEFAULT '{}',
                expiration_date     DATE,
                status              VARCHAR(20) NOT NULL DEFAULT 'pending_review',
                verification_passed BOOLEAN,
                upload_id           UUID REFERENCES agents.document_collection_uploads(id) ON DELETE SET NULL,
                storage_path        VARCHAR(500),
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_candidate_document UNIQUE (candidate_id, document_type_id, workspace_id)
            );
        """)
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_candidate_documents_candidate
            ON ats.candidate_documents(candidate_id);
            CREATE INDEX IF NOT EXISTS idx_candidate_documents_workspace
            ON ats.candidate_documents(workspace_id);
        """)

        # Seed function for default document types
        await pool.execute("""
            CREATE OR REPLACE FUNCTION ats.seed_document_type_defaults(p_workspace_id UUID)
            RETURNS void AS $$
            BEGIN
                INSERT INTO ats.document_types (workspace_id, slug, name, category, requires_front_back, is_verifiable, icon, is_default, sort_order) VALUES
                    (p_workspace_id, 'id_card',         'ID-kaart',           'identity',    true,  true,  'credit-card',    true,  0),
                    (p_workspace_id, 'driver_license',   'Rijbewijs',          'certificate', false, true,  'car',            false, 1),
                    (p_workspace_id, 'passport',         'Paspoort',           'identity',    false, true,  'book-open',      false, 2),
                    (p_workspace_id, 'bank_details',     'Bankgegevens',       'financial',   false, false, 'landmark',       false, 3),
                    (p_workspace_id, 'medical_cert',     'Medisch attest',     'certificate', false, true,  'heart-pulse',    false, 4),
                    (p_workspace_id, 'work_permit',      'Arbeidsvergunning',  'certificate', false, true,  'file-badge',     false, 5),
                    (p_workspace_id, 'diploma',          'Diploma/Certificaat','certificate', false, true,  'graduation-cap', false, 6)
                ON CONFLICT (workspace_id, slug) DO UPDATE SET icon = EXCLUDED.icon WHERE ats.document_types.icon IS NULL;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Seed defaults for all existing workspaces
        await pool.execute("""
            DO $$
            DECLARE
                ws RECORD;
            BEGIN
                FOR ws IN SELECT id FROM system.workspaces LOOP
                    PERFORM ats.seed_document_type_defaults(ws.id);
                END LOOP;
            END $$;
        """)

        logger.info("Document collection v2 tables and seed data initialized")

        logger.info("Schema migrations completed")
    except Exception as e:
        logger.warning(f"Schema migration warning (may be ok if already done): {e}")
