# Unified Conversations Table — Migration Plan

## Problem

Pre-screening and document collection each have their own conversation tables with nearly identical schemas. As we add more agents, this pattern leads to duplicated tables, duplicated repositories, and inconsistent column naming.

**Current state:**

```
agents.pre_screening_sessions          agents.document_collections
├── id                                 ├── id
├── vacancy_id                         ├── vacancy_id
├── candidate_id                       ├── candidate_id
├── candidate_name                     ├── candidate_name
├── candidate_phone                    ├── candidate_phone
├── application_id                     ├── application_id
├── status (active/completed/abandoned)├── status (active/completed/needs_review/abandoned)
├── channel (voice/whatsapp/chat)      ├── channel (whatsapp)
├── message_count                      ├── message_count
├── agent_state (jsonb)                ├── agent_state (jsonb)
├── session_id                         ├── session_id
├── started_at                         ├── started_at
├── completed_at                       ├── completed_at
├── is_test                            ├── (missing)
├── (missing)                          ├── workspace_id
├── (missing)                          ├── candidacy_id
├── pre_screening_id                   ├── config_id
├── (N/A)                              ├── collection_plan (jsonb)
├── (N/A)                              ├── documents_required (jsonb)
├── (N/A)                              ├── goal
└── (N/A)                              └── retry_count

agents.pre_screening_session_turns     agents.document_collection_session_turns
├── id                                 ├── id
├── conversation_id (FK)               ├── collection_id (FK)
├── role (user/agent)                  ├── role (user/agent)
├── message                            ├── message
└── created_at                         └── created_at
```

The message tables are identical except for the FK column name.

---

## Proposed Schema

### `agents.conversations` (unified conversation root)

```sql
CREATE TABLE agents.conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type      VARCHAR(50) NOT NULL,          -- 'prescreening', 'document_collection', future agents
    workspace_id    UUID NOT NULL,                  -- FK: system.workspaces

    -- Candidate context
    vacancy_id      UUID,                           -- FK: ats.vacancies
    candidate_id    UUID,                           -- FK: ats.candidates
    candidacy_id    UUID,                           -- FK: ats.candidacies
    application_id  UUID,                           -- FK: ats.applications
    candidate_name  VARCHAR(255) NOT NULL,          -- denormalized for quick lookup
    candidate_phone VARCHAR(50),                    -- denormalized, used for webhook routing

    -- Agent config reference (nullable, agent-specific)
    config_id       UUID,                           -- FK to pre_screenings, doc_collection_configs, etc.

    -- Conversation state
    status          VARCHAR(30) NOT NULL DEFAULT 'active',  -- active, completed, needs_review, abandoned
    channel         VARCHAR(30) NOT NULL DEFAULT 'whatsapp', -- voice, whatsapp, chat, web
    message_count   INTEGER NOT NULL DEFAULT 0,
    is_test         BOOLEAN NOT NULL DEFAULT false,
    session_id      VARCHAR(255),                   -- external session ID (ADK, LiveKit, etc.)

    -- Agent runtime state (opaque to the framework, owned by each agent)
    agent_state     JSONB DEFAULT '{}',

    -- Agent-specific config data (plan, goal, required items, etc.)
    agent_config    JSONB DEFAULT '{}',

    -- Retry tracking
    retry_count     INTEGER NOT NULL DEFAULT 0,

    -- Timestamps
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_conversations_agent_type ON agents.conversations(agent_type);
CREATE INDEX idx_conversations_workspace ON agents.conversations(workspace_id);
CREATE INDEX idx_conversations_candidate_phone ON agents.conversations(candidate_phone) WHERE status = 'active';
CREATE INDEX idx_conversations_vacancy ON agents.conversations(vacancy_id);
CREATE INDEX idx_conversations_status ON agents.conversations(status) WHERE status = 'active';
CREATE INDEX idx_conversations_candidate ON agents.conversations(candidate_id);
```

### `agents.conversation_turns` (unified message log)

```sql
CREATE TABLE agents.conversation_turns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agents.conversations(id),
    role            TEXT NOT NULL CHECK (role IN ('user', 'agent', 'system')),
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',             -- optional per-message metadata (e.g. media URLs)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversation_turns_conversation ON agents.conversation_turns(conversation_id);
```

### What stays in agent-specific tables

These tables have agent-specific schemas and stay separate, but re-point their FK to `agents.conversations`:

