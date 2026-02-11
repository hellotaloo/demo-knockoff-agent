-- Migration 016: Move tables to appropriate schemas
-- Phase 5: Reorganize tables into ats.* and adk.* schemas
--
-- This migration:
-- 1. Moves ATS business tables to ats.* schema
-- 2. Moves ADK session tables to adk.* schema
-- 3. Creates backwards-compatibility views in public schema

-- ============================================================================
-- PART 1: Move ATS business tables to ats schema
-- ============================================================================

-- Move tables using ALTER TABLE SET SCHEMA (preserves data, indexes, constraints)
DO $$
BEGIN
    -- vacancies
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'vacancies') THEN
        ALTER TABLE public.vacancies SET SCHEMA ats;
        RAISE NOTICE 'Moved vacancies to ats schema';
    END IF;

    -- applications
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'applications') THEN
        ALTER TABLE public.applications SET SCHEMA ats;
        RAISE NOTICE 'Moved applications to ats schema';
    END IF;

    -- application_answers
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'application_answers') THEN
        ALTER TABLE public.application_answers SET SCHEMA ats;
        RAISE NOTICE 'Moved application_answers to ats schema';
    END IF;

    -- pre_screenings
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'pre_screenings') THEN
        ALTER TABLE public.pre_screenings SET SCHEMA ats;
        RAISE NOTICE 'Moved pre_screenings to ats schema';
    END IF;

    -- pre_screening_questions
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'pre_screening_questions') THEN
        ALTER TABLE public.pre_screening_questions SET SCHEMA ats;
        RAISE NOTICE 'Moved pre_screening_questions to ats schema';
    END IF;

    -- screening_conversations
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'screening_conversations') THEN
        ALTER TABLE public.screening_conversations SET SCHEMA ats;
        RAISE NOTICE 'Moved screening_conversations to ats schema';
    END IF;

    -- conversation_messages
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'conversation_messages') THEN
        ALTER TABLE public.conversation_messages SET SCHEMA ats;
        RAISE NOTICE 'Moved conversation_messages to ats schema';
    END IF;

    -- document_collection_conversations
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'document_collection_conversations') THEN
        ALTER TABLE public.document_collection_conversations SET SCHEMA ats;
        RAISE NOTICE 'Moved document_collection_conversations to ats schema';
    END IF;

    -- document_collection_messages
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'document_collection_messages') THEN
        ALTER TABLE public.document_collection_messages SET SCHEMA ats;
        RAISE NOTICE 'Moved document_collection_messages to ats schema';
    END IF;

    -- document_uploads
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'document_uploads') THEN
        ALTER TABLE public.document_uploads SET SCHEMA ats;
        RAISE NOTICE 'Moved document_uploads to ats schema';
    END IF;

    -- document_verifications (may not exist in all environments)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'document_verifications') THEN
        ALTER TABLE public.document_verifications SET SCHEMA ats;
        RAISE NOTICE 'Moved document_verifications to ats schema';
    ELSE
        RAISE NOTICE 'document_verifications table does not exist, skipping';
    END IF;

    -- scheduled_interviews
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'scheduled_interviews') THEN
        ALTER TABLE public.scheduled_interviews SET SCHEMA ats;
        RAISE NOTICE 'Moved scheduled_interviews to ats schema';
    END IF;
END $$;

-- ============================================================================
-- PART 2: Move ADK session tables to adk schema
-- ============================================================================

DO $$
BEGIN
    -- sessions
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'sessions') THEN
        ALTER TABLE public.sessions SET SCHEMA adk;
        RAISE NOTICE 'Moved sessions to adk schema';
    END IF;

    -- events
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'events') THEN
        ALTER TABLE public.events SET SCHEMA adk;
        RAISE NOTICE 'Moved events to adk schema';
    END IF;

    -- app_states
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'app_states') THEN
        ALTER TABLE public.app_states SET SCHEMA adk;
        RAISE NOTICE 'Moved app_states to adk schema';
    END IF;

    -- user_states
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'user_states') THEN
        ALTER TABLE public.user_states SET SCHEMA adk;
        RAISE NOTICE 'Moved user_states to adk schema';
    END IF;

    -- adk_internal_metadata
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'adk_internal_metadata') THEN
        ALTER TABLE public.adk_internal_metadata SET SCHEMA adk;
        RAISE NOTICE 'Moved adk_internal_metadata to adk schema';
    END IF;
END $$;

-- ============================================================================
-- PART 3: Create backwards-compatibility views in public schema
-- These allow existing code to continue working during transition
-- ============================================================================

-- ATS table views (only create if table exists in ats schema)
DO $$
BEGIN
    -- Core tables (always exist)
    CREATE OR REPLACE VIEW public.vacancies AS SELECT * FROM ats.vacancies;
    CREATE OR REPLACE VIEW public.applications AS SELECT * FROM ats.applications;
    CREATE OR REPLACE VIEW public.application_answers AS SELECT * FROM ats.application_answers;
    CREATE OR REPLACE VIEW public.pre_screenings AS SELECT * FROM ats.pre_screenings;
    CREATE OR REPLACE VIEW public.pre_screening_questions AS SELECT * FROM ats.pre_screening_questions;
    CREATE OR REPLACE VIEW public.screening_conversations AS SELECT * FROM ats.screening_conversations;
    CREATE OR REPLACE VIEW public.conversation_messages AS SELECT * FROM ats.conversation_messages;
    CREATE OR REPLACE VIEW public.document_collection_conversations AS SELECT * FROM ats.document_collection_conversations;
    CREATE OR REPLACE VIEW public.document_collection_messages AS SELECT * FROM ats.document_collection_messages;
    CREATE OR REPLACE VIEW public.document_uploads AS SELECT * FROM ats.document_uploads;
    CREATE OR REPLACE VIEW public.scheduled_interviews AS SELECT * FROM ats.scheduled_interviews;
    CREATE OR REPLACE VIEW public.candidates AS SELECT * FROM ats.candidates;

    -- Optional tables (may not exist in all environments)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'ats' AND table_name = 'document_verifications') THEN
        CREATE OR REPLACE VIEW public.document_verifications AS SELECT * FROM ats.document_verifications;
    END IF;
END $$;

-- ADK table views (Google ADK library may still look in public schema)
CREATE OR REPLACE VIEW public.sessions AS SELECT * FROM adk.sessions;
CREATE OR REPLACE VIEW public.events AS SELECT * FROM adk.events;
CREATE OR REPLACE VIEW public.app_states AS SELECT * FROM adk.app_states;
CREATE OR REPLACE VIEW public.user_states AS SELECT * FROM adk.user_states;
CREATE OR REPLACE VIEW public.adk_internal_metadata AS SELECT * FROM adk.adk_internal_metadata;

-- Comments
COMMENT ON VIEW public.vacancies IS 'Backwards-compatibility view - use ats.vacancies directly';
COMMENT ON VIEW public.applications IS 'Backwards-compatibility view - use ats.applications directly';
COMMENT ON VIEW public.sessions IS 'Backwards-compatibility view - use adk.sessions directly';

-- Log completion
DO $$
DECLARE
    ats_tables INTEGER;
    adk_tables INTEGER;
BEGIN
    SELECT COUNT(*) INTO ats_tables
    FROM information_schema.tables
    WHERE table_schema = 'ats' AND table_type = 'BASE TABLE';

    SELECT COUNT(*) INTO adk_tables
    FROM information_schema.tables
    WHERE table_schema = 'adk' AND table_type = 'BASE TABLE';

    RAISE NOTICE 'Migration 016 complete: % tables in ats schema, % tables in adk schema', ats_tables, adk_tables;
END $$;
