-- Migration 026: Add is_test column to candidates table
--
-- This migration:
-- 1. Adds is_test column to ats.candidates to flag test candidates
-- 2. Defaults to false for existing candidates

-- Add is_test column
ALTER TABLE ats.candidates
ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT false;

-- Comment for documentation
COMMENT ON COLUMN ats.candidates.is_test IS 'Flag to indicate test candidates created during admin testing';

-- Index for filtering test candidates
CREATE INDEX IF NOT EXISTS idx_candidates_is_test
ON ats.candidates(is_test);
