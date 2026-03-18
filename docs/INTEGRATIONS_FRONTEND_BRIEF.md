# Integrations - Frontend Implementation Brief

## Overview

The Integrations page allows workspace admins to connect external services (ATS systems, calendar/meeting tools) to Taloo. Each integration can be configured with credentials, tested with a health check, and toggled on/off.

## Available Integrations

| Provider | Slug | Purpose | Credentials Required |
|----------|------|---------|---------------------|
| **Connexys** (Bullhorn) | `connexys` | ATS - sync candidates & vacancies from Salesforce | Instance URL, Consumer Key, Consumer Secret |
| **Microsoft Teams & Outlook** | `microsoft` | Calendar scheduling & video calls via Microsoft Graph | Tenant ID, Client ID, Client Secret |

## API Endpoints

Base URL: `/integrations`

### 1. List available integrations (catalog)

```
GET /integrations
```

**Response:** `IntegrationResponse[]`
```json
[
  {
    "id": "uuid",
    "slug": "connexys",
    "name": "Connexys",
    "vendor": "Bullhorn",
    "description": "ATS & recruitment platform op Salesforce",
    "icon": null,
    "is_active": true
  }
]
```

Use this to render the list of integration cards. Only show integrations where `is_active` is `true`.

---

### 2. List workspace connections

```
GET /integrations/connections
```

**Response:** `ConnectionResponse[]`
```json
[
  {
    "id": "uuid",
    "integration": { "id": "uuid", "slug": "connexys", "name": "Connexys", ... },
    "is_active": true,
    "has_credentials": true,
    "health_status": "healthy",
    "last_health_check_at": "2026-03-18T14:30:00Z",
    "settings": {},
    "created_at": "2026-03-18T12:00:00Z",
    "updated_at": "2026-03-18T14:30:00Z"
  }
]
```

Cross-reference with the catalog: if an integration has no connection, show it as "not configured". If it has a connection, show the status.

---

### 3. Save credentials

Provider-specific endpoints. Use `PUT` (idempotent — creates or overwrites).

**Connexys:**
```
PUT /integrations/connections/connexys
```
```json
{
  "instance_url": "https://company.my.salesforce.com",
  "consumer_key": "3MVG9...",
  "consumer_secret": "ABC123..."
}
```

**Microsoft:**
```
PUT /integrations/connections/microsoft
```
```json
{
  "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "client_secret": "secret-value"
}
```

**Response:** `ConnectionResponse` (the created/updated connection)

---

### 4. Run health check

```
POST /integrations/connections/{connection_id}/health-check
```

**Response:** `HealthCheckResponse`
```json
{
  "connection_id": "uuid",
  "provider": "connexys",
  "health_status": "healthy",
  "message": "Connected to Salesforce (company.my.salesforce.com)",
  "checked_at": "2026-03-18T14:30:00Z"
}
```

Health status values: `"healthy"`, `"unhealthy"`, `"unknown"`

---

### 5. Update connection (toggle on/off, update settings)

```
PATCH /integrations/connections/{connection_id}
```
```json
{
  "is_active": false,
  "settings": {}
}
```

Both fields are optional.

---

### 6. Delete connection

```
DELETE /integrations/connections/{connection_id}
```

Returns `204 No Content`. Removes the connection and all stored credentials.

---

## UI Design Suggestions

### Integrations Overview Page

```
┌─────────────────────────────────────────────────────────┐
│  Integrations                                           │
│                                                         │
│  ┌─────────────────────┐  ┌─────────────────────┐      │
│  │ 🔵 Connexys         │  │ 🔵 Microsoft        │      │
│  │ Bullhorn             │  │ Teams & Outlook      │      │
│  │                      │  │                      │      │
│  │ ● Connected          │  │ ○ Not configured     │      │
│  │ Last check: 2m ago   │  │                      │      │
│  │                      │  │                      │      │
│  │ [Configure] [Test]   │  │ [Configure]          │      │
│  └─────────────────────┘  └─────────────────────┘      │
└─────────────────────────────────────────────────────────┘
```

### Card states

| State | `has_credentials` | `health_status` | Display |
|-------|-------------------|-----------------|---------|
| Not configured | `false` | `unknown` | Grey dot, "Niet geconfigureerd", only Configure button |
| Configured, untested | `true` | `unknown` | Yellow dot, "Niet getest", Configure + Test buttons |
| Healthy | `true` | `healthy` | Green dot, "Verbonden", Configure + Test + toggle |
| Unhealthy | `true` | `unhealthy` | Red dot, "Verbinding mislukt", Configure + Test buttons |

### Configuration Modal/Drawer

When clicking "Configure" on an integration, show a form with the provider-specific fields:

**Connexys form fields:**
| Field | Label | Type | Required | Placeholder |
|-------|-------|------|----------|-------------|
| `instance_url` | Salesforce URL | text | yes | `https://company.my.salesforce.com` |
| `consumer_key` | Consumer Key | text | yes | |
| `consumer_secret` | Consumer Secret | password | yes | |

**Microsoft form fields:**
| Field | Label | Type | Required | Placeholder |
|-------|-------|------|----------|-------------|
| `tenant_id` | Tenant ID | text | yes | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `client_id` | Client ID | text | yes | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `client_secret` | Client Secret | password | yes | |

### Flow

1. User opens Integrations page → `GET /integrations` + `GET /integrations/connections`
2. User clicks Configure on Connexys → show form modal
3. User fills in credentials → `PUT /integrations/connections/connexys`
4. On success → automatically run `POST /integrations/connections/{id}/health-check`
5. Show health result (green = success, red = error with message)
6. User can toggle active/inactive → `PATCH /integrations/connections/{id}`
7. User can delete connection → confirm dialog → `DELETE /integrations/connections/{id}`

### Important Notes

- **Never display stored credentials** — the API only returns `has_credentials: true/false`, never the actual values
- **Health check can take a few seconds** — show a loading spinner on the Test button
- **All labels should be in Dutch (nl-BE)** per project conventions
- **Re-run health check after saving new credentials** to give immediate feedback
