# Publish Pre-Screening API

This document describes the API endpoints for publishing pre-screenings and managing their online/offline status.

## Overview

Publishing a pre-screening creates AI agents (ElevenLabs for voice calls, WhatsApp for messaging) with the configured questions.

### Key Behavior

> **Publishing automatically sets the pre-screening ONLINE.**
> 
> When you call the publish endpoint, the agents are created AND immediately activated. No separate "go online" call is needed.
> 
> The online/offline toggle is only for **temporarily pausing** agents without having to republish.

## Endpoints

### 1. Publish Pre-Screening

**`POST /vacancies/{vacancy_id}/pre-screening/publish`**

Creates AI agents for the pre-screening with the current configuration.

#### Request Body

```typescript
interface PublishRequest {
  enable_voice?: boolean;    // Create ElevenLabs agent (default: true)
  enable_whatsapp?: boolean; // Create WhatsApp agent (default: true)
}
```

#### Response

```typescript
interface PublishResponse {
  status: "success";
  published_at: string;           // ISO 8601 timestamp
  elevenlabs_agent_id?: string;   // ElevenLabs agent ID (if voice enabled)
  whatsapp_agent_id?: string;     // WhatsApp agent ID (if whatsapp enabled)
  is_online: boolean;             // Always true after publish (automatically goes online)
  message: string;
}
```

#### Example

```javascript
// Publish with both voice and WhatsApp enabled
const response = await fetch(`/vacancies/${vacancyId}/pre-screening/publish`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    enable_voice: true,
    enable_whatsapp: true
  })
});

const data = await response.json();
// {
//   status: "success",
//   published_at: "2026-01-31T12:00:00Z",
//   elevenlabs_agent_id: "agent_abc123",
//   whatsapp_agent_id: "vacancy-uuid",
//   is_online: true,
//   message: "Pre-screening published and is now online"
// }
```

#### Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Invalid vacancy ID format |
| 404 | No pre-screening found for vacancy |
| 500 | Failed to create voice/WhatsApp agent |

---

### 2. Update Status (Online/Offline)

**`PATCH /vacancies/{vacancy_id}/pre-screening/status`**

Toggle the online/offline status of a published pre-screening.

> **When to use:** This endpoint is for temporarily pausing agents (e.g., during maintenance or off-hours). Publishing already sets the status to online, so you don't need to call this after publishing.

#### Request Body

```typescript
interface StatusUpdateRequest {
  is_online: boolean;
}
```

#### Response

```typescript
interface StatusUpdateResponse {
  status: "success";
  is_online: boolean;
  message: string;
  elevenlabs_agent_id?: string;
  whatsapp_agent_id?: string;
}
```

#### Example

```javascript
// Set pre-screening online
const response = await fetch(`/vacancies/${vacancyId}/pre-screening/status`, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ is_online: true })
});

const data = await response.json();
// {
//   status: "success",
//   is_online: true,
//   message: "Pre-screening is now online",
//   elevenlabs_agent_id: "agent_abc123",
//   whatsapp_agent_id: "vacancy-uuid"
// }
```

#### Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Invalid vacancy ID format |
| 400 | Pre-screening not published yet |
| 404 | No pre-screening found for vacancy |

---

### 3. Get Pre-Screening (Updated)

**`GET /vacancies/{vacancy_id}/pre-screening`**

Now includes publishing fields in the response.

#### Response (New Fields)

```typescript
interface PreScreeningResponse {
  // ... existing fields ...
  
  // New publishing fields
  published_at?: string;          // ISO 8601 timestamp (null if never published)
  is_online: boolean;             // Whether agents are actively handling calls/messages
  elevenlabs_agent_id?: string;   // ElevenLabs agent ID
  whatsapp_agent_id?: string;     // WhatsApp agent ID
}
```

---

## Frontend Implementation Guide

### State Management

```typescript
interface PreScreeningState {
  // Existing fields
  id: string;
  intro: string;
  knockout_questions: Question[];
  qualification_questions: Question[];
  // ...
  
  // Publishing state
  published_at: string | null;
  is_online: boolean;
  elevenlabs_agent_id: string | null;
  whatsapp_agent_id: string | null;
}
```

