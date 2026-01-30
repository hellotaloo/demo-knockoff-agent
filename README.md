# Taloo Agent Demo

Google ADK-powered agents for candidate screening and interview generation.

## Agents

| Agent | Purpose | Interface |
|-------|---------|-----------|
| `knockout_agent` | WhatsApp/Voice candidate screening | Twilio webhook |
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

Open http://localhost:8001 - select `interview_generator` or `knockout_agent`.

### 5. Test WhatsApp Webhook Locally (Optional)

```bash
# Start the FastAPI server
uvicorn app:app --reload --port 8080

# In another terminal, expose via ngrok
ngrok http 8080
```

Then configure the ngrok URL as your Twilio webhook.

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
├── knockout_agent/
│   ├── __init__.py
│   └── agent.py              # WhatsApp screening agent
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

Edit `knockout_agent/agent.py` to customize the agent's behavior:

```python
from google.adk.agents.llm_agent import Agent

root_agent = Agent(
    name="whatsapp_agent",
    model="gemini-2.0-flash",
    instruction="Your custom instructions here...",
    description="Your agent description",
    tools=[],  # Add tools here
)
```

## Adding Tools

You can add custom tools for your agent to use:

```python
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    # Your implementation
    return {"city": city, "temp": "72°F", "condition": "sunny"}

root_agent = Agent(
    name="whatsapp_agent",
    model="gemini-2.0-flash",
    instruction="You are a helpful assistant that can check the weather.",
    description="WhatsApp agent with weather capability",
    tools=[get_weather],
)
```

## Resources

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [Twilio WhatsApp API](https://www.twilio.com/docs/whatsapp)
- [Google Cloud Run](https://cloud.google.com/run/docs)
