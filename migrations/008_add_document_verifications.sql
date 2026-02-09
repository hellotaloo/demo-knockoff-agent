-- Migration: Add document_verifications table for audit trail
-- This table stores verification results for identity documents and certificates
-- with fraud detection results for compliance and analytics purposes

CREATE TABLE IF NOT EXISTS document_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Linking
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
    vacancy_id UUID REFERENCES vacancies(id) ON DELETE SET NULL,

    -- Document classification
    document_category VARCHAR(50) NOT NULL,
    document_category_confidence DECIMAL(3,2) NOT NULL,

    -- Name extraction and verification
    extracted_name TEXT,
    name_extraction_confidence DECIMAL(3,2),
    expected_candidate_name TEXT,
    name_match_result VARCHAR(20),  -- exact_match, partial_match, no_match, ambiguous
    name_match_confidence DECIMAL(3,2),
    name_match_details TEXT,

    -- Fraud detection
    fraud_risk_level VARCHAR(10) NOT NULL,  -- low, medium, high
    fraud_indicators JSONB DEFAULT '[]'::jsonb,
    overall_fraud_confidence DECIMAL(3,2) NOT NULL,

    -- Quality assessment
    image_quality VARCHAR(20) NOT NULL,
    readability_issues JSONB DEFAULT '[]'::jsonb,

    -- Outcome
    verification_passed BOOLEAN NOT NULL,
    verification_summary TEXT NOT NULL,

    -- Metadata
    image_hash TEXT,  -- SHA256 of image for deduplication
    verified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    verified_by VARCHAR(100) DEFAULT 'system',  -- user ID if manually triggered

    -- Audit
    raw_agent_response TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_document_verifications_application_id
ON document_verifications(application_id);

CREATE INDEX idx_document_verifications_vacancy_id
ON document_verifications(vacancy_id);

CREATE INDEX idx_document_verifications_fraud_risk
ON document_verifications(fraud_risk_level);

CREATE INDEX idx_document_verifications_verified_at
ON document_verifications(verified_at DESC);

CREATE INDEX idx_document_verifications_image_hash
ON document_verifications(image_hash)
WHERE image_hash IS NOT NULL;

-- Comments for documentation
COMMENT ON TABLE document_verifications IS
'Audit trail of document verification requests with fraud detection results';

COMMENT ON COLUMN document_verifications.fraud_indicators IS
'Array of fraud indicator objects with type, description, severity, confidence';

COMMENT ON COLUMN document_verifications.image_hash IS
'SHA256 hash of original image for detecting duplicate submissions';

COMMENT ON COLUMN document_verifications.document_category IS
'Document type: driver_license, medical_certificate, work_permit, certificate_diploma, unknown, unreadable';

COMMENT ON COLUMN document_verifications.fraud_risk_level IS
'Overall fraud risk: low (authentic), medium (review needed), high (likely fake)';

COMMENT ON COLUMN document_verifications.image_quality IS
'Image quality: excellent, good, acceptable, poor, unreadable';
