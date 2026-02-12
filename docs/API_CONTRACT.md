# Taloo Backend API Contract

Complete API reference for the Taloo recruitment screening platform.

## Changelog

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
21. [Demo](#demo)
22. [Error Reference](#error-reference)

---

## Authentication

The API is open with no endpoint-level authentication. Security relies on:

- **Webhook HMAC Validation**: ElevenLabs webhooks require SHA256 HMAC signature verification via `elevenlabs-signature` header
- **Trusted External Services**: Twilio webhooks are trusted via IP range
- **CORS**: Currently allows all origins (`*`)

```
No Authorization header required for any endpoint.
```

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
  is_online?: boolean;
  channels: ChannelsResponse;
  agents: AgentsResponse;
  recruiter_id?: string;         // UUID - foreign key to recruiters table
  recruiter?: RecruiterSummary;  // Full recruiter info (if assigned)
  client_id?: string;            // UUID - foreign key to clients table
  client?: ClientSummary;        // Full client info (if assigned)
  candidates_count: number;
  completed_count: number;
  qualified_count: number;
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
  answers: QuestionAnswerResponse[];
  synced: boolean;
  synced_at?: string;
  overall_score?: number;
  knockout_passed: number;
  knockout_total: number;
  qualification_count: number;
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
| `status` | string | Yes | - | Filter: `new`, `generated`, or `archived` |
| `limit` | number | No | 50 | Results per page (1-100) |
| `offset` | number | No | 0 | Pagination offset |

**Status Definitions:**

- `new`: No pre-screening record (questions not generated yet)
- `generated`: Has pre-screening record (questions exist, can be online/offline)
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
| 500 | TWILIO_WHATSAPP_NUMBER not configured |

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
| `reseed` | boolean | No | true | Reseed after reset |

**Response:**

```typescript
interface DemoResetResponse {
  status: "reset";
  message: string;
  elevenlabs_cleanup: {
    agents_deleted: number;
    errors: number;
  };
  seed?: DemoSeedResponse;
}
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
