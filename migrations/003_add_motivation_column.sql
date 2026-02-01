-- Migration: Add motivation column for qualification question score explanations
-- Run this in Supabase SQL Editor

-- Add motivation column to application_answers for qualification question score justification
ALTER TABLE application_answers 
ADD COLUMN IF NOT EXISTS motivation TEXT DEFAULT NULL;

-- Add comment for documentation
COMMENT ON COLUMN application_answers.motivation IS 'AI-generated explanation of the score: what was good/bad, what is missing for 100%';
