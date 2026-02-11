-- Migration 012: Create schemas and candidates table
-- Phase 1: Non-breaking, additive changes only
--
-- This migration:
-- 1. Creates ats schema for ATS business tables
-- 2. Creates adk schema for Google ADK session tables
-- 3. Creates ats.candidates table as central candidate registry

-- Create schemas if they don't exist
CREATE SCHEMA IF NOT EXISTS ats;
CREATE SCHEMA IF NOT EXISTS adk;

-- Create candidates table in ats schema
-- This is the single source of truth for candidate information
CREATE TABLE IF NOT EXISTS ats.candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Contact information
    phone VARCHAR(20),                    -- E.164 format (e.g., +32412345678)
    email VARCHAR(255),

    -- Name fields
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(255) NOT NULL,

    -- Metadata
    source VARCHAR(50) DEFAULT 'application',  -- application, manual, import
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Comments for documentation
COMMENT ON TABLE ats.candidates IS 'Central candidate registry - single source of truth for candidate information';
COMMENT ON COLUMN ats.candidates.phone IS 'Primary identifier, E.164 format. Unique constraint for non-null values.';
COMMENT ON COLUMN ats.candidates.source IS 'How the candidate was added: application, manual entry, or bulk import';

-- Unique index on phone (only for non-null values)
-- This allows multiple candidates without phone, but phone must be unique when present
CREATE UNIQUE INDEX IF NOT EXISTS idx_ats_candidates_phone
ON ats.candidates(phone) WHERE phone IS NOT NULL;

-- Index on email for lookups (not unique - same email might appear with different phones)
CREATE INDEX IF NOT EXISTS idx_ats_candidates_email
ON ats.candidates(email) WHERE email IS NOT NULL;

-- Index on full_name for search
CREATE INDEX IF NOT EXISTS idx_ats_candidates_full_name
ON ats.candidates(full_name);

-- Create updated_at trigger function in ats schema
CREATE OR REPLACE FUNCTION ats.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to candidates table
DROP TRIGGER IF EXISTS update_candidates_updated_at ON ats.candidates;
CREATE TRIGGER update_candidates_updated_at
    BEFORE UPDATE ON ats.candidates
    FOR EACH ROW
    EXECUTE FUNCTION ats.update_updated_at_column();
