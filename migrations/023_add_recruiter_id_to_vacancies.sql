-- Migration: Add recruiter_id foreign key to vacancies table

-- Add recruiter_id column to vacancies table
ALTER TABLE ats.vacancies ADD COLUMN IF NOT EXISTS recruiter_id UUID REFERENCES ats.recruiters(id);

-- Add index for efficient joins
CREATE INDEX IF NOT EXISTS idx_vacancies_recruiter_id ON ats.vacancies(recruiter_id);

-- Add comment
COMMENT ON COLUMN ats.vacancies.recruiter_id IS 'Foreign key to the recruiter who owns this vacancy';
