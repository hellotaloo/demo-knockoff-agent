# Vacancy List API - Status Badge Guide

## Overview

The `GET /vacancies` endpoint now returns an `is_online` field that allows the frontend to correctly display status badges for pre-screening agents.

## Endpoint

```
GET /vacancies
```

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | - | Filter by vacancy status |
| `source` | string | - | Filter by source (e.g., "salesforce") |
| `limit` | int | 50 | Results per page (1-100) |
| `offset` | int | 0 | Pagination offset |

## Response Schema

```typescript
interface VacancyListResponse {
  vacancies: Vacancy[];
  total: number;
  limit: number;
  offset: number;
}

interface Vacancy {
  id: string;
  title: string;
  company: string;
  location: string | null;
  description: string | null;
  status: string;
  created_at: string;           // ISO 8601 datetime
  archived_at: string | null;   // ISO 8601 datetime
  source: string | null;
  source_id: string | null;
  has_screening: boolean;       // True if pre-screening exists
  is_online: boolean | null;    // null=draft, true=online, false=offline
  channels: Channels;           // Available screening channels
}

interface Channels {
  voice: boolean;               // True if elevenlabs_agent_id is set
  whatsapp: boolean;            // True if whatsapp_agent_id is set
}
```

## Status Badge Logic

Use the combination of `has_screening` and `is_online` to determine which badge to display:

| `has_screening` | `is_online` | Badge | Color | Meaning |
|-----------------|-------------|-------|-------|---------|
| `false` | `null` | Draft | Amber | No questions configured yet |
| `true` | `null` | Draft | Amber | Questions exist, not published |
| `true` | `true` | Online | Green | Agent is live and accepting candidates |
| `true` | `false` | Offline | Gray | Agent is paused/offline |

### TypeScript Implementation

```typescript
type BadgeVariant = 'draft' | 'online' | 'offline';

interface BadgeConfig {
  label: string;
  variant: BadgeVariant;
  color: string;
}

function getStatusBadge(vacancy: Vacancy): BadgeConfig {
  // No pre-screening exists OR not published yet
  if (vacancy.is_online === null) {
    return {
      label: 'Draft',
      variant: 'draft',
      color: 'amber'  // or your design system equivalent
    };
  }
  
  // Published and online
  if (vacancy.is_online === true) {
    return {
      label: 'Online',
      variant: 'online',
      color: 'green'
    };
  }
  
  // Published but offline
  return {
    label: 'Offline',
    variant: 'offline',
    color: 'gray'
  };
}
```

### React Component Example

```tsx
import { Badge } from '@/components/ui/badge';

const statusConfig = {
  draft: { label: 'Draft', variant: 'warning' as const },
  online: { label: 'Online', variant: 'success' as const },
  offline: { label: 'Offline', variant: 'secondary' as const },
};

function VacancyStatusBadge({ vacancy }: { vacancy: Vacancy }) {
  const status = vacancy.is_online === null 
    ? 'draft' 
    : vacancy.is_online 
      ? 'online' 
      : 'offline';
  
  const config = statusConfig[status];
  
  return (
    <Badge variant={config.variant}>
      {config.label}
    </Badge>
  );
}
```

## Example Response

```json
{
  "vacancies": [
    {
      "id": "cd1d4ee9-343c-4fc4-b10e-c0bccac001eb",
      "title": "Senior Developer",
      "company": "Acme Corp",
      "location": "Brussels",
      "status": "screening_active",
      "has_screening": true,
      "is_online": true,
      "channels": {
        "voice": true,
        "whatsapp": true
      },
      "created_at": "2025-01-15T10:00:00Z",
      "archived_at": null,
      "source": "salesforce",
      "source_id": "SF-12345"
    },
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "title": "Junior Designer",
      "company": "Design Co",
      "location": "Antwerp",
      "status": "new",
      "has_screening": true,
      "is_online": false,
      "channels": {
        "voice": true,
        "whatsapp": false
      },
      "created_at": "2025-01-20T14:30:00Z",
      "archived_at": null,
      "source": "salesforce",
      "source_id": "SF-67890"
    },
    {
      "id": "f9e8d7c6-b5a4-3210-fedc-ba0987654321",
      "title": "Marketing Manager",
      "company": "Brand Inc",
      "location": "Ghent",
      "status": "new",
      "has_screening": false,
      "is_online": null,
      "channels": {
        "voice": false,
        "whatsapp": false
      },
      "created_at": "2025-01-25T09:15:00Z",
      "archived_at": null,
      "source": "salesforce",
      "source_id": "SF-11111"
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
}
```

## Advanced: Distinguishing Draft States

If you need to show different UI for "no questions yet" vs "questions exist but not published":

```typescript
function getDetailedStatus(vacancy: Vacancy) {
  if (!vacancy.has_screening) {
    return 'no-questions';  // Show "Add Questions" CTA
  }
  
  if (vacancy.is_online === null) {
    return 'unpublished';   // Show "Publish" CTA
  }
  
  return vacancy.is_online ? 'online' : 'offline';
}
```

## Migration Notes

- The `is_online` field is newly added to this endpoint
- Existing integrations will receive the new field automatically
- No breaking changes to existing fields
