# Candidate Detail Endpoint — Frontend Brief

## Overview

`GET /candidates/{candidate_id}` is the **single endpoint** for the candidate detail panel. It returns everything needed — no extra API calls required.

Used in both:
- **Pipeline view** (Kanban) → click candidate card → side panel
- **Candidates view** → click candidate row → side panel

## Response Shape

```typescript
interface CandidateDetailResponse {
  // --- Core info ---
  id: string
  phone?: string
  email?: string
  first_name?: string
  last_name?: string
  full_name: string
  source?: string
  status: "new" | "qualified" | "active" | "placed" | "inactive"
  status_updated_at?: string
  availability: "available" | "unavailable" | "unknown"
  available_from?: string        // YYYY-MM-DD
  rating?: number                // 0.0–5.0
  is_test: boolean
  created_at: string
  updated_at: string

  // --- Nested arrays ---
  applications: ApplicationSummary[]
  skills: SkillSummary[]
  attributes: AttributeSummary[]
  candidacies: CandidacySummary[]
  documents: DocumentSummary[]
  timeline: ActivityEntry[]
}
```

## Nested Types

### CandidacySummary

Replaces the separate `GET /candidacies?candidate_id=...` call. Each entry is a pipeline position.

```typescript
interface CandidacySummary {
  id: string
  vacancy_id?: string            // null = talent pool
  stage: CandidacyStage
  source?: string                // "voice" | "whatsapp" | "cv" | "manual" | "import"
  stage_updated_at: string
  created_at: string
  vacancy_title?: string
  vacancy_company?: string
  is_open_application: boolean
  latest_application?: CandidacyApplicationBrief
}

interface CandidacyApplicationBrief {
  id: string
  channel: string                // "voice" | "whatsapp" | "cv"
  status: string                 // "active" | "completed"
  qualified?: boolean
  open_questions_score?: number  // 0–100
  knockout_passed: number
  knockout_total: number
  completed_at?: string
}

type CandidacyStage =
  | "new"
  | "pre_screening"
  | "qualified"
  | "interview_planned"
  | "interview_done"
  | "offer"
  | "placed"
  | "rejected"
  | "withdrawn"
```

### DocumentSummary

Documents collected from the candidate (ID cards, certificates, etc.).

```typescript
interface DocumentSummary {
  id: string
  document_type_id: string
  document_type_name: string     // e.g. "Rijbewijs"
  document_type_slug?: string    // e.g. "driver_license"
  document_number?: string
  expiration_date?: string       // YYYY-MM-DD
  status: string                 // "pending_review" | "approved" | "rejected"
  verification_passed?: boolean
  storage_path?: string
  notes?: string
  created_at: string
  updated_at: string
}
```

### AttributeSummary

Structured facts collected by agents or entered manually.

```typescript
interface AttributeSummary {
  id: string
  attribute_type_id: string
  slug: string                   // e.g. "has_own_transport"
  name: string                   // e.g. "Eigen vervoer"
  category: string               // "legal" | "transport" | "availability" | "financial" | "personal" | "general"
  data_type: string              // "text" | "boolean" | "date" | "select" | "multi_select" | "number"
  options?: { value: string; label: string }[]
  icon?: string                  // lucide icon name
  value?: string                 // always string, interpret by data_type
  source?: string                // "pre_screening" | "contract" | "manual" | "cv_analysis"
  verified: boolean
  created_at: string
}
```

### ApplicationSummary

```typescript
interface ApplicationSummary {
  id: string
  vacancy_id: string
  vacancy_title: string
  vacancy_company: string
  channel: string                // "voice" | "whatsapp" | "cv"
  status: string                 // "active" | "completed" | "abandoned"
  qualified?: boolean
  started_at: string
  completed_at?: string
}
```

### SkillSummary

```typescript
interface SkillSummary {
  id: string
  skill_name: string
  skill_code?: string
  skill_category?: string        // "skills" | "education" | "certificates" | "personality"
  score?: number                 // 0.0–1.0
  evidence?: string
  source: string                 // "cv_analysis" | "manual" | "screening" | "import"
  created_at: string
}
```

### ActivityEntry

