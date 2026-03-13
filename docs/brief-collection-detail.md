# Document Collection Detail Panel — Frontend Brief

## Overview

`GET /workspaces/{workspace_id}/document-collection/collections/{collection_id}/detail` is the **single endpoint** for the collection detail panel. Returns everything needed — plan, document statuses, workflow progress, chat messages.

Used in:
- **Document Collection view** → click collection row → side panel (same pattern as candidate detail)

## Endpoint

```
GET /workspaces/{workspace_id}/document-collection/collections/{collection_id}/detail
Authorization: Bearer <token>
```

## Response Shape

```typescript
interface DocumentCollectionFullDetailResponse {
  // --- Base collection info ---
  id: string;
  config_id: string;
  workspace_id: string;
  vacancy_id?: string;
  vacancy_title?: string;
  application_id?: string;
  candidacy_stage?: CandidacyStage;  // Current pipeline stage (null if no candidacy linked)
  candidate_name: string;
  candidate_phone?: string;
  status: "active" | "completed" | "needs_review" | "abandoned";
  progress: "pending" | "started" | "in_progress";
  channel: string;                 // "whatsapp"
  retry_count: number;
  message_count: number;
  documents_collected: number;     // Count of verified uploads
  documents_total: number;         // Total required documents
  started_at: string;
  updated_at: string;
  completed_at?: string;

  // --- Links ---
  candidacy_id?: string;           // Link to candidacy record
  candidate_id?: string;           // Link to candidate record

  // --- Enriched data ---
  plan?: CollectionPlanResponse;                    // Smart planner output (JSONB)
  document_statuses: CollectionDocumentStatusResponse[];  // Merged plan + upload state
  workflow_steps: WorkflowStepResponse[];           // Progress bar steps
  messages: CollectionMessageResponse[];            // WhatsApp chat transcript
  uploads: CollectionUploadResponse[];              // Raw upload records
  documents_required: DocumentTypeResponse[];       // Full document type objects
}
```

## Nested Types

### CollectionPlanResponse

The smart planner generates a structured conversation plan stored as JSONB. This is the parsed output.

```typescript
interface CollectionPlanResponse {
  summary?: string;              // Short admin summary (Dutch), for the header
  deadline_note?: string;        // e.g. "Start op 24 maart"
  intro_message?: string;        // Opening WhatsApp message
  documents_to_collect: CollectionPlanDocumentResponse[];
  attributes_to_collect: object[];   // e.g. [{slug: "iban", name: "IBAN nummer"}]
  conversation_steps: CollectionPlanStepResponse[];
  agent_managed_tasks: object[];
  already_complete: string[];    // Document slugs already collected
  final_step?: object;
}

interface CollectionPlanDocumentResponse {
  slug: string;                  // e.g. "id_card"
  name: string;                  // e.g. "ID-kaart"
  reason?: string;               // Why this document is needed
  priority: "required" | "recommended";
}

interface CollectionPlanStepResponse {
  step: number;                  // 1-based sequence
  topic: string;                 // e.g. "ID-scan"
  items: string[];               // Document/attribute slugs handled in this step
  message: string;               // Agent message template (Dutch)
}
```

### CollectionDocumentStatusResponse

Merged view combining the plan's documents with actual upload state. **This is the primary data source for the Documenten tab.**

```typescript
interface CollectionDocumentStatusResponse {
  slug: string;                  // e.g. "id_card"
  name: string;                  // e.g. "ID-kaart"
  priority: "required" | "recommended";
  status: "pending" | "asked" | "received" | "verified" | "failed" | "skipped";
  upload_id?: string;            // If an upload exists
  verification_passed?: boolean;
  uploaded_at?: string;
}
```

**Status flow:** `pending` → `asked` → `received` → `verified`

### WorkflowStepResponse

Steps for the horizontal progress bar at the top of the Tijdlijn tab.

```typescript
interface WorkflowStepResponse {
  id: string;                    // e.g. "plan_generated", "collecting"
  label: string;                 // Dutch display label
  status: "completed" | "current" | "pending" | "failed";
}
```

Default step sequence:
1. `plan_generated` — "Plan opgesteld"
2. `collecting` — "Verzamelen"
3. `reviewing_skipped` — "Opvolging"
4. `complete` — "Afgerond"

