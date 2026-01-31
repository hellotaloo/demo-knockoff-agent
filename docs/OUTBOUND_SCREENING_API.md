# Outbound Screening API

Initiate outbound screening conversations with candidates via voice call or WhatsApp.

## Overview

The `/screening/outbound` endpoint is the main entry point for starting screening conversations with candidates. It supports two channels:

- **Voice**: Outbound phone calls using ElevenLabs Conversational AI + Twilio
- **WhatsApp**: Outbound WhatsApp messages using Twilio

Both channels use the vacancy-specific screening agent that was created when the pre-screening was published.

## Prerequisites

### For Voice Calls
- `ELEVENLABS_API_KEY` must be set
- `ELEVENLABS_PHONE_NUMBER_ID` must be set (Twilio number imported to ElevenLabs)
- Pre-screening must be published with `enable_voice=True`

### For WhatsApp
- `TWILIO_ACCOUNT_SID` must be set
- `TWILIO_AUTH_TOKEN` must be set
- `TWILIO_WHATSAPP_NUMBER` must be set
- Pre-screening must be published with `enable_whatsapp=True`

## Endpoint

### Initiate Outbound Screening

```
POST /screening/outbound
Content-Type: application/json
```

**Request Body:**

```json
{
  "vacancy_id": "550e8400-e29b-41d4-a716-446655440000",
  "channel": "voice",
  "phone_number": "+31612345678",
  "candidate_name": "Jan"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `vacancy_id` | string (UUID) | Yes | The vacancy ID to use for screening |
| `channel` | string | Yes | Either `"voice"` or `"whatsapp"` |
| `phone_number` | string | Yes | Phone number in E.164 format (e.g., `+31612345678`) |
| `candidate_name` | string | No | Candidate's name for personalization |

**Response (Voice - Success):**

```json
{
  "success": true,
  "message": "Call initiated successfully",
  "channel": "voice",
  "conversation_id": "conv-abc123",
  "call_sid": "CA1234567890abcdef",
  "whatsapp_message_sid": null
}
```

**Response (WhatsApp - Success):**

```json
{
  "success": true,
  "message": "WhatsApp screening initiated",
  "channel": "whatsapp",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
  "call_sid": null,
  "whatsapp_message_sid": "SM1234567890abcdef"
}
```

**Response (Error):**

```json
{
  "detail": "Pre-screening is not published yet"
}
```

## Error Responses

| Status | Error | Cause |
|--------|-------|-------|
| 400 | `Invalid vacancy ID format` | vacancy_id is not a valid UUID |
| 400 | `No pre-screening configured for this vacancy` | Vacancy has no pre-screening |
| 400 | `Pre-screening is not published yet` | Must publish first |
| 400 | `Pre-screening is offline` | Set online via PATCH status endpoint |
| 400 | `Voice agent not configured` | Publish with `enable_voice=True` |
| 400 | `WhatsApp agent not configured` | Publish with `enable_whatsapp=True` |
| 404 | `Vacancy not found` | Invalid vacancy ID |
| 500 | `ELEVENLABS_API_KEY required` | Missing environment variable |
| 500 | `TWILIO_WHATSAPP_NUMBER not configured` | Missing environment variable |

## Workflow

### 1. Prepare the Pre-Screening

Before using outbound screening, ensure:

1. Create/update pre-screening questions via `PUT /vacancies/{id}/pre-screening`
2. Publish the pre-screening via `POST /vacancies/{id}/pre-screening/publish`
3. Ensure it's online (published sets it online automatically)

### 2. Initiate Outbound Screening

```bash
# Voice call
curl -X POST https://your-api/screening/outbound \
  -H "Content-Type: application/json" \
  -d '{
    "vacancy_id": "550e8400-e29b-41d4-a716-446655440000",
    "channel": "voice",
    "phone_number": "+31612345678",
    "candidate_name": "Jan"
  }'

# WhatsApp message
curl -X POST https://your-api/screening/outbound \
  -H "Content-Type: application/json" \
  -d '{
    "vacancy_id": "550e8400-e29b-41d4-a716-446655440000",
    "channel": "whatsapp",
    "phone_number": "+31612345678",
    "candidate_name": "Jan"
  }'
```

### 3. Monitor the Conversation

- **Voice**: Monitor in ElevenLabs dashboard or via `call_sid` in Twilio console
- **WhatsApp**: Use `/vacancies/{id}/conversations` to list conversations, `/screening/conversations/{id}` for details

## Code Examples

### Python

```python
import requests

# Initiate a voice call screening
response = requests.post(
    "https://your-api/screening/outbound",
    json={
        "vacancy_id": "550e8400-e29b-41d4-a716-446655440000",
        "channel": "voice",
        "phone_number": "+31612345678",
        "candidate_name": "Jan"
    }
)

result = response.json()
if result["success"]:
    print(f"Call initiated: {result['call_sid']}")
else:
    print(f"Error: {result.get('detail')}")
```

### JavaScript

```javascript
async function initiateScreening(vacancyId, channel, phoneNumber, candidateName) {
  const response = await fetch('/screening/outbound', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      vacancy_id: vacancyId,
      channel: channel,  // 'voice' or 'whatsapp'
      phone_number: phoneNumber,
      candidate_name: candidateName,
    }),
  });
  
  const result = await response.json();
  
  if (result.success) {
    console.log(`${channel} screening initiated:`, result.conversation_id);
    return result;
  } else {
    throw new Error(result.detail || 'Failed to initiate screening');
  }
}

// Usage
initiateScreening(
  '550e8400-e29b-41d4-a716-446655440000',
  'whatsapp',
  '+31612345678',
  'Jan'
);
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    POST /screening/outbound                         │
│                    {vacancy_id, channel, phone, name}               │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Lookup Vacancy │
                    │ & Pre-Screening│
                    └───────┬───────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
    ┌─────────────────┐         ┌─────────────────┐
    │ channel="voice" │         │channel="whatsapp"│
    └────────┬────────┘         └────────┬────────┘
             │                           │
             ▼                           ▼
    ┌─────────────────┐         ┌─────────────────┐
    │   ElevenLabs    │         │     Twilio      │
    │  Outbound Call  │         │    WhatsApp     │
    │  (agent_id)     │         │    Message      │
    └────────┬────────┘         └────────┬────────┘
             │                           │
             ▼                           ▼
    ┌─────────────────┐         ┌─────────────────┐
    │  Twilio Voice   │         │   Candidate's   │
    │    Gateway      │         │    WhatsApp     │
    └────────┬────────┘         └─────────────────┘
             │
             ▼
    ┌─────────────────┐
    │   Candidate's   │
    │     Phone       │
    └─────────────────┘
```

## Phone Number Format

Phone numbers should be in E.164 format:
- Netherlands: `+31612345678`
- Belgium: `+32412345678`
- Germany: `+4915123456789`

The API will automatically add a `+` prefix if missing.

## Legacy Endpoint

The old `/voice/call` endpoint is deprecated but still available for backward compatibility. It uses a static default agent instead of vacancy-specific questions.

```
POST /voice/call (deprecated)
```

Use `/screening/outbound` with `channel="voice"` instead.
