# ATS Import — Frontend Brief (v2)

> **Breaking change:** The previous SSE streaming implementation (`text/event-stream`) has been replaced with a simple **POST + polling** pattern. **Delete all SSE/streaming code** (EventSource, fetch stream reader, SSE buffer parsing, `text/event-stream` handling) and replace it with the polling approach below.

## Overview

Vacancies are imported from a simulated external ATS (Applicant Tracking System). The import runs as a **background task** on the server. The frontend starts the import with a POST, then **polls a status endpoint every 3 seconds** to get progress updates.

The progress focuses on **pre-screening generation** — the ATS data import (recruiters, clients, vacancies) happens silently. The frontend shows a queue of vacancies with real-time status updates as pre-screening questions are generated for each one.

## API Endpoints

### 1. `POST /demo/import-ats` — Start the import

Kicks off the import as a background task. Returns immediately.

**Response:**
```json
{"status": "started", "message": "Import gestart. Poll GET /demo/import-ats/status voor voortgang."}
```

If an import is already running:
```json
{"status": "already_running", "message": "Import is already in progress"}
```

### 2. `GET /demo/import-ats/status` — Poll for progress

Returns the current state of the import. **Poll this every 3 seconds.**

## Status Response Shapes

The response always has a `status` field. The shape depends on the current phase:

### Phase 0: No import has run yet

```json
{"status": "idle", "message": "Geen import actief"}
```

### Phase 1: Importing ATS data (recruiters, clients, vacancies)

Short phase (~2-3 seconds). No vacancy details yet.

```json
{
  "status": "importing",
  "message": "Vacatures importeren...",
  "vacancies": []
}
```

### Phase 2: Generating pre-screening questions

The `vacancies` array contains every imported vacancy with its current generation status.

```json
{
  "status": "generating",
  "message": "Pre-screening vragen genereren...",
  "vacancies": [
    {"id": "3158c4d2-...", "title": "Operator Mengafdeling", "status": "published", "questions_count": 6, "activity": "Gepubliceerd"},
    {"id": "a1b2c3d4-...", "title": "Magazijnmedewerker", "status": "generating", "activity": "Knockout & kwalificatievragen opstellen..."},
    {"id": "f9e8d7c6-...", "title": "Heftruckchauffeur", "status": "queued"}
  ]
}
```

Each vacancy has one of 4 statuses:

| `status` | Meaning |
|----------|---------|
| `"queued"` | Waiting to be processed |
| `"generating"` | Currently generating questions (~5-15s) |
| `"published"` | Done — includes `questions_count` |
| `"failed"` | Generation failed |

The `activity` field (optional, only present during/after generation) shows what the AI agent is doing. During generation, it cycles through detailed reasoning steps every ~1.5 seconds:

- `"Vacaturetekst ontvangen, begin met analyse..."`
- `"Kernvereisten identificeren uit de functieomschrijving..."`
- `"Zoeken naar harde eisen: werkvergunning, locatie, beschikbaarheid..."`
- `"Knockout criteria formuleren op basis van must-haves..."`
- `"Kwalificatievragen opstellen voor ervaring en motivatie..."`
- ... (13 messages total)

After generation completes:
- `"3 knockout + 4 kwalificatievragen gegenereerd"` — questions ready
- `"Pre-screening publiceren..."` — publishing via workflow
- `"Gepubliceerd"` — done
- `"Generatie mislukt"` — failed

### Phase 3: Complete

All vacancies processed. This is the terminal state.

```json
{
  "status": "complete",
  "message": "Pre-screening vragen genereren...",
  "vacancies": [
    {"id": "3158c4d2-...", "title": "Operator Mengafdeling", "status": "published", "questions_count": 6},
    {"id": "a1b2c3d4-...", "title": "Magazijnmedewerker", "status": "published", "questions_count": 7}
  ],
  "total": 7,
  "published": 7,
  "failed": 0
}
```

When there were no new vacancies to import (all already existed):
```json
{
  "status": "complete",
  "message": "Pre-screening vragen genereren...",
  "vacancies": [],
  "total": 0,
  "published": 0,
  "failed": 0
}
```

