-- Migration 017: Create candidate_activities table for timeline tracking
-- This table provides a unified activity log for candidate interactions

CREATE TABLE IF NOT EXISTS ats.candidate_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Core linking
    candidate_id UUID NOT NULL REFERENCES ats.candidates(id) ON DELETE CASCADE,
    application_id UUID REFERENCES ats.applications(id) ON DELETE SET NULL,
    vacancy_id UUID REFERENCES ats.vacancies(id) ON DELETE SET NULL,

    -- Event details
    event_type VARCHAR(50) NOT NULL,
    channel VARCHAR(20),  -- voice, whatsapp, cv, web

    -- Actor information
    actor_type VARCHAR(20) NOT NULL DEFAULT 'system',  -- candidate, agent, recruiter, system
    actor_id TEXT,  -- recruiter user ID if applicable

    -- Flexible payload for event-specific data
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Human-readable summary
    summary TEXT,

    -- Timestamp
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Comments for documentation
COMMENT ON TABLE ats.candidate_activities IS 'Unified activity log for candidate timeline view';
COMMENT ON COLUMN ats.candidate_activities.event_type IS 'Type of activity: screening_started, screening_completed, message_sent, etc.';
COMMENT ON COLUMN ats.candidate_activities.channel IS 'Channel where activity occurred: voice, whatsapp, cv, web';
COMMENT ON COLUMN ats.candidate_activities.actor_type IS 'Who performed the action: candidate, agent, recruiter, system';
COMMENT ON COLUMN ats.candidate_activities.actor_id IS 'User ID of recruiter if actor_type is recruiter';
COMMENT ON COLUMN ats.candidate_activities.metadata IS 'Event-specific data as JSON (e.g., score, status, document_type)';

-- Index for timeline queries (candidate + chronological)
CREATE INDEX IF NOT EXISTS idx_candidate_activities_timeline
ON ats.candidate_activities(candidate_id, created_at DESC);

-- Index for filtering by event type
CREATE INDEX IF NOT EXISTS idx_candidate_activities_event_type
ON ats.candidate_activities(event_type);

-- Index for application-level activity lookup
CREATE INDEX IF NOT EXISTS idx_candidate_activities_application
ON ats.candidate_activities(application_id)
WHERE application_id IS NOT NULL;

-- Index for vacancy-level activity lookup
CREATE INDEX IF NOT EXISTS idx_candidate_activities_vacancy
ON ats.candidate_activities(vacancy_id)
WHERE vacancy_id IS NOT NULL;

-- Index for actor lookups (e.g., "show all recruiter actions")
CREATE INDEX IF NOT EXISTS idx_candidate_activities_actor
ON ats.candidate_activities(actor_type, actor_id)
WHERE actor_id IS NOT NULL;
