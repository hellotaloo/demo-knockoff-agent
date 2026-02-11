# CLAUDE.md - Taloo Backend

## Project Overview

Taloo Backend is an AI-powered recruitment screening platform built with Python/FastAPI and Google ADK. It automates candidate screening through WhatsApp, voice calls, and CV analysis using Gemini 2.0 Flash LLM.

## Tech Stack

- **Framework**: FastAPI (async REST API)
- **Python**: 3.11+
- **AI/Agents**: Google ADK with Gemini 2.0 Flash
- **Database**: PostgreSQL (Supabase) with asyncpg
- **Voice**: ElevenLabs API
- **Messaging**: Twilio (WhatsApp)
- **Server**: Uvicorn (ASGI)

## Project Structure

```
taloo-backend/
├── src/                      # Main application code
│   ├── config.py             # Environment config, constants
│   ├── database.py           # DB pool, migrations
│   ├── dependencies.py       # FastAPI dependency injection
│   ├── exceptions.py         # Custom error handling
│   ├── models/               # Pydantic schemas
│   ├── repositories/         # Data access layer
│   ├── services/             # Business logic layer
│   ├── routers/              # API endpoints (15 routers)
│   └── utils/                # Helper functions
├── tests/                    # Test files
├── migrations/               # Database migrations
├── fixtures/                 # Demo data for seeding
├── docs/                     # API documentation
└── app.py                    # FastAPI app entrypoint
```

## Key Patterns

- **Service-Repository Pattern**: Services handle business logic, repositories handle data access
- **ADK Session Management**: SessionManager caches runners, DatabaseSessionService persists to PostgreSQL
- **Dependency Injection**: Via FastAPI `Depends()` in `src/dependencies.py`
- **SSE Streaming**: Interview generation uses Server-Sent Events

## Common Commands

```bash
# Start local development
source .venv/bin/activate
uvicorn app:app --reload --port 8080

# Start with ngrok for webhook testing
./start-local-dev.sh

# ADK web UI for agent testing
adk web --port 8001

# Run Python scripts
python <script.py>

# Deploy to Cloud Run
gcloud run deploy taloo-agent --source . --region europe-west1

# Git operations
git status
git add <files>
git commit -m "message"
git push
```

## Environment Variables

Required in `.env`:
- `DATABASE_URL` - Supabase PostgreSQL connection
- `GOOGLE_API_KEY` - Gemini API key
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER`
- `ELEVENLABS_API_KEY`, `ELEVENLABS_WEBHOOK_SECRET`
- `ENVIRONMENT` - production|staging|development

## Code Style

- Ruff linter (line length 120)
- Double quotes for strings
- 4-space indentation
- Services: `*Service`, Repositories: `*Repository`
- All user-facing content in Dutch (Flemish nl-BE)

## Agents

All agents are Google ADK agents using Gemini models.

### Core Agents
1. **Interview Generator** (`interview_generator/agent.py`) - Generates knockout + qualification questions from vacancy text
2. **Knockout Agent** (`knockout_agent/agent.py`) - WhatsApp screening conversations
3. **Voice Agent** (`voice_agent/agent.py`) - ElevenLabs phone screening with Dutch prompts

### Specialized Agents
4. **CV Analyzer** (`cv_analyzer/agent.py`) - CV analysis and parsing via Gemini
5. **Document Collection Agent** (`document_collection_agent/agent.py`) - Document upload conversations
6. **Document Recognition Agent** (`document_recognition_agent/agent.py`) - ID document verification
7. **Transcript Processor** (`transcript_processor/agent.py`) - Call transcript processing
8. **Candidate Simulator** (`candidate_simulator/agent.py`) - Testing/simulation persona
9. **Data Query Agent** (`data_query_agent/agent.py`) - Database queries via natural language
10. **Recruiter Analyst** (`recruiter_analyst/agent.py`) - Recruitment analytics and insights

## API Endpoints

- `POST /interview/generate` - Generate interview questions (SSE)
- `POST /interview/feedback` - Apply feedback to interview (SSE)
- `POST /webhook` - Twilio WhatsApp webhook
- `POST /webhook/elevenlabs` - ElevenLabs post-call webhook
- `POST /outbound/call` - Initiate phone screening
- `POST /cv/analyze` - CV analysis via Gemini
- `GET /health` - Health check

## Database

PostgreSQL with 25+ migrations in `migrations/`. Schema auto-runs on startup via `run_schema_migrations()`.

### Supabase Branching

**IMPORTANT**: Always apply migrations to the **staging** branch, not production!

| Branch | Project Ref | Use For |
|--------|-------------|---------|
| main (production) | `szascstjqkmssauvfaaj` | Production data - DO NOT modify directly |
| staging | `svebhvifkcxrsbpxjptr` | Development and testing - apply migrations here |

When using the Supabase MCP tools, always use `project_id: svebhvifkcxrsbpxjptr` for migrations.

## When Making Changes

- Always use async/await for database and external API calls
- Add new routers to `src/routers/__init__.py` and register in `app.py`
- Keep prompts/instructions in Dutch for user-facing content
- Use Pydantic models for request/response validation
- **IMPORTANT**: After adding/modifying/removing API endpoints, always update `docs/API_CONTRACT.md` to reflect the changes
