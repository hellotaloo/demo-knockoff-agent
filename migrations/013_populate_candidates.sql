-- Migration 013: Populate candidates table from existing data
-- Phase 2: Data migration - extract and deduplicate candidate information
--
-- Strategy:
-- 1. Insert candidates from applications (phone as primary key)
-- 2. Update with email from screening_conversations where available
-- 3. Insert candidates with email only (no phone) as fallback

-- Step 1: Insert candidates from applications table
-- Use a CTE to deduplicate by phone, taking the most recent name
WITH ranked_candidates AS (
    SELECT
        candidate_phone AS phone,
        candidate_name AS full_name,
        split_part(candidate_name, ' ', 1) AS first_name,
        CASE
            WHEN position(' ' IN candidate_name) > 0
            THEN substring(candidate_name FROM position(' ' IN candidate_name) + 1)
            ELSE NULL
        END AS last_name,
        'application' AS source,
        started_at,
        ROW_NUMBER() OVER (PARTITION BY candidate_phone ORDER BY started_at DESC) AS rn
    FROM applications
    WHERE candidate_phone IS NOT NULL
      AND candidate_phone != ''
)
INSERT INTO ats.candidates (phone, full_name, first_name, last_name, source, created_at)
SELECT phone, full_name, first_name, last_name, source, started_at
FROM ranked_candidates
WHERE rn = 1
  AND NOT EXISTS (SELECT 1 FROM ats.candidates c WHERE c.phone = ranked_candidates.phone);

-- Step 2: Update candidates with email from screening_conversations
-- Take the most recent email for each phone number
UPDATE ats.candidates c
SET email = sc.candidate_email
FROM (
    SELECT DISTINCT ON (candidate_phone)
        candidate_phone,
        candidate_email
    FROM screening_conversations
    WHERE candidate_phone IS NOT NULL
      AND candidate_phone != ''
      AND candidate_email IS NOT NULL
      AND candidate_email != ''
    ORDER BY candidate_phone, started_at DESC
) sc
WHERE c.phone = sc.candidate_phone
  AND c.email IS NULL;

-- Step 3: Insert candidates without phone (from screening_conversations with email only)
-- These are candidates who only have email, no phone number
WITH email_only_candidates AS (
    SELECT
        candidate_email AS email,
        candidate_name AS full_name,
        split_part(candidate_name, ' ', 1) AS first_name,
        CASE
            WHEN position(' ' IN candidate_name) > 0
            THEN substring(candidate_name FROM position(' ' IN candidate_name) + 1)
            ELSE NULL
        END AS last_name,
        'application' AS source,
        started_at,
        ROW_NUMBER() OVER (PARTITION BY candidate_email ORDER BY started_at DESC) AS rn
    FROM screening_conversations
    WHERE (candidate_phone IS NULL OR candidate_phone = '')
      AND candidate_email IS NOT NULL
      AND candidate_email != ''
)
INSERT INTO ats.candidates (email, full_name, first_name, last_name, source, created_at)
SELECT email, full_name, first_name, last_name, source, started_at
FROM email_only_candidates
WHERE rn = 1
  AND NOT EXISTS (SELECT 1 FROM ats.candidates c WHERE c.email = email_only_candidates.email);

-- Log migration result
DO $$
DECLARE
    total_candidates INTEGER;
    with_phone INTEGER;
    with_email INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_candidates FROM ats.candidates;
    SELECT COUNT(*) INTO with_phone FROM ats.candidates WHERE phone IS NOT NULL;
    SELECT COUNT(*) INTO with_email FROM ats.candidates WHERE email IS NOT NULL;

    RAISE NOTICE 'Migration 013 complete: % total candidates, % with phone, % with email',
        total_candidates, with_phone, with_email;
END $$;
