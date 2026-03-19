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
├── agents/                   # All AI agents (Google ADK)
│   ├── candidate_simulator/
│   ├── cv_analyzer/
│   ├── database_query/
│   ├── document_collection/
│   │   ├── collection/
│   │   └── recognition/
│   ├── interview_question_generator/
│   ├── pre_screening/
│   │   ├── interview_analyzer/
│   │   ├── transcript_processor/
│   │   ├── voice/
│   │   └── whatsapp/
│   └── recruiter_analyst/
├── src/                      # Main application code
│   ├── config.py             # Environment config, constants
│   ├── database.py           # DB pool, migrations
│   ├── dependencies.py       # FastAPI dependency injection
│   ├── exceptions.py         # Custom error handling
│   ├── models/               # Pydantic schemas
│   ├── repositories/         # Data access layer
│   ├── services/             # Business logic layer
│   ├── routers/              # API endpoints
│   └── utils/                # Helper functions
├── data/                     # Data & fixtures
│   └── fixtures/             # Demo data for seeding
├── tests/                    # Test files
├── scripts/                  # Utility scripts
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
gcloud run deploy taloo-agent --source . --region europe-west1 --project knockoff-bot-demo

# Git operations
git status
git add <files>
git commit -m "message"
git push
```

## Environments

| Environment | Config | Twilio | Database | Deployment |
|-------------|--------|--------|----------|------------|
| **Local** | `.env` file | Sandbox (`+14155238886`) | Local branch | `./start-local-dev.sh` |
| **Staging** | Cloud Run env vars | Production (`+32456820441`) | Main branch | `gcloud run deploy` |

### Environment Variables

Required in `.env` (local development):
- `ENVIRONMENT=local`
- `DATABASE_URL` - Supabase PostgreSQL (local branch)
- `GOOGLE_API_KEY` - Gemini API key
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER` - Sandbox credentials
- `ELEVENLABS_API_KEY`, `ELEVENLABS_WEBHOOK_SECRET`

## Code Style

- Ruff linter (line length 120)
- Double quotes for strings
- 4-space indentation
- Services: `*Service`, Repositories: `*Repository`
- All user-facing content in Dutch (Flemish nl-BE)

## Agents

All agents are Google ADK agents using Gemini models.

### Core Agents
1. **Interview Generator** (`agents/interview_question_generator/agent.py`) - Generates knockout + qualification questions from vacancy text
2. **Pre-screening WhatsApp Agent** (`agents/pre_screening/whatsapp/agent.py`) - WhatsApp screening conversations (code-controlled flow)
3. **Voice Agent** (`agents/pre_screening/voice/`) - Self-contained pre-screening v2 microservice

### Specialized Agents
4. **CV Analyzer** (`agents/cv_analyzer/agent.py`) - CV analysis and parsing via Gemini
5. **Document Collection Agent** (`agents/document_collection/whatsapp/agent.py`) - Document upload conversations
6. **Document Recognition Agent** (`agents/document_collection/recognition/agent.py`) - ID document verification
7. **Transcript Processor** (`agents/pre_screening/transcript_processor/agent.py`) - Call transcript processing
8. **Candidate Simulator** (`agents/candidate_simulator/agent.py`) - Testing/simulation persona
9. **Data Query Agent** (`agents/database_query/agent.py`) - Database queries via natural language
10. **Recruiter Analyst** (`agents/recruiter_analyst/agent.py`) - Recruitment analytics and insights
11. **Interview Analysis** (`agents/pre_screening/interview_analyzer/agent.py`) - Interview quality analysis

## API Endpoints

- `POST /interview/generate` - Generate interview questions (SSE)
- `POST /interview/feedback` - Apply feedback to interview (SSE)
- `POST /webhook` - Twilio WhatsApp webhook
- `POST /webhook/elevenlabs` - ElevenLabs post-call webhook
- `POST /outbound/call` - Initiate phone screening
- `POST /cv/analyze` - CV analysis via Gemini
- `GET /health` - Health check

## Database

PostgreSQL hosted on Supabase. Migrations are managed via **Git** through the Supabase GitHub integration.

### Supabase Projects

| Environment | Project Ref | Use For |
|-------------|-------------|---------|
| **Main** | `beniqwbanoqhxyrjwulg` | Production/staging DB — linked to GitHub |
| **Preview** | Auto-created per PR | Testing migrations before merge |

### Migration Workflow (Git-based)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  NEVER use `apply_migration` via Supabase MCP for DDL changes!              │
│  ALL schema changes go through Git → PR → Merge in the taloo-database repo  │
│                                                                             │
│  Database repo path: /Users/lunar/Desktop/sites/taloo-workspace/taloo-database │
│  Migration files: supabase/migrations/                                      │
│  Remote: https://github.com/hellotaloo/taloo-database.git                   │
│  Production branch: master                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**When schema changes are needed, Claude Code should:**

1. Generate a timestamped migration file directly:
```bash
# Create migration file with timestamp (format: YYYYMMDDHHmmss)
TIMESTAMP=$(date -u +"%Y%m%d%H%M%S")
FILE="/Users/lunar/Desktop/sites/taloo-workspace/taloo-database/supabase/migrations/${TIMESTAMP}_<descriptive_name>.sql"
```

2. Write the SQL to that file using the Write tool

3. Commit and push from the database repo:
```bash
cd /Users/lunar/Desktop/sites/taloo-workspace/taloo-database
git checkout -b feature/<branch_name>
git add supabase/migrations/
git commit -m "<descriptive message>"
git push -u origin feature/<branch_name>
```

4. Create a PR using `gh pr create` in the taloo-database repo

5. After user approves, merge the PR → Supabase auto-applies the migration

**IMPORTANT: NEVER push directly to master.** All migrations must go through a feature branch + PR, regardless of complexity.

### MCP Tool Usage

When using Supabase MCP tools:
- `execute_sql` → Use `beniqwbanoqhxyrjwulg` for **read-only queries only**. NEVER for DDL.
- `list_tables` → Fine for inspection
- `apply_migration` → **DO NOT USE** — migrations go through Git

## When Making Changes

- **CRITICAL: Always test code before delivering** - Never deliver untested code. When creating new scripts, functions, or making edits, run the code to verify it works correctly before presenting it as complete. This includes:
  - Running new scripts to verify they execute without errors
  - Testing new API endpoints with sample requests
  - Running existing tests if modifying tested code (`python -m pytest`)
  - Starting the server (`uvicorn app:app --reload --port 8080`) to verify imports and syntax
- Always use async/await for database and external API calls
- Add new routers to `src/routers/__init__.py` and register in `app.py`
- Keep prompts/instructions in Dutch for user-facing content
- Use Pydantic models for request/response validation
- **IMPORTANT**: After adding/modifying/removing API endpoints, always update `docs/API_CONTRACT.md` to reflect the changes
