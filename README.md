# Taloo Agent Demo

Google ADK-powered agents for candidate screening and interview generation.

## Agents

| Agent | Purpose | Interface |
|-------|---------|-----------|
| `pre_screening_whatsapp_agent` | WhatsApp candidate screening | Twilio webhook |
| `interview_generator` | Generate interview questions from vacancy text | REST API + SSE |

## Prerequisites

- Python 3.10+
- Google API Key (for Gemini)
- Twilio account (for WhatsApp - optional)
- Supabase PostgreSQL (for session persistence)
- Google Cloud CLI (for deployment)

## Local Development

### 1. Setup Environment

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and add your keys:
# - GOOGLE_API_KEY: https://aistudio.google.com/apikey
# - DATABASE_URL: Supabase connection string
# - TWILIO_*: Optional, for WhatsApp
```

#### Using Staging Environment

The project includes a staging environment with a separate Supabase database branch:

```bash
# Production environment (default)
cp .env.example .env
# Edit .env with production credentials

# Staging environment
# The .env.staging file is pre-configured with staging database
# You need to update the DATABASE_URL with your staging database password

# Get the password from: Supabase Dashboard > Staging Branch > Settings > Database
# Replace YOUR_STAGING_DB_PASSWORD in .env.staging

# Run with staging environment
# Option 1: Rename files
mv .env .env.production
mv .env.staging .env

# Option 2: Use environment variable
export $(cat .env.staging | xargs) && uvicorn app:app --reload --port 8080
```

**Environment Details:**
- Production Project ID: `szascstjqkmssauvfaaj`
- Staging Project ID: `svebhvifkcxrsbpxjptr`
- Staging URL: `https://svebhvifkcxrsbpxjptr.supabase.co`

### 3. Start the Backend API

```bash
source .venv/bin/activate
uvicorn app:app --reload --port 8080
```

The API is now available at `http://localhost:8080`.

**Test endpoints:**

```bash
# Health check
curl http://localhost:8080/health

# Generate interview questions (SSE stream)
curl -X POST http://localhost:8080/interview/generate \
  -H "Content-Type: application/json" \
  -d '{"vacancy_text": "Productieoperator 2 ploegen in regio Diest."}'
```

### 4. Test with ADK Web UI

For interactive agent testing:

```bash
source .venv/bin/activate
adk web --port 8001
```

Open http://localhost:8001 - select `interview_generator`.

### 5. Test WhatsApp & Voice Webhooks Locally

For testing webhooks from Twilio (WhatsApp) and ElevenLabs (Voice) on your local machine:

#### Quick Start (Recommended)
```bash
# Automated setup - starts ngrok tunnel and backend
./start-local-dev.sh
```

This script will:
1. Start ngrok tunnel on port 8080
2. Display the webhook URLs you need to configure
3. Start the FastAPI backend with auto-reload

#### Manual Setup
```bash
# Terminal 1: Start ngrok
ngrok http 8080

# Terminal 2: Start backend
uvicorn app:app --reload --port 8080
```

#### Configure Webhooks

After starting ngrok, update these URLs (replace `YOUR_NGROK_URL` with the URL shown):

**Twilio (WhatsApp):**
- Console: [Twilio Messaging](https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox)
- Webhook URL: `https://YOUR_NGROK_URL/webhook`
- Method: POST

**ElevenLabs (Voice):**
- Console: [ElevenLabs Agents](https://elevenlabs.io/app/conversational-ai)
- Post-call webhook: `https://YOUR_NGROK_URL/webhook/elevenlabs`

**Note:** ngrok URLs change on each restart unless you use a paid plan with a fixed subdomain.

#### Troubleshooting Local Testing

**Problem:** Webhooks hitting production while testing locally

If your local backend can't find conversations created via test buttons:
1. Verify your `.env` file points to the correct database (not production)
2. Check that Twilio/ElevenLabs webhooks point to your ngrok URL (not production)
3. Restart backend after changing `.env` to ensure new configuration is loaded

```bash
# Check which database you're connected to
cat .env | grep SUPABASE_URL

# Should show your local/staging URL, not production
```

## Interview Generator API

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/interview/generate` | Generate questions from vacancy (SSE stream) |
| POST | `/interview/feedback` | Process feedback on questions (SSE stream) |
| GET | `/interview/session/{id}` | Get current session state |

### SSE Events

```
data: {"type": "status", "status": "thinking", "message": "Vacature analyseren..."}
data: {"type": "status", "status": "tool_call", "message": "Vragen genereren..."}
data: {"type": "complete", "message": "...", "interview": {...}, "session_id": "uuid"}
data: [DONE]
```

See [docs/FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md) for full API documentation.

## Deploy to Cloud Run

### 1. Authenticate

```bash
gcloud auth login
```

### 2. Deploy

```bash
gcloud run deploy taloo-agent --source . --region europe-west1 --allow-unauthenticated
```

**Production URL:** `https://taloo-agent-182581851450.europe-west1.run.app`

### 3. Verify Deployment

```bash
curl https://taloo-agent-182581851450.europe-west1.run.app/health
```

### 4. Configure Twilio (Optional)

1. Go to [Twilio Console](https://console.twilio.com/) > Messaging > WhatsApp Sandbox
2. Set the webhook URL to: `https://taloo-agent-182581851450.europe-west1.run.app/webhook`
3. Set HTTP method to POST

## Project Structure

```
.
├── pre_screening_whatsapp_agent/
│   ├── __init__.py
│   └── agent.py              # WhatsApp screening agent (code-controlled flow)
├── interview_generator/
│   ├── __init__.py
│   └── agent.py              # Interview question generator agent
├── docs/
│   └── FRONTEND_INTEGRATION.md   # Frontend integration guide
├── app.py                    # FastAPI server (webhooks + API)
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## Architecture

```
WhatsApp User
     │
     ▼
Twilio API ──POST /webhook──► Cloud Run (FastAPI)
     ▲                              │
     │                              ▼
     │                        ADK Runner
     │                              │
     │                              ▼
     │                        whatsapp_agent
     │                              │
     │                              ▼
     └──────TwiML response────  Gemini 2.0 Flash
```

## Customizing the Agent

The WhatsApp screening agent uses a code-controlled flow pattern. Edit `pre_screening_whatsapp_agent/agent.py` to customize the behavior. The agent uses Python code to manage conversation flow, with the LLM only generating conversational responses.

## Resources

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [Twilio WhatsApp API](https://www.twilio.com/docs/whatsapp)
- [Google Cloud Run](https://cloud.google.com/run/docs)


