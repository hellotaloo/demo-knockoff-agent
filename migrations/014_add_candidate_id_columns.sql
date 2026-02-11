-- Migration 014: Add candidate_id foreign key columns
-- Phase 3: Add nullable FK columns for backwards compatibility
--
-- Adds candidate_id to:
-- - applications
-- - screening_conversations
-- - scheduled_interviews
-- - document_collection_conversations

-- Add candidate_id to applications
ALTER TABLE applications
ADD COLUMN IF NOT EXISTS candidate_id UUID REFERENCES ats.candidates(id) ON DELETE SET NULL;

-- Add candidate_id to screening_conversations
ALTER TABLE screening_conversations
ADD COLUMN IF NOT EXISTS candidate_id UUID REFERENCES ats.candidates(id) ON DELETE SET NULL;

-- Add candidate_id to scheduled_interviews
ALTER TABLE scheduled_interviews
ADD COLUMN IF NOT EXISTS candidate_id UUID REFERENCES ats.candidates(id) ON DELETE SET NULL;

-- Add candidate_id to document_collection_conversations
ALTER TABLE document_collection_conversations
ADD COLUMN IF NOT EXISTS candidate_id UUID REFERENCES ats.candidates(id) ON DELETE SET NULL;

-- Create indexes for the new foreign keys (for query performance)
CREATE INDEX IF NOT EXISTS idx_applications_candidate_id
ON applications(candidate_id) WHERE candidate_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_screening_conversations_candidate_id
ON screening_conversations(candidate_id) WHERE candidate_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_candidate_id
ON scheduled_interviews(candidate_id) WHERE candidate_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_document_collection_conversations_candidate_id
ON document_collection_conversations(candidate_id) WHERE candidate_id IS NOT NULL;

-- Comments for documentation
COMMENT ON COLUMN applications.candidate_id IS 'Reference to ats.candidates - the central candidate record';
COMMENT ON COLUMN screening_conversations.candidate_id IS 'Reference to ats.candidates - the central candidate record';
COMMENT ON COLUMN scheduled_interviews.candidate_id IS 'Reference to ats.candidates - the central candidate record';
COMMENT ON COLUMN document_collection_conversations.candidate_id IS 'Reference to ats.candidates - the central candidate record';
