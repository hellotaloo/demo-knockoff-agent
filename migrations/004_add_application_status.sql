-- Add status column to applications table
-- Tracks the processing state: active -> processing -> completed

-- Add status column with default 'active' (safer default)
ALTER TABLE applications 
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';

-- Update existing completed applications to have 'completed' status
UPDATE applications SET status = 'completed' WHERE completed = true;

-- Add check constraint for valid status values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'applications_status_check'
    ) THEN
        ALTER TABLE applications 
        ADD CONSTRAINT applications_status_check 
        CHECK (status IN ('active', 'processing', 'completed'));
    END IF;
END $$;

-- Create index for filtering by status
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
