# Taloo Backend API Contract

Complete API reference for the Taloo recruitment screening platform.

## Changelog

- **2026-02-09** — Initial contract — generated from codebase

---

## Table of Contents

1. [Authentication](#authentication)
2. [Common Types](#common-types)
3. [Health](#health)
4. [Vacancies](#vacancies)
5. [Applications](#applications)
6. [Pre-Screening](#pre-screening)
7. [Interviews](#interviews)
8. [Screening](#screening)
9. [Outbound](#outbound)
10. [CV Analysis](#cv-analysis)
11. [Data Query](#data-query)
12. [Documents](#documents)
13. [Document Collection](#document-collection)
14. [Webhooks](#webhooks)
15. [Demo](#demo)
16. [Error Reference](#error-reference)

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
type VacancyStatus = "new" | "draft" | "screening_active" | "archived";
type VacancySource = "salesforce" | "bullhorn" | "manual";
type InterviewChannel = "voice" | "whatsapp";
type QuestionType = "knockout" | "qualification";
type ApplicationStatus = "active" | "processing" | "completed" | "abandoned";
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

Get a single vacancy by ID.

**Auth:** None

**Path Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `vacancy_id` | string (UUID) | Vacancy identifier |

**Response:** `VacancyResponse`

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

### POST /interview/generate

Generate interview questions from vacancy text. Returns SSE stream.

**Auth:** None

**Request Body:**

```typescript
interface GenerateInterviewRequest {
  vacancy_text: string;
  session_id?: string;
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
    }>;
    knockout_failed_action: string;
    qualification_questions: Array<{
      id: string;
      question: string;
      ideal_answer: string;
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
| 400 | vacancy_text required |

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
    knockout_questions: Array<{ id: string; question: string }>;
    knockout_failed_action: string;
    qualification_questions: Array<{ id: string; question: string; ideal_answer: string }>;
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
  ideal_answer?: string;  // Required for qualification questions
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
