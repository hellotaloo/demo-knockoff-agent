# Frontend Migration: Application Status Refactoring

## Summary

The `completed` boolean field has been removed from the Application API response. The `status` field is now the single source of truth for tracking application workflow state.

**Breaking Change**: The `completed` field no longer exists in API responses.

## Migration Guide

### Before (Old Structure)

```json
{
  "id": "app-123",
  "candidate_name": "Jan Peeters",
  "channel": "voice",
  "completed": true,
  "qualified": true,
  "status": "completed"
}
```

### After (New Structure)

```json
{
  "id": "app-123",
  "candidate_name": "Jan Peeters",
  "channel": "voice",
  "status": "completed",
  "qualified": true
}
```

## Status Values

| Status | Description | Display Text (NL) |
|--------|-------------|-------------------|
| `active` | Screening in progress, candidate is answering questions | "Bezig" |
| `processing` | Screening ended, AI is analyzing the transcript | "Verwerken..." |
| `completed` | Screening finished, check `qualified` for outcome | "Afgerond" |

## Code Migration

### TypeScript Interface

```typescript
// Before
interface Application {
  completed: boolean;
  qualified: boolean;
  status: string;
}

// After
interface Application {
  status: 'active' | 'processing' | 'completed';
  qualified: boolean;  // Only meaningful when status === 'completed'
}
```

### Checking Completion Status

```typescript
// Before
if (application.completed) {
  // Show results
}

// After
if (application.status === 'completed') {
  // Show results
}
```

### Filtering Applications

```typescript
// Before
const completedApps = applications.filter(app => app.completed);
const inProgressApps = applications.filter(app => !app.completed);

// After
const completedApps = applications.filter(app => app.status === 'completed');
const inProgressApps = applications.filter(app => app.status !== 'completed');
```

### Displaying Status in UI

```typescript
// Before
<Badge>{application.completed ? 'Afgerond' : 'Bezig'}</Badge>

// After
function getStatusLabel(status: string): string {
  switch (status) {
    case 'completed': return 'Afgerond';
    case 'processing': return 'Verwerken...';
    case 'active': return 'Bezig';
    default: return status;
  }
}

<Badge>{getStatusLabel(application.status)}</Badge>
```

### Showing Qualification Status

```typescript
// Qualification is only meaningful when screening is completed
if (application.status === 'completed') {
  if (application.qualified) {
    // Show "Gekwalificeerd" badge
  } else {
    // Show "Niet gekwalificeerd" badge
  }
}
```

## API Query Parameters

The `?completed=true` query parameter **still works** for backwards compatibility. It is translated internally to `status='completed'`.

```
GET /vacancies/{id}/applications?completed=true
// Equivalent to filtering by status='completed'

GET /vacancies/{id}/applications?completed=false
// Equivalent to filtering by status!='completed' (active or processing)
```

## Data Model

```
                   +-----------+
                   |   active  |  Application created, screening in progress
                   +-----+-----+
                         |
                         v
                   +-----------+
                   | processing|  Transcript is being analyzed by AI
                   +-----+-----+
                         |
                         v
                   +-----------+
                   | completed |  Screening finished
                   +-----+-----+
                         |
                   +-----+-----+
                   |           |
                   v           v
            qualified=true  qualified=false
            (Passed)        (Failed)
```

## Stats Response Changes

The `VacancyStatsResponse` model has also been updated:

```typescript
// Before
interface VacancyStats {
  completed: number;      // Count of completed applications
  qualified: number;      // Count of qualified applications
}

// After
interface VacancyStats {
  completed_count: number;   // Count of applications with status='completed'
  qualified_count: number;   // Count of applications with qualified=true
}
```

## Questions?

If you have questions about this migration, check the backend API documentation in `docs/REST_API_ENDPOINTS.MD` or contact the backend team.
