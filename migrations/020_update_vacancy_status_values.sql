-- Migration: Update vacancy status values
-- Old: new, draft, in_progress, agent_created, screening_active, archived
-- New: concept, open, on_hold, filled, closed

-- 1. Drop the old check constraint
ALTER TABLE ats.vacancies DROP CONSTRAINT IF EXISTS vacancies_status_check;

-- 2. Map old status values to new ones
UPDATE ats.vacancies SET status = 'concept' WHERE status IN ('new', 'draft');
UPDATE ats.vacancies SET status = 'open' WHERE status IN ('in_progress', 'agent_created', 'screening_active');
UPDATE ats.vacancies SET status = 'closed' WHERE status = 'archived';

-- 3. Add new check constraint with new values
ALTER TABLE ats.vacancies ADD CONSTRAINT vacancies_status_check
CHECK (status IN ('concept', 'open', 'on_hold', 'filled', 'closed'));

-- 4. Add comment documenting the new values
COMMENT ON COLUMN ats.vacancies.status IS 'Vacancy lifecycle status: concept, open, on_hold, filled, closed';
