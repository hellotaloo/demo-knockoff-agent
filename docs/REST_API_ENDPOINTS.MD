# Backend Endpoints: Vacancies & Applications

This document describes the API endpoints needed to load vacancies and applications from the backend.

## Overview

The frontend currently uses mock data for:
1. **Vacancies** - Job postings that need interview agents
2. **Applications** - Candidate interview results per vacancy

These endpoints will replace the mock data with real backend data.

---

## Data Structures

### Vacancy

```python
class VacancyStatus(str, Enum):
    NEW = "new"                    # Just imported, needs interview setup
    DRAFT = "draft"                # Pre-screening being configured
    SCREENING_ACTIVE = "screening_active"  # Pre-screening is live
    ARCHIVED = "archived"          # No longer active

class VacancySource(str, Enum):
    SALESFORCE = "salesforce"
    BULLHORN = "bullhorn"
    MANUAL = "manual"

class Vacancy(BaseModel):
    id: str
    title: str
    company: str
    location: str
    description: str              # Full job description (markdown supported)
    status: VacancyStatus
    created_at: datetime          # ISO 8601 format
    archived_at: Optional[datetime] = None
    source: Optional[VacancySource] = None
    source_id: Optional[str] = None  # External ID in source system
```

### Application (Interview Result)

```python
class InterviewChannel(str, Enum):
    VOICE = "voice"
    WHATSAPP = "whatsapp"

class QuestionAnswer(BaseModel):
    question_id: str              # e.g., "k1", "q2"
    question_text: str
    answer: str
    passed: Optional[bool] = None  # Only for knockout questions

class Application(BaseModel):
    id: str
    vacancy_id: str
    candidate_name: str
    channel: InterviewChannel
    
    # Interview status
    completed: bool               # Did candidate finish all questions?
    qualified: bool               # Passed all knockout + scoring threshold
    
    # Timing
    started_at: datetime          # ISO 8601
    completed_at: Optional[datetime] = None
    interaction_seconds: int      # Total call/chat duration
    
    # Answers
    answers: List[QuestionAnswer]
    
    # Sync status
    synced: bool                  # Has been pushed back to CRM?
    synced_at: Optional[datetime] = None
```

---

## Endpoints

### 1. List Vacancies

```
GET /vacancies
```

