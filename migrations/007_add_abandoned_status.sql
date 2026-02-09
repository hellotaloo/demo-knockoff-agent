-- Migration: Add 'abandoned' status to applications table
-- This allows marking applications as abandoned instead of deleting them
-- when re-initiating tests, preserving test history for analytics

-- Drop existing status constraint
ALTER TABLE applications
DROP CONSTRAINT IF EXISTS applications_status_check;

-- Add new constraint with 'abandoned' status
-- Valid statuses: active, processing, completed, abandoned
ALTER TABLE applications
ADD CONSTRAINT applications_status_check
CHECK (status IN ('active', 'processing', 'completed', 'abandoned'));

-- Add comment explaining abandoned status
COMMENT ON COLUMN applications.status IS 'Application status: active (in progress), processing (AI analyzing), completed (finished with results), abandoned (superseded by newer test)';
