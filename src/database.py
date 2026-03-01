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

        # =====================================================================
        # Ontology tables
        # =====================================================================
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.ontology_types (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES ats.workspaces(id) ON DELETE CASCADE,
                slug        VARCHAR(50) NOT NULL,
                name        VARCHAR(100) NOT NULL,
                name_plural VARCHAR(100),
                description TEXT,
                icon        VARCHAR(50),
                color       VARCHAR(7),
                sort_order  INTEGER NOT NULL DEFAULT 0,
                is_system   BOOLEAN NOT NULL DEFAULT false,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ontology_type_workspace_slug UNIQUE (workspace_id, slug)
            );
        """)

        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.ontology_entities (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES ats.workspaces(id) ON DELETE CASCADE,
                type_id     UUID NOT NULL REFERENCES ats.ontology_types(id) ON DELETE CASCADE,
                name        VARCHAR(200) NOT NULL,
                description TEXT,
                icon        VARCHAR(50),
                color       VARCHAR(7),
                external_id VARCHAR(255),
                metadata    JSONB NOT NULL DEFAULT '{}',
                sort_order  INTEGER NOT NULL DEFAULT 0,
                is_active   BOOLEAN NOT NULL DEFAULT true,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ontology_entity_workspace_name UNIQUE (workspace_id, type_id, name)
            );
        """)

        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.ontology_relation_types (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES ats.workspaces(id) ON DELETE CASCADE,
                slug        VARCHAR(50) NOT NULL,
                name        VARCHAR(100) NOT NULL,
                source_type_id UUID REFERENCES ats.ontology_types(id) ON DELETE SET NULL,
                target_type_id UUID REFERENCES ats.ontology_types(id) ON DELETE SET NULL,
                is_system   BOOLEAN NOT NULL DEFAULT false,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ontology_reltype_workspace_slug UNIQUE (workspace_id, slug)
            );
        """)

        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.ontology_relations (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id    UUID NOT NULL REFERENCES ats.workspaces(id) ON DELETE CASCADE,
                source_entity_id UUID NOT NULL REFERENCES ats.ontology_entities(id) ON DELETE CASCADE,
                target_entity_id UUID NOT NULL REFERENCES ats.ontology_entities(id) ON DELETE CASCADE,
                relation_type_id UUID NOT NULL REFERENCES ats.ontology_relation_types(id) ON DELETE CASCADE,
                metadata        JSONB NOT NULL DEFAULT '{}',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ontology_relation UNIQUE (source_entity_id, target_entity_id, relation_type_id),
                CONSTRAINT chk_no_self_relation CHECK (source_entity_id != target_entity_id)
            );
        """)

        # Ontology indexes
        await pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_ontology_types_workspace ON ats.ontology_types(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_entities_workspace ON ats.ontology_entities(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_entities_type ON ats.ontology_entities(type_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_entities_workspace_type ON ats.ontology_entities(workspace_id, type_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_entities_external ON ats.ontology_entities(workspace_id, external_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_relations_workspace ON ats.ontology_relations(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_relations_source ON ats.ontology_relations(source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_relations_target ON ats.ontology_relations(target_entity_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_relations_type ON ats.ontology_relations(relation_type_id);
            CREATE INDEX IF NOT EXISTS idx_ontology_relation_types_workspace ON ats.ontology_relation_types(workspace_id);
        """)

        # Ontology seed function
        await pool.execute("""
            CREATE OR REPLACE FUNCTION ats.seed_ontology_defaults(p_workspace_id UUID)
            RETURNS void AS $$
            DECLARE
                v_category_type_id UUID;
                v_function_type_id UUID;
                v_document_type_id UUID;
                v_skill_type_id UUID;
            BEGIN
                INSERT INTO ats.ontology_types (workspace_id, slug, name, name_plural, icon, color, sort_order, is_system) VALUES
                    (p_workspace_id, 'category',      'Categorie',    'Categorieën',   'folder',       '#8B5CF6', 0, true),
                    (p_workspace_id, 'job_function',   'Functie',      'Functies',      'briefcase',    '#3B82F6', 1, true),
                    (p_workspace_id, 'document_type',  'Documenttype', 'Documenttypes', 'file-text',    '#10B981', 2, true),
                    (p_workspace_id, 'skill',          'Vaardigheid',  'Vaardigheden',  'star',         '#F59E0B', 3, true),
                    (p_workspace_id, 'requirement',    'Vereiste',     'Vereisten',     'check-circle', '#EF4444', 4, true)
                ON CONFLICT (workspace_id, slug) DO NOTHING;

                SELECT id INTO v_category_type_id FROM ats.ontology_types WHERE workspace_id = p_workspace_id AND slug = 'category';
                SELECT id INTO v_function_type_id FROM ats.ontology_types WHERE workspace_id = p_workspace_id AND slug = 'job_function';
                SELECT id INTO v_document_type_id FROM ats.ontology_types WHERE workspace_id = p_workspace_id AND slug = 'document_type';
                SELECT id INTO v_skill_type_id FROM ats.ontology_types WHERE workspace_id = p_workspace_id AND slug = 'skill';

                INSERT INTO ats.ontology_relation_types (workspace_id, slug, name, source_type_id, target_type_id, is_system) VALUES
                    (p_workspace_id, 'belongs_to',  'Behoort tot',      v_function_type_id, v_category_type_id, true),
                    (p_workspace_id, 'requires',    'Vereist',           v_function_type_id, v_document_type_id, true),
                    (p_workspace_id, 'has_skill',   'Heeft vaardigheid', v_function_type_id, v_skill_type_id,    true)
                ON CONFLICT (workspace_id, slug) DO NOTHING;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Seed defaults for all existing workspaces
        await pool.execute("""
            DO $$
            DECLARE
                ws RECORD;
            BEGIN
                FOR ws IN SELECT id FROM ats.workspaces LOOP
                    PERFORM ats.seed_ontology_defaults(ws.id);
                END LOOP;
            END $$;
        """)

        logger.info("Ontology tables and seed data initialized")

        # =====================================================================
        # Office locations table
        # =====================================================================
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.office_locations (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES ats.workspaces(id) ON DELETE CASCADE,
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
            ALTER TABLE ats.pre_screenings
            ADD COLUMN IF NOT EXISTS analysis_result JSONB DEFAULT NULL;
        """)

        logger.info("Schema migrations completed")
    except Exception as e:
        logger.warning(f"Schema migration warning (may be ok if already done): {e}")