### Error

```json
{
  "status": "error",
  "message": "Connection refused"
}
```

## TypeScript Types

```typescript
type PreScreeningStatus = "queued" | "generating" | "published" | "failed";
type ImportStatus = "idle" | "importing" | "generating" | "complete" | "error";

interface ImportVacancy {
  id: string;              // UUID — the vacancy's database ID
  title: string;
  status: PreScreeningStatus;
  questions_count?: number; // Only present when status === "published"
  activity?: string;        // Human-readable agent activity (e.g., "Knockout & kwalificatievragen opstellen...")
}

interface ImportProgress {
  status: ImportStatus;
  message: string;
  vacancies: ImportVacancy[];
  // Only present when status === "complete":
  total?: number;
  published?: number;
  failed?: number;
}

// POST /demo/import-ats response
interface ImportStartResponse {
  status: "started" | "already_running";
  message: string;
}
```

## Behavior

### Trigger
- A "Sync ATS" / "Importeer vacatures" button on the Pre-screening overview page
- Button should be visible when there are no vacancies, or as a general action in the toolbar

### Flow

1. Click button → `POST /demo/import-ats`
2. If response is `already_running`, show a message and don't start polling
3. Start polling `GET /demo/import-ats/status` every **3 seconds**
4. Show a modal/overlay with progress based on the response:
   - `importing` → loading spinner with "Vacatures importeren..."
   - `generating` → render the vacancy queue from `vacancies` array
   - `complete` → stop polling, show success, **refetch the vacancy list**
   - `error` → stop polling, show error message
5. User can **close the modal or refresh the page** at any time — the import continues in the background. Re-opening the page and polling `/status` will show the current progress.

### Queue visualization

| Status | Visual | Label |
|--------|--------|-------|
| `queued` | Grey/dimmed | — |
| `generating` | Spinner or brain/sparkle icon | "Vragen genereren..." |
| `published` | Green checkmark | "6 vragen" (use `questions_count`) |
| `failed` | Orange warning icon | "Mislukt" |

Vacancies are processed one-by-one. Question generation takes ~5-15 seconds per vacancy.

### Error handling

- If polling returns `error`, show the message and stop polling
- If a network error occurs during polling, retry on the next interval
- The import is idempotent — calling POST again after completion safely skips existing vacancies (`total: 0`)

## Frontend Implementation

```typescript
// 1. Start the import
const startImport = async () => {
  const res = await fetch("/demo/import-ats", { method: "POST" });
  const data: ImportStartResponse = await res.json();

  if (data.status === "already_running") {
    // Show "already running" message, but still start polling
  }

  startPolling();
};

// 2. Poll for progress
let pollInterval: ReturnType<typeof setInterval>;

const startPolling = () => {
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch("/demo/import-ats/status");
      const progress: ImportProgress = await res.json();

      // Update UI based on progress.status
      setProgress(progress);

      if (progress.status === "complete" || progress.status === "error") {
        clearInterval(pollInterval);

        if (progress.status === "complete") {
          await refetchVacancies();
        }
      }
    } catch {
      // Network error — retry on next interval
    }
  }, 3000);
};

// 3. Clean up on unmount
onUnmount(() => clearInterval(pollInterval));
```

## Reset Flow

The full demo flow is two steps:

1. `POST /demo/reset` — Clears all data, seeds candidates and ontology (no vacancies)
2. `POST /demo/import-ats` → poll `GET /demo/import-ats/status` — Imports vacancies and generates pre-screenings

After reset, the vacancy list is empty. The user clicks "Sync ATS" to populate it.

## What to delete

Remove all SSE/streaming related code from the previous implementation:
- `EventSource` or `fetch` stream reader logic
- SSE buffer parsing (`buffer.split("\n\n")`, `line.replace("data: ", "")`)
- `text/event-stream` content type handling
- `[DONE]` terminator handling
- Any `QueueEvent`, `UpdateEvent`, `StatusEvent`, `CompleteEvent`, `ErrorEvent` types from the old SSE approach
- The old `ImportEvent` union type
