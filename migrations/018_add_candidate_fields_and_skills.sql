-- Migration 018: Add candidate status, availability, rating fields and skills table
--
-- This migration:
-- 1. Adds status, availability, and rating columns to ats.candidates
-- 2. Creates ats.candidate_skills table for ESCO skill tracking

-- ============================================================================
-- PART 1: Add new columns to ats.candidates
-- ============================================================================

-- Status tracking
ALTER TABLE ats.candidates
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'new';

ALTER TABLE ats.candidates
ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ DEFAULT NOW();

-- Availability tracking
ALTER TABLE ats.candidates
ADD COLUMN IF NOT EXISTS availability VARCHAR(20) DEFAULT 'unknown';

ALTER TABLE ats.candidates
ADD COLUMN IF NOT EXISTS available_from DATE;

-- Recruiter rating (e.g., 4.5)
ALTER TABLE ats.candidates
ADD COLUMN IF NOT EXISTS rating DECIMAL(2,1);

-- Comments
COMMENT ON COLUMN ats.candidates.status IS 'Candidate status: new, qualified, active, placed, inactive';
COMMENT ON COLUMN ats.candidates.status_updated_at IS 'When status was last changed';
COMMENT ON COLUMN ats.candidates.availability IS 'Availability status: available, unavailable, unknown';
COMMENT ON COLUMN ats.candidates.available_from IS 'Date when candidate becomes available (NULL = immediate)';
COMMENT ON COLUMN ats.candidates.rating IS 'Recruiter-assigned rating (0.0 - 5.0)';

-- Index for filtering by status
CREATE INDEX IF NOT EXISTS idx_candidates_status
ON ats.candidates(status);

-- Index for filtering by availability
CREATE INDEX IF NOT EXISTS idx_candidates_availability
ON ats.candidates(availability);

-- ============================================================================
-- PART 2: Create candidate_skills table
-- ============================================================================

CREATE TABLE IF NOT EXISTS ats.candidate_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID NOT NULL REFERENCES ats.candidates(id) ON DELETE CASCADE,

    -- Skill identification
    skill_name VARCHAR(255) NOT NULL,
    skill_code VARCHAR(50),                    -- Optional ESCO code for future use
    skill_category VARCHAR(50),                -- skills, education, certificates, personality

    -- Scoring from JobBERT or manual
    score DECIMAL(3,2),                        -- 0.00 - 1.00
    evidence TEXT,                             -- Source text that matched the skill

    -- Source tracking
    source VARCHAR(50) DEFAULT 'manual',       -- cv_analysis, manual, screening, import

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- One entry per skill per candidate
    UNIQUE(candidate_id, skill_name)
);

-- Comments
COMMENT ON TABLE ats.candidate_skills IS 'Candidate skills extracted from CV analysis (JobBERT/ESCO) or manually added';
COMMENT ON COLUMN ats.candidate_skills.skill_name IS 'Skill name (e.g., "manage warehouse operations")';
COMMENT ON COLUMN ats.candidate_skills.skill_code IS 'Optional ESCO skill code for standardization';
COMMENT ON COLUMN ats.candidate_skills.skill_category IS 'Category: skills, education, certificates, personality';
COMMENT ON COLUMN ats.candidate_skills.score IS 'Confidence score from JobBERT (0.00-1.00) or NULL for manual';
COMMENT ON COLUMN ats.candidate_skills.evidence IS 'Text from CV/screening that matched this skill';
COMMENT ON COLUMN ats.candidate_skills.source IS 'How skill was added: cv_analysis, manual, screening, import';

-- Index for candidate skill lookups
CREATE INDEX IF NOT EXISTS idx_candidate_skills_candidate_id
ON ats.candidate_skills(candidate_id);

-- Index for skill name searches
CREATE INDEX IF NOT EXISTS idx_candidate_skills_skill_name
ON ats.candidate_skills(skill_name);

-- Index for category filtering
CREATE INDEX IF NOT EXISTS idx_candidate_skills_category
ON ats.candidate_skills(skill_category)
WHERE skill_category IS NOT NULL;

-- ============================================================================
-- PART 3: Create backwards-compatibility view
-- ============================================================================

-- Update the public.candidates view to include new columns
CREATE OR REPLACE VIEW public.candidates AS SELECT * FROM ats.candidates;
CREATE OR REPLACE VIEW public.candidate_skills AS SELECT * FROM ats.candidate_skills;
