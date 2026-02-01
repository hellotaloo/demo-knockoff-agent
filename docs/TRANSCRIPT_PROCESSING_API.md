# Voice Transcript Processing API

## Overview

This feature enables automatic processing of voice call transcripts from ElevenLabs. When a voice screening call ends, ElevenLabs sends a webhook with the full transcript, which is then analyzed by an AI agent to evaluate the candidate's responses against the pre-screening questions.

## Architecture

```
ElevenLabs Voice Call
        ↓
   Call ends
        ↓
POST /webhook/elevenlabs (post_call_transcription)
        ↓
   Look up pre-screening by agent_id
        ↓
   Retrieve interview questions
        ↓
   Process transcript with AI agent
        ↓
   Store results in application_answers
```

## Webhook Endpoint

### `POST /webhook/elevenlabs`

Receives post-call webhooks from ElevenLabs.

**Headers:**
- `elevenlabs-signature`: HMAC signature for validation (format: `t=timestamp,v0=hash`)

**Request Body (post_call_transcription):**
```json
{
  "type": "post_call_transcription",
  "event_timestamp": 1739537297,
  "data": {
    "agent_id": "abc123",
    "conversation_id": "conv_xyz",
    "status": "done",
    "transcript": [
      {
        "role": "agent",
        "message": "Hallo! Je spreekt met Izy...",
        "time_in_call_secs": 0
      },
      {
        "role": "user",
        "message": "Ja, ik kan binnen 2 weken starten.",
        "time_in_call_secs": 15
      }
    ],
    "metadata": {
      "call_duration_secs": 120
    }
  }
}
```

**Response (200 OK):**
```json
{
  "status": "processed",
  "application_id": "uuid-of-created-application",
  "overall_passed": true,
  "knockout_results": 3,
  "qualification_results": 2,
  "notes": "Candidate passed all knockout questions"
}
```

## Transcript Processing

### Knockout Questions
Knockout questions are evaluated as binary pass/fail:
- **Pass indicators**: "ja", "ja hoor", "jawel", "zeker", "dat klopt", "uiteraard"
- **Fail indicators**: "nee", "helaas niet", "nog niet", "ik heb geen..."

If any knockout question fails, `overall_passed` is `false`.

### Qualification Questions
Qualification questions are scored 0-100 based on how well the candidate's answer matches the `ideal_answer`:
- **0-20**: No relevant answer or strongly deviating
- **21-40**: Minimally relevant, missing important points
- **41-60**: Partially relevant, missing some points
- **61-80**: Good answer, covers most important points
- **81-100**: Excellent answer, meets or exceeds ideal

## Database Schema

### New Columns

**applications table:**
```sql
ALTER TABLE applications 
ADD COLUMN conversation_id TEXT DEFAULT NULL;
```

**application_answers table:**
```sql
ALTER TABLE application_answers 
ADD COLUMN score INTEGER DEFAULT NULL,
ADD COLUMN source TEXT DEFAULT 'chat';
```

- `score`: 0-100 for qualification questions, NULL for knockout
- `source`: 'chat', 'whatsapp', or 'voice'
- `conversation_id`: ElevenLabs conversation ID for voice calls

### Migration

Run the migration in Supabase SQL Editor:
```sql
-- See migrations/001_add_transcript_processing_columns.sql
```

## Configuration

### Environment Variables

```bash
# Required for webhook validation (get from ElevenLabs dashboard)
ELEVENLABS_WEBHOOK_SECRET=your-hmac-secret
```

### ElevenLabs Dashboard Setup

1. Go to [ElevenLabs Agents Settings](https://elevenlabs.io/app/agents/settings)
2. Enable "Post-call webhooks"
3. Set webhook URL: `https://your-domain.com/webhook/elevenlabs`
4. Copy the HMAC secret to `ELEVENLABS_WEBHOOK_SECRET`
5. Enable "Transcription" webhook type

## Security

### HMAC Validation

The webhook validates requests using HMAC-SHA256:

1. Parse `elevenlabs-signature` header: `t=timestamp,v0=hash`
2. Validate timestamp is within 30 minutes
3. Compute HMAC: `sha256(timestamp + "." + body)`
4. Compare with provided hash

If `ELEVENLABS_WEBHOOK_SECRET` is not set, validation is skipped (development mode).

### IP Whitelisting (Optional)

ElevenLabs webhooks originate from these IPs:
- US: 34.67.146.145, 34.59.11.47
- EU: 35.204.38.71, 34.147.113.54

## Usage Flow

1. **Voice call initiated** → Creates `screening_conversations` record with `channel='voice'`
2. **Call in progress** → ElevenLabs handles the conversation
3. **Call ends** → ElevenLabs sends `post_call_transcription` webhook
4. **Webhook received** → Transcript processed by AI agent
5. **Results stored** → `applications` and `application_answers` records created
6. **Conversation updated** → `screening_conversations` status set to 'completed'

## Error Handling

| Error | Response |
|-------|----------|
| Invalid signature | 401 Unauthorized |
| Invalid payload | 400 Bad Request |
| Agent not found | 404 Not Found |
| Processing error | 500 Internal Server Error |

## Related Files

- `transcript_processor/agent.py` - AI agent for transcript analysis
- `app.py` - Webhook endpoint (`/webhook/elevenlabs`)
- `voice_agent/agent.py` - Voice call initiation
- `migrations/001_add_transcript_processing_columns.sql` - Database migration