```
agents.pre_screening_answers
├── conversation_id (FK → agents.conversations, replaces application_id linkage)
├── question_id, question_text, answer
├── passed, score, rating, motivation, source

agents.document_collection_uploads
├── conversation_id (FK → agents.conversations, replaces collection_id)
├── document_type_id, document_side, image_hash
├── storage_path, verification_result, verification_passed, status
```

---

## Column Mapping

### Pre-screening → Unified

| `pre_screening_sessions` | `conversations` | Notes |
|--------------------------|-----------------|-------|
| `id` | `id` | |
| *(missing)* | `agent_type = 'prescreening'` | New discriminator |
| *(inferred via vacancy)* | `workspace_id` | Now explicit |
| `vacancy_id` | `vacancy_id` | |
| `candidate_id` | `candidate_id` | |
| *(missing)* | `candidacy_id` | Now tracked |
| `application_id` | `application_id` | |
| `candidate_name` | `candidate_name` | |
| `candidate_phone` | `candidate_phone` | |
| `pre_screening_id` | `config_id` | Generic FK |
| `status` | `status` | |
| `channel` | `channel` | |
| `message_count` | `message_count` | |
| `is_test` | `is_test` | |
| `session_id` | `session_id` | |
| `agent_state` | `agent_state` | |
| `started_at` | `started_at` | |
| `completed_at` | `completed_at` | |

### Document collection → Unified

| `document_collections` | `conversations` | Notes |
|------------------------|-----------------|-------|
| `id` | `id` | |
| *(implicit)* | `agent_type = 'document_collection'` | New discriminator |
| `workspace_id` | `workspace_id` | |
| `vacancy_id` | `vacancy_id` | |
| `candidate_id` | `candidate_id` | |
| `candidacy_id` | `candidacy_id` | |
| `application_id` | `application_id` | |
| `candidate_name` | `candidate_name` | |
| `candidate_phone` | `candidate_phone` | |
| `config_id` | `config_id` | |
| `status` | `status` | |
| `channel` | `channel` | |
| `message_count` | `message_count` | |
| *(missing)* | `is_test` | Now available |
| `session_id` | `session_id` | |
| `agent_state` | `agent_state` | |
| `collection_plan` | `agent_config.plan` | Moved to JSONB |
| `documents_required` | `agent_config.documents_required` | Moved to JSONB |
| `goal` | `agent_config.goal` | Moved to JSONB |
| `retry_count` | `retry_count` | |
| `started_at` | `started_at` | |
| `completed_at` | `completed_at` | |

---

## Repository Changes

### New: `ConversationRepository` (unified)

```python
class ConversationRepository:
    """Unified conversation CRUD for all TalooAgent types."""

    async def create(self, agent_type, workspace_id, candidate_name, ...) -> Record
    async def get_by_id(self, conversation_id) -> Optional[Record]
    async def find_active_by_phone(self, phone, agent_type=None) -> Optional[Record]
    async def update_status(self, conversation_id, status, completed_at=None)
    async def update_agent_state(self, conversation_id, agent_state)
    async def add_turn(self, conversation_id, role, message, metadata=None)
    async def get_turns(self, conversation_id) -> list[Record]
    async def increment_message_count(self, conversation_id)
    async def list_for_vacancy(self, vacancy_id, agent_type=None, ...) -> list[Record]
    async def list_for_workspace(self, workspace_id, agent_type=None, ...) -> list[Record]
```

### Existing repos to update

| Repository | Change |
|------------|--------|
| `conversation_repo.py` | Redirect to unified table, deprecate old methods |
| `document_collection_repo.py` | Redirect to unified table for conversation CRUD |
| `application_repo.py` | `pre_screening_answers` FK → `conversation_id` |

---

## Integration with TalooAgent

The `TalooAgent` base class gets a built-in `create_conversation()` method:

```python
class TalooAgent(ABC):
    async def create_conversation(
        self,
        candidate_id, candidate_name, vacancy_id,
        channel, config_id=None, **kwargs
    ) -> str:
        """Create a conversation record. Returns conversation_id."""
        repo = ConversationRepository(self.pool)
        return await repo.create(
            agent_type=self.agent_type.value,
            workspace_id=self.workspace_id,
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            vacancy_id=vacancy_id,
            channel=channel,
            config_id=config_id,
            **kwargs,
        )
```

