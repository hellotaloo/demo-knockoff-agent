-- Migration: Add scheduled_interviews table
-- Stores interview time slots selected by candidates during voice/WhatsApp screening

CREATE TABLE IF NOT EXISTS scheduled_interviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Core linking (vacancy-centric, not agent-centric)
    vacancy_id UUID NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,

    -- Conversation tracking
    conversation_id TEXT NOT NULL,  -- ElevenLabs conversation_id

    -- Candidate info
    candidate_name TEXT,
    candidate_phone TEXT,

    -- Selected slot details
    selected_date DATE NOT NULL,
    selected_time TEXT NOT NULL,  -- e.g., "10u", "14u"
    selected_slot_text TEXT,  -- Full Dutch text: "maandag 17 februari om 10 uur"

    -- Status tracking
    status TEXT CHECK (status IN ('scheduled', 'confirmed', 'cancelled', 'rescheduled', 'completed', 'no_show')) DEFAULT 'scheduled',

    -- Channel source
    channel TEXT CHECK (channel IN ('voice', 'whatsapp')) DEFAULT 'voice',

    -- Timestamps
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Notes/metadata
    notes TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_vacancy_id
ON scheduled_interviews(vacancy_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_conversation_id
ON scheduled_interviews(conversation_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_application_id
ON scheduled_interviews(application_id)
WHERE application_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_status
ON scheduled_interviews(status);

CREATE INDEX IF NOT EXISTS idx_scheduled_interviews_date
ON scheduled_interviews(selected_date);

-- Prevent duplicate bookings for same conversation
CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduled_interviews_unique_conversation
ON scheduled_interviews(conversation_id)
WHERE status = 'scheduled';
