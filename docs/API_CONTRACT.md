# Taloo Backend API Contract

Complete API reference for the Taloo recruitment screening platform.

## Changelog

- **2026-03-11** — Added `custom_field_extraction` (JSONB) field to document type entities for LLM-driven field extraction config (top-level only); added CRUD endpoints `POST /ontology/entities`, `PATCH /ontology/entities/{id}`, `DELETE /ontology/entities/{id}`; updated list sorting: items with children first (A-Z), then leaf items (A-Z); updated `is_verifiable` on Arbeidskaart, Vrijstelling arbeidskaart, VakantieAttest, C3.2 afdruk, Grensarbeider
- **2026-03-11** — Replaced planned workspace-scoped ontology with implemented `/ontology` endpoints: `GET /ontology` (overview), `GET /ontology/entities?type=document_type` (list with parent-child hierarchy), `GET /ontology/entities/{id}` (single entity). Document types seeded from Prato Flex with 43 parent types and 473 detail types across 4 categories (identity, certificate, financial, other)
- **2026-03-09** — Added `documents_required: DocumentTypeResponse[]` to `DocumentCollectionDetailResponse` (resolves stored slugs into full document type objects with name, icon, category); added Lucide icons to seeded document types
- **2026-03-09** — Added derived `progress` field to `DocumentCollectionResponse` (computed from messages: `"pending"` → `"started"` → `"in_progress"`); added `documents_collected` and `documents_total` fields for progress counters. General `status` remains unchanged (`active`/`completed`/`needs_review`/`abandoned`)
- **2026-03-09** — Split `POST /demo/import-ats` with `module` query parameter: `"pre_screening"` (default, existing behavior) or `"document_collection"` (creates configs per vacancy + sample conversations). Document collection demo data moved from `/demo/seed` to this endpoint
- **2026-03-09** — Added Document Collection v2 system: workspace-scoped document types CRUD, collection configs (per-vacancy or default), document resolution/merge logic, conversation tracking, and candidate document portfolio. All under `/workspaces/{workspace_id}/document-collection/`. 7 new database tables (`ats.document_types`, `ats.document_collection_configs`, `ats.document_collection_requirements`, `ats.document_collections`, `ats.document_collection_messages`, `ats.document_collection_uploads`, `ats.candidate_documents`)
- **2026-03-01** — Added `GET /pre-screening/config` and `PATCH /pre-screening/config` endpoints for global pre-screening agent configuration (require_consent, allow_escalation, planning_mode, schedule settings, messages); added `GET /vacancies/{vacancy_id}/pre-screening/settings` and `PATCH /vacancies/{vacancy_id}/pre-screening/settings` for per-vacancy channel toggles
- **2026-03-01** — Added `POST /playground/start` endpoint for browser-based LiveKit WebRTC voice playground (returns access token for frontend to connect directly to pre-screening V2 agent, no database records created)
- **2026-02-28** — Replaced VAPI voice provider with LiveKit pre-screening v2 agent; added `POST /webhook/livekit/call-result` endpoint for receiving structured call results; outbound voice calls now dispatch via LiveKit SIP
- **2026-02-28** — Added ATS Simulator endpoints (`GET /ats-simulator/api/v1/vacancies`, `GET /ats-simulator/api/v1/recruiters`, `GET /ats-simulator/api/v1/clients`) and `POST /demo/import-ats` for simulated ATS integration; demo seed now imports via ATS API instead of direct DB inserts
- **2026-02-28** — Added Interview Analysis endpoints (`POST /pre-screenings/{id}/analyze`, `GET /pre-screenings/{id}/analysis`) with per-question clarity scoring, knockout ambiguity checks, drop-off risk, funnel data, and one-liner summary for Teams notifications
- **2026-02-19** — ~~Added Ontology endpoints for workspace knowledge graph management~~ (replaced by simplified `/ontology` endpoints on 2026-03-11)
- **2026-02-17** — Added `POST /screening/web-call` endpoint for browser-based VAPI voice simulation (no database records created, for testing/demo only)
- **2026-02-16** — Enhanced `AgentStatusResponse` with stats: `total_screenings`, `qualified_count`, `qualification_rate`, `last_activity_at` (populated for prescreening agent)
- **2026-02-16** — Added `candidate_name` field to ActivityResponse in vacancy timelines (`GET /vacancies/{vacancy_id}`)
- **2026-02-16** — Added `applicants` array to VacancyResponse (lightweight ApplicantSummary for candidates who did pre-screening)
- **2026-02-16** — Removed redundant `recruiter_id` and `client_id` fields from VacancyResponse (use `recruiter.id` and `client.id` instead)
- **2026-02-16** — Added `GET /architecture` endpoint for backend architecture visualization (returns JSON for frontend graph rendering)
- **2026-02-16** — Added `activities` field to NavigationCountsResponse (`GET /agents/counts`) with `active` and `stuck` counts
- **2026-02-16** — Added `active_count` field to TasksResponse for counting non-stuck active tasks
- **2026-02-15** — Added `workflow_steps` array to TaskRow for visual workflow progress representation; enables frontend to render step indicators
- **2026-02-15** — Added `step_detail` field to TaskRow for granular workflow status (e.g., "WhatsApp gesprek", "Gesprek verwerken"); `current_step_label` now shows simple English labels ("In Progress", "Processing")
- **2026-02-15** — Added lightweight `GET /agents/counts` endpoint for navigation sidebar counts
- **2026-02-15** — Renamed endpoints: `/activities` → `/monitoring` (event log), new `/api/activities/tasks` (active workflow tasks)
- **2026-02-15** — Added `workflow_activities` query param to `/demo/reset` for seeding dashboard demo data
- **2026-02-14** — Added Authentication endpoints with Google OAuth and dev-login for local testing
- **2026-02-12** — Added GET/PUT `/elevenlabs/voice-config/{agent_id}` endpoints for storing/retrieving voice settings in database
- **2026-02-12** — Added PATCH `/elevenlabs/agent/{agent_id}/config` endpoint for updating ElevenLabs agent voice configuration (voice_id, model_id, stability, similarity_boost)
- **2026-02-12** — Changed `/interview/generate` to accept `vacancy_id` instead of `vacancy_text`; backend now fetches vacancy from database
- **2026-02-12** — Added `vacancy_snippet` field to interview questions (knockout and qualification); links questions to source vacancy text for frontend highlighting
- **2026-02-11** — Added `is_test` field to candidates table and API responses; added `is_test` filter to GET /candidates endpoint
- **2026-02-11** — Added Agent endpoints for listing vacancies by agent status (GET /agents/prescreening/vacancies, GET /agents/preonboarding/vacancies)
- **2026-02-11** — Added client_id to vacancies, VacancyResponse now includes client info (ClientSummary)
- **2026-02-11** — Added Recruiters table with vacancy ownership (recruiter_id foreign key on vacancies)
- **2026-02-11** — Added Clients table and fixture data (name, location, industry, logo)
- **2026-02-11** — Changed VacancyStatus to lifecycle statuses (concept, open, on_hold, filled, closed) - decoupled from screening config
- **2026-02-11** — Added agents field to vacancy responses (prescreening, preonboarding, insights)
- **2026-02-11** — Added activity timeline to GET /vacancies/{vacancy_id} endpoint
- **2026-02-11** — Added activity timeline to GET /candidates/{candidate_id} endpoint
- **2026-02-11** — Added optional candidate_email to save-slot for sending calendar invites to candidates
- **2026-02-11** — Added Candidates endpoints (list, get, update status/rating)
- **2026-02-11** — Added cancel endpoint, calendar_event_id tracking, improved reschedule with event cancellation
- **2026-02-11** — Added reschedule endpoint (POST /api/scheduling/interviews/by-conversation/{conversation_id}/reschedule)
- **2026-02-10** — Added Scheduling endpoints (get-time-slots, save-slot, update notes by conversation_id)
- **2026-02-09** — Initial contract — generated from codebase

---

## Table of Contents

