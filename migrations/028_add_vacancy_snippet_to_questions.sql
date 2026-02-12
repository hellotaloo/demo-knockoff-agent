-- Add vacancy_snippet column to pre_screening_questions
-- This stores the exact text from the vacancy that the question is based on
-- Used by frontend to visually link questions to their source in the vacancy text

ALTER TABLE ats.pre_screening_questions
ADD COLUMN IF NOT EXISTS vacancy_snippet TEXT;

COMMENT ON COLUMN ats.pre_screening_questions.vacancy_snippet IS 'Exact text snippet from vacancy that this question is derived from - for frontend highlighting';
