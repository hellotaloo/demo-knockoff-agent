-- Migration: Add document collection tables
-- This enables WhatsApp-based document collection with real-time verification

-- Document collection conversations (similar to screening_conversations)
CREATE TABLE IF NOT EXISTS document_collection_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    vacancy_id UUID REFERENCES vacancies(id) ON DELETE SET NULL,
    session_id TEXT NOT NULL,  -- ADK session ID for state persistence

    candidate_name TEXT NOT NULL,
    candidate_phone TEXT NOT NULL,

    documents_required JSONB DEFAULT '[]'::jsonb,  -- ["id_front", "id_back"]
    retry_count INT DEFAULT 0,  -- Track retry attempts (max 3)

    status TEXT CHECK (status IN ('active', 'completed', 'abandoned', 'needs_review')) DEFAULT 'active',
    message_count INT DEFAULT 0,

    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT unique_active_collection UNIQUE (application_id, status)
        WHERE status = 'active'  -- Only one active collection per application
);

-- Messages in document collection conversations
CREATE TABLE IF NOT EXISTS document_collection_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES document_collection_conversations(id) ON DELETE CASCADE,
    role TEXT CHECK (role IN ('user', 'agent')) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document uploads linked to conversations
CREATE TABLE IF NOT EXISTS document_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES document_collection_conversations(id) ON DELETE CASCADE,
    application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,

    document_side VARCHAR(20) NOT NULL,  -- "id_front", "id_back", "work_permit", etc.
    image_hash TEXT NOT NULL,  -- SHA256 for deduplication

    verification_result JSONB,  -- Full result from document_recognition_agent
    verification_passed BOOLEAN NOT NULL,

    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_document_collection_conversations_application
ON document_collection_conversations(application_id);

CREATE INDEX idx_document_collection_conversations_phone_status
ON document_collection_conversations(candidate_phone, status);

CREATE INDEX idx_document_collection_conversations_session
ON document_collection_conversations(session_id);

CREATE INDEX idx_document_collection_messages_conversation
ON document_collection_messages(conversation_id, created_at);

CREATE INDEX idx_document_uploads_conversation
ON document_uploads(conversation_id);

CREATE INDEX idx_document_uploads_application
ON document_uploads(application_id);

CREATE INDEX idx_document_uploads_image_hash
ON document_uploads(image_hash);

-- Comments for documentation
COMMENT ON TABLE document_collection_conversations IS
'WhatsApp conversations for collecting identity documents from candidates with real-time verification';

COMMENT ON COLUMN document_collection_conversations.retry_count IS
'Number of retry attempts for failed document verifications (max 3 before escalation to manual review)';

COMMENT ON COLUMN document_collection_conversations.documents_required IS
'JSON array of document types needed: ["id_front", "id_back", "work_permit", "medical_certificate"]';

COMMENT ON TABLE document_collection_messages IS
'Chat messages between agent and candidate during document collection';

COMMENT ON TABLE document_uploads IS
'Individual document images uploaded by candidates with verification results from document_recognition_agent';

COMMENT ON COLUMN document_uploads.verification_result IS
'Full JSON result from document verification including: category, extracted_name, fraud_risk, confidence scores';

COMMENT ON COLUMN document_uploads.image_hash IS
'SHA256 hash of original image bytes for detecting duplicate uploads';
