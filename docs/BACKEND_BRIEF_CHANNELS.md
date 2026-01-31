# Backend Brief: Add `channels` to Vacancy List Response

## Context

The pre-screening overview now displays channel icons (Voice / WhatsApp) for each vacancy. The frontend expects a `channels` object in the vacancy list response, but the backend doesn't return this field yet.

## Current Problem

The "Channels" column shows "-" for all vacancies because `channels` is undefined in the response.

## Required Change

Add `channels` object to the vacancy list response at `GET /vacancies`.

### Current Response

```json
{
  "id": "cd1d4ee9-343c-4fc4-b10e-c0bccac001eb",
  "title": "Senior Developer",
  "has_screening": true,
  "is_online": true,
  ...
}
```

### Required Response

```json
{
  "id": "cd1d4ee9-343c-4fc4-b10e-c0bccac001eb",
  "title": "Senior Developer",
  "has_screening": true,
  "is_online": true,
  "channels": {
    "voice": true,
    "whatsapp": true
  },
  ...
}
```

## Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `channels.voice` | boolean | `true` if `elevenlabs_agent_id` is set on the pre-screening |
| `channels.whatsapp` | boolean | `true` if `whatsapp_agent_id` is set on the pre-screening |

## Logic

```sql
SELECT 
  v.*,
  ps.is_online,
  CASE WHEN ps.elevenlabs_agent_id IS NOT NULL THEN true ELSE false END AS voice_enabled,
  CASE WHEN ps.whatsapp_agent_id IS NOT NULL THEN true ELSE false END AS whatsapp_enabled
FROM vacancies v
LEFT JOIN pre_screenings ps ON ps.vacancy_id = v.id
```

Then format as:
```json
"channels": {
  "voice": voice_enabled,
  "whatsapp": whatsapp_enabled
}
```

## Default Value

If no pre-screening exists for a vacancy, return:
```json
"channels": {
  "voice": false,
  "whatsapp": false
}
```

## Frontend Usage

The frontend displays:
- Phone icon when `channels.voice === true`
- WhatsApp icon when `channels.whatsapp === true`
- Dash "-" when both are `false`

## Priority

Medium - UI column is already visible, showing placeholder values.

## Reference

See `VACANCY_LIST_API.md` for the complete API schema.
