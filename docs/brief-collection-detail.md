# Document Collection Detail Panel — Frontend Brief

## Overview

`GET /workspaces/{workspace_id}/document-collection/collections/{collection_id}/detail` is the **single endpoint** for the collection detail panel. Returns everything needed — collection items checklist, workflow progress, chat messages.

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
  candidacy_stage?: CandidacyStage;
  goal: CollectionGoal;
  candidate_name: string;
  candidate_phone?: string;
  status: "active" | "completed" | "needs_review" | "abandoned";
  progress: "pending" | "started" | "in_progress";
  channel: string;
  retry_count: number;
  message_count: number;
  documents_collected: number;
  documents_total: number;
  started_at: string;
  updated_at: string;
  completed_at?: string;

  // --- Links ---
  candidacy_id?: string;
  candidate_id?: string;

  // --- Plan summary (recruiter-facing) ---
  summary?: string;              // Short admin summary (Dutch)
  deadline_note?: string;        // e.g. "Start op 24 maart"

  // --- Unified checklist: documents + attributes with status ---
  collection_items: CollectionItemStatusResponse[];

  // --- Other enriched data ---
  workflow_steps: WorkflowStepResponse[];
  messages: CollectionMessageResponse[];
  uploads: CollectionUploadResponse[];
  documents_required: DocumentTypeResponse[];
}
```

## Key Types

### CollectionItemStatusResponse

Unified status for every item being collected — both documents and attributes. **This is the primary data source for the header checklist.**

```typescript
type CollectionItemType = "document" | "attribute" | "task";

interface CollectionItemStatusResponse {
  slug: string;                  // e.g. "id_card", "iban", "medical_screening"
  name: string;                  // e.g. "ID-kaart", "IBAN", "Medische schifting"
  type: CollectionItemType;      // "document", "attribute", or "task"
  priority: "required" | "recommended";
  status: DocumentStatus;        // "pending" | "asked" | "received" | "verified" | "failed" | "skipped"
  value?: string;                // For attributes: the collected value (e.g. "BE68 5390 0754 7034")
  upload_id?: string;            // For documents: upload reference
  verification_passed?: boolean; // For documents: verification result
  uploaded_at?: string;          // For documents: upload timestamp
}
```

### CandidacyStage

```typescript
type CandidacyStage =
  | "new" | "pre_screening" | "qualified"
  | "interview_planned" | "interview_done"
  | "offer" | "placed" | "rejected" | "withdrawn";

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

### CollectionGoal

```typescript
type CollectionGoal = "collect_basic" | "collect_and_sign" | "document_renewal";

const goalLabels: Record<CollectionGoal, string> = {
  collect_basic:    "Documenten & gegevens",
  collect_and_sign: "Verzamelen & ondertekenen",
  document_renewal: "Document vernieuwing",
};
```

### WorkflowStepResponse

```typescript
interface WorkflowStepResponse {
  id: string;
  label: string;
  status: "completed" | "current" | "pending" | "failed";
}
```

### CollectionMessageResponse

```typescript
interface CollectionMessageResponse {
  role: "user" | "agent" | "system";
  message: string;
  created_at: string;
}
```

## Panel Layout

```
┌──────────────────────────────────────────────────────────┐
│  HEADER (always visible, scrolls with content)           │
│  ┌──────────────────────────────────────────────────────┐│
│  │ Pieter de Vries                               [X]   ││
│  │ Productieoperator  ·  Lopend  ·  Nieuw  ·  WhatsApp ││
│  │ 📞 +32487...  → Kandidaat  → Kandidatuur            ││
│  │                                                       ││
│  │ "Pieter start op 24 maart. ID-kaart, rijbewijs en    ││
│  │  bankgegevens nog nodig."                             ││
│  │  Start op 24 maart                                    ││
│  │                                                       ││
│  │ DOCUMENTEN (2/3)                                      ││
│  │  ✅ ID-kaart                                          ││
│  │  ✅ Rijbewijs                     13 mrt 15:03       ││
│  │  ⏳ IBAN                                              ││
│  │                                                       ││
│  │ GEGEVENS (1/2)                                        ││
│  │  ✅ Woonplaats                    Gent                ││
│  │  ⏳ Noodcontact                                       ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  [ Tijdlijn ]  [ Chat ]                                  │
│                                                          │
│ ─── TAB: Tijdlijn ─────────────────────────────────────│
│  [✓ Plan] → [● Verzamelen] → [ Opvolging] → [ Afgerond]│
│                                                          │
│  ● 13 mrt, 14:30  Verzamelplan gegenereerd              │
│  ● 13 mrt, 14:31  WhatsApp intro verstuurd              │
│  ● 13 mrt, 15:02  ID-kaart ontvangen ✓                  │
│  ● 13 mrt, 15:03  Rijbewijs ontvangen ✓                 │
│                                                          │
│ ─── TAB: Chat ─────────────────────────────────────────│
│  🤖 Hoi Pieter! Leuk dat je start als...                │
│  👤 Hoi! Ja klopt                                        │
│  🤖 Top! Kun je een foto van je ID sturen?               │
│  👤 [foto]                                               │
│  🤖 ✅ ID-kaart goed ontvangen! Nu je rijbewijs...      │
└──────────────────────────────────────────────────────────┘
```

## Data Source Mapping

| Section | Data source | Notes |
|---------|-------------|-------|
| **Header title** | `candidate_name` | |
| **Header subtitle** | `status`, `goal` | Status + goal badges |
| **Summary** | `summary` | From plan, recruiter-facing |
| **Documenten checklist** | `collection_items` where `type === "document"` | Counter: verified / total |
| **Gegevens checklist** | `collection_items` where `type === "attribute"` | Counter: received+verified / total |
| **Taken checklist** | `collection_items` where `type === "task"` | Counter: received+verified / total |
| **Tijdlijn** | `workflow_steps` + `GET /monitoring?candidate_id=...&vacancy_id=...` | |
| **Chat** | `messages` | WhatsApp transcript |

## Item Status Rendering

```typescript
const itemStatusConfig = {
  pending:  { label: "Wachtend",      icon: "clock",           color: "gray" },
  asked:    { label: "Gevraagd",      icon: "message-circle",  color: "blue" },
  received: { label: "Ontvangen",     icon: "download",        color: "yellow" },
  verified: { label: "Geverifieerd",  icon: "check-circle-2",  color: "green" },
  failed:   { label: "Mislukt",       icon: "x-circle",        color: "red" },
  skipped:  { label: "Overgeslagen",  icon: "skip-forward",    color: "gray" },
};

// Each item row shows:
// - Status icon (left)
// - Item name
// - "(optioneel)" label if priority === "recommended"
// - For attributes with value: show value on the right (mono font)
// - For documents with uploaded_at: show timestamp on the right
// - Green check if verification_passed
```

## What Changed (v2 → v3)

| Before | After |
|--------|-------|
| `plan` (full agent script) | `summary` + `deadline_note` (header only) |
| `document_statuses` (docs only) | `collection_items` (docs + attributes unified) |
| Tabs: Tijdlijn, Documenten, Plan, Chat | Tabs: Tijdlijn, Chat |
| Documenten tab with card grid | Header checklist (always visible) |
| Plan tab with conversation steps | Removed (internal agent detail) |

## Related Endpoints

| Endpoint | Use |
|----------|-----|
| `GET .../collections` | List view (paginated, filtered) |
| `GET .../collections/{id}/detail` | **Full detail panel** (this endpoint) |
| `POST .../collections/{id}/abandon` | Mark collection as abandoned |
| `GET /monitoring?candidate_id=...` | Timeline events for Tijdlijn tab |
