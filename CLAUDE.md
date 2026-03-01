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
1. **Interview Generator** (`interview_generator/agent.py`) - Generates knockout + qualification questions from vacancy text
2. **Pre-screening WhatsApp Agent** (`pre_screening_whatsapp_agent/agent.py`) - WhatsApp screening conversations (code-controlled flow)
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

PostgreSQL hosted on Supabase with branch-based environments.

### Supabase Environments

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ALWAYS USE THE LOCAL BRANCH FOR DDL CHANGES                                │
│  Project ID: vrpdzvattqlrtbaowapx                                           │
│                                                                             │
│  NEVER modify the staging (main) branch schema directly!                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Environment | Branch | Project Ref | Use For |
|-------------|--------|-------------|---------|
| **Local dev** | local | `vrpdzvattqlrtbaowapx` | All development, testing, and DDL changes |
| **Staging/Demo** | main | `beniqwbanoqhxyrjwulg` | Cloud Run demos - migrate via merge only |
| **Production** | (future) | TBD | Not set up yet |

### Creating & Modifying Tables (CRITICAL)

**ALWAYS use `apply_migration` via the Supabase MCP** for any DDL changes (CREATE TABLE, ALTER TABLE, etc.).
This ensures changes are tracked as Supabase migrations and can be merged from local → main.

**NEVER use `execute_sql` for DDL changes** — it bypasses the migration system and changes won't be included in branch merges.

**Example — Creating a new table:**
```
mcp__plugin_supabase_supabase__apply_migration(
    project_id="vrpdzvattqlrtbaowapx",
    name="create_office_locations",
    query="CREATE TABLE ats.office_locations (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), ...);"
)
```

**Example — Adding a column:**
```
mcp__plugin_supabase_supabase__apply_migration(
    project_id="vrpdzvattqlrtbaowapx",
    name="add_analysis_result_to_pre_screenings",
    query="ALTER TABLE ats.pre_screenings ADD COLUMN analysis_result JSONB;"
)
```

### Migration Workflow

**Step 1: Develop on local branch**
- Use `apply_migration` with `project_id: vrpdzvattqlrtbaowapx` for ALL schema changes
- Use `execute_sql` with `project_id: vrpdzvattqlrtbaowapx` for data queries/inserts only

**Step 2: Deploy to staging**
- Merge local → main via Supabase MCP:
```
mcp__plugin_supabase_supabase__merge_branch(branch_id="23001d49-d5ee-4820-8186-5e6d4b6c869a")
```
- This applies all tracked migrations from local → staging (main)

**Step 3: Verify**
- Test on Cloud Run staging environment
- If issues, fix on local branch and merge again

### MCP Tool Usage

When using Supabase MCP tools:
- `apply_migration` → **ALWAYS** use `project_id: vrpdzvattqlrtbaowapx` (local) — for ALL DDL changes
- `execute_sql` → Use `vrpdzvattqlrtbaowapx` for dev, `beniqwbanoqhxyrjwulg` only for read-only queries. **NEVER for DDL.**
- `list_tables` → Either project is fine for inspection

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