1. [Authentication](#authentication)
2. [Common Types](#common-types)
3. [Health](#health)
4. [Vacancies](#vacancies)
5. [Applications](#applications)
6. [Candidates](#candidates)
7. [Clients](#clients)
8. [Recruiters](#recruiters)
9. [Agents](#agents)
10. [Pre-Screening](#pre-screening)
11. [Interviews](#interviews)
12. [Screening](#screening)
13. [Outbound](#outbound)
14. [CV Analysis](#cv-analysis)
15. [Data Query](#data-query)
16. [Documents](#documents)
17. [Document Collection](#document-collection)
18. [Webhooks](#webhooks)
19. [Scheduling](#scheduling)
20. [ElevenLabs](#elevenlabs)
21. [Activities](#activities)
22. [Architecture](#architecture)
23. [Ontology](#ontology)
24. [ATS Simulator](#ats-simulator)
25. [Demo](#demo)
26. [Error Reference](#error-reference)

---

## Authentication

The API uses **Supabase Auth with Google OAuth** for user authentication. Protected endpoints require a valid JWT token.

### Headers

```
Authorization: Bearer <access_token>
X-Workspace-ID: <workspace_uuid>
```

### Auth Endpoints

#### POST /auth/dev-login

**Development-only** endpoint for local testing. Creates a dev user and returns a valid JWT token.

**Auth:** None (only works when `ENVIRONMENT=local`)

**Response:**

```typescript
interface AuthCallbackResponse {
  access_token: string;      // JWT token (24hr expiry)
  refresh_token: string;     // Not functional for dev-login
  token_type: "bearer";
  expires_in: number;        // Seconds until expiry
  user: UserProfileResponse;
  workspaces: WorkspaceSummary[];
}

interface UserProfileResponse {
  id: string;
  email: string;
  full_name: string;
  avatar_url?: string;
  phone?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  logo_url?: string;
  role: "owner" | "admin" | "member";
}
```

**Example Response:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dev-refresh-token-not-functional",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "4079a85f-11ea-4d32-9c5c-be908b4020e1",
    "email": "dev@taloo.be",
    "full_name": "Dev User",
    "avatar_url": null,
    "phone": null,
    "is_active": true,
    "created_at": "2026-02-14T13:11:02.205952Z",
    "updated_at": "2026-02-14T13:11:02.205952Z"
  },
  "workspaces": [
    {
      "id": "00000000-0000-0000-0000-000000000001",
      "name": "Default Workspace",
      "slug": "default",
      "logo_url": null,
      "role": "owner"
    }
  ]
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 403 | Dev login only available in local/development environment |

---

#### GET /auth/login/google

Initiate Google OAuth login flow. Redirects user to Google consent page.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `redirect_to` | string | No | URL to redirect after login |

**Response:** HTTP 302 redirect to Google OAuth

---

#### GET /auth/callback

OAuth callback handler. Exchanges authorization code for tokens.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `code` | string | Yes | Authorization code from OAuth |

**Response:** `AuthCallbackResponse` (same as dev-login)

---

#### POST /auth/refresh

Refresh access token using refresh token.

**Auth:** None

**Request Body:**

```typescript
interface RefreshTokenRequest {
  refresh_token: string;
}
```

**Response:**

```typescript
interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}
```

---

#### POST /auth/logout

Log out the current user.

**Auth:** Optional Bearer token

**Response:**

```json
{ "success": true }
```

---

#### GET /auth/me

Get current user info and workspaces.

**Auth:** Bearer token required

**Response:**

```typescript
interface AuthMeResponse {
  user: UserProfileResponse;
  workspaces: WorkspaceSummary[];
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 401 | Authorization header required |
| 401 | Invalid authorization header format |
| 401 | Invalid or malformed token |
| 401 | Token expired |

---

### Multi-Workspace Support

Users can belong to multiple workspaces with role-based access:

| Role | Permissions |
|------|-------------|
| `owner` | Full access, can delete workspace |
| `admin` | Manage members, full data access |
| `member` | View and edit workspace data |

When accessing workspace-scoped data, include the `X-Workspace-ID` header.

---

### Webhook Authentication

- **ElevenLabs**: SHA256 HMAC signature via `elevenlabs-signature` header
- **Twilio**: Trusted via IP range

---

## Common Types

### Pagination

```typescript
interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
```

### Enums

```typescript
type VacancyStatus = "concept" | "open" | "on_hold" | "filled" | "closed";
type VacancySource = "salesforce" | "bullhorn" | "manual";
type InterviewChannel = "voice" | "whatsapp";
type QuestionType = "knockout" | "qualification";
type ApplicationStatus = "active" | "processing" | "completed" | "abandoned";
type CandidateStatus = "new" | "qualified" | "active" | "placed" | "inactive";
type AvailabilityStatus = "available" | "unavailable" | "unknown";
type DocumentCategory = "driver_license" | "medical_certificate" | "work_permit" | "certificate_diploma" | "id_card" | "unknown" | "unreadable";
type FraudRiskLevel = "low" | "medium" | "high";
type ImageQuality = "excellent" | "good" | "acceptable" | "poor" | "unreadable";
```

### SSE Event Format

All streaming endpoints use Server-Sent Events:

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

Events are sent as `data: {JSON}\n\n`. Stream ends with `data: [DONE]\n\n`.

---

## Health

### GET /health

Health check endpoint.

**Auth:** None

**Response:**

```typescript
interface HealthResponse {
  status: "ok";
  service: "taloo-backend";
}
```

```json
{
  "status": "ok",
  "service": "taloo-backend"
}
```

---

## Vacancies

### GET /vacancies

List all vacancies with pagination and filters.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `status` | string | No | - | Filter by VacancyStatus |
| `source` | string | No | - | Filter by VacancySource |
| `limit` | number | No | 50 | Results per page (1-100) |
| `offset` | number | No | 0 | Pagination offset |

**Response:**

```typescript
interface ChannelsResponse {
  voice: boolean;
  whatsapp: boolean;
  cv: boolean;
}

interface AgentStatusResponse {
  exists: boolean;         // True if agent is generated/configured
  status: "online" | "offline" | null;  // Agent status (null if not applicable)
  // Stats (populated for prescreening agent when exists=true)
  total_screenings?: number;    // Total number of screenings
  qualified_count?: number;     // Number of qualified candidates
  qualification_rate?: number;  // Percentage (0-100)
  last_activity_at?: string;    // ISO timestamp of last screening activity
}

interface AgentsResponse {
  prescreening: AgentStatusResponse;   // Pre-screening AI agent
  preonboarding: AgentStatusResponse;  // Pre-onboarding AI agent (document collection)
  insights: AgentStatusResponse;       // Insights AI agent (analytics)
}

interface RecruiterSummary {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  team?: string;
  role?: string;
  avatar_url?: string;
}

interface ClientSummary {
  id: string;
  name: string;
  location?: string;
  industry?: string;
  logo?: string;
}

interface ApplicantSummary {
  id: string;
  name: string;
  phone?: string;
  channel: "voice" | "whatsapp" | "cv";
  status: "active" | "processing" | "completed";
  qualified: boolean;
  score?: number;        // Average qualification score (0-100)
  started_at: string;
  completed_at?: string;
}

interface VacancyResponse {
  id: string;
  title: string;
  company: string;
  location?: string;
  description?: string;
  status: VacancyStatus;
  created_at: string;
  archived_at?: string;
  source?: VacancySource;
  source_id?: string;
  has_screening: boolean;
  published_at?: string;  // ISO timestamp when pre-screening was published (null = draft)
  is_online?: boolean;
  channels: ChannelsResponse;
  agents: AgentsResponse;
  recruiter?: RecruiterSummary;   // Full recruiter info (if assigned) - use recruiter.id for ID
  client?: ClientSummary;         // Full client info (if assigned) - use client.id for ID
  applicants: ApplicantSummary[]; // Candidates who completed pre-screening (excludes test applications)
  candidates_count: number;
  completed_count: number;
  qualified_count: number;
  avg_score?: number;             // Average qualification score across all applications
  last_activity_at?: string;
}

interface VacanciesListResponse {
  vacancies: VacancyResponse[];
  total: number;
  limit: number;
  offset: number;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid query parameters |

---

### GET /vacancies/{vacancy_id}

Get a single vacancy by ID with activity timeline.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Response:**

```typescript
interface VacancyDetailResponse extends VacancyResponse {
  timeline: ActivityResponse[];  // Activity timeline for this vacancy, newest first (max 50)
}
```

Note: See `ActivityResponse` in [Candidates](#candidates) section for the activity object structure.

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |

---

### POST /vacancies/{vacancy_id}/cv-application

Create an application from CV upload.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Request Body:**

```typescript
interface CVApplicationRequest {
  pdf_base64: string;
  candidate_name: string;
  candidate_phone?: string;
  candidate_email?: string;
}
```

**Response:**

```typescript
interface ApplicationResponse {
  id: string;
  vacancy_id: string;
  candidate_name: string;
  channel: InterviewChannel | "cv";
  status: ApplicationStatus;
  qualified: boolean;
  started_at: string;
  completed_at?: string;
  interaction_seconds: number;
  answers: QuestionAnswerResponse[];  // Always includes ALL questions, even if not answered yet
  synced: boolean;
  synced_at?: string;
  open_questions_score?: number;
  knockout_passed: number;
  knockout_total: number;
  open_questions_total: number;
  summary?: string;
  interview_slot?: string;
  meeting_slots?: string[];
  is_test: boolean;
}

interface QuestionAnswerResponse {
  question_id: string;
  question_text: string;
  question_type?: QuestionType;
  answer?: string;
  passed?: boolean;
  score?: number;
  rating?: "weak" | "below_average" | "average" | "good" | "excellent";
  motivation?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | Invalid PDF data |
| 404 | Vacancy not found |
| 404 | No pre-screening configured |

---

### GET /vacancies/{vacancy_id}/stats

Get statistics for a vacancy.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Response:**

```typescript
interface VacancyStatsResponse {
  vacancy_id: string;
  total_applications: number;
  completed_count: number;
  completion_rate: number;
  qualified_count: number;
  qualification_rate: number;
  channel_breakdown: Record<string, number>;
  avg_interaction_seconds: number;
  last_application_at?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |

---

### GET /stats

Get aggregated dashboard statistics across all vacancies.

**Auth:** None

**Response:**

```typescript
interface DashboardStatsResponse {
  total_prescreenings: number;
  total_prescreenings_this_week: number;
  completed_count: number;
  completion_rate: number;
  qualified_count: number;
  qualification_rate: number;
  channel_breakdown: Record<string, number>;
}
```

---

## Applications

### GET /vacancies/{vacancy_id}/applications

List applications for a vacancy.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `qualified` | boolean | No | - | Filter by qualification status |
| `completed` | boolean | No | - | Filter by completion status |
| `synced` | boolean | No | - | Filter by sync status |
| `is_test` | boolean | No | - | Filter test/production applications |
| `limit` | number | No | 50 | Results per page (1-100) |
| `offset` | number | No | 0 | Pagination offset |

**Response:**

```typescript
interface ApplicationsListResponse {
  applications: ApplicationResponse[];
  total: number;
  limit: number;
  offset: number;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |

---

### GET /applications/{application_id}

Get a single application with answers.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `application_id` | string (UUID) | Application identifier |

**Response:** `ApplicationResponse`

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid application ID format |
| 404 | Application not found |

---

### POST /applications/reprocess-tests

Reprocess all test applications through scoring pipeline.

**Auth:** None

**Response:**

```typescript
interface ReprocessResponse {
  status: "completed";
  processed: number;
  errors: number;
  results: Array<{
    application_id: string;
    success: boolean;
    error?: string;
  }>;
  error_details: string[];
}
```

---

## Candidates

### GET /candidates

List candidates with skills, vacancy count, and last activity.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `limit` | number | No | 50 | Results per page (1-100) |
| `offset` | number | No | 0 | Pagination offset |
| `status` | CandidateStatus | No | - | Filter by status |
| `availability` | AvailabilityStatus | No | - | Filter by availability |
| `search` | string | No | - | Search by name, email, or phone |
| `is_test` | boolean | No | - | Filter by test flag: true for test candidates, false for real ones |
| `sort_by` | string | No | "status" | Sort field: status, name, last_activity, rating, availability |
| `sort_order` | string | No | "asc" | Sort order: asc or desc |

**Response:**

```typescript
interface CandidateSkillResponse {
  id: string;
  skill_name: string;
  skill_code?: string;
  skill_category?: string;  // skills, education, certificates, personality
  score?: number;           // 0.0-1.0
  evidence?: string;
  source: string;           // cv_analysis, manual, screening, import
  created_at: string;
}

interface CandidateListResponse {
  id: string;
  phone?: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  full_name: string;
  source?: string;
  status: CandidateStatus;
  status_updated_at?: string;
  availability: AvailabilityStatus;
  available_from?: string;  // YYYY-MM-DD
  rating?: number;          // 0.0-5.0
  is_test: boolean;         // Flag for test candidates created during admin testing
  created_at: string;
  updated_at: string;
  skills: CandidateSkillResponse[];
  vacancy_count: number;
  last_activity?: string;
}
```

---

### GET /candidates/{candidate_id}

Get a single candidate with applications, skills, and activity timeline.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `candidate_id` | string (UUID) | Candidate identifier |

**Response:**

```typescript
interface CandidateApplicationSummary {
  id: string;
  vacancy_id: string;
  vacancy_title: string;
  vacancy_company: string;
  channel: string;
  status: string;
  qualified?: boolean;
  started_at: string;
  completed_at?: string;
}

interface ActivityResponse {
  id: string;
  candidate_id: string;
  candidate_name?: string;  // Included in vacancy timelines (GET /vacancies/{vacancy_id})
  application_id?: string;
  vacancy_id?: string;
  event_type: string;  // screening_started, qualified, disqualified, interview_scheduled, etc.
  channel?: string;    // voice, whatsapp, cv, web
  actor_type: string;  // candidate, agent, recruiter, system
  actor_id?: string;
  metadata: Record<string, any>;
  summary?: string;    // Human-readable description in Dutch
  created_at: string;
}

interface CandidateWithApplicationsResponse {
  id: string;
  phone?: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  full_name: string;
  source?: string;
  status: CandidateStatus;
  status_updated_at?: string;
  availability: AvailabilityStatus;
  available_from?: string;
  rating?: number;
  is_test: boolean;         // Flag for test candidates created during admin testing
  created_at: string;
  updated_at: string;
  applications: CandidateApplicationSummary[];
  skills: CandidateSkillResponse[];
  timeline: ActivityResponse[];  // Activity timeline, newest first (max 50)
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Candidate not found |

---

### PATCH /candidates/{candidate_id}/status

Update a candidate's status.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `candidate_id` | string (UUID) | Candidate identifier |

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `status` | CandidateStatus | Yes | New status value |

**Response:**

```typescript
interface UpdateStatusResponse {
  status: "success";
  candidate_id: string;
  new_status: CandidateStatus;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Candidate not found |

---

### PATCH /candidates/{candidate_id}/rating

Update a candidate's rating.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `candidate_id` | string (UUID) | Candidate identifier |

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `rating` | number | Yes | Rating from 0 to 5 |

**Response:**

```typescript
interface UpdateRatingResponse {
  status: "success";
  candidate_id: string;
  new_rating: number;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Candidate not found |

---

## Clients

Client/company information for recruitment tracking.

### Database Schema

```typescript
interface Client {
  id: string;           // UUID
  name: string;         // Required - company name
  location?: string;    // City, country
  industry?: string;    // Industry sector
  logo?: string;        // Path to logo image (e.g., "/companies/name.png")
  website?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}
```

### Available Clients (Fixtures)

| Name | Location | Industry | Logo |
|------|----------|----------|------|
| Vandemoortele | Gent, België | Voeding | `/companies/vandmoortele.png` |
| Agristo | Harelbeke, België | Voeding | `/companies/agristo.png` |
| Colruyt Group | Halle, België | Retail | `/companies/colruyt_group.png` |
| Essers | Genk, België | Logistiek | `/companies/essers.png` |
| Nike Laakdal | Laakdal, België | Logistiek | - |
| McDonalds Genk | Genk, België | Horeca | `/companies/mcdonalds.png` |
| Intern | België | Intern | - |

> **Note:** API endpoints for clients (CRUD operations) are not yet implemented. Currently, clients are managed directly in the database.

---

## Recruiters

Recruiter information for vacancy ownership. Every vacancy is owned by a recruiter.

### Database Schema

```typescript
interface Recruiter {
  id: string;           // UUID
  name: string;         // Required - recruiter name
  email?: string;       // Unique email address
  phone?: string;
  team?: string;        // Team/region assignment
  role?: string;        // Job title (e.g., "Senior Recruiter", "Team Lead")
  avatar_url?: string;  // Profile image URL
  is_active: boolean;   // Default: true
  created_at: string;
  updated_at: string;
}
```

### Vacancy Ownership

Vacancies have an optional `recruiter_id` foreign key linking to the recruiters table:

```typescript
interface VacancyResponse {
  // ... existing fields
  recruiter_id?: string;  // UUID - owner recruiter
}
```

### Available Recruiters (Fixtures)

| Name | Email | Phone | Team | Role |
|------|-------|-------|------|------|
| Sarah De Vos | sarah.devos@taloo.be | +32 473 12 34 56 | West-Vlaanderen | Senior Recruiter |
| Thomas Peeters | thomas.peeters@taloo.be | +32 476 98 76 54 | Limburg | Recruiter |
| Emma Janssen | emma.janssen@taloo.be | +32 479 11 22 33 | Vlaams-Brabant | Junior Recruiter |
| Pieter Wouters | pieter.wouters@taloo.be | +32 478 44 55 66 | Oost-Vlaanderen | Team Lead |
| Lisa Maes | lisa.maes@taloo.be | +32 477 77 88 99 | Antwerpen | Senior Recruiter |

> **Note:** API endpoints for recruiters (CRUD operations) are not yet implemented. Currently, recruiters are managed directly in the database.

---

## Agents

Agent-centric views of vacancies, grouped by AI agent configuration status.

### GET /agents/prescreening/vacancies

List vacancies by pre-screening agent status.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `status` | string | Yes | - | Filter: `new`, `generated`, `published`, or `archived` |
| `limit` | number | No | 50 | Results per page (1-100) |
| `offset` | number | No | 0 | Pagination offset |

**Status Definitions:**

- `new`: No pre-screening record (questions not generated yet)
- `generated`: Has pre-screening record but NOT published (draft)
- `published`: Has pre-screening record AND published (can be online/offline)
- `archived`: Vacancy status is 'closed' or 'filled'

**Response:**

```typescript
interface AgentVacancyListResponse {
  vacancies: VacancyResponse[];
  total: number;
  limit: number;
  offset: number;
}
```

```json
{
  "vacancies": [
    {
      "id": "uuid",
      "title": "Operator Mengafdeling",
      "company": "Vandemoortele",
      "location": "Gent",
      "status": "open",
      "created_at": "2025-01-15T10:00:00Z",
      "has_screening": true,
      "is_online": true,
      "channels": { "voice": true, "whatsapp": true, "cv": false },
      "agents": {
        "prescreening": { "exists": true, "status": "online" },
        "preonboarding": { "exists": false, "status": null },
        "insights": { "exists": false, "status": null }
      },
      "recruiter": { "id": "uuid", "name": "Sarah De Vos" },
      "client": { "id": "uuid", "name": "Vandemoortele" },
      "candidates_count": 15,
      "completed_count": 12,
      "qualified_count": 8,
      "last_activity_at": "2025-01-20T09:15:00Z"
    }
  ],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

---

### GET /agents/preonboarding/vacancies

List vacancies by pre-onboarding agent status.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `status` | string | Yes | - | Filter: `new`, `generated`, or `archived` |
| `limit` | number | No | 50 | Results per page (1-100) |
| `offset` | number | No | 0 | Pagination offset |

**Status Definitions:**

- `new`: `preonboarding_agent_enabled` is false or NULL
- `generated`: `preonboarding_agent_enabled` is true
- `archived`: Vacancy status is 'closed' or 'filled'

**Response:** Same structure as `/agents/prescreening/vacancies`

---

### GET /agents/counts

Get lightweight counts for navigation sidebar. Returns vacancy counts by agent status without fetching full vacancy data.

**Auth:** None

**Response:**

```typescript
interface NavigationCountsResponse {
  prescreening: {
    new: number;
    generated: number;
    archived: number;
  };
  preonboarding: {
    new: number;
    generated: number;
    archived: number;
  };
  activities: {
    active: number;   // Active workflows (not stuck)
    stuck: number;    // Workflows with no update for > 1 hour
  };
}
```

```json
{
  "prescreening": {
    "new": 7,
    "generated": 3,
    "archived": 2
  },
  "preonboarding": {
    "new": 7,
    "generated": 0,
    "archived": 2
  },
  "activities": {
    "active": 5,
    "stuck": 2
  }
}
```

---

## Pre-Screening

### PUT /vacancies/{vacancy_id}/pre-screening

Create or update pre-screening configuration.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Request Body:**

```typescript
interface PreScreeningQuestionRequest {
  id: string;
  question: string;
  ideal_answer?: string;
  vacancy_snippet?: string;  // Exact text from vacancy this question is based on
}

interface PreScreeningRequest {
  intro: string;
  knockout_questions: PreScreeningQuestionRequest[];
  knockout_failed_action: string;
  qualification_questions: PreScreeningQuestionRequest[];
  final_action: string;
  approved_ids?: string[];
}
```

**Response:**

```typescript
interface PreScreeningUpdateResponse {
  status: "created" | "updated";
  message: string;
  pre_screening_id: string;
  vacancy_id: string;
  vacancy_status: VacancyStatus;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |

---

### GET /vacancies/{vacancy_id}/pre-screening

Get pre-screening configuration.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Response:**

```typescript
interface PreScreeningQuestionResponse {
  id: string;
  question_type: QuestionType;
  position: number;
  question_text: string;
  ideal_answer?: string;
  vacancy_snippet?: string;  // Exact text from vacancy this question is based on
  is_approved: boolean;
}

interface PreScreeningResponse {
  id: string;
  vacancy_id: string;
  intro: string;
  knockout_questions: PreScreeningQuestionResponse[];
  knockout_failed_action: string;
  qualification_questions: PreScreeningQuestionResponse[];
  final_action: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  published_at?: string;
  is_online: boolean;
  elevenlabs_agent_id?: string;
  whatsapp_agent_id?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |
| 404 | No pre-screening found |

---

### DELETE /vacancies/{vacancy_id}/pre-screening

Delete pre-screening configuration.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Response:**

```typescript
interface PreScreeningDeleteResponse {
  status: "deleted";
  message: string;
  vacancy_id: string;
  vacancy_status: VacancyStatus;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |
| 404 | No pre-screening to delete |

---

### POST /vacancies/{vacancy_id}/pre-screening/publish

Publish pre-screening and create agents.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Request Body:**

```typescript
interface PublishPreScreeningRequest {
  enable_voice?: boolean;   // default: true
  enable_whatsapp?: boolean; // default: true
  enable_cv?: boolean;       // default: false
}
```

**Response:**

```typescript
interface PublishPreScreeningResponse {
  status: "published";
  published_at: string;
  elevenlabs_agent_id?: string;
  whatsapp_agent_id?: string;
  is_online: boolean;
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | No pre-screening to publish |
| 404 | Vacancy not found |
| 500 | Failed to create ElevenLabs agent |

---

### PATCH /vacancies/{vacancy_id}/pre-screening/status

Update pre-screening status and channel toggles.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Request Body:**

```typescript
interface StatusUpdateRequest {
  is_online?: boolean;
  voice_enabled?: boolean;
  whatsapp_enabled?: boolean;
  cv_enabled?: boolean;
}
```

**Response:**

```typescript
interface StatusUpdateResponse {
  status: "updated";
  is_online: boolean;
  channels: {
    voice: boolean;
    whatsapp: boolean;
    cv: boolean;
  };
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | Pre-screening not published yet |
| 404 | Vacancy not found |
| 404 | No pre-screening found |

---

### GET /vacancies/{vacancy_id}/pre-screening/settings

Get per-vacancy pre-screening channel settings.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Response:**

```typescript
interface PreScreeningSettingsResponse {
  voice_enabled: boolean;
  whatsapp_enabled: boolean;
  cv_enabled: boolean;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | No pre-screening found |

---

### PATCH /vacancies/{vacancy_id}/pre-screening/settings

Update per-vacancy pre-screening channel settings. All fields optional.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Request Body:**

```typescript
interface PreScreeningSettingsUpdateRequest {
  voice_enabled?: boolean;
  whatsapp_enabled?: boolean;
  cv_enabled?: boolean;
}
```

**Response:** Same as `PreScreeningSettingsResponse` above.

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | No fields to update |
| 404 | No pre-screening found |

---

### GET /pre-screening/config

Get the global pre-screening agent configuration (single row, applies to all screenings).

**Auth:** None

**Response:**

```typescript
interface PreScreeningConfigResponse {
  id: string;                    // Config row UUID
  max_unrelated_answers: number; // Max off-topic answers before ending (default: 2)
  schedule_days_ahead: number;   // Days ahead to offer for scheduling (default: 3)
  schedule_start_offset: number; // Days offset before first available slot (default: 1)
  planning_mode: string;         // "funnel" | "direct" | "calendar"
  intro_message: string | null;  // Custom intro message
  success_message: string | null;// Custom success message
  require_consent: boolean;      // Ask candidate consent before screening
  allow_escalation: boolean;     // Allow candidates to request a human
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Pre-screening config not found |

---

### PATCH /pre-screening/config

Update the global pre-screening agent configuration. All fields optional.

**Auth:** None

**Request Body:**

```typescript
interface PreScreeningConfigUpdateRequest {
  max_unrelated_answers?: number;
  schedule_days_ahead?: number;
  schedule_start_offset?: number;
  planning_mode?: string;         // "funnel" | "direct" | "calendar"
  intro_message?: string;
  success_message?: string;
  require_consent?: boolean;
  allow_escalation?: boolean;
}
```

**Response:** Same as `PreScreeningConfigResponse` above.

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | No fields to update |
| 404 | Pre-screening config not found |

---

## Interview Analysis

Evaluates pre-screening interview questions for quality, clarity, drop-off risk, and provides actionable tips.

### `POST /pre-screenings/{pre_screening_id}/analyze`

Run interview analysis. If `questions` and `vacancy` are provided in the body, uses those (draft mode — result not persisted). Otherwise loads from DB and caches the result.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pre_screening_id` | UUID | The pre-screening configuration ID |

**Request Body (optional):**

```json
{
  "questions": [
    { "id": "ko_1", "text": "Mag je wettelijk werken in België?", "type": "knockout" },
    { "id": "qual_1", "text": "Hoe goed ben je met cijfers?", "type": "qualifying" }
  ],
  "vacancy": { "id": "v1", "title": "Bakkerijmedewerker", "description": "..." }
}
```

**Response (200):**

```json
{
  "summary": {
    "completionRate": 64,
    "avgTimeSeconds": 107,
    "verdict": "good",
    "verdictHeadline": "Dit interview is goed opgebouwd",
    "verdictDescription": "De knockout-vragen zijn helder en snel te beantwoorden...",
    "oneLiner": "Goed interview met heldere knockout-vragen, let op bij de open kwalificatievragen."
  },
  "questions": [
    {
      "questionId": "ko_1",
      "completionRate": 98,
      "avgTimeSeconds": 8,
      "dropOffRisk": "low",
      "clarityScore": 95,
      "tip": null
    }
  ],
  "funnel": [
    { "step": "Start", "candidates": 200 },
    { "step": "ko_1", "candidates": 196 },
    { "step": "Voltooid", "candidates": 128 }
  ]
}
```

**Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| `summary.completionRate` | int (0-100) | Estimated % of candidates completing the full interview |
| `summary.avgTimeSeconds` | int | Estimated total duration in seconds |
| `summary.verdict` | `"excellent"` \| `"good"` \| `"needs_work"` \| `"poor"` | Overall quality rating |
| `summary.verdictHeadline` | string | Dutch headline for the UI banner |
| `summary.verdictDescription` | string | 1-2 sentence Dutch explanation with actionable advice |
| `summary.oneLiner` | string | Single Dutch sentence for Teams notifications |
| `questions[].questionId` | string | Maps to input question ID (ko_N / qual_N) |
| `questions[].completionRate` | int (0-100) | Cumulative completion rate at this question |
| `questions[].avgTimeSeconds` | int | Estimated seconds for this question |
| `questions[].dropOffRisk` | `"low"` \| `"medium"` \| `"high"` | Risk level |
| `questions[].clarityScore` | int (0-100) | Clarity and unambiguity score |
| `questions[].tip` | string \| null | Improvement suggestion in Dutch, null if fine |
| `funnel[].step` | string | `"Start"`, question ID, or `"Voltooid"` |
| `funnel[].candidates` | int | Simulated remaining candidates (starts at 200) |

### `GET /pre-screenings/{pre_screening_id}/analysis`

Get cached analysis result. Returns 404 if no analysis has been run yet.

**Response (200):** Same shape as POST response above.

**Errors:**

| Status | Description |
|--------|-------------|
| 404 | No analysis found (run POST first) |
| 400 | Invalid pre-screening ID format |

---

## Interviews

### Vacancy Snippet Linking

All interview questions (knockout and qualification) include a `vacancy_snippet` field that contains the exact text from the vacancy that the question is based on. This enables the frontend to:

- Visually highlight which part of the vacancy each question relates to
- Show tooltips linking questions to their source text
- Validate that questions are grounded in actual vacancy requirements

**Example:**
```json
{
  "id": "ko_2",
  "question": "Kan je werken in een 2-ploegensysteem?",
  "vacancy_snippet": "Je werkt in een 2-ploegensysteem (6u-14u / 14u-22u)"
}
```

For standard questions not derived from specific vacancy text (e.g., work permit), the snippet indicates this:
```json
{
  "vacancy_snippet": "Standaard knockout vraag - niet afgeleid van specifieke vacaturetekst"
}
```

---

### POST /interview/generate

Generate interview questions from a vacancy. The backend fetches the vacancy text from the database. Returns SSE stream.

**Auth:** None

**Request Body:**

```typescript
interface GenerateInterviewRequest {
  vacancy_id: string;   // UUID of the vacancy to generate questions for
  session_id?: string;  // Optional: reuse session for feedback
}
```

**Response:** Server-Sent Events

**SSE Events:**

```typescript
// Status update
interface StatusEvent {
  type: "status";
  status: "thinking";
  message: string;  // Dutch: "Vacaturetekst ontvangen, begin met analyse..."
}

// Thinking step (shows reasoning)
interface ThinkingEvent {
  type: "thinking";
  step: string;
  content: string;
}

// Complete with generated interview
interface CompleteEvent {
  type: "complete";
  session_id: string;
  interview: {
    intro: string;
    knockout_questions: Array<{
      id: string;
      question: string;
      vacancy_snippet: string;  // Exact text from vacancy this question is based on
    }>;
    knockout_failed_action: string;
    qualification_questions: Array<{
      id: string;
      question: string;
      ideal_answer: string;
      vacancy_snippet: string;  // Exact text from vacancy this question is based on
    }>;
    final_action: string;
  };
}

// Error
interface ErrorEvent {
  type: "error";
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | Vacancy has no description text |
| 404 | Vacancy not found |

---

### POST /interview/feedback

Submit feedback to refine generated interview. Returns SSE stream.

**Auth:** None

**Request Body:**

```typescript
interface FeedbackRequest {
  session_id: string;
  message: string;
}
```

**Response:** Server-Sent Events (same format as generate)

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | session_id required |
| 404 | Session not found |

---

### GET /interview/session/{session_id}

Get current session state.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response:**

```typescript
interface SessionResponse {
  session_id: string;
  interview: {
    intro: string;
    knockout_questions: Array<{ id: string; question: string; vacancy_snippet: string }>;
    knockout_failed_action: string;
    qualification_questions: Array<{ id: string; question: string; ideal_answer: string; vacancy_snippet: string }>;
    final_action: string;
  };
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Session not found |

---

### POST /interview/reorder

Reorder interview questions.

**Auth:** None

**Request Body:**

```typescript
interface ReorderRequest {
  session_id: string;
  knockout_order?: string[];      // Question IDs in new order
  qualification_order?: string[]; // Question IDs in new order
}
```

**Response:**

```typescript
interface ReorderResponse {
  status: "reordered";
  interview: { /* same as SessionResponse.interview */ };
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | session_id required |
| 400 | Invalid question ID in order |
| 404 | Session not found |

---

### POST /interview/delete

Delete a question from interview.

**Auth:** None

**Request Body:**

```typescript
interface DeleteQuestionRequest {
  session_id: string;
  question_id: string;  // e.g., "ko_1" or "qual_2"
}
```

**Response:**

```typescript
interface DeleteQuestionResponse {
  status: "deleted";
  deleted: string;
  interview: { /* updated interview */ };
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | session_id required |
| 400 | question_id required |
| 404 | Session not found |
| 404 | Question not found |

---

### POST /interview/add

Add a new question to interview.

**Auth:** None

**Request Body:**

```typescript
interface AddQuestionRequest {
  session_id: string;
  question_type: QuestionType;
  question: string;
  ideal_answer?: string;       // Required for qualification questions
  vacancy_snippet?: string;    // Text from vacancy this question relates to
}
```

**Response:**

```typescript
interface AddQuestionResponse {
  status: "added";
  added: string;  // New question ID
  question: {
    id: string;
    question: string;
    ideal_answer?: string;
    vacancy_snippet?: string;  // Text from vacancy this question relates to
  };
  interview: { /* updated interview */ };
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | session_id required |
| 400 | question_type must be "knockout" or "qualification" |
| 400 | ideal_answer required for qualification questions |
| 404 | Session not found |

---

### POST /interview/restore-session

Restore interview session from saved pre-screening.

**Auth:** None

**Request Body:**

```typescript
interface RestoreSessionRequest {
  vacancy_id: string;
}
```

**Response:**

```typescript
interface RestoreSessionResponse {
  status: "restored";
  session_id: string;
  interview: { /* restored interview */ };
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 404 | Vacancy not found |
| 404 | No pre-screening to restore |

---

## Screening

### POST /screening/chat

Real-time chat screening conversation. Returns SSE stream.

**Auth:** None

**Request Body:**

```typescript
interface ScreeningChatRequest {
  vacancy_id: string;
  message: string;           // Use "START" for first message
  session_id?: string;       // Continue existing conversation
  candidate_name?: string;   // Required for first message
  is_test?: boolean;         // Mark as test conversation
}
```

**Response:** Server-Sent Events

**SSE Events:**

```typescript
// Status
interface StatusEvent {
  type: "status";
  status: "thinking";
  message: string;  // "Antwoord genereren..."
}

// Complete
interface CompleteEvent {
  type: "complete";
  message: string;
  session_id: string;
}

// Error
interface ErrorEvent {
  type: "error";
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | candidate_name required for first message |
| 404 | Vacancy not found |
| 404 | No pre-screening found |

---

### GET /screening/conversations/{conversation_id}

Get conversation details.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `conversation_id` | string (UUID) | Conversation identifier |

**Response:**

```typescript
interface ScreeningConversationResponse {
  id: string;
  vacancy_id: string;
  candidate_name: string;
  candidate_email?: string;
  status: string;
  started_at: string;
  completed_at?: string;
  message_count: number;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid conversation ID format |
| 404 | Conversation not found |

---

### POST /screening/conversations/{conversation_id}/complete

Manually complete a conversation.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `conversation_id` | string (UUID) | Conversation identifier |

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `qualified` | boolean | Yes | Whether candidate qualified |

**Response:**

```typescript
interface CompleteConversationResponse {
  status: "completed";
  conversation_id: string;
  application_id: string;
  qualified: boolean;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid conversation ID format |
| 400 | qualified parameter required |
| 404 | Conversation not found |

---

### POST /vacancies/{vacancy_id}/simulate

Simulate a screening interview. Returns SSE stream.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Request Body:**

```typescript
interface SimulateInterviewRequest {
  persona?: "qualified" | "borderline" | "unqualified" | "rushed" | "enthusiastic" | "custom";
  custom_persona?: string;    // Required when persona="custom"
  candidate_name?: string;
}
```

**Response:** Server-Sent Events

**SSE Events:**

```typescript
// Simulation start
interface StartEvent {
  type: "start";
  candidate_name: string;
  persona: string;
}

// Agent message
interface AgentEvent {
  type: "agent";
  message: string;
}

// Candidate response
interface CandidateEvent {
  type: "candidate";
  message: string;
}

// Q&A pair summary
interface QAPairEvent {
  type: "qa_pair";
  question_id: string;
  question: string;
  answer: string;
  passed?: boolean;
  score?: number;
}

// Complete
interface CompleteEvent {
  type: "complete";
  application_id: string;
  qualified: boolean;
  summary: string;
}

// Error
interface ErrorEvent {
  type: "error";
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | custom_persona required when persona is "custom" |
| 404 | Vacancy not found |
| 404 | No pre-screening found |

---

## Outbound

### POST /screening/outbound

Initiate outbound screening via voice call or WhatsApp.

**Auth:** None

**Request Body:**

```typescript
interface OutboundScreeningRequest {
  vacancy_id: string;
  channel: InterviewChannel;     // "voice" or "whatsapp"
  phone_number: string;          // E.164 format (+31612345678)
  first_name: string;
  last_name: string;
  is_test?: boolean;
  test_conversation_id?: string; // For testing without real call
}
```

**Response:**

```typescript
interface OutboundScreeningResponse {
  success: boolean;
  message: string;
  channel: InterviewChannel;
  conversation_id?: string;
  application_id?: string;
  call_sid?: string;              // For voice calls
  whatsapp_message_sid?: string;  // For WhatsApp
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | No pre-screening configured for this vacancy |
| 400 | Pre-screening is not published yet |
| 400 | Pre-screening is offline |
| 400 | Voice agent not configured |
| 400 | WhatsApp agent not configured |
| 404 | Vacancy not found |
| 500 | ELEVENLABS_API_KEY required |
| 500 | LIVEKIT_URL not configured |
| 500 | TWILIO_WHATSAPP_NUMBER not configured |

---

### POST /webhook/livekit/call-result

Receive structured call results from the LiveKit pre-screening v2 voice agent.

Called by the agent's `_on_session_complete` callback when a call ends. Processes results into `application_answers`, updates application status, fires workflow events, and triggers notifications.

**Auth:** `X-Webhook-Secret` header (must match `LIVEKIT_WEBHOOK_SECRET` env var)

**Request Body:**

```typescript
interface LiveKitCallResultPayload {
  call_id: string;                    // Room name used as correlation key
  status: string;                     // "completed" | "voicemail" | "not_interested" | "knockout_failed" | "escalated" | "unclear" | "irrelevant" | "incomplete"
  consent_given?: boolean;
  voicemail_detected: boolean;
  passed_knockout: boolean;
  interested_in_alternatives: boolean;
  knockout_answers: {
    question_id: string;
    internal_id: string;              // DB question UUID for round-tripping
    question_text: string;
    result: string;                   // "pass" | "fail" | "unclear" | "irrelevant" | "recruiter_requested"
    raw_answer: string;
    candidate_note: string;
  }[];
  open_answers: {
    question_id: string;
    internal_id: string;
    question_text: string;
    answer_summary: string;
    candidate_note: string;
  }[];
  chosen_timeslot?: string;           // e.g. "dinsdag 4 maart om 10 uur"
  scheduling_preference?: string;
}
```

**Response:**

```typescript
{
  status: "processed";
  application_id: string;
  qualified: boolean;
  call_id: string;
}
```

---

### POST /screening/web-call

Create a VAPI web call session for browser-based voice simulation.

This is for testing/demo purposes only - no database records are created. Returns configuration for the frontend to use with VAPI Web SDK to start a voice call directly in the browser.

**Auth:** None

**Request Body:**

```typescript
interface VapiWebCallRequest {
  vacancy_id: string;
  candidate_name?: string;  // Default: "Test Kandidaat"
  first_name?: string;      // Extracted from candidate_name if not provided
}
```

**Response:**

```typescript
interface VapiWebCallResponse {
  success: boolean;
  squad_id: string;              // VAPI squad ID for the call
  vapi_public_key: string;       // Public key for VAPI Web SDK initialization
  assistant_overrides: {
    variableValues: {
      greeting: string;          // Dutch time-based greeting
      first_name: string;
      vacancy_id: string;
      vacancy_title: string;
      knockout_questions: string;      // Formatted list of knockout questions
      qualification_questions: string; // Formatted list of qualification questions
      first_knockout_question: string;
      first_qualification_question: string;
      pre_screening_id: string;
    };
    server?: {
      url: string;
      timeoutSeconds: number;
    };
  };
}
```

**Frontend Usage:**

```typescript
import Vapi from '@vapi-ai/web';

// 1. Get config from backend
const response = await fetch('/api/screening/web-call', {
  method: 'POST',
  body: JSON.stringify({ vacancy_id: '...', candidate_name: 'Test' })
});
const config = await response.json();

// 2. Initialize VAPI with public key
const vapi = new Vapi(config.vapi_public_key);

// 3. Start call with squad (pass null for first two params when using squad)
vapi.start(null, config.assistant_overrides, config.squad_id);

// 4. Handle events
vapi.on('call-start', () => console.log('Call started'));
vapi.on('call-end', () => console.log('Call ended'));
vapi.on('message', (msg) => {
  if (msg.type === 'transcript') {
    console.log(`${msg.role}: ${msg.transcript}`);
  }
});
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | No pre-screening configured for this vacancy |
| 400 | Pre-screening is not published yet |
| 400 | Pre-screening is offline |
| 404 | Vacancy not found |
| 500 | VAPI_PUBLIC_KEY not configured |

---

## Playground

### POST /playground/start

Start a browser-based voice playground session using LiveKit WebRTC.

Creates a LiveKit access token with embedded agent dispatch. When the browser connects using this token, LiveKit auto-creates the room and starts the pre-screening V2 voice agent. No database records are created — this is for testing/demo only.

**Auth:** None

**Request Body:**

```typescript
interface PlaygroundStartRequest {
  vacancy_id: string;
  candidate_name?: string;     // Default: "Playground Kandidaat"
  persona_name?: string;       // Default: "Anna" — voice persona name used in prompts and voicemail (e.g. "Eva", "Sophie")
  start_agent?: string;        // Skip to specific step: "greeting" | "screening" | "open_questions" | "scheduling"
  require_consent?: boolean;   // Default: false
  candidate_known?: boolean;   // Default: false — known candidate with existing data
  allow_escalation?: boolean;  // Default: false — allow handoff to human recruiter
  voice_id?: string;           // ElevenLabs voice ID override (defaults to DB config)
  known_answers?: Record<string, string>;  // Pre-known knockout answers by question ID to skip (e.g. {"ko_1": "ja", "ko_2": "ja"})
  existing_booking_date?: string;          // Existing appointment to skip scheduling (e.g. "dinsdag 4 maart om 10 uur")
}
```

**Response:**

```typescript
interface PlaygroundStartResponse {
  success: boolean;
  livekit_url: string;        // WebSocket URL for LiveKit connection
  access_token: string;       // JWT token for browser to join room
  room_name: string;          // Room identifier (playground-{id})
}
```

**Frontend Usage:**

```typescript
import { Room, RoomEvent } from 'livekit-client';

// 1. Get token from backend
const response = await fetch('/playground/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ vacancy_id: '...', candidate_name: 'Test' })
});
const { livekit_url, access_token } = await response.json();

// 2. Connect to room
const room = new Room();
await room.connect(livekit_url, access_token);

// 3. Enable microphone
await room.localParticipant.setMicrophoneEnabled(true);

// 4. Agent audio auto-subscribes
room.on(RoomEvent.TrackSubscribed, (track) => {
  if (track.kind === 'audio') track.attach();
});

// 5. Disconnect when done
room.disconnect();
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID |
| 400 | No pre-screening configured for this vacancy |
| 400 | Pre-screening not published |
| 400 | Pre-screening is offline |
| 404 | Vacancy not found |
| 500 | LIVEKIT_URL not configured |

---

## CV Analysis

### POST /cv/analyze

Analyze a CV against screening questions.

**Auth:** None

**Request Body:**

```typescript
interface CVQuestionRequest {
  id: string;
  question: string;
  ideal_answer?: string;
}

interface CVAnalyzeRequest {
  pdf_base64: string;
  knockout_questions: CVQuestionRequest[];
  qualification_questions: CVQuestionRequest[];
}
```

**Response:**

```typescript
interface CVQuestionAnalysisResponse {
  id: string;
  question_text: string;
  cv_evidence: string;
  is_answered: boolean;
  clarification_needed?: string;
}

interface CVAnalyzeResponse {
  knockout_analysis: CVQuestionAnalysisResponse[];
  qualification_analysis: CVQuestionAnalysisResponse[];
  cv_summary: string;
  clarification_questions: string[];
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid PDF data |
| 400 | knockout_questions required |
| 400 | qualification_questions required |

---

## Data Query

### POST /data-query

Natural language query on recruitment data. Returns SSE stream.

**Auth:** None

**Request Body:**

```typescript
interface DataQueryRequest {
  question: string;
  session_id?: string;  // Continue context
}
```

**Response:** Server-Sent Events

**SSE Events:**

```typescript
// Status
interface StatusEvent {
  type: "status";
  status: "thinking";
  message: string;
}

// Thinking step
interface ThinkingEvent {
  type: "thinking";
  step: string;
  content: string;
}

// Complete
interface CompleteEvent {
  type: "complete";
  session_id: string;
  answer: string;
  data?: any;  // Structured data if applicable
}

// Error
interface ErrorEvent {
  type: "error";
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | question required |

---

### GET /data-query/session/{session_id}

Get data query session state.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response:**

```typescript
interface DataQuerySessionResponse {
  session_id: string;
  state: any;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Session not found |

---

### DELETE /data-query/session/{session_id}

Delete a data query session.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `session_id` | string | Session identifier |

**Response:**

```typescript
interface DeleteSessionResponse {
  status: "deleted";
  message: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Session not found |

---

## Documents

### POST /documents/verify

Verify a document image (ID, license, certificate).

**Auth:** None

**Request Body:**

```typescript
interface DocumentVerifyRequest {
  image_base64: string;
  application_id?: string;
  candidate_name?: string;
  document_type_hint?: DocumentCategory;
  save_verification?: boolean;
}
```

**Response:**

```typescript
interface FraudIndicator {
  indicator_type: "synthetic_image" | "digital_manipulation" | "inconsistent_fonts" | "poor_quality" | "tampered_data" | "inconsistent_layout" | "suspicious_artifacts";
  description: string;
  severity: "low" | "medium" | "high";
  confidence: number;  // 0.0-1.0
}

interface DocumentVerifyResponse {
  document_category: DocumentCategory;
  document_category_confidence: number;
  extracted_name?: string;
  name_extraction_confidence: number;
  name_match_performed: boolean;
  name_match_result?: "exact_match" | "partial_match" | "no_match" | "ambiguous";
  name_match_confidence?: number;
  name_match_details?: string;
  fraud_risk_level: FraudRiskLevel;
  fraud_indicators: FraudIndicator[];
  overall_fraud_confidence: number;
  image_quality: ImageQuality;
  readability_issues: string[];
  verification_passed: boolean;
  verification_summary: string;
  verification_id?: string;
  processed_at: string;
  raw_agent_response?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | image_base64 required |
| 400 | Invalid base64 image data |
| 404 | Application not found (when application_id provided) |

---

## Document Collection

### POST /documents/collect

Initiate document collection via WhatsApp.

**Auth:** None

**Request Body:**

```typescript
interface OutboundDocumentRequest {
  vacancy_id: string;
  candidate_name: string;
  candidate_lastname: string;
  whatsapp_number: string;  // E.164 format
  documents: Array<"id_card" | "driver_license">;
  application_id?: string;
}
```

**Response:**

```typescript
interface OutboundDocumentResponse {
  conversation_id: string;
  vacancy_id: string;
  candidate_name: string;
  whatsapp_number: string;
  documents_requested: string[];
  opening_message: string;
  application_id?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID format |
| 400 | Invalid phone number format |
| 400 | At least one document type required |
| 404 | Vacancy not found |

---

### GET /documents/debug/{phone_number}

Debug active document collections for a phone number.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `phone_number` | string | Phone number (with or without +) |

**Response:**

```typescript
interface DocumentDebugResponse {
  document_collections: Array<{
    conversation_id: string;
    status: string;
    documents_requested: string[];
  }>;
  screening_conversations: Array<{
    conversation_id: string;
    status: string;
  }>;
}
```

---

### POST /webhook/documents

Twilio webhook for document collection messages.

**Auth:** None (Twilio trusted)

**Request Body:** (Twilio form data)

| Field | Type | Description |
|-------|------|-------------|
| `Body` | string | Message text |
| `From` | string | WhatsApp number (whatsapp:+1234567890) |
| `NumMedia` | number | Number of media attachments |
| `MediaUrl0` | string | URL of first media (if any) |
| `MediaContentType0` | string | MIME type of first media |

**Response:** TwiML XML

**User-Facing Messages (Dutch):**

| Scenario | Message |
|----------|---------|
| No active collection | `Geen actieve document verzameling gevonden. Neem contact op met ons voor hulp.` |
| Max retries exceeded | `Na 3 pogingen kunnen we helaas niet verder. Een medewerker zal binnenkort contact met je opnemen.` |

---

## Document Collection v2 (Workspace-Scoped)

All endpoints under `/workspaces/{workspace_id}/document-collection/`. Requires authentication (`Bearer` token).

**Base path:** `/workspaces/{workspace_id}/document-collection`

### Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/document-types` | List document types |
| POST | `/document-types` | Create document type |
| PATCH | `/document-types/{id}` | Update document type |
| DELETE | `/document-types/{id}` | Soft-delete (is_active=false) |
| GET | `/configs` | List collection configs |
| POST | `/configs` | Create config |
| GET | `/configs/{id}` | Get config with required documents |
| PUT | `/configs/{id}` | Update config |
| DELETE | `/configs/{id}` | Delete config |
| PATCH | `/configs/{id}/status` | Toggle online/whatsapp flags |
| GET | `/configs/{id}/documents` | List required documents |
| PUT | `/configs/{id}/documents` | Replace all required documents |
| GET | `/resolve` | Resolve which documents are needed |
| GET | `/collections` | List document collections |
| GET | `/collections/{id}` | Get collection with messages + uploads |
| POST | `/collections/{id}/abandon` | Mark collection as abandoned |
| POST | `/start` | Start a new document collection |

---

### Types

```typescript
// --- Document Types ---

interface DocumentTypeResponse {
  id: string;                    // UUID
  workspace_id: string;          // UUID
  slug: string;                  // e.g. "id_card", "drivers_license"
  name: string;                  // Display name, e.g. "ID-kaart"
  description?: string;
  category: string;              // "identity" | "certificate" | "financial" | "other"
  requires_front_back: boolean;  // If true, agent collects front + back
  is_verifiable: boolean;        // If true, document_recognition_agent can verify
  icon?: string;                 // Frontend icon name
  is_default: boolean;           // Auto-included in workspace default onboarding
  is_active: boolean;
  sort_order: number;
  created_at: string;            // ISO timestamp
  updated_at: string;
}

interface DocumentTypeCreate {
  slug: string;                  // ^[a-z0-9_]+$ (1-50 chars)
  name: string;                  // 1-200 chars
  description?: string;
  category?: string;             // Default: "identity"
  requires_front_back?: boolean; // Default: false
  is_verifiable?: boolean;       // Default: false
  icon?: string;
  is_default?: boolean;          // Default: false
  sort_order?: number;           // Default: 0
}

interface DocumentTypeUpdate {
  name?: string;
  description?: string;
  category?: string;
  requires_front_back?: boolean;
  is_verifiable?: boolean;
  icon?: string;
  is_default?: boolean;
  is_active?: boolean;
  sort_order?: number;
}

// --- Collection Configs ---

interface CollectionConfigResponse {
  id: string;
  workspace_id: string;
  vacancy_id?: string;           // null = workspace default config
  name?: string;
  intro_message?: string;        // Agent opening message template
  status: string;                // "draft" | "active" | "archived"
  is_online: boolean;
  whatsapp_enabled: boolean;
  created_at: string;
  updated_at: string;
}

interface CollectionConfigDetailResponse extends CollectionConfigResponse {
  documents: CollectionRequirementResponse[];  // Required documents for this config
}

interface CollectionRequirementResponse {
  id: string;
  document_type_id: string;
  document_type: DocumentTypeResponse;  // Full document type object
  position: number;                     // Collection order
  is_required: boolean;                 // Required vs optional
  notes?: string;                       // Instructions for this doc
}

interface CollectionConfigCreate {
  vacancy_id?: string;           // null = workspace default
  name?: string;
  intro_message?: string;
  document_type_ids: string[];   // UUIDs of document types to require
}

interface CollectionConfigUpdate {
  name?: string;
  intro_message?: string;
  status?: string;
  is_online?: boolean;
  whatsapp_enabled?: boolean;
  document_type_ids?: string[];  // If provided, replaces all requirements
}

interface CollectionConfigStatusUpdate {
  is_online?: boolean;
  whatsapp_enabled?: boolean;
}

// --- Requirements ---

interface RequirementItem {
  document_type_id: string;
  position?: number;             // Default: 0
  is_required?: boolean;         // Default: true
  notes?: string;
}

interface SetRequirementsRequest {
  documents: RequirementItem[];
}

// --- Document Resolution ---

interface ResolveDocumentsResponse {
  documents: DocumentTypeResponse[];
  source: string;                // "default" | "vacancy" | "merged"
}

// --- Collections ---

interface DocumentCollectionResponse {
  id: string;
  config_id: string;
  workspace_id: string;
  vacancy_id?: string;
  vacancy_title?: string;            // Vacancy title (joined from vacancies table)
  application_id?: string;
  candidate_name: string;
  candidate_phone?: string;
  status: string;                // "active" | "completed" | "needs_review" | "abandoned"
  progress: string;              // Derived from messages: "pending" | "started" | "in_progress"
  channel: string;               // "whatsapp"
  retry_count: number;
  message_count: number;
  documents_collected: number;   // Count of verified uploads
  documents_total: number;       // Total required documents (from documents_required array)
  started_at: string;
  updated_at: string;
  completed_at?: string;
}

interface DocumentCollectionDetailResponse extends DocumentCollectionResponse {
  messages: CollectionMessageResponse[];
  uploads: CollectionUploadResponse[];
  documents_required: DocumentTypeResponse[];  // Full document type objects resolved from stored slugs
}

interface CollectionMessageResponse {
  role: string;                  // "user" | "agent" | "system"
  message: string;
  created_at: string;
}

interface CollectionUploadResponse {
  id: string;
  document_type_id?: string;
  document_side: string;         // "front" | "back" | "single"
  verification_passed?: boolean;
  status: string;                // "pending" | "verified" | "rejected" | "needs_review"
  uploaded_at: string;
}

// --- Start Collection ---

interface StartCollectionRequest {
  candidate_name: string;        // min 1 char
  candidate_lastname: string;    // min 1 char
  whatsapp_number: string;       // E.164: ^\+?[1-9]\d{1,14}$
  vacancy_id?: string;           // If provided, uses vacancy-specific config
  application_id?: string;
  candidate_id?: string;
}

interface StartCollectionResponse {
  collection_id: string;
  config_id: string;
  candidate_name: string;
  whatsapp_number: string;
  documents_required: DocumentTypeResponse[];
  source: string;                // "default" | "vacancy" | "merged"
}
```

---

### GET /document-types

List all document types for a workspace.

**Auth:** Bearer token

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `category` | string | No | - | Filter by category (`identity`, `certificate`, `financial`, `other`) |
| `is_active` | boolean | No | `true` | Filter by active status |

**Response:** `DocumentTypeResponse[]`

---

### POST /document-types

Create a new document type.

**Auth:** Bearer token

**Request Body:** `DocumentTypeCreate`

**Response:** `DocumentTypeResponse` (201 Created)

---

### PATCH /document-types/{doc_type_id}

Update a document type. All fields optional.

**Auth:** Bearer token

**Request Body:** `DocumentTypeUpdate`

**Response:** `DocumentTypeResponse`

---

### DELETE /document-types/{doc_type_id}

Soft-delete a document type (sets `is_active=false`).

**Auth:** Bearer token

**Response:** `{ "success": true }`

---

### GET /configs

List collection configs for a workspace.

**Auth:** Bearer token

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `vacancy_id` | string (UUID) | No | Filter by vacancy |

**Response:** `CollectionConfigResponse[]`

---

### POST /configs

Create a collection config. Set `vacancy_id=null` for workspace default.

**Auth:** Bearer token

**Request Body:** `CollectionConfigCreate`

**Response:** `CollectionConfigDetailResponse` (201 Created)

---

### GET /configs/{config_id}

Get a config with its required documents.

**Auth:** Bearer token

**Response:** `CollectionConfigDetailResponse`

---

### PUT /configs/{config_id}

Update a config. If `document_type_ids` is provided, replaces all requirements.

**Auth:** Bearer token

**Request Body:** `CollectionConfigUpdate`

**Response:** `CollectionConfigDetailResponse`

---

### DELETE /configs/{config_id}

Delete a collection config. Requirements cascade-delete.

**Auth:** Bearer token

**Response:** `{ "success": true }`

---

### PATCH /configs/{config_id}/status

Toggle `is_online` and/or `whatsapp_enabled` flags.

**Auth:** Bearer token

**Request Body:** `CollectionConfigStatusUpdate`

**Response:** `CollectionConfigResponse`

---

### GET /configs/{config_id}/documents

List required documents for a config.

**Auth:** Bearer token

**Response:** `CollectionRequirementResponse[]`

---

### PUT /configs/{config_id}/documents

Replace all required documents for a config.

**Auth:** Bearer token

**Request Body:** `SetRequirementsRequest`

**Response:** `CollectionRequirementResponse[]`

---

### GET /resolve

Resolve which documents are needed for a candidate. Merges workspace defaults with vacancy-specific requirements.

**Auth:** Bearer token

**Query Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `vacancy_id` | string (UUID) | No | If provided, merges vacancy config with defaults |

**Response:** `ResolveDocumentsResponse`

**Resolution Logic:**
1. No `vacancy_id` → returns workspace default docs
2. `vacancy_id` with config → merges default + vacancy-specific (dedup by type, vacancy overrides)
3. `vacancy_id` without config → falls back to defaults

---

### GET /collections

List document collections with filtering and pagination.

**Auth:** Bearer token

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `vacancy_id` | string (UUID) | No | - | Filter by vacancy |
| `status` | string | No | - | Filter: `active`, `completed`, `needs_review`, `abandoned` |
| `limit` | number | No | 50 | Results per page (1-200) |
| `offset` | number | No | 0 | Pagination offset |

**Response:** `PaginatedResponse<DocumentCollectionResponse>`

```typescript
{
  items: DocumentCollectionResponse[];
  total: number;
  limit: number;
  offset: number;
}
```

---

### GET /collections/{collection_id}

Get a document collection with its messages and uploads.

**Auth:** Bearer token

**Response:** `DocumentCollectionDetailResponse`

---

### POST /collections/{collection_id}/abandon

Mark a document collection as abandoned.

**Auth:** Bearer token

**Response:** `{ "success": true }`

---

### POST /start

Start a new document collection. Creates database records and resolves which documents are needed. Does NOT send WhatsApp messages (agent integration is a later phase).

**Auth:** Bearer token

**Request Body:** `StartCollectionRequest`

**Response:** `StartCollectionResponse` (201 Created)

---

### Default Seeded Document Types

Every workspace is seeded with these defaults:

| Slug | Name | Category | Icon (Lucide) | Front/Back | Verifiable | Default |
|------|------|----------|---------------|------------|------------|---------|
| `id_card` | ID-kaart | identity | `credit-card` | Yes | Yes | Yes |
| `driver_license` | Rijbewijs | certificate | `car` | No | Yes | No |
| `passport` | Paspoort | identity | `book-open` | No | Yes | No |
| `bank_details` | Bankgegevens | financial | `landmark` | No | No | No |
| `medical_cert` | Medisch attest | certificate | `heart-pulse` | No | Yes | No |
| `work_permit` | Arbeidsvergunning | certificate | `file-badge` | No | Yes | No |
| `diploma` | Diploma/Certificaat | certificate | `graduation-cap` | No | Yes | No |

---

## Webhooks

### POST /webhook

Main Twilio webhook for WhatsApp messages (smart routing).

**Auth:** None (Twilio trusted)

**Request Body:** (Twilio form data)

| Field | Type | Description |
|-------|------|-------------|
| `Body` | string | Message text |
| `From` | string | WhatsApp number (whatsapp:+1234567890) |
| `NumMedia` | number | Number of media attachments |
| `MediaUrl0` | string | URL of first media (if any) |
| `MediaContentType0` | string | MIME type of first media |

**Response:** TwiML XML

**Routing Priority:**
1. Active document collection → Document collection handler
2. Active pre-screening conversation → Screening handler
3. No active conversation → Generic fallback

**User-Facing Messages (Dutch):**

| Scenario | Message |
|----------|---------|
| No active conversation | `Hallo! Er is momenteel geen actief gesprek. Als je bent uitgenodigd voor een screening, wacht dan even op ons bericht.` |

---

### POST /webhook/elevenlabs

ElevenLabs voice call webhook.

**Auth:** HMAC SHA256 signature validation

**Headers:**

| Header | Description |
|--------|-------------|
| `elevenlabs-signature` | `t=timestamp,v0=hash` format |

**Request Body:**

```typescript
interface ElevenLabsWebhookData {
  agent_id: string;
  conversation_id: string;
  status?: string;
  transcript: Array<{
    role: "agent" | "user";
    message: string;
    timestamp?: number;
  }>;
  metadata?: Record<string, any>;
  analysis?: Record<string, any>;
}

interface ElevenLabsWebhookPayload {
  type: "post_call_transcription" | "post_call_audio" | "call_initiation_failure";
  event_timestamp: number;
  data: ElevenLabsWebhookData;
}
```

**Response:**

```typescript
interface ElevenLabsWebhookResponse {
  status: "processed" | "skipped";
  application_id?: string;
  overall_passed?: boolean;
  knockout_results?: Array<{
    question_id: string;
    passed: boolean;
  }>;
  qualification_results?: Array<{
    question_id: string;
    score: number;
    rating: string;
  }>;
  notes?: string;
  summary?: string;
  interview_slot?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 401 | Invalid signature |
| 400 | Invalid webhook payload |

---

## Scheduling

### POST /api/scheduling/get-time-slots

Get available time slots for scheduling interviews.

**Auth:** None

**Request Body:**

```typescript
interface GetTimeSlotsRequest {
  conversation_id?: string;
  recruiter_id?: string;
}
```

**Response:**

```typescript
interface TimeSlot {
  date: string;        // YYYY-MM-DD
  dutch_date: string;  // "vrijdag 13 februari"
  morning: string[];   // ["10u", "11u"]
  afternoon: string[]; // ["14u", "16u"]
}

interface GetTimeSlotsResponse {
  slots: TimeSlot[];
  formatted_text: string;
}
```

---

### POST /api/scheduling/save-slot

Save a selected interview time slot and create a Google Calendar event.

**Auth:** None

**Request Body:**

```typescript
interface SaveSlotRequest {
  conversation_id: string;  // ElevenLabs conversation_id
  selected_date: string;    // YYYY-MM-DD
  selected_time: string;    // e.g., "10u", "14u"
  selected_slot_text?: string;
  candidate_name?: string;
  candidate_phone?: string;
  candidate_email?: string; // If provided, candidate receives Google Calendar invite
  notes?: string;
  debug?: boolean;          // Skip DB lookup, just create calendar event
}
```

**Response:**

```typescript
interface SaveSlotResponse {
  success: boolean;
  scheduled_interview_id?: string;
  message: string;
  vacancy_id?: string;
  vacancy_title?: string;
  selected_date: string;
  selected_time: string;
  selected_slot_text?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Vacancy not found for conversation_id |
| 500 | Failed to save scheduled slot |

---

### PATCH /api/scheduling/interviews/by-conversation/{conversation_id}/notes

Update notes for a scheduled interview by ElevenLabs conversation_id.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `conversation_id` | string | ElevenLabs conversation_id |

**Request Body:**

```typescript
interface UpdateNotesRequest {
  notes: string;
  append?: boolean;  // If true, append to existing notes. If false, replace.
}
```

**Response:**

```typescript
interface UpdateNotesResponse {
  success: boolean;
  message: string;
  conversation_id: string;
  scheduled_interview_id?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | No scheduled interview found for conversation_id |
| 500 | Failed to update interview notes |

---

### POST /api/scheduling/interviews/by-conversation/{conversation_id}/reschedule

Reschedule an existing interview to a new time slot.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `conversation_id` | string | ElevenLabs conversation_id |

**Request Body:**

```typescript
interface RescheduleRequest {
  new_date: string;          // YYYY-MM-DD
  new_time: string;          // e.g., "10u", "14u"
  new_slot_text?: string;    // Full Dutch text, e.g., "maandag 17 februari om 14u"
  reason?: string;           // Reason for rescheduling
}
```

**Response:**

```typescript
interface RescheduleResponse {
  success: boolean;
  message: string;
  conversation_id: string;
  previous_interview_id: string;
  previous_status: string;   // Will be "rescheduled"
  new_interview_id: string;
  new_date: string;
  new_time: string;
  new_slot_text?: string;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Cannot reschedule a cancelled interview |
| 400 | Cannot reschedule a completed interview |
| 404 | No active scheduled interview found for conversation_id |
| 500 | Failed to reschedule interview |

---

### POST /api/scheduling/interviews/by-conversation/{conversation_id}/cancel

Cancel a scheduled interview and its Google Calendar event.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `conversation_id` | string | ElevenLabs conversation_id |

**Request Body:**

```typescript
interface CancelRequest {
  reason?: string;  // Optional reason for cancellation
}
```

**Response:**

```typescript
interface CancelResponse {
  success: boolean;
  message: string;
  conversation_id: string;
  interview_id: string;
  previous_status: string;
  calendar_event_cancelled: boolean;
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | No active scheduled interview found for conversation_id |
| 500 | Failed to cancel interview |

---

## ElevenLabs

### PATCH /elevenlabs/agent/{agent_id}/config

Update the voice and TTS model configuration for an ElevenLabs conversational AI agent.

This endpoint calls the ElevenLabs API to update the agent's TTS settings, allowing users to change the voice, model, stability, and similarity boost before starting a conversation.

**Auth:** None (requires ELEVENLABS_API_KEY in environment)

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `agent_id` | string | The ElevenLabs agent ID |

**Request Body:**

```typescript
interface UpdateAgentVoiceConfigRequest {
  voice_id: string;           // The ElevenLabs voice ID to use
  model_id: string;           // TTS model (see available models below)
  stability?: number;         // Voice stability 0-1 (higher = more consistent)
  similarity_boost?: number;  // Similarity boost 0-1 (higher = more similar to original)
}
```

**Available TTS Models:**

| Model ID | Description |
|----------|-------------|
| `eleven_turbo_v2` | Fast, low-latency model |
| `eleven_multilingual_v2` | Multilingual support |
| `eleven_flash_v2_5` | Ultra-fast streaming |
| `eleven_v3_conversational` | Latest conversational model (recommended) |

**Response:**

```typescript
interface UpdateAgentVoiceConfigResponse {
  success: boolean;
  message: string;
  agent_id: string;
  voice_id: string;
  model_id: string;
  stability?: number;
  similarity_boost?: number;
}
```

**Example Request:**

```json
{
  "voice_id": "cjVigY5qzO86Huf0OWal",
  "model_id": "eleven_v3_conversational",
  "stability": 0.5,
  "similarity_boost": 0.8
}
```

**Example Response:**

```json
{
  "success": true,
  "message": "Agent voice configuration updated successfully",
  "agent_id": "abc123",
  "voice_id": "cjVigY5qzO86Huf0OWal",
  "model_id": "eleven_v3_conversational",
  "stability": 0.5,
  "similarity_boost": 0.8
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Agent not found |
| 422 | Validation error (invalid voice_id, model_id, etc.) |
| 500 | ELEVENLABS_API_KEY not configured |
| 502 | Error connecting to ElevenLabs API |
| 504 | Timeout connecting to ElevenLabs API |

---

### GET /elevenlabs/voice-config/{agent_id}

Retrieve the saved voice configuration settings for an ElevenLabs agent from the database.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `agent_id` | string | The ElevenLabs agent ID |

**Response:**

```typescript
interface VoiceConfigResponse {
  id: string;               // UUID of the config record
  agent_id: string;         // ElevenLabs agent ID
  voice_id: string;         // The voice ID
  model_id: string;         // TTS model ID
  stability?: number;       // Voice stability 0-1
  similarity_boost?: number; // Similarity boost 0-1
  created_at: string;       // ISO timestamp
  updated_at: string;       // ISO timestamp
}
```

**Example Response:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "agent_id": "abc123",
  "voice_id": "cjVigY5qzO86Huf0OWal",
  "model_id": "eleven_v3_conversational",
  "stability": 0.5,
  "similarity_boost": 0.8,
  "created_at": "2026-02-12T10:30:00Z",
  "updated_at": "2026-02-12T10:30:00Z"
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 404 | Voice configuration not found for agent |

---

### PUT /elevenlabs/voice-config/{agent_id}

Save or update the voice configuration settings for an ElevenLabs agent in the database.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `agent_id` | string | The ElevenLabs agent ID |

**Request Body:**

```typescript
interface VoiceConfigRequest {
  voice_id: string;           // The ElevenLabs voice ID to use
  model_id?: string;          // TTS model (default: eleven_v3_conversational)
  stability?: number;         // Voice stability 0-1
  similarity_boost?: number;  // Similarity boost 0-1
}
```

**Response:** `VoiceConfigResponse` (same as GET)

**Example Request:**

```json
{
  "voice_id": "cjVigY5qzO86Huf0OWal",
  "model_id": "eleven_v3_conversational",
  "stability": 0.5,
  "similarity_boost": 0.8
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 422 | Validation error (invalid values) |

---

## Activities

Unified view of all active agent tasks (pre-screening, document collection, scheduling, etc.).

### GET /api/activities/tasks

Get all active workflow tasks as a table view.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `status` | string | No | `active` | Filter: `active`, `completed`, or `all` |
| `stuck_only` | boolean | No | `false` | Only show stuck tasks (no update > 1 hour) |
| `limit` | number | No | 50 | Results per page (1-200) |
| `offset` | number | No | 0 | Pagination offset |

**Response:**

```typescript
interface WorkflowStep {
  id: string;                    // Step identifier (e.g., "in_progress", "processing")
  label: string;                 // Dutch display label (e.g., "Gesprek", "Verwerken")
  status: "completed" | "current" | "pending" | "failed";
}

interface TaskRow {
  id: string;                    // Workflow instance ID
  candidate_name?: string;       // From context
  vacancy_title?: string;        // From context
  workflow_type: string;         // pre_screening, document_collection, scheduling
  workflow_type_label: string;   // Human-readable: "Pre-screening", "Document Collection"
  current_step: string;          // Raw step: in_progress, processing, complete
  current_step_label: string;    // Human-readable step: "In Progress", "Processing", "Complete"
  step_detail?: string;          // Granular detail: "WhatsApp gesprek", "Gesprek verwerken" (null when not applicable)
  status: string;                // active, stuck, completed
  is_stuck: boolean;             // True if no update > 1 hour
  updated_at: string;            // ISO timestamp
  time_ago: string;              // "2 min ago", "1 hour ago"
  workflow_steps: WorkflowStep[]; // Visual workflow progress for rendering step indicators
}

interface TasksResponse {
  tasks: TaskRow[];
  total: number;
  stuck_count: number;           // Number of stuck tasks in result set
  active_count: number;          // Number of active (non-stuck) tasks
}
```

**Example Response:**

```json
{
  "tasks": [
    {
      "id": "8d84fb06-7cf3-4e99-9668-93d05f2a0fee",
      "candidate_name": "Jan Peeters",
      "vacancy_title": "Operator Mengafdeling",
      "workflow_type": "pre_screening",
      "workflow_type_label": "Pre-screening",
      "current_step": "in_progress",
      "current_step_label": "In Progress",
      "step_detail": "WhatsApp gesprek",
      "status": "active",
      "is_stuck": false,
      "updated_at": "2026-02-15T08:50:27.231819+00:00",
      "time_ago": "just now",
      "workflow_steps": [
        { "id": "in_progress", "label": "Gesprek", "status": "current" },
        { "id": "processing", "label": "Verwerken", "status": "pending" },
        { "id": "processed", "label": "Notificaties", "status": "pending" },
        { "id": "complete", "label": "Afgerond", "status": "pending" }
      ]
    },
    {
      "id": "a1b2c3d4-5e6f-7890-abcd-ef1234567890",
      "candidate_name": "Marie Claes",
      "vacancy_title": "Magazijnier",
      "workflow_type": "pre_screening",
      "workflow_type_label": "Pre-screening",
      "current_step": "processing",
      "current_step_label": "Processing",
      "step_detail": "Gesprek verwerken",
      "status": "active",
      "is_stuck": false,
      "updated_at": "2026-02-15T08:48:00.000000+00:00",
      "time_ago": "2 min ago",
      "workflow_steps": [
        { "id": "in_progress", "label": "Gesprek", "status": "completed" },
        { "id": "processing", "label": "Verwerken", "status": "current" },
        { "id": "processed", "label": "Notificaties", "status": "pending" },
        { "id": "complete", "label": "Afgerond", "status": "pending" }
      ]
    },
    {
      "id": "bae9bfa2-6fda-40d3-8078-61fc5cb6b2ab",
      "candidate_name": "Anna Vermeersch",
      "vacancy_title": "Heftruckchauffeur",
      "workflow_type": "document_collection",
      "workflow_type_label": "Document Collection",
      "current_step": "waiting",
      "current_step_label": "Waiting",
      "step_detail": "Wacht op Rijbewijs",
      "status": "stuck",
      "is_stuck": true,
      "updated_at": "2026-02-15T07:10:00.000000+00:00",
      "time_ago": "1 hour ago",
      "workflow_steps": [
        { "id": "request_sent", "label": "Verzoek", "status": "completed" },
        { "id": "waiting", "label": "Wachten", "status": "current" },
        { "id": "verifying", "label": "Verifiëren", "status": "pending" },
        { "id": "complete", "label": "Afgerond", "status": "pending" }
      ]
    }
  ],
  "total": 15,
  "stuck_count": 1,
  "active_count": 14
}
```

**Status Indicators:**

| Status | Meaning |
|--------|---------|
| `active` | Task is in progress, recently updated |
| `stuck` | No update for > 1 hour (may need attention) |
| `completed` | Task finished successfully |

**Workflow Types:**

| Type | Label | Description |
|------|-------|-------------|
| `pre_screening` | Pre-screening | WhatsApp/voice screening conversation |
| `document_collection` | Document Collection | ID/license/certificate collection |
| `scheduling` | Interview Planning | Calendar scheduling |

**Pre-Screening Steps:**

| Step (`current_step`) | Label (`current_step_label`) | Detail (`step_detail`) |
|----------------------|------------------------------|------------------------|
| `in_progress` | "In Progress" | "WhatsApp gesprek" or "Voice gesprek" |
| `processing` | "Processing" | "Gesprek verwerken" |
| `processed` | "Processed" | "Notificaties verzonden" |
| `complete` | "Complete" | `null` |
| `failed` | "Failed" | "Kandidaat niet gekwalificeerd" |
| `timed_out` | "Timed Out" | "Geen reactie ontvangen" |

**Document Collection Steps:**

| Step (`current_step`) | Label (`current_step_label`) | Detail (`step_detail`) |
|----------------------|------------------------------|------------------------|
| `waiting` | "Waiting" | "Wacht op {document_type}" |
| `verifying` | "Verifying" | "{document_type} verifiëren" |
| `waiting_backside` | "Waiting" | "Wacht op achterkant" |
| `complete` | "Complete" | `null` |
| `expired` | "Expired" | "Verzoek verlopen" |
| `timed_out` | "Timed Out" | "Geen reactie ontvangen" |

**Pre-Screening Flow:**

```
Outbound API    Conversation ends    Transcript done    Notifications
     │                 │                   │                 │
     ▼                 ▼                   ▼                 ▼
in_progress ──────► processing ──────► processed ──────► complete
```

**Example Pre-Screening Task:**

```json
{
  "id": "62f965e5-2db5-41dd-8a93-22a9754395b4",
  "candidate_name": "Luuk Mulder",
  "vacancy_title": "Winkelmedewerker Bakkerij",
  "workflow_type": "pre_screening",
  "workflow_type_label": "Pre-screening",
  "current_step": "in_progress",
  "current_step_label": "In Progress",
  "step_detail": "WhatsApp gesprek",
  "status": "active",
  "is_stuck": false,
  "updated_at": "2026-02-15T20:22:40.400578+00:00",
  "time_ago": "5 min ago",
  "workflow_steps": [
    { "id": "in_progress", "label": "Gesprek", "status": "current" },
    { "id": "processing", "label": "Verwerken", "status": "pending" },
    { "id": "processed", "label": "Notificaties", "status": "pending" },
    { "id": "complete", "label": "Afgerond", "status": "pending" }
  ]
}
```

**Workflow Step Visualization:**

The `workflow_steps` array enables rendering a visual progress indicator:

```
Pre-screening:
  ● Gesprek → ○ Verwerken → ○ Notificaties → ○ Afgerond
  ↑ current

Document Collection:
  ✓ Verzoek → ● Wachten → ○ Verifiëren → ○ Afgerond
  ↑ completed  ↑ current
```

Step status values:
- `completed`: Step is done (render as checkmark or filled circle)
- `current`: Currently active step (render highlighted)
- `pending`: Not yet reached (render as empty circle)
- `failed`: Step failed (render as error/red)

---

## Architecture

### GET /architecture

Get the backend architecture as JSON for visualization.

Returns all components (routers, services, repositories, agents, external integrations), their relationships, and layer groupings suitable for rendering with graph libraries like React Flow, D3.js, or vis.js.

**Auth:** None

**Response:**

```typescript
interface ArchitectureNode {
  id: string;              // Unique identifier (e.g., "router:vacancies", "service:vacancy")
  type: string;            // Component type: "router", "service", "repository", "agent", "external"
  name: string;            // Display name (e.g., "VacancyService")
  layer: string;           // Layer: "api", "service", "repository", "agent", "external"
  file_path?: string;      // Relative file path (e.g., "src/routers/vacancies.py")
  description?: string;    // Brief description
  metadata?: object;       // Additional info (e.g., model name for agents)
}

interface ArchitectureEdge {
  source: string;          // Source node id
  target: string;          // Target node id
  type: string;            // Relationship: "uses", "calls", "integrates", "stores"
  label?: string;          // Edge label (e.g., "webhook", "config")
}

interface ArchitectureGroup {
  id: string;              // Group id (e.g., "api")
  name: string;            // Display name (e.g., "API Layer")
  layer: string;           // Layer identifier
  color?: string;          // Suggested color (e.g., "#4CAF50")
}

interface ArchitectureStats {
  routers: number;
  services: number;
  repositories: number;
  agents: number;
  external: number;
}

interface ArchitectureResponse {
  nodes: ArchitectureNode[];
  edges: ArchitectureEdge[];
  groups: ArchitectureGroup[];
  metadata: {
    stats: ArchitectureStats;
  };
}
```

**Example Response:**

```json
{
  "nodes": [
    {
      "id": "router:vacancies",
      "type": "router",
      "name": "Vacancies",
      "layer": "api",
      "file_path": "src/routers/vacancies.py",
      "description": "Vacancy CRUD and listing"
    },
    {
      "id": "service:vacancy",
      "type": "service",
      "name": "VacancyService",
      "layer": "service",
      "file_path": "src/services/vacancy_service.py",
      "description": "Vacancy business logic and stats"
    },
    {
      "id": "agent:transcript_processor",
      "type": "agent",
      "name": "Transcript Processor",
      "layer": "agent",
      "file_path": "transcript_processor/agent.py",
      "description": "Analyzes voice call transcripts",
      "metadata": {"model": "gemini-2.0-flash"}
    },
    {
      "id": "external:vapi",
      "type": "external",
      "name": "VAPI",
      "layer": "external",
      "description": "Voice AI platform for phone screening"
    }
  ],
  "edges": [
    {"source": "router:vacancies", "target": "service:vacancy", "type": "uses"},
    {"source": "service:vacancy", "target": "repo:vacancy", "type": "uses"},
    {"source": "router:vapi", "target": "external:vapi", "type": "integrates", "label": "webhook"}
  ],
  "groups": [
    {"id": "api", "name": "API Layer", "layer": "api", "color": "#4CAF50"},
    {"id": "service", "name": "Services", "layer": "service", "color": "#2196F3"},
    {"id": "repository", "name": "Repositories", "layer": "repository", "color": "#FF9800"},
    {"id": "agent", "name": "AI Agents", "layer": "agent", "color": "#9C27B0"},
    {"id": "external", "name": "External Services", "layer": "external", "color": "#607D8B"}
  ],
  "metadata": {
    "stats": {
      "routers": 23,
      "services": 19,
      "repositories": 12,
      "agents": 9,
      "external": 6
    }
  }
}
```

**Frontend Usage:**

The response structure is designed to work with popular graph visualization libraries:

- **React Flow**: Map nodes directly, use `groups` for grouping nodes
- **D3.js Force Graph**: Use `nodes` and `edges` (as links)
- **vis.js Network**: Direct mapping with clustering support
- **Cytoscape.js**: Compatible node/edge structure

---

## ATS Simulator

Simulates an external Applicant Tracking System (e.g., Salesforce) API. Serves fixture data through realistic REST endpoints with different field names than internal models.

### GET /ats-simulator/api/v1/vacancies

List vacancies from the simulated ATS.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `page` | integer | No | `1` | Page number |
| `page_size` | integer | No | `50` | Items per page (max 100) |
| `status` | string | No | - | Filter: `active`, `inactive`, `draft` |

**Response:**

```typescript
interface ATSVacancyListResponse {
  data: ATSVacancy[];
  total_count: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

interface ATSVacancy {
  external_id: string;       // e.g. "sf-1633942"
  title: string;
  company_name: string;
  work_location: string | null;
  description_html: string | null;
  status: string;            // "active", "inactive", "draft"
  created_date: string | null;
  recruiter_email: string | null;
  client_name: string | null;
}
```

---

### GET /ats-simulator/api/v1/recruiters

List recruiters from the simulated ATS.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `page` | integer | No | `1` | Page number |
| `page_size` | integer | No | `50` | Items per page (max 100) |

**Response:**

```typescript
interface ATSRecruiterListResponse {
  data: ATSRecruiter[];
  total_count: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

interface ATSRecruiter {
  external_id: string;
  full_name: string;
  email: string | null;
  phone_number: string | null;
  department: string | null;  // maps to internal "team"
  job_title: string | null;   // maps to internal "role"
  photo_url: string | null;
  active: boolean;
}
```

---

### GET /ats-simulator/api/v1/clients

List clients/companies from the simulated ATS.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `page` | integer | No | `1` | Page number |
| `page_size` | integer | No | `50` | Items per page (max 100) |

**Response:**

```typescript
interface ATSClientListResponse {
  data: ATSClient[];
  total_count: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

interface ATSClient {
  external_id: string;
  company_name: string;       // maps to internal "name"
  headquarters: string | null; // maps to internal "location"
  sector: string | null;       // maps to internal "industry"
  logo_url: string | null;
}
```

---

### POST /demo/import-ats

Trigger a streaming import from the ATS simulator. Returns an SSE stream with per-vacancy progress events.

**Auth:** None

**Response:** `text/event-stream` (Server-Sent Events)

See [brief.md](brief.md) for full SSE event documentation and frontend implementation guide.

**Event types:** `status`, `vacancy_importing`, `vacancy_imported`, `complete`, `error`

**Example stream:**
```
data: {"type": "status", "step": "connecting", "message": "Verbinding maken met ATS..."}
data: {"type": "status", "step": "recruiters", "message": "5 recruiters geïmporteerd", "count": 5}
data: {"type": "vacancy_importing", "index": 0, "total": 7, "source_id": "sf-1633942", "title": "Operator Mengafdeling"}
data: {"type": "vacancy_imported", "index": 0, "total": 7, "id": "uuid", "source_id": "sf-1633942", "title": "Operator Mengafdeling", "skipped": false}
data: {"type": "complete", "result": {"recruiters_imported": 5, "clients_imported": 7, "vacancies_imported": 7, "errors": []}}
data: [DONE]
```

---

## Demo

### POST /demo/seed

Seed demo data (vacancies, applications, pre-screenings).

**Auth:** None

**Response:**

```typescript
interface DemoSeedResponse {
  status: "seeded";
  message: string;
  vacancies: Array<{
    id: string;
    title: string;
  }>;
  applications_count: number;
  pre_screenings: string[];
}
```

---

### POST /demo/reset

Reset all data and optionally reseed.

**Auth:** None

**Query Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `reseed` | boolean | No | `true` | Reseed with demo data after reset |
| `activities` | boolean | No | `true` | Include agent activities in reseed |
| `workflow_activities` | boolean | No | `true` | Include activities dashboard demo data (workflow tasks) |

**Response:**

```typescript
interface DemoResetResponse {
  status: "success";
  message: string;
  seed?: DemoSeedResponse;
  workflow_activities_count?: number;  // When workflow_activities=true
}
```

**Example:**

```bash
# Full reset with all demo data including activities dashboard
curl -X POST "http://localhost:8080/demo/reset?reseed=true&workflow_activities=true"
```

---

## Error Reference

### Standard Error Response Format

```typescript
interface ErrorResponse {
  error: string;
  details?: Record<string, any>;
}

// FastAPI validation error
interface ValidationErrorResponse {
  detail: Array<{
    loc: (string | number)[];
    msg: string;
    type: string;
  }>;
}
```

### HTTP Status Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Bad Request — Invalid input, UUID format, or missing required fields |
| 401 | Unauthorized — Invalid webhook signature |
| 404 | Not Found — Resource does not exist |
| 500 | Internal Server Error — Unexpected error or missing configuration |

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid vacancy ID format` | UUID parsing failed | Use valid UUID format |
| `Vacancy not found` | No vacancy with given ID | Check vacancy exists |
| `No pre-screening found` | Vacancy has no screening config | Create pre-screening first |
| `Pre-screening is not published yet` | Must publish before use | Call publish endpoint |
| `Pre-screening is offline` | Screening is toggled off | Set `is_online: true` |
| `Session not found` | Invalid or expired session | Start new session |
| `Invalid signature` | HMAC validation failed | Check webhook secret |

---

## Ontology

Generic reference data system for entity types with parent-child hierarchies and category grouping. Currently supports `document_type` — more types (job functions, skills) will be added.

All endpoints are prefixed with `/ontology`.

### Supported Entity Types

| Type | Label | Status |
|------|-------|--------|
| `document_type` | Documenttypes | **Live** |
| `job_function` | Functies | Planned |
| `skill` | Vaardigheden | Planned |

### Overview

#### `GET /ontology`

Returns all registered entity types with counts and available categories.

**Query params:**
- `workspace_id` (uuid, required) — Workspace to scope results

**Response:**
```json
{
  "types": [
    {
      "type": "document_type",
      "label": "Documenttypes",
      "description": "Document- en certificaattypes voor kandidaten",
      "total": 43,
      "categories": ["certificate", "financial", "identity", "other"]
    }
  ]
}
```

### List Entities

#### `GET /ontology/entities`

List entities by type with parent-child hierarchy. Parents are returned with nested children.

**Query params:**
- `type` (string, required) — Entity type (`document_type`)
- `workspace_id` (uuid, required) — Workspace to scope results
- `category` (string, optional) — Filter by category
- `include_children` (boolean, default `true`) — Nest children under parents
- `include_inactive` (boolean, default `false`) — Include soft-deleted entities
- `limit` (int, default `200`, max `1000`) — Max items to return

**Response:**
```json
{
  "type": "document_type",
  "items": [
    {
      "id": "uuid",
      "type": "document_type",
      "slug": "id_card",
      "name": "ID-kaart",
      "description": null,
      "category": "identity",
      "icon": "credit-card",
      "is_default": true,
      "is_active": true,
      "sort_order": 1,
      "metadata": {
        "is_verifiable": true,
        "requires_front_back": true
      },
      "custom_field_extraction": null,
      "children": [],
      "children_count": 0
    },
    {
      "id": "uuid",
      "type": "document_type",
      "slug": "rijbewijs",
      "name": "Rijbewijs",
      "category": "certificate",
      "icon": "car",
      "is_default": true,
      "sort_order": 3,
      "metadata": {
        "prato_flex_type_id": "10",
        "is_verifiable": true,
        "requires_front_back": true
      },
      "custom_field_extraction": {
        "fields": ["expiry_date", "license_categories"],
        "instructions": "Extract the expiry date and all license categories visible on the document."
      },
      "children": [
        {
          "id": "uuid",
          "slug": "prato_10_AM",
          "name": "AM",
          "category": "certificate",
          "sort_order": 0,
          "metadata": {
            "prato_flex_type_id": "10",
            "prato_flex_detail_type_id": "AM"
          }
        }
      ],
      "children_count": 12
    }
  ],
  "total": 43,
  "categories": ["certificate", "financial", "identity", "other"]
}
```

> **Sorting:** Items with children are returned first (A-Z), followed by leaf items (A-Z).
```

### Get Entity

#### `GET /ontology/entities/{entity_id}`

Get a single entity by ID with optional children.

**Query params:**
- `include_children` (boolean, default `true`) — Nest children

**Response:** Same shape as a single item from the list endpoint.

---

### Create Entity

#### `POST /ontology/entities`

Create a new document type.

**Query params:**
- `workspace_id` (UUID, required)

**Request body:**
```json
{
  "slug": "my_doc_type",
  "name": "My Document",
  "description": null,
  "category": "identity",
  "icon": null,
  "is_default": false,
  "is_verifiable": false,
  "requires_front_back": false,
  "sort_order": 0,
  "parent_id": null,
  "custom_field_extraction": null
}
```

**Response:** `201` — Full `OntologyEntity` object.

---

### Update Entity

#### `PATCH /ontology/entities/{entity_id}`

Partially update a document type. Only provided fields are updated.

To clear `custom_field_extraction`, send `"custom_field_extraction": null` explicitly.

**Request body** (all fields optional):
```json
{
  "name": "Updated Name",
  "is_verifiable": true,
  "custom_field_extraction": {
    "fields": ["expiry_date"],
    "instructions": "Extract the expiry date from the document."
  }
}
```

**Response:** `200` — Full `OntologyEntity` with updated values and children.

---

### Delete Entity

#### `DELETE /ontology/entities/{entity_id}`

Soft-deletes a document type (sets `is_active = false`). The entity remains in the database but is excluded from default list responses.

**Response:** `204 No Content`

---

### Document Type Categories

For `type=document_type`, the following categories are available:

| Category | Description | Examples |
|----------|-------------|----------|
| `identity` | Identity documents | ID-kaart, Paspoort, Verblijfsdocument |
| `certificate` | Work certificates & licenses | Rijbewijs, Heftruckbrevet, VCA |
| `financial` | Financial documents | SIS-kaart, Studentenkaart |
| `other` | Other documents | Diploma |

### Document Type Metadata Fields

Type-specific fields stored in the `metadata` object for `document_type` entities:

| Field | Type | Description |
|-------|------|-------------|
| `requires_front_back` | boolean | Upload should request front + back images |
| `is_verifiable` | boolean | Can be sent through AI verification |
| `prato_flex_type_id` | string | External Prato Flex certificate code (for sync) |
| `prato_flex_detail_type_id` | string | Child-level Prato Flex detail code (children only) |

### `custom_field_extraction`

Top-level document types (no parent) may have a `custom_field_extraction` JSONB blob. This is passed to the LLM during document verification to instruct which fields to extract beyond the defaults.

Structure is free-form — recommended shape:

```json
{
  "fields": ["expiry_date", "license_categories"],
  "instructions": "Extract the expiry date and all license categories visible on the document."
}
```

- Only relevant for `is_verifiable = true` documents
- Ignored for child document types
- Set/clear via `PATCH /ontology/entities/{id}`

### Seeded Data

Document types are pre-seeded from Prato Flex (parent company workforce tool):
- **43 parent types** across 4 categories
- **473 detail types** (children) linked via parent-child hierarchy
- All mapped with `prato_flex_type_id` / `prato_flex_detail_type_id` for external sync

---

## Candidacies

Tracks a candidate's position in a vacancy pipeline (or talent pool when no vacancy is linked).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/candidacies` | List candidacies |
| `POST` | `/candidacies` | Add candidate to pipeline |
| `PATCH` | `/candidacies/{id}/stage` | Move to a new stage |

---

### GET /candidacies

**Query params:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `vacancy_id` | UUID | No | Scope to one vacancy (Kanban view) |
| `workspace_id` | UUID | No | Defaults to `00000000-0000-0000-0000-000000000001` |
| `stage` | string | No | Filter by stage |

**Response:** `CandidacyResponse[]`

---

### POST /candidacies

**Query params:** `workspace_id` (optional, defaults to default workspace)

**Body:**
```json
{
  "candidate_id": "uuid",
  "vacancy_id": "uuid | null",
  "stage": "new",
  "source": "manual | voice | whatsapp | cv | import"
}
```

Returns `409` if the candidate already has a candidacy for the given vacancy.

---

### PATCH /candidacies/{id}/stage

**Query params:** `stage` (required) — new stage value

**Response:** Updated `CandidacyResponse`

---

### CandidacyResponse

```json
{
  "id": "uuid",
  "vacancy_id": "uuid | null",
  "candidate_id": "uuid",
  "stage": "new | pre_screening | qualified | interview_planned | interview_done | offer | placed | rejected | withdrawn",
  "source": "string | null",
  "stage_updated_at": "datetime",
  "created_at": "datetime",
  "updated_at": "datetime",
  "candidate": {
    "id": "uuid",
    "full_name": "string",
    "phone": "string | null",
    "email": "string | null"
  },
  "vacancy": {
    "id": "uuid",
    "title": "string",
    "company": "string | null"
  } | null,
  "latest_application": {
    "id": "uuid",
    "channel": "voice | whatsapp | cv",
    "qualified": "boolean | null",
    "open_questions_score": "integer (0-100) | null",
    "knockout_passed": "integer",
    "knockout_total": "integer",
    "completed_at": "datetime | null"
  } | null
}
```

`vacancy` is `null` when `vacancy_id` is null (talent pool entry).
`latest_application` is `null` when no completed screening exists yet (e.g. manually added candidates).