### UI Components

#### 1. Publish Button

Show when pre-screening exists but hasn't been published:

```tsx
{!preScreening.published_at && (
  <Button onClick={handlePublish}>
    Publish Pre-Screening
  </Button>
)}
```

#### 2. Republish Button

Show when pre-screening has been published (allows updating agents with new questions):

```tsx
{preScreening.published_at && (
  <Button variant="outline" onClick={handlePublish}>
    Republish Changes
  </Button>
)}
```

#### 3. Online/Offline Toggle

Only show after publishing:

```tsx
{preScreening.published_at && (
  <Switch
    checked={preScreening.is_online}
    onCheckedChange={handleStatusChange}
    label={preScreening.is_online ? "Online" : "Offline"}
  />
)}
```

#### 4. Status Indicators

```tsx
// Publishing status badge
{preScreening.published_at ? (
  <Badge variant={preScreening.is_online ? "success" : "warning"}>
    {preScreening.is_online ? "Online" : "Offline"}
  </Badge>
) : (
  <Badge variant="secondary">Draft</Badge>
)}

// Last published timestamp
{preScreening.published_at && (
  <Text size="sm" color="muted">
    Last published: {formatDate(preScreening.published_at)}
  </Text>
)}
```

**Note:** Publishing automatically sets the pre-screening online. The toggle is only for temporarily pausing agents.

### Publish Flow

```tsx
async function handlePublish() {
  setPublishing(true);
  
  try {
    // Show channel selection dialog
    const channels = await showPublishDialog();
    
    const response = await fetch(`/vacancies/${vacancyId}/pre-screening/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enable_voice: channels.voice,
        enable_whatsapp: channels.whatsapp
      })
    });
    
    if (!response.ok) {
      throw new Error('Failed to publish');
    }
    
    const data = await response.json();
    
    // Update local state
    setPreScreening(prev => ({
      ...prev,
      published_at: data.published_at,
      elevenlabs_agent_id: data.elevenlabs_agent_id,
      whatsapp_agent_id: data.whatsapp_agent_id,
      is_online: data.is_online
    }));
    
    // Note: is_online will be true - publishing automatically goes online
    toast.success('Pre-screening published and is now online!');
  } catch (error) {
    toast.error('Failed to publish pre-screening');
  } finally {
    setPublishing(false);
  }
}
```

### Status Toggle Flow

```tsx
async function handleStatusChange(isOnline: boolean) {
  try {
    const response = await fetch(`/vacancies/${vacancyId}/pre-screening/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_online: isOnline })
    });
    
    if (!response.ok) {
      throw new Error('Failed to update status');
    }
    
    const data = await response.json();
    
    setPreScreening(prev => ({
      ...prev,
      is_online: data.is_online
    }));
    
    toast.success(data.message);
  } catch (error) {
    toast.error('Failed to update status');
  }
}
```

---

## Database Migration

Run this SQL to add the new columns:

```sql
-- Add publishing columns to pre_screenings table
ALTER TABLE pre_screenings ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;
ALTER TABLE pre_screenings ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT FALSE;
ALTER TABLE pre_screenings ADD COLUMN IF NOT EXISTS elevenlabs_agent_id TEXT;
ALTER TABLE pre_screenings ADD COLUMN IF NOT EXISTS whatsapp_agent_id TEXT;
```

---

## Workflow Summary

```
┌─────────────────┐
│  Draft State    │  pre_screening exists, published_at = null
│  (Editing)      │  
└────────┬────────┘
         │ Click "Publish"
         ▼
┌─────────────────┐
│  Published      │  published_at set, is_online = true (automatic)
│  (Online)       │  Agents actively handling calls/messages
└────────┬────────┘
         │ Toggle offline (optional)
         ▼
┌─────────────────┐
│  Published      │  is_online = false
│  (Offline)      │  Agents paused, not handling calls/messages
└─────────────────┘
```
