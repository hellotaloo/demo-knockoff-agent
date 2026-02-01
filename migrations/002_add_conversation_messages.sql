-- Migration: Add conversation_messages table and is_test flags
-- Run this in Supabase SQL Editor

-- Create conversation_messages table for storing all chat messages
CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES screening_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'agent')),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups by conversation
CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation 
ON conversation_messages(conversation_id);

-- Index for chronological ordering
CREATE INDEX IF NOT EXISTS idx_conversation_messages_created 
ON conversation_messages(conversation_id, created_at);

-- Add is_test flag to screening_conversations
ALTER TABLE screening_conversations 
ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT false;

-- Add is_test flag to applications
ALTER TABLE applications 
ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT false;

-- Add indexes for filtering by is_test
CREATE INDEX IF NOT EXISTS idx_screening_conversations_is_test 
ON screening_conversations(is_test);

CREATE INDEX IF NOT EXISTS idx_applications_is_test 
ON applications(is_test);

-- Add comments for documentation
COMMENT ON TABLE conversation_messages IS 'Stores all messages from WhatsApp and voice conversations for display and processing';
COMMENT ON COLUMN conversation_messages.role IS 'Message sender: user (candidate) or agent (AI assistant)';
COMMENT ON COLUMN screening_conversations.is_test IS 'True for internal test conversations from admin chat';
COMMENT ON COLUMN applications.is_test IS 'True for applications from internal test conversations';