### CollectionMessageResponse

```typescript
interface CollectionMessageResponse {
  role: "user" | "agent" | "system";
  message: string;
  created_at: string;
}
```

### CollectionUploadResponse

```typescript
interface CollectionUploadResponse {
  id: string;
  document_type_id?: string;
  document_side: "front" | "back" | "single";
  verification_passed?: boolean;
  status: "pending" | "verified" | "rejected" | "needs_review";
  uploaded_at: string;
}
```

### CandidacyStage

The candidate's current position in the recruitment pipeline.

```typescript
type CandidacyStage =
  | "new"
  | "pre_screening"
  | "qualified"
  | "interview_planned"
  | "interview_done"
  | "offer"
  | "placed"
  | "rejected"
  | "withdrawn";

// Dutch labels for display
const stageLabels: Record<CandidacyStage, string> = {
  new: "Nieuw",
  pre_screening: "Pre-screening",
  qualified: "Gekwalificeerd",
  interview_planned: "Gesprek gepland",
  interview_done: "Gesprek afgerond",
  offer: "Aanbod",
  placed: "Geplaatst",
  rejected: "Afgewezen",
  withdrawn: "Teruggetrokken",
};
```

## Wireframe

```
┌──────────────────────────────────────────────────────────┐
│  HEADER                                                  │
│  ┌──────────────────────────────────────────────────────┐│
│  │ Pieter de Vries  →  Productieoperator (2 ploegen)   ││
│  │ ● Lopend  ·  0/3 documenten  ·  WhatsApp  ·  Nieuw  ││
│  │                                                       ││
│  │ "Pieter start op 24 maart. ID-kaart, rijbewijs en    ││
│  │  bankgegevens nog nodig. Medisch onderzoek gepland    ││
│  │  via werkgever."                                      ││
│  │  ─ plan.summary                                       ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  [ Tijdlijn ]  [ Documenten ]  [ Plan ]  [ Chat ]       │
│                                                          │
│ ─── TAB: Tijdlijn ─────────────────────────────────────│
│  Workflow progress bar (from workflow_steps):             │
│  [✓ Plan opgesteld] → [● Verzamelen] → [ Opvolging] → …│
│                                                          │
│  Timeline events (activities for this candidate+vacancy):│
│  ● 13 mrt, 14:30  Verzamelplan gegenereerd              │
│  ● 13 mrt, 14:31  WhatsApp intro verstuurd              │
│  ● 13 mrt, 15:02  ID-kaart ontvangen ✓                  │
│  ● 13 mrt, 15:03  Rijbewijs ontvangen ✓                 │
│                                                          │
│ ─── TAB: Documenten ───────────────────────────────────│
│  Card per document (from document_statuses):             │
│                                                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │ ID-kaart     │ │ Rijbewijs    │ │ IBAN          │    │
│  │ ✅ Geverif.  │ │ ⏳ Wachtend  │ │ ⏳ Wachtend  │    │
│  │ 13 mrt 15:02 │ │              │ │              │    │
│  └──────────────┘ └──────────────┘ └──────────────┘    │
│                                                          │
│ ─── TAB: Plan ─────────────────────────────────────────│
│  Conversation script (read-only, from plan):             │
│                                                          │
│  Step 1: ID-scan                                         │
│  "Maak een foto van voor- en achterkant van je ID"       │
│  Items: id_card                                          │
│                                                          │
│  Step 2: Rijbewijs                                       │
│  "Heb je je rijbewijs bij de hand? Stuur een foto"       │
│  Items: driver_license                                   │
│                                                          │
│  Step 3: Bankgegevens                                    │
│  "Wat is je IBAN-nummer?"                                │
│  Items: iban                                             │
│                                                          │
│ ─── TAB: Chat ─────────────────────────────────────────│
│  WhatsApp transcript (from messages):                    │
│                                                          │
│  🤖 Hoi Pieter! Leuk dat je start als...                │
│  👤 Hoi! Ja klopt                                        │
│  🤖 Top! Kun je een foto van je ID sturen?               │
│  👤 [foto]                                               │
│  🤖 ✅ ID-kaart goed ontvangen! Nu je rijbewijs...      │
└──────────────────────────────────────────────────────────┘
```

## Tab → Data Source Mapping

