-- Migration: Add channel enabled flags to pre_screenings
-- These flags allow toggling channels on/off independently of agent configuration

-- Add channel enabled columns with defaults
-- voice_enabled and whatsapp_enabled default to TRUE so existing pre-screenings with agents remain enabled
-- All channels default to FALSE - must be explicitly enabled

ALTER TABLE pre_screenings 
ADD COLUMN IF NOT EXISTS voice_enabled BOOLEAN DEFAULT FALSE;

ALTER TABLE pre_screenings 
ADD COLUMN IF NOT EXISTS whatsapp_enabled BOOLEAN DEFAULT FALSE;

ALTER TABLE pre_screenings 
ADD COLUMN IF NOT EXISTS cv_enabled BOOLEAN DEFAULT FALSE;

-- Add comments for documentation
COMMENT ON COLUMN pre_screenings.voice_enabled IS 'Whether voice channel is enabled (requires elevenlabs_agent_id to be set)';
COMMENT ON COLUMN pre_screenings.whatsapp_enabled IS 'Whether WhatsApp channel is enabled (requires whatsapp_agent_id to be set)';
COMMENT ON COLUMN pre_screenings.cv_enabled IS 'Whether CV analysis channel is enabled';
