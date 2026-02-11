-- Migration: Add logo column to clients table

ALTER TABLE ats.clients ADD COLUMN IF NOT EXISTS logo TEXT;

COMMENT ON COLUMN ats.clients.logo IS 'URL or path to client logo image';
