-- Migration: Add client_id foreign key to vacancies table

-- Add client_id column to vacancies table
ALTER TABLE ats.vacancies ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES ats.clients(id);

-- Add index for efficient joins
CREATE INDEX IF NOT EXISTS idx_vacancies_client_id ON ats.vacancies(client_id);

-- Add comment
COMMENT ON COLUMN ats.vacancies.client_id IS 'Foreign key to the client/company this vacancy belongs to';