This solves the interleaving problem in the outbound router — `on_start()` can now:
1. Check availability
2. Create conversation record (gets `conversation_id`)
3. Log activity
4. Create workflow (has `conversation_id`)

Then the channel-specific helper just dispatches the call/message.

---

## Migration Strategy

### Phase 1: Create new tables (non-breaking)
1. Create `agents.conversations` and `agents.conversation_turns` tables
2. Create the unified `ConversationRepository`
3. Add `create_conversation()` to `TalooAgent` base class

### Phase 2: Dual-write (backwards compatible)
1. Update routers to write to BOTH old and new tables
2. Update reads to prefer new table, fall back to old
3. Backfill existing data from old tables to new

### Phase 3: Switch reads (verify)
1. Point all reads to new tables
2. Keep old tables as read-only backup
3. Verify frontend audit trail, conversation history, etc.

### Phase 4: Drop old tables (cleanup)
1. Remove old table writes
2. Drop old repositories
3. Drop old tables after confirming no references

### Migration SQL (Phase 1)

```sql
-- Backfill pre-screening sessions
INSERT INTO agents.conversations (
    id, agent_type, workspace_id, vacancy_id, candidate_id, application_id,
    candidate_name, candidate_phone, config_id, status, channel,
    message_count, is_test, session_id, agent_state, started_at, completed_at,
    created_at, updated_at
)
SELECT
    ps.id, 'prescreening', v.workspace_id, ps.vacancy_id, ps.candidate_id,
    ps.application_id, ps.candidate_name, ps.candidate_phone,
    ps.pre_screening_id, ps.status, ps.channel, ps.message_count,
    COALESCE(ps.is_test, false), ps.session_id, COALESCE(ps.agent_state, '{}'),
    ps.started_at, ps.completed_at, ps.created_at, ps.updated_at
FROM agents.pre_screening_sessions ps
LEFT JOIN ats.vacancies v ON v.id = ps.vacancy_id;

-- Backfill pre-screening turns
INSERT INTO agents.conversation_turns (id, conversation_id, role, message, created_at)
SELECT id, conversation_id, role, message, created_at
FROM agents.pre_screening_session_turns;

-- Backfill document collections
INSERT INTO agents.conversations (
    id, agent_type, workspace_id, vacancy_id, candidate_id, candidacy_id,
    application_id, candidate_name, candidate_phone, config_id, status, channel,
    message_count, is_test, session_id, agent_state, agent_config, retry_count,
    started_at, completed_at, created_at, updated_at
)
SELECT
    dc.id, 'document_collection', dc.workspace_id, dc.vacancy_id, dc.candidate_id,
    dc.candidacy_id, dc.application_id, dc.candidate_name, dc.candidate_phone,
    dc.config_id, dc.status, dc.channel, dc.message_count, false, dc.session_id,
    COALESCE(dc.agent_state, '{}'),
    jsonb_build_object(
        'plan', dc.collection_plan,
        'documents_required', dc.documents_required,
        'goal', dc.goal
    ),
    dc.retry_count, dc.started_at, dc.completed_at, dc.created_at, dc.updated_at
FROM agents.document_collections dc;

-- Backfill document collection turns
INSERT INTO agents.conversation_turns (id, conversation_id, role, message, created_at)
SELECT id, collection_id, role, message, created_at
FROM agents.document_collection_session_turns;
```

---

## Impact on Frontend

The frontend currently calls:
- `GET /screening/conversations/{id}` — returns pre-screening conversation
- `GET /workspaces/{ws}/document-collection/collections/{id}` — returns document collection detail

These endpoints stay but internally query `agents.conversations` instead. Response shapes don't change — the router maps from the unified table to the existing response models.

The audit trail (`GET /monitoring`) already works across both agents via `system.activity_log` and is unaffected.

---

## Files Affected

| Area | Files |
|------|-------|
| **Migration** | `taloo-database/supabase/migrations/XXXXXX_unified_conversations.sql` |
| **New repo** | `src/repositories/conversation_repo.py` (rewrite) |
| **Base class** | `src/agents/base.py` (add `create_conversation()`) |
| **Pre-screening** | `src/routers/outbound.py`, `src/routers/screening.py`, `src/routers/webhooks.py`, `src/routers/livekit_webhook.py` |
| **Doc collection** | `src/routers/document_collection.py`, `src/services/document_collection_service.py`, `src/services/document_collection_planner_service.py` |
| **Models** | `src/models/screening.py`, `src/models/document_collection.py` |
