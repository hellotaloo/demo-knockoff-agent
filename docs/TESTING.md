# Testing Guide

This document describes all tests in the Taloo Backend and how to run them.

## Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Start the local server (required for all tests)
uvicorn app:app --reload --port 8080
```

## Quick Reference

| Test File | Description | Command |
|-----------|-------------|---------|
| `tests/test_scheduling.py` | Scheduling API tests | `pytest tests/test_scheduling.py -v` |
| `tests/test_scheduling_manual.py` | Manual calendar verification | `MANUAL_CONFIRM=1 pytest tests/test_scheduling_manual.py -v -s` |

---

## Test Suites

### 1. Scheduling Tests (`tests/test_scheduling.py`)

Automated tests for the scheduling API endpoints.

**Run:**
```bash
pytest tests/test_scheduling.py -v
```

**Tests included:**

| Test | Description |
|------|-------------|
| `test_get_time_slots` | Get available interview time slots |
| `test_save_slot` | Save/confirm a selected time slot |
| `test_reschedule` | Reschedule an interview to a new time |
| `test_reschedule_not_found` | Verify 404 for invalid conversation_id |
| `test_update_notes` | Update interview notes |
| `test_update_notes_append` | Append to existing notes |
| `test_get_slots_without_conversation_id` | Get slots without context |
| `test_slots_have_correct_format` | Validate Dutch date/time format |

**Fixtures used:**
- `client` - Async HTTP client
- `vacancy_id` - Test vacancy with pre-screening
- `published_pre_screening` - Ensures pre-screening is published
- `mock_conversation` - Simulated ElevenLabs conversation_id
- `available_slots` - Pre-fetched time slots

---

### 2. Manual Calendar Verification (`tests/test_scheduling_manual.py`)

Single flow test for manually verifying Google Calendar integration.

**Run with manual pauses:**
```bash
MANUAL_CONFIRM=1 pytest tests/test_scheduling_manual.py -v -s
```

**Run without pauses:**
```bash
pytest tests/test_scheduling_manual.py -v -s
```

**Test flow:**

1. **Create** - Creates appointment at 10u
   - ✅ Verify: Calendar shows event at 10:00

2. **Update Notes** - Adds interview summary
   - ✅ Verify: Calendar unchanged

3. **Reschedule** - Moves appointment to 14u
   - ✅ Verify: Old event at 10:00 is GONE
   - ✅ Verify: New event at 14:00 is visible

4. **Cancel** - Cancels the appointment
   - ✅ Verify: Event at 14:00 is GONE
   - ✅ Verify: Calendar is empty

**Expected result:** After test completes, no calendar events should remain for "Test Kandidaat Lifecycle".

---

## Test Configuration

### pytest Configuration (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `MANUAL_CONFIRM` | Set to `1` to pause between steps in manual tests | No |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `GOOGLE_CALENDAR_IMPERSONATE_EMAIL` | Recruiter calendar email | For calendar tests |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to service account JSON | For calendar tests |

---

## Fixtures (`tests/conftest.py`)

Shared fixtures for all test files.

### `client`
Async HTTP client configured for `localhost:8080`.

### `vacancy_id`
Returns a vacancy ID with pre-screening configured. Seeds demo data if needed.

### `published_pre_screening`
Ensures the vacancy has a published and online pre-screening. Creates one if missing.

### `mock_conversation`
Creates a mock screening conversation using the `/screening/outbound` endpoint with `test_conversation_id`. This simulates an ElevenLabs voice call without making a real call.

### `available_slots`
Pre-fetches available time slots from `/api/scheduling/get-time-slots`.

---

## Running All Tests

```bash
# Run all scheduling tests
pytest tests/test_scheduling.py tests/test_scheduling_manual.py -v

# Run with coverage (if pytest-cov installed)
pytest tests/ -v --cov=src

# Run specific test
pytest tests/test_scheduling.py::TestSchedulingFlow::test_reschedule -v
```

---

## Troubleshooting

### "No pre-screening configured"
The test fixtures will automatically create and publish a pre-screening. If this fails:
```bash
# Seed demo data manually
curl -X POST http://localhost:8080/demo/seed
```

### "relation scheduled_interviews does not exist"
Run the database migration:
```bash
python -c "
import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()
async def migrate():
    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    with open('migrations/010_add_scheduled_interviews.sql') as f:
        await conn.execute(f.read())
    with open('migrations/011_add_calendar_event_id.sql') as f:
        await conn.execute(f.read())
    print('Migrations applied!')
    await conn.close()
asyncio.run(migrate())
"
```

### Calendar events not being created/cancelled
Check that these environment variables are set:
- `GOOGLE_SERVICE_ACCOUNT_FILE` - Path to service account JSON
- `GOOGLE_CALENDAR_IMPERSONATE_EMAIL` - Recruiter's email address

---

## Adding New Tests

1. Create test file in `tests/` directory
2. Use existing fixtures from `conftest.py`
3. Use `@pytest.mark.asyncio` for async tests
4. Follow naming convention: `test_<feature>.py`

Example:
```python
import pytest
import httpx

class TestMyFeature:
    @pytest.mark.asyncio
    async def test_something(self, client: httpx.AsyncClient):
        resp = await client.get("/my-endpoint")
        assert resp.status_code == 200
```
