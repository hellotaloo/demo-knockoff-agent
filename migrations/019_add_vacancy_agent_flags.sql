-- Migration: Add agent activation flags to vacancies
-- These track which AI agents are enabled for each vacancy

ALTER TABLE ats.vacancies ADD COLUMN IF NOT EXISTS prescreening_agent_enabled BOOLEAN DEFAULT false;
ALTER TABLE ats.vacancies ADD COLUMN IF NOT EXISTS preonboarding_agent_enabled BOOLEAN DEFAULT false;
ALTER TABLE ats.vacancies ADD COLUMN IF NOT EXISTS insights_agent_enabled BOOLEAN DEFAULT false;

-- Set prescreening_agent_enabled = true for vacancies that have a published pre-screening
UPDATE ats.vacancies v
SET prescreening_agent_enabled = true
WHERE EXISTS (
    SELECT 1 FROM ats.pre_screenings ps
    WHERE ps.vacancy_id = v.id AND ps.published_at IS NOT NULL
);

COMMENT ON COLUMN ats.vacancies.prescreening_agent_enabled IS 'Whether the pre-screening AI agent is enabled for this vacancy';
COMMENT ON COLUMN ats.vacancies.preonboarding_agent_enabled IS 'Whether the pre-onboarding AI agent (document collection) is enabled for this vacancy';
COMMENT ON COLUMN ats.vacancies.insights_agent_enabled IS 'Whether the insights AI agent (analytics) is enabled for this vacancy';
