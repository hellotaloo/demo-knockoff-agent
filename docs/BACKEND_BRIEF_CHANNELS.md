# Backend Brief: Add `channels` to Vacancy List Response

## Context

The pre-screening overview now displays channel icons (Voice / WhatsApp / CV) for each vacancy. The frontend expects a `channels` object in the vacancy list response.

## Required Response

```json
{
  "id": "cd1d4ee9-343c-4fc4-b10e-c0bccac001eb",
  "title": "Senior Developer",
  "has_screening": true,
  "is_online": true,
  "channels": {
    "voice": true,
    "whatsapp": true,
    "cv": true
  },
  ...
}
```

## Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `channels.voice` | boolean | `true` if `elevenlabs_agent_id` is set on the pre-screening |
| `channels.whatsapp` | boolean | `true` if `whatsapp_agent_id` is set on the pre-screening |
| `channels.cv` | boolean | `true` if a pre-screening exists (CV analysis uses the questions) |

## Logic

```sql
SELECT 
  v.*,
  ps.is_online,
  (ps.elevenlabs_agent_id IS NOT NULL) AS voice_enabled,
  (ps.whatsapp_agent_id IS NOT NULL) AS whatsapp_enabled,
  (ps.id IS NOT NULL) AS cv_enabled
FROM vacancies v
LEFT JOIN pre_screenings ps ON ps.vacancy_id = v.id
```

Then format as:
```json
"channels": {
  "voice": voice_enabled,
  "whatsapp": whatsapp_enabled,
  "cv": cv_enabled
}
```

## Default Value

If no pre-screening exists for a vacancy, return:
```json
"channels": {
  "voice": false,
  "whatsapp": false,
  "cv": false
}
```

## Frontend Usage

The frontend displays:
- Phone icon when `channels.voice === true`
- WhatsApp icon when `channels.whatsapp === true`
- CV/Document icon when `channels.cv === true`
- Dash "-" when all are `false`

## CV Channel Details

The CV channel is enabled whenever a pre-screening exists because:
- CV analysis uses the knockout and qualification questions from the pre-screening
- No additional configuration is required (unlike Voice/WhatsApp which need agent IDs)
- The `/cv/analyze` endpoint accepts a PDF and the questions, returning analysis results

See `CV_ANALYZER_API.md` for the complete CV analysis API documentation.

## Reference

See `VACANCY_LIST_API.md` for the complete API schema.
