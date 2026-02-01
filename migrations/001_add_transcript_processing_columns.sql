-- Migration: Add columns for voice transcript processing
-- Run this in Supabase SQL Editor

-- Add score column to application_answers for qualification question scoring (0-100)
ALTER TABLE application_answers 
ADD COLUMN IF NOT EXISTS score INTEGER DEFAULT NULL;

-- Add source column to track which channel the answer came from
ALTER TABLE application_answers 
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'chat';

-- Add conversation_id column to applications table to link ElevenLabs conversations
ALTER TABLE applications 
ADD COLUMN IF NOT EXISTS conversation_id TEXT DEFAULT NULL;

-- Add index for looking up applications by conversation_id
CREATE INDEX IF NOT EXISTS idx_applications_conversation_id 
ON applications(conversation_id) 
WHERE conversation_id IS NOT NULL;

-- Add summary column to applications for AI-generated executive summary
ALTER TABLE applications 
ADD COLUMN IF NOT EXISTS summary TEXT DEFAULT NULL;

-- Add interview_slot column to applications for selected interview date/time
ALTER TABLE applications 
ADD COLUMN IF NOT EXISTS interview_slot TEXT DEFAULT NULL;

-- Add comment for documentation
COMMENT ON COLUMN application_answers.score IS 'Score 0-100 for qualification questions, NULL for knockout questions';
COMMENT ON COLUMN application_answers.source IS 'Channel source: chat, whatsapp, or voice';
COMMENT ON COLUMN applications.conversation_id IS 'ElevenLabs conversation ID for voice calls';
COMMENT ON COLUMN applications.summary IS 'AI-generated one-sentence executive summary of candidate';
COMMENT ON COLUMN applications.interview_slot IS 'Selected interview date/time from voice call, or none_fit if no option worked';
