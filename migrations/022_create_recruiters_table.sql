-- Migration: Create recruiters table for managing recruiter information

CREATE TABLE IF NOT EXISTS ats.recruiters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    team TEXT,
    role TEXT,
    avatar_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add index on email for lookups
CREATE INDEX IF NOT EXISTS idx_recruiters_email ON ats.recruiters(email);

-- Add index on team for filtering
CREATE INDEX IF NOT EXISTS idx_recruiters_team ON ats.recruiters(team);

-- Add trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION ats.update_recruiters_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_recruiters_updated_at ON ats.recruiters;
CREATE TRIGGER trigger_recruiters_updated_at
    BEFORE UPDATE ON ats.recruiters
    FOR EACH ROW
    EXECUTE FUNCTION ats.update_recruiters_updated_at();

-- Add comment
COMMENT ON TABLE ats.recruiters IS 'Recruiter information - each vacancy is owned by a recruiter';
