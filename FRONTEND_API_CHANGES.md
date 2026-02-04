# Frontend API Changes Documentation

## Overview
This document tracks API changes during the Taloo Backend refactoring. The goal is to maintain backward compatibility during Phase 1-6, with minor standardization changes in Phase 7.

---

## Phase 1: Configuration Extraction ✅ COMPLETE

**Status**: No API changes
**Breaking Changes**: None
**Impact**: Zero - purely internal refactoring

### Changes Made
- Created `src/` directory structure
- Extracted configuration to `src/config.py`:
  - Environment variables (DATABASE_URL, Twilio, ElevenLabs)
  - Logging configuration
  - Application constants (SIMPLE_EDIT_KEYWORDS, SIMULATED_REASONING)
- Updated `app.py` to import from centralized config

### Frontend Action Required
✅ None - all endpoints remain unchanged

---

## Phase 2: Extract Pydantic Models ✅ COMPLETE

**Status**: Complete
**Breaking Changes**: None
**Impact**: Zero - models define request/response structure but don't change it

### Changes Made
- Moved all Pydantic BaseModel classes to `src/models/`
- Organized by domain:
  - `enums.py` - VacancyStatus, VacancySource, InterviewChannel
  - `vacancy.py` - VacancyResponse, VacancyStatsResponse, DashboardStatsResponse, ChannelsResponse
  - `application.py` - ApplicationResponse, QuestionAnswerResponse, CVApplicationRequest
  - `pre_screening.py` - PreScreening request/response models
  - `interview.py` - Interview request models
  - `screening.py` - Screening request/response models
  - `outbound.py` - Outbound screening models
  - `webhook.py` - ElevenLabs webhook models
  - `cv.py` - CV analysis models
  - `data_query.py` - Data query models
- Created `src/models/__init__.py` for convenient imports
- Updated `app.py` to import all models from `src.models`

### Frontend Action Required
✅ None - all request/response formats remain identical

---

## Phase 3-6: Database, Service, Router Extraction (Planned)

**Status**: Not started
**Breaking Changes**: None
**Impact**: Zero - internal architecture refactoring only

### Planned Changes
- Extract SQL to repository classes
- Extract business logic to service classes
- Split endpoints into domain-specific routers
- Add dependency injection

### Frontend Action Required
✅ None - all endpoints keep same paths and contracts

---

## Phase 7: Standardization (Planned - Minor Changes Expected)

**Status**: Not started
**Breaking Changes**: Minor response format standardization
**Impact**: Low - standardizes inconsistent response patterns

### Potential Changes

#### 7.1: List Endpoint Response Format
**Current State** (inconsistent):
```json
// Some endpoints return:
{"vacancies": [...], "total": 100, "limit": 50, "offset": 0}

// Others return:
{"applications": [...], "total": 50, "limit": 50, "offset": 0}
```

**Proposed** (standardized):
```json
{
  "items": [...],      // Renamed from specific resource name
  "total": 100,
  "limit": 50,
  "offset": 0
}
```

**Frontend Migration Path**:
1. Backend can return BOTH formats temporarily (old + new fields)
2. Frontend updates to use `items` instead of resource-specific field
3. Backend removes old field after frontend is updated

#### 7.2: Error Response Format
**Current State**:
- HTTPException with detail field (FastAPI default)
- SSE streams with `{"type": "error", "message": "..."}`

**Proposed**:
- Standardize to `{"error": "message"}` for REST endpoints
- Keep SSE format unchanged

**Frontend Impact**: Minimal - FastAPI auto-serializes HTTPException consistently

#### 7.3: Success Response Format
**Current State** (inconsistent):
```json
// Some endpoints return:
{"status": "success", "message": "...", "data": {...}}

// Others return:
{...}  // Direct data object

// Others return:
{"status": "success"}  // Status only
```

**Proposed**:
- REST endpoints: Return data directly (no wrapper)
- Status-only endpoints: `{"status": "success"}`
- SSE streams: Keep existing format

**Frontend Impact**: Low - most endpoints already return data directly

---

## Breaking vs Non-Breaking Changes Summary

### ✅ Non-Breaking (Phases 1-6)
All refactoring through Phase 6 is **100% backward compatible**:
- Configuration extraction
- Model organization
- Database layer extraction
- Service layer extraction
- Router extraction
- Dependency injection

### ⚠️ Potentially Breaking (Phase 7)
Minor standardization changes that may require frontend updates:
- List response format: `vacancies` → `items`
- Consistent error format
- Standardized success responses

**Mitigation Strategy**:
- Dual-format support during transition
- Gradual migration with both old/new fields
- Clear migration timeline
- Version headers (optional)

---

## Migration Timeline

| Phase | Status | Breaking Changes | Frontend Action |
|-------|--------|------------------|-----------------|
| 1 | ✅ Complete | None | None |
| 2 | ✅ Complete | None | None |
| 3 | 🔜 Next | None | None |
| 4 | Planned | None | None |
| 5 | Planned | None | None |
| 6 | Planned | None | None |
| 7 | Planned | Minor | Coordinate with backend team |

---

## Testing Checklist

After each phase, verify these critical endpoints:

### Core Endpoints
- ✅ `GET /health` - Health check
- ✅ `GET /vacancies` - List vacancies
- `GET /vacancies/{id}` - Get vacancy detail
- `GET /vacancies/{id}/stats` - Get vacancy stats
- `GET /stats` - Dashboard stats

### Application Endpoints
- `POST /vacancies/{id}/cv-application` - Create CV application
- `GET /vacancies/{id}/applications` - List applications
- `GET /applications/{id}` - Get application detail

### Pre-Screening Endpoints
- `PUT /vacancies/{id}/pre-screening` - Save pre-screening
- `GET /vacancies/{id}/pre-screening` - Get pre-screening
- `POST /vacancies/{id}/pre-screening/publish` - Publish pre-screening

### Interview Endpoints
- `POST /interview/generate` - Generate interview (SSE stream)
- `POST /interview/feedback` - Provide feedback (SSE stream)
- `GET /interview/session/{id}` - Get interview session

### Screening Endpoints
- `POST /screening/chat` - Screening chat (SSE stream)
- `GET /vacancies/{id}/conversations` - List conversations
- `POST /screening/outbound` - Initiate outbound screening

### Webhook Endpoints
- `POST /webhook` - Twilio WhatsApp webhook
- `POST /webhook/elevenlabs` - ElevenLabs post-call webhook

---

## Contact

For questions about API changes:
- Check this document first
- Review the refactoring plan: `/Users/lunar/.claude/plans/spicy-soaring-pillow.md`
- Test endpoints after each phase deployment

---

## Version History

| Date | Phase | Changes |
|------|-------|---------|
| 2026-02-04 | Phase 1 | Configuration extraction - no API changes |
| 2026-02-04 | Phase 2 | Pydantic models extraction - no API changes |