Returns all vacancies with optional filtering.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: `new`, `draft`, `screening_active`, `archived` |
| `source` | string | Filter by source: `salesforce`, `bullhorn`, `manual` |
| `limit` | int | Max results (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

**Response:**
```json
{
  "vacancies": [
    {
      "id": "vac-123",
      "title": "Operator (2-ploegen)",
      "company": "Klant regio Diest",
      "location": "Diest, België",
      "description": "### Over deze job\n...",
      "status": "new",
      "created_at": "2026-01-30T09:00:00Z",
      "archived_at": null,
      "source": "salesforce",
      "source_id": "SF-00123"
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

---

### 2. Get Single Vacancy

```
GET /vacancies/{vacancy_id}
```

Returns a single vacancy by ID.

**Response:**
```json
{
  "id": "vac-123",
  "title": "Operator (2-ploegen)",
  "company": "Klant regio Diest",
  "location": "Diest, België",
  "description": "### Over deze job\nSamen met onze klant...",
  "status": "screening_active",
  "created_at": "2026-01-30T09:00:00Z",
  "archived_at": null,
  "source": "salesforce",
  "source_id": "SF-00123"
}
```

**Error Response (404):**
```json
{
  "detail": "Vacancy not found"
}
```

---

### 3. List Applications for Vacancy

```
GET /vacancies/{vacancy_id}/applications
```

Returns all applications (interview results) for a vacancy.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `qualified` | bool | Filter by qualification status |
| `completed` | bool | Filter by completion status |
| `synced` | bool | Filter by sync status |
| `limit` | int | Max results (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

**Response:**
```json
{
  "applications": [
    {
      "id": "app-1",
      "vacancy_id": "vac-123",
      "candidate_name": "Jan Peeters",
      "channel": "voice",
      "completed": true,
      "qualified": true,
      "started_at": "2026-01-29T09:15:00Z",
      "completed_at": "2026-01-29T09:18:45Z",
      "interaction_seconds": 225,
      "answers": [
        {
          "question_id": "k1",
          "question_text": "Heb je een technische achtergrond?",
          "answer": "Ja, ik heb 5 jaar ervaring als machineoperator.",
          "passed": true
        },
        {
          "question_id": "q1",
          "question_text": "Welke ervaring heb je met machines?",
          "answer": "Bij mijn vorige werkgever was ik verantwoordelijk voor...",
          "passed": null
        }
      ],
      "synced": true,
      "synced_at": "2026-01-29T09:20:00Z"
    }
  ],
  "total": 5,
  "limit": 50,
  "offset": 0
}
```

---

### 4. Get Single Application

```
GET /applications/{application_id}
```

Returns a single application with full details.

**Response:**
Same structure as individual application in list response.

**Error Response (404):**
```json
{
  "detail": "Application not found"
}
```

---

### 5. Get Application Statistics

```
GET /vacancies/{vacancy_id}/stats
```

Returns aggregated statistics for a vacancy.

**Response:**
```json
{
  "vacancy_id": "vac-123",
  "total_applications": 15,
  "completed": 12,
  "completion_rate": 80,
  "qualified": 8,
  "qualification_rate": 67,
  "channel_breakdown": {
    "voice": 10,
    "whatsapp": 5
  },
  "avg_interaction_seconds": 195,
  "last_application_at": "2026-01-29T14:30:00Z"
}
```

---

## Frontend Integration

### API Client Updates

Add to `lib/interview-api.ts`:

```typescript
// Types
export interface Vacancy {
  id: string;
  title: string;
  company: string;
  location: string;
  description: string;
  status: 'new' | 'draft' | 'screening_active' | 'archived';
  created_at: string;
  archived_at: string | null;
  source: 'salesforce' | 'bullhorn' | 'manual' | null;
  source_id: string | null;
}

export interface QuestionAnswer {
  question_id: string;
  question_text: string;
  answer: string;
  passed: boolean | null;
}

export interface Application {
  id: string;
  vacancy_id: string;
  candidate_name: string;
  channel: 'voice' | 'whatsapp';
  completed: boolean;
  qualified: boolean;
  started_at: string;
  completed_at: string | null;
  interaction_seconds: number;
  answers: QuestionAnswer[];
  synced: boolean;
  synced_at: string | null;
}

// API functions
export async function getVacancies(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<{ vacancies: Vacancy[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set('status', params.status);
  if (params?.limit) searchParams.set('limit', params.limit.toString());
  if (params?.offset) searchParams.set('offset', params.offset.toString());
  
  const url = `${BACKEND_URL}/vacancies?${searchParams}`;
  const response = await fetch(url);
  
  if (!response.ok) throw new Error('Failed to fetch vacancies');
  return response.json();
}

export async function getVacancy(vacancyId: string): Promise<Vacancy> {
  const response = await fetch(`${BACKEND_URL}/vacancies/${vacancyId}`);
  
  if (!response.ok) throw new Error('Vacancy not found');
  return response.json();
}

export async function getApplications(
  vacancyId: string,
  params?: { qualified?: boolean; completed?: boolean }
): Promise<{ applications: Application[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.qualified !== undefined) {
    searchParams.set('qualified', params.qualified.toString());
  }
  if (params?.completed !== undefined) {
    searchParams.set('completed', params.completed.toString());
  }
  
  const url = `${BACKEND_URL}/vacancies/${vacancyId}/applications?${searchParams}`;
  const response = await fetch(url);
  
  if (!response.ok) throw new Error('Failed to fetch applications');
  return response.json();
}
```

### Page Updates Needed

1. **`app/interviews/page.tsx`** - Replace `dummyVacancies` with `getVacancies()` call
2. **`app/interviews/generate/[id]/page.tsx`** - Replace `mockVacancy` and `mockApplications` with API calls

---

## CORS Configuration

Ensure the backend allows requests from the frontend:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Error Handling

All endpoints should return consistent error responses:

```python
from fastapi import HTTPException

# 404 - Not Found
raise HTTPException(status_code=404, detail="Vacancy not found")

# 400 - Bad Request
raise HTTPException(status_code=400, detail="Invalid status filter")

# 500 - Server Error
raise HTTPException(status_code=500, detail="Database connection failed")
```

---

## Database Considerations

### Storage Options

1. **In-memory** (for demo/development)
   - Simple dict/list storage
   - Lost on restart

2. **SQLite** (for persistence without infrastructure)
   - Good for single-instance deployments
   - Easy to set up

3. **PostgreSQL/Supabase** (for production)
   - Scalable
   - Already used for other features

### Suggested Tables

```sql
-- Vacancies table
CREATE TABLE vacancies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT,
    status TEXT DEFAULT 'new',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    archived_at TIMESTAMPTZ,
    source TEXT,
    source_id TEXT
);

-- Applications table
CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vacancy_id UUID REFERENCES vacancies(id),
    candidate_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    completed BOOLEAN DEFAULT FALSE,
    qualified BOOLEAN DEFAULT FALSE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    interaction_seconds INTEGER DEFAULT 0,
    synced BOOLEAN DEFAULT FALSE,
    synced_at TIMESTAMPTZ,
    conversation_id TEXT DEFAULT NULL  -- ElevenLabs conversation ID for voice calls
);

-- Question answers (stored as JSONB or separate table)
CREATE TABLE application_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID REFERENCES applications(id),
    question_id TEXT NOT NULL,
    question_text TEXT NOT NULL,
    answer TEXT,
    passed BOOLEAN,  -- NULL for qualification questions
    score INTEGER DEFAULT NULL,  -- 0-100 for qualification questions
    source TEXT DEFAULT 'chat'  -- 'chat', 'whatsapp', or 'voice'
);
```

---

## Testing

### Manual Testing

```bash
# List vacancies
curl http://localhost:8080/vacancies

# Filter by status
curl "http://localhost:8080/vacancies?status=new"

# Get single vacancy
curl http://localhost:8080/vacancies/vac-123

