# Activities Dashboard - Frontend Brief

## Overview

A unified table view showing all active agent tasks across the platform. This gives recruiters real-time visibility into what AI agents are working on, which tasks may be stuck, and overall workflow progress.

## API Endpoint

```
GET /api/activities/tasks
```

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | `"active"` \| `"completed"` \| `"all"` | `"active"` | Filter by task status |
| `stuck_only` | boolean | `false` | Only show stuck tasks |
| `limit` | number | 50 | Results per page (max 200) |
| `offset` | number | 0 | Pagination offset |

### Response

```typescript
interface TaskRow {
  id: string;
  candidate_name: string | null;
  vacancy_title: string | null;
  workflow_type: string;           // "pre_screening", "document_collection"
  workflow_type_label: string;     // "Pre-screening", "Document Collection"
  current_step: string;            // "waiting", "knockout", "complete"
  current_step_label: string;      // "Knockout vraag 2/3", "Wacht op ID kaart"
  status: string;                  // "active", "stuck", "completed"
  is_stuck: boolean;
  updated_at: string;              // ISO timestamp
  time_ago: string;                // "2 min ago", "1 hour ago"
}

interface TasksResponse {
  tasks: TaskRow[];
  total: number;
  stuck_count: number;
}
```

---

## UI Design

### Table Layout

| Kandidaat | Vacature | Agent | Stap | Status | Laatste Update |
|-----------|----------|-------|------|--------|----------------|
| Jan Peeters | Operator Mengafdeling | Pre-screening | Knockout vraag 2/3 | Active | 2 min geleden |
| Marie Claes | Kassamedewerker | Pre-screening | Knockout vraag 1/3 | Active | 5 min geleden |
| Anna Vermeersch | Magazijnier | Document Collection | Wacht op Rijbewijs | Stuck | 1 uur geleden |

### Column Mapping

| Column Header | Field | Notes |
|---------------|-------|-------|
| Kandidaat | `candidate_name` | May be null (show "-" or "Onbekend") |
| Vacature | `vacancy_title` | May be null |
| Agent | `workflow_type_label` | Human-readable workflow type |
| Stap | `current_step_label` | Contextual step description |
| Status | `status` + `is_stuck` | See status badges below |
| Laatste Update | `time_ago` | Human-readable relative time |

### Status Badges

| Status | Badge Color | Label |
|--------|-------------|-------|
| `active` (not stuck) | Green | Actief |
| `stuck` / `is_stuck: true` | Yellow/Orange | Vast |
| `completed` | Gray | Afgerond |

### Filters

1. **Status Tabs** (top of table):
   - Actief (default) - `?status=active`
   - Afgerond - `?status=completed`
   - Alles - `?status=all`

2. **Stuck Filter** (toggle/checkbox):
   - "Toon alleen vastgelopen taken" - `?stuck_only=true`

3. **Stuck Count Badge**:
   - Show `stuck_count` as badge on "Actief" tab: "Actief (2 vast)"

---

## Example Requests

```bash
# Get all active tasks (default)
curl "http://localhost:8080/api/activities/tasks"

# Get only stuck tasks
curl "http://localhost:8080/api/activities/tasks?stuck_only=true"

# Get completed tasks
curl "http://localhost:8080/api/activities/tasks?status=completed"

# Pagination
curl "http://localhost:8080/api/activities/tasks?limit=20&offset=40"
```

---

## Demo Data

For development, seed demo data with:

```bash
curl -X POST "http://localhost:8080/demo/reset?reseed=true&workflow_activities=true"
```

This creates:
- Pre-screening tasks at various knockout question steps
- Document collection tasks waiting for different document types
- Tasks linked to real candidate/vacancy names from fixtures

---

## Polling / Real-time Updates

The dashboard should poll for updates:

```typescript
// Recommended: Poll every 30 seconds
useEffect(() => {
  const interval = setInterval(() => {
    fetchTasks();
  }, 30000);
  return () => clearInterval(interval);
}, []);
```

Future enhancement: WebSocket support for real-time updates.

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Empty response (`tasks: []`) | Show empty state: "Geen actieve taken" |
| API error | Show error banner, retry button |
| Null `candidate_name` | Show placeholder: "-" or "Onbekend" |
| Null `vacancy_title` | Show placeholder: "-" |

---

## Mobile Considerations

For mobile/responsive:
- Hide "Vacature" column on small screens
- Stack "Agent" and "Stap" into single column
- Use status icon instead of text badge

---

## Future Enhancements

1. **Click to detail**: Click row to open candidate/application detail
2. **Actions**: "Herinner" button to resend message to stuck tasks
3. **Filters**: Filter by workflow_type, search by candidate name
4. **Sorting**: Sort by updated_at, status, candidate_name
5. **Bulk actions**: Select multiple stuck tasks for batch operations
