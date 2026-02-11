-- Migration: Create clients table for managing company/client information

CREATE TABLE IF NOT EXISTS ats.clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    location TEXT,
    industry TEXT,
    website TEXT,
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add index on name for searching
CREATE INDEX IF NOT EXISTS idx_clients_name ON ats.clients(name);

-- Add trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION ats.update_clients_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_clients_updated_at ON ats.clients;
CREATE TRIGGER trigger_clients_updated_at
    BEFORE UPDATE ON ats.clients
    FOR EACH ROW
    EXECUTE FUNCTION ats.update_clients_updated_at();

-- Add comment
COMMENT ON TABLE ats.clients IS 'Company/client information for recruitment tracking';