```typescript
interface ActivityEntry {
  id: string
  candidate_id: string
  application_id?: string
  vacancy_id?: string
  event_type: string             // "screening_started" | "qualified" | "disqualified" | etc.
  channel?: string               // "voice" | "whatsapp" | "cv" | "web"
  actor_type: string             // "candidate" | "agent" | "recruiter" | "system"
  actor_id?: string
  metadata: Record<string, any>
  summary?: string               // Dutch human-readable
  created_at: string
}
```

## Example Response

```json
{
  "id": "be8e49f2-335c-4322-a360-748c3668fb60",
  "full_name": "Bram Jansen",
  "phone": "32487441391",
  "email": null,
  "status": "new",
  "availability": "unknown",
  "rating": null,
  "is_test": false,

  "candidacies": [
    {
      "id": "a3d9ce14-...",
      "vacancy_id": "9cb4e150-...",
      "stage": "pre_screening",
      "source": "whatsapp",
      "stage_updated_at": "2026-03-12T13:04:33Z",
      "vacancy_title": "Technisch commercieel binnendienst medewerker",
      "vacancy_company": "Klant regio Kortemark",
      "is_open_application": false,
      "latest_application": {
        "id": "44fa5934-...",
        "channel": "whatsapp",
        "status": "completed",
        "qualified": true,
        "open_questions_score": 72,
        "knockout_passed": 3,
        "knockout_total": 3,
        "completed_at": "2026-03-12T13:15:00Z"
      }
    }
  ],

  "attributes": [
    {
      "slug": "has_own_transport",
      "name": "Eigen vervoer",
      "category": "transport",
      "data_type": "boolean",
      "icon": "car",
      "value": "true",
      "source": "pre_screening",
      "verified": false
    },
    {
      "slug": "available_from",
      "name": "Beschikbaar vanaf",
      "category": "availability",
      "data_type": "date",
      "icon": "calendar",
      "value": "2026-04-01",
      "source": "pre_screening",
      "verified": false
    }
  ],

  "documents": [
    {
      "document_type_name": "Rijbewijs",
      "document_type_slug": "driver_license",
      "status": "approved",
      "verification_passed": true,
      "expiration_date": "2028-06-15"
    }
  ],

  "skills": [
    {
      "skill_name": "Heftruckbrevet",
      "skill_category": "certificates",
      "score": 1.0,
      "source": "cv_analysis"
    }
  ],

  "applications": [...],
  "timeline": [...]
}
```

## Frontend Migration

### Before (2 API calls)

```typescript
// Pipeline view: click candidate
const candidacies = await getCandidacies({ candidate_id })  // GET /candidacies?candidate_id=...
const candidate = await getCandidate(candidateId)            // GET /candidates/{id}
```

### After (1 API call)

```typescript
// Both views: click candidate
const candidate = await getCandidate(candidateId)            // GET /candidates/{id}
// candidate.candidacies replaces the separate call
// candidate.attributes + candidate.documents are new
```

### What to update in the FE

1. **Remove** the `getCandidacies({ candidate_id })` call from `candidate-detail-pane.tsx`
2. **Use** `candidate.candidacies` instead — same data, different shape (flattened vacancy info instead of nested objects)
3. **Add** `candidacies`, `attributes`, `documents` to the `APICandidateDetail` type in `types.ts`
4. **Build** attributes section grouped by `category` (see [brief.md](brief.md) for rendering rules)
5. **Build** documents section showing status badges

### Mapping from old Candidacy type

| Old (`GET /candidacies`) | New (`candidate.candidacies[]`) |
|---|---|
| `candidate` (nested object) | Not needed (you're already on the candidate) |
| `vacancy.id` | `vacancy_id` |
| `vacancy.title` | `vacancy_title` |
| `vacancy.company` | `vacancy_company` |
| `vacancy.is_open_application` | `is_open_application` |
| `latest_application.status` | `latest_application.status` |
| `linked_vacancies` | Not included (use `candidacies` array itself — all vacancies are listed) |

## Value Interpretation (attributes)

The `value` field is always a string. Frontend interprets based on `data_type`:

| data_type | Storage | Display |
|-----------|---------|---------|
| `text` | `"Jan Peeters"` | Plain text |
| `boolean` | `"true"` / `"false"` | Toggle / check icon |
| `date` | `"2026-04-01"` | Formatted date |
| `number` | `"42"` | Number |
| `select` | `"eu_citizen"` | Lookup label from `options` |
| `multi_select` | `"day,night"` | Split by `,`, lookup labels |
