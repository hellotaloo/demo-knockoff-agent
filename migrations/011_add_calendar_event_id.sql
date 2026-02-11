-- Migration: Add calendar_event_id to scheduled_interviews
-- Allows proper calendar event lifecycle management (create, update, cancel)

ALTER TABLE scheduled_interviews
ADD COLUMN IF NOT EXISTS calendar_event_id TEXT;

-- Index for looking up by calendar event
CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_calendar_event_id
ON scheduled_interviews(calendar_event_id)
WHERE calendar_event_id IS NOT NULL;
