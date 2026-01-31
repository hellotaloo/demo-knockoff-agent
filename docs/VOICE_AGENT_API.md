# Voice Agent API - ElevenLabs Integration

Outbound voice call screening using ElevenLabs Conversational AI + Twilio.

## Overview

The Voice Agent enables automated phone call screenings in Dutch. The system:
1. Creates an ElevenLabs conversational AI agent with a screening interview script
2. Initiates outbound calls via Twilio to candidate phone numbers
3. Conducts the screening interview automatically

## Prerequisites

Before using the Voice Agent API, you need:

1. **ElevenLabs Account** with API access
   - Get API key from: https://elevenlabs.io/app/settings/api-keys

2. **Twilio Account** (free trial works)
   - Sign up at: https://www.twilio.com/try-twilio

3. **Verified Phone Number** in Twilio + ElevenLabs (see setup below)

4. **Environment Variables** configured:
   ```bash
   ELEVENLABS_API_KEY=your-elevenlabs-api-key
   ELEVENLABS_PHONE_NUMBER_ID=your-imported-twilio-phone-id
   ```

## Quick Setup (Verified Caller ID - Outbound Only)

This is the fastest way to test outbound calls using your own phone number.

### Step 1: Verify Your Number in Twilio

1. Log into [Twilio Console](https://console.twilio.com)
2. Go to **Phone Numbers** → **Manage** → **Verified Caller IDs**
3. Click **Add a new Caller ID**
4. Enter your mobile number and verify via SMS or call
5. Copy your **Account SID** and **Auth Token** from the dashboard

### Step 2: Import into ElevenLabs

1. Go to [ElevenLabs Phone Numbers](https://elevenlabs.io/app/conversational-ai/phone-numbers)
2. Click **Import Phone Number**
3. Fill in:
   - **Label**: "My Test Number" (or any name)
   - **Phone Number**: Your verified number (e.g., +31612345678)
   - **Twilio SID**: Your Account SID
   - **Twilio Token**: Your Auth Token
4. Click **Import**
5. Copy the **phone_number_id** shown after import

### Step 3: Configure Environment

Add to your `.env` file:
```bash
ELEVENLABS_API_KEY=xi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ELEVENLABS_PHONE_NUMBER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### Step 4: Test the Call

```bash
curl -X POST http://localhost:8080/voice/call \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+31612345678", "candidate_name": "Test"}'
```

Your phone should ring within seconds!

## Endpoints

### Initiate Voice Call

```
POST /voice/call
Content-Type: application/json
```

**Request Body:**
```json
{
  "phone_number": "+31612345678",
  "candidate_name": "Jan"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `phone_number` | string | Yes | Phone number in E.164 format |
| `candidate_name` | string | No | Candidate name for personalization |

**Response (Success):**
```json
{
  "success": true,
  "message": "Call initiated successfully",
  "conversation_id": "abc123-conversation-id",
  "call_sid": "CA1234567890abcdef"
}
```

**Response (Error):**
```json
{
  "detail": "ELEVENLABS_API_KEY environment variable is required"
}
```

### Get Voice Agent Info

```
GET /voice/agent
```

Returns information about the current screening agent.

**Response:**
```json
{
  "agent_id": "abc123-agent-id",
  "agent_name": "taloo-screening-nl",
  "language": "nl",
  "status": "ready"
}
```

## Interview Script

The default Dutch screening script includes:

### Knockout Questions (Required)
1. "Heb je een geldige werkvergunning voor Nederland?"
2. "Ben je beschikbaar om binnen 2 weken te starten?"
3. "Kun je in ploegendienst werken?"

If any knockout question is answered negatively, the call ends politely.

### Qualification Questions
1. "Kun je kort vertellen over je relevante werkervaring?"
2. "Wat trekt je aan in deze functie?"

### Closing
After successful screening, the agent informs the candidate that a recruiter will follow up within 2 business days.

## Code Examples

### Python

```python
import requests

# Initiate a call
response = requests.post(
    "http://localhost:8080/voice/call",
    json={
        "phone_number": "+31612345678",
        "candidate_name": "Jan"
    }
)

result = response.json()
print(f"Call initiated: {result['conversation_id']}")
```

### JavaScript

```javascript
async function initiateVoiceCall(phoneNumber, candidateName) {
  const response = await fetch('/voice/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      phone_number: phoneNumber,
      candidate_name: candidateName,
    }),
  });
  
  const result = await response.json();
  
  if (result.success) {
    console.log('Call initiated:', result.conversation_id);
    return result;
  } else {
    throw new Error(result.detail || 'Failed to initiate call');
  }
}

// Usage
initiateVoiceCall('+31612345678', 'Jan')
  .then(result => console.log('Success:', result))
  .catch(error => console.error('Error:', error));
```

### cURL

```bash
# Initiate a voice call
curl -X POST http://localhost:8080/voice/call \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+31612345678", "candidate_name": "Jan"}'

# Get agent info
curl http://localhost:8080/voice/agent
```

## Error Handling

| Status | Error | Cause | Solution |
|--------|-------|-------|----------|
| 500 | `ELEVENLABS_API_KEY required` | Missing API key | Set environment variable |
| 500 | `ELEVENLABS_PHONE_NUMBER_ID required` | Missing phone ID | Import Twilio number to ElevenLabs |
| 500 | `Failed to initiate call` | API error | Check ElevenLabs dashboard for details |

## Phone Number Format

Phone numbers should be in E.164 format:
- Netherlands: `+31612345678`
- Belgium: `+32412345678`
- Germany: `+4915123456789`

The API will automatically add a `+` prefix if missing.

## Monitoring Calls

After initiating a call, you can monitor it in:
1. **ElevenLabs Dashboard**: https://elevenlabs.io/app/conversational-ai/history
2. **Twilio Console**: Using the `call_sid` from the response

## Cost Considerations

ElevenLabs charges based on:
- Minutes of voice generation
- API calls

See: https://elevenlabs.io/pricing/api

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Your Backend   │────>│   ElevenLabs     │────>│   Twilio    │
│  POST /voice/   │     │   Agents API     │     │   Voice     │
│     call        │     │                  │     │   Gateway   │
└─────────────────┘     └──────────────────┘     └──────┬──────┘
                                                        │
                                                        v
                                               ┌─────────────────┐
                                               │   Candidate     │
                                               │   Phone         │
                                               └─────────────────┘
```

## Future Enhancements

Planned improvements:
- Dynamic interview scripts based on vacancy pre-screening config
- Call recording and transcription storage
- Webhook for call completion events
- Batch calling for multiple candidates
