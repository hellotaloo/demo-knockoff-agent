-- Migration 027: Rename candidate_activities to agent_activities
-- The table stores all system activities (agent, recruiter, candidate, system actions),
-- not just candidate activities. The name agent_activities better reflects its purpose.

-- Rename the table
ALTER TABLE IF EXISTS ats.candidate_activities RENAME TO agent_activities;

-- Update table comment
COMMENT ON TABLE ats.agent_activities IS 'Unified activity log for agent actions, candidate interactions, and recruiter actions';

-- Rename indexes to match new table name
ALTER INDEX IF EXISTS idx_candidate_activities_timeline RENAME TO idx_agent_activities_timeline;
ALTER INDEX IF EXISTS idx_candidate_activities_event_type RENAME TO idx_agent_activities_event_type;
ALTER INDEX IF EXISTS idx_candidate_activities_application RENAME TO idx_agent_activities_application;
ALTER INDEX IF EXISTS idx_candidate_activities_vacancy RENAME TO idx_agent_activities_vacancy;
ALTER INDEX IF EXISTS idx_candidate_activities_actor RENAME TO idx_agent_activities_actor;
