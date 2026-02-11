-- Migration 015: Backfill candidate_id references
-- Phase 4: Link existing records to candidates
--
-- Strategy:
-- 1. Link by phone number (primary identifier)
-- 2. Link by email as fallback
-- 3. Link via application relationship for dependent tables

-- Step 1: Link applications to candidates by phone
UPDATE applications a
SET candidate_id = c.id
FROM ats.candidates c
WHERE a.candidate_phone = c.phone
  AND a.candidate_phone IS NOT NULL
  AND a.candidate_phone != ''
  AND a.candidate_id IS NULL;

-- Step 2: Link screening_conversations to candidates by phone
UPDATE screening_conversations sc
SET candidate_id = c.id
FROM ats.candidates c
WHERE sc.candidate_phone = c.phone
  AND sc.candidate_phone IS NOT NULL
  AND sc.candidate_phone != ''
  AND sc.candidate_id IS NULL;

-- Step 3: Link screening_conversations to candidates by email (fallback for those without phone)
UPDATE screening_conversations sc
SET candidate_id = c.id
FROM ats.candidates c
WHERE sc.candidate_email = c.email
  AND (sc.candidate_phone IS NULL OR sc.candidate_phone = '')
  AND sc.candidate_email IS NOT NULL
  AND sc.candidate_email != ''
  AND sc.candidate_id IS NULL;

-- Step 4: Link scheduled_interviews to candidates by phone
UPDATE scheduled_interviews si
SET candidate_id = c.id
FROM ats.candidates c
WHERE si.candidate_phone = c.phone
  AND si.candidate_phone IS NOT NULL
  AND si.candidate_phone != ''
  AND si.candidate_id IS NULL;

-- Step 5: Link scheduled_interviews via application (fallback)
-- If scheduled_interview has application_id, inherit candidate_id from application
UPDATE scheduled_interviews si
SET candidate_id = a.candidate_id
FROM applications a
WHERE si.application_id = a.id
  AND si.candidate_id IS NULL
  AND a.candidate_id IS NOT NULL;

-- Step 6: Link document_collection_conversations to candidates by phone
UPDATE document_collection_conversations dcc
SET candidate_id = c.id
FROM ats.candidates c
WHERE dcc.candidate_phone = c.phone
  AND dcc.candidate_phone IS NOT NULL
  AND dcc.candidate_phone != ''
  AND dcc.candidate_id IS NULL;

-- Step 7: Link document_collection_conversations via application (fallback)
UPDATE document_collection_conversations dcc
SET candidate_id = a.candidate_id
FROM applications a
WHERE dcc.application_id = a.id
  AND dcc.candidate_id IS NULL
  AND a.candidate_id IS NOT NULL;

-- Log migration results
DO $$
DECLARE
    apps_linked INTEGER;
    apps_unlinked INTEGER;
    convs_linked INTEGER;
    convs_unlinked INTEGER;
    interviews_linked INTEGER;
    interviews_unlinked INTEGER;
    docs_linked INTEGER;
    docs_unlinked INTEGER;
BEGIN
    SELECT COUNT(*) INTO apps_linked FROM applications WHERE candidate_id IS NOT NULL;
    SELECT COUNT(*) INTO apps_unlinked FROM applications WHERE candidate_id IS NULL;

    SELECT COUNT(*) INTO convs_linked FROM screening_conversations WHERE candidate_id IS NOT NULL;
    SELECT COUNT(*) INTO convs_unlinked FROM screening_conversations WHERE candidate_id IS NULL;

    SELECT COUNT(*) INTO interviews_linked FROM scheduled_interviews WHERE candidate_id IS NOT NULL;
    SELECT COUNT(*) INTO interviews_unlinked FROM scheduled_interviews WHERE candidate_id IS NULL;

    SELECT COUNT(*) INTO docs_linked FROM document_collection_conversations WHERE candidate_id IS NOT NULL;
    SELECT COUNT(*) INTO docs_unlinked FROM document_collection_conversations WHERE candidate_id IS NULL;

    RAISE NOTICE 'Migration 015 complete:';
    RAISE NOTICE '  applications: % linked, % unlinked', apps_linked, apps_unlinked;
    RAISE NOTICE '  screening_conversations: % linked, % unlinked', convs_linked, convs_unlinked;
    RAISE NOTICE '  scheduled_interviews: % linked, % unlinked', interviews_linked, interviews_unlinked;
    RAISE NOTICE '  document_collection_conversations: % linked, % unlinked', docs_linked, docs_unlinked;
END $$;
