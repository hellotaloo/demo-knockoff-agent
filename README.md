# ADK WhatsApp Agent

A Google ADK-powered WhatsApp agent using Twilio, deployable to Google Cloud Run.

## Prerequisites

- Python 3.10+
- Google API Key (for Gemini)
- Twilio account with WhatsApp Sandbox or Business API
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

# Edit .env and add your API key
# Get your key from: https://aistudio.google.com/apikey
```

### 3. Test with ADK Web UI

Use the built-in ADK web interface to test your agent locally:

```bash
adk web knockout_agent
```

Open http://localhost:8000 in your browser.

### 4. Test Webhook Locally

To test the Twilio webhook integration:

```bash
# Start the FastAPI server
uvicorn app:app --reload --port 8080

# In another terminal, expose via ngrok
ngrok http 8080
```

Then configure the ngrok URL as your Twilio webhook.

## Deploy to Cloud Run

### 1. Deploy

```bash
gcloud run deploy whatsapp-agent \
  --source . \
  --region us-central1 \
  --set-env-vars GOOGLE_API_KEY=your-api-key \
  --allow-unauthenticated
```

### 2. Configure Twilio

1. Go to [Twilio Console](https://console.twilio.com/) > Messaging > WhatsApp Sandbox
2. Set the webhook URL to: `https://your-cloud-run-url/webhook`
3. Set HTTP method to POST

## Project Structure

```
.
├── knockout_agent/
│   ├── __init__.py
│   └── agent.py          # Agent definition
├── app.py                # FastAPI webhook server
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .env.example
├── .gitignore
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