| Tab | Data source | Notes |
|-----|-------------|-------|
| **Header** | `candidate_name`, `vacancy_title`, `status`, `documents_collected`/`documents_total`, `channel`, `candidacy_stage`, `plan.summary` | Always visible |
| **Tijdlijn** | `workflow_steps` (progress bar) + separate activities endpoint (events) | Activities: `GET /monitoring?candidate_id=...&vacancy_id=...` |
| **Documenten** | `document_statuses` | Card grid, one card per document |
| **Plan** | `plan.conversation_steps` | Read-only conversation script |
| **Chat** | `messages` | WhatsApp transcript, role-based styling |

## Header Mapping

```typescript
// Header line 1: candidate name → vacancy title
const headerTitle = `${collection.candidate_name}`;
const headerSubtitle = collection.vacancy_title;  // may be null

// Header line 2: status badge + progress + channel
const statusLabel = {
  active: "Lopend",
  completed: "Afgerond",
  needs_review: "Beoordeling nodig",
  abandoned: "Verlaten",
}[collection.status];

const progressText = `${collection.documents_collected}/${collection.documents_total} documenten`;

// Header line 3: candidacy stage badge (if linked)
const stageBadge = collection.candidacy_stage
  ? stageLabels[collection.candidacy_stage]
  : null;

// Header summary: plan.summary (if available)
const summary = collection.plan?.summary;
```

## Document Status Card Rendering

```typescript
const statusConfig = {
  pending:   { label: "Wachtend",   color: "gray",   icon: "clock" },
  asked:     { label: "Gevraagd",   color: "blue",   icon: "message-circle" },
  received:  { label: "Ontvangen",  color: "yellow", icon: "download" },
  verified:  { label: "Geverifieerd", color: "green", icon: "check-circle" },
  failed:    { label: "Mislukt",    color: "red",    icon: "x-circle" },
  skipped:   { label: "Overgeslagen", color: "gray",  icon: "skip-forward" },
};

// For each document_statuses item:
// - Show name as card title
// - Show status badge with color + label
// - Show uploaded_at if present (formatted as "13 mrt 15:02")
// - Show verification_passed icon if verified
```

## Workflow Progress Bar

```typescript
// Render workflow_steps as a horizontal stepper:
// [✓ Step 1] ─── [● Step 2] ─── [○ Step 3] ─── [○ Step 4]

const stepStyle = {
  completed: { icon: "check", color: "green" },
  current:   { icon: "dot",   color: "blue", pulse: true },
  pending:   { icon: "dot",   color: "gray" },
  failed:    { icon: "x",     color: "red" },
};
```

## Chat Tab Rendering

```typescript
// Messages are ordered chronologically (oldest first)
// Style by role:
const messageStyle = {
  agent: { align: "left",  bg: "bg-muted",   label: "Agent" },
  user:  { align: "right", bg: "bg-primary/10", label: "Kandidaat" },
  system: { align: "center", bg: "bg-yellow-50", label: "Systeem" },
};
```

## Example Usage

```typescript
// Fetch collection detail
const collection = await fetch(
  `/workspaces/${workspaceId}/document-collection/collections/${collectionId}/detail`,
  { headers: { Authorization: `Bearer ${token}` } }
).then(r => r.json());

// Header
const title = collection.candidate_name;
const subtitle = collection.vacancy_title;
const summary = collection.plan?.summary;
const progress = `${collection.documents_collected}/${collection.documents_total}`;

// Documenten tab
const docCards = collection.document_statuses.map(doc => ({
  name: doc.name,
  status: doc.status,
  verified: doc.verification_passed,
  uploadedAt: doc.uploaded_at,
}));

// Plan tab
const steps = collection.plan?.conversation_steps ?? [];

// Chat tab
const messages = collection.messages;

// Workflow progress
const workflowSteps = collection.workflow_steps;
```

## Related Endpoints

| Endpoint | Use |
|----------|-----|
| `GET .../collections` | List view (paginated, filtered) |
| `GET .../collections/{id}` | Basic detail (messages + uploads, no plan/workflow) |
| `GET .../collections/{id}/detail` | **Full detail panel** (this endpoint) |
| `POST .../collections/{id}/abandon` | Mark collection as abandoned |
| `GET /monitoring?candidate_id=...` | Timeline events for Tijdlijn tab |
