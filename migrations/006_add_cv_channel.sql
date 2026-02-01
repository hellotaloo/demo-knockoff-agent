-- Migration: Add 'cv' as a valid channel type for applications
-- This allows applications to be created from CV uploads/analysis

-- Drop the existing check constraint
ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_channel_check;

-- Add the new check constraint with 'cv' included
ALTER TABLE applications 
ADD CONSTRAINT applications_channel_check 
CHECK (channel IN ('voice', 'whatsapp', 'cv'));

-- Add comment for documentation
COMMENT ON COLUMN applications.channel IS 'Application channel: voice, whatsapp, or cv';
