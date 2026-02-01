-- Migration: Remove redundant 'completed' boolean column from applications
-- The 'status' column now serves as the single source of truth for workflow state:
--   - 'active': Application started, screening in progress
--   - 'processing': Transcript is being analyzed by AI
--   - 'completed': Screening finished (check 'qualified' for outcome)
--
-- This migration:
-- 1. Ensures data consistency between completed and status
-- 2. Drops the redundant completed column
-- 3. Makes status column NOT NULL

-- Step 1: Ensure all data is synced (status matches completed boolean)
-- Applications with completed=true should have status='completed'
UPDATE applications 
SET status = 'completed' 
WHERE completed = true AND status != 'completed';

-- Applications with completed=false should have status='active' or 'processing'
UPDATE applications 
SET status = 'active' 
WHERE completed = false AND status = 'completed';

-- Step 2: Drop the completed column
ALTER TABLE applications DROP COLUMN IF EXISTS completed;

-- Step 3: Add NOT NULL constraint to status (with default for safety)
ALTER TABLE applications ALTER COLUMN status SET NOT NULL;

-- Step 4: Add comment documenting the status values
COMMENT ON COLUMN applications.status IS 'Workflow state: active (in progress), processing (AI analyzing), completed (finished)';