# Get applications
curl http://localhost:8080/vacancies/vac-123/applications

# Filter qualified only
curl "http://localhost:8080/vacancies/vac-123/applications?qualified=true"
```

### Expected Behavior

1. Empty lists return `{ "vacancies": [], "total": 0 }` (not 404)
2. Invalid IDs return 404 with `{ "detail": "..." }`
3. All datetime fields use ISO 8601 format with timezone

---

---

## Interview Configuration Endpoints

These endpoints manage the interview questions generated by the AI for each vacancy.

### 6. Save Interview Configuration

```
PUT /vacancies/{vacancy_id}/interview
```

Saves or updates the interview configuration for a vacancy. Also updates the vacancy status to `screening_active`.

**Request Body:**
```json
{
  "intro": "Hallo! Leuk dat je solliciteert. Ben je klaar voor een paar korte vragen?",
  "knockout_questions": [
    {"id": "ko_1", "question": "Ben je in het bezit van een geldige Belgische werkvergunning?"},
    {"id": "ko_2", "question": "Kan je werken in een 2-ploegensysteem?"}
  ],
  "knockout_failed_action": "Helaas voldoe je niet aan de basisvereisten. Interesse in andere matches?",
  "qualification_questions": [
    {"id": "qual_1", "question": "Welke ervaring heb je met productiemachines?"},
    {"id": "qual_2", "question": "Kan je een voorbeeld geven van hoe je een storing hebt opgelost?"}
  ],
  "final_action": "Perfect! We plannen een gesprek met de recruiter.",
  "approved_ids": ["ko_1", "ko_2", "qual_1"]
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Interview configuration saved",
  "vacancy_id": "vac-123",
  "vacancy_status": "screening_active"
}
```

---

### 7. Get Interview Configuration

```
GET /vacancies/{vacancy_id}/interview
```

Returns the interview configuration for a vacancy.

**Response:**
```json
{
  "vacancy_id": "vac-123",
  "intro": "Hallo! Leuk dat je solliciteert...",
  "knockout_questions": [
    {"id": "ko_1", "question": "Ben je in het bezit van een geldige Belgische werkvergunning?"},
    {"id": "ko_2", "question": "Kan je werken in een 2-ploegensysteem?"}
  ],
  "knockout_failed_action": "Helaas voldoe je niet aan de basisvereisten...",
  "qualification_questions": [
    {"id": "qual_1", "question": "Welke ervaring heb je met productiemachines?"},
    {"id": "qual_2", "question": "Kan je een voorbeeld geven..."}
  ],
  "final_action": "Perfect! We plannen een gesprek met de recruiter.",
  "approved_ids": ["ko_1", "ko_2", "qual_1"],
  "created_at": "2026-01-30T10:00:00Z",
  "updated_at": "2026-01-30T10:30:00Z"
}
```

**Error Response (404):**
```json
{
  "detail": "No interview configuration found for this vacancy"
}
```

---

### 8. Delete Interview Configuration

```
DELETE /vacancies/{vacancy_id}/interview
```

Deletes the interview configuration for a vacancy. Resets the vacancy status to `new`.

**Response:**
```json
{
  "status": "success",
  "message": "Interview configuration deleted",
  "vacancy_id": "vac-123",
  "vacancy_status": "new"
}
```

---

## Frontend Integration - Interview Configuration

Add to `lib/interview-api.ts`:

```typescript
export interface InterviewQuestion {
  id: string;
  question: string;
}

export interface InterviewConfig {
  vacancy_id?: string;
  intro: string;
  knockout_questions: InterviewQuestion[];
  knockout_failed_action: string;
  qualification_questions: InterviewQuestion[];
  final_action: string;
  approved_ids: string[];
  created_at?: string;
  updated_at?: string;
}

export async function saveInterviewConfig(
  vacancyId: string,
  config: Omit<InterviewConfig, 'vacancy_id' | 'created_at' | 'updated_at'>
): Promise<{ status: string; vacancy_id: string; vacancy_status: string }> {
  const response = await fetch(`${BACKEND_URL}/vacancies/${vacancyId}/interview`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  
  if (!response.ok) throw new Error('Failed to save interview config');
  return response.json();
}

export async function getInterviewConfig(vacancyId: string): Promise<InterviewConfig> {
  const response = await fetch(`${BACKEND_URL}/vacancies/${vacancyId}/interview`);
  
  if (response.status === 404) return null;
  if (!response.ok) throw new Error('Failed to fetch interview config');
  return response.json();
}

export async function deleteInterviewConfig(vacancyId: string): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/vacancies/${vacancyId}/interview`, {
    method: 'DELETE',
  });
  
  if (!response.ok) throw new Error('Failed to delete interview config');
}
```

---

## Implementation Priority

1. **Phase 1**: `GET /vacancies` and `GET /vacancies/{id}` - Enables vacancy listing
2. **Phase 2**: `GET /vacancies/{id}/applications` - Enables dashboard view
3. **Phase 3**: Statistics endpoint - Nice to have for dashboard widgets
4. **Phase 4**: Interview config endpoints - Save generated questions to vacancy