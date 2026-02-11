"""
Pytest fixtures for Taloo Backend tests.

These fixtures provide reusable test setup for API integration tests.
"""
import uuid

import httpx
import pytest

BASE_URL = "http://localhost:8080"


@pytest.fixture
async def client():
    """Async HTTP client for API calls."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


@pytest.fixture
async def vacancy_id(client: httpx.AsyncClient) -> str:
    """Get or create a test vacancy with pre-screening."""
    # First check for a vacancy with pre-screening
    resp = await client.get("/vacancies?limit=10")
    if resp.status_code == 200:
        for v in resp.json().get("items", []):
            if v.get("has_screening"):
                return v["id"]

    # No vacancy with screening found - seed demo data
    resp = await client.post("/demo/seed")
    assert resp.status_code == 200, f"Failed to seed demo data: {resp.text}"
    return resp.json()["vacancies"][0]["id"]


@pytest.fixture
async def published_pre_screening(client: httpx.AsyncClient, vacancy_id: str) -> str:
    """Ensure vacancy has a published pre-screening."""
    resp = await client.get(f"/vacancies/{vacancy_id}/pre-screening")

    if resp.status_code == 404:
        # Create a basic pre-screening
        create_resp = await client.put(
            f"/vacancies/{vacancy_id}/pre-screening",
            json={
                "intro": "Hallo! Dit is een test pre-screening.",
                "knockout_questions": [
                    {"id": "ko_1", "question": "Ben je beschikbaar voor voltijds werk?"}
                ],
                "knockout_failed_action": "Helaas kom je niet in aanmerking.",
                "qualification_questions": [
                    {"id": "qual_1", "question": "Wat is je ervaring?", "ideal_answer": "Relevante ervaring"}
                ],
                "final_action": "Bedankt voor je tijd!"
            }
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"Failed to create pre-screening: {create_resp.text}")
        resp = await client.get(f"/vacancies/{vacancy_id}/pre-screening")

    ps = resp.json()
    if not ps.get("published_at"):
        # Publish the pre-screening
        pub_resp = await client.post(
            f"/vacancies/{vacancy_id}/pre-screening/publish",
            json={"enable_voice": True, "enable_whatsapp": False}
        )
        if pub_resp.status_code != 200:
            pytest.skip(f"Failed to publish pre-screening: {pub_resp.text}")
        ps = (await client.get(f"/vacancies/{vacancy_id}/pre-screening")).json()

    # Ensure it's online
    if not ps.get("is_online"):
        await client.patch(
            f"/vacancies/{vacancy_id}/pre-screening/status",
            json={"is_online": True}
        )

    return ps["id"]


@pytest.fixture
async def mock_conversation(
    client: httpx.AsyncClient,
    vacancy_id: str,
    published_pre_screening: str
) -> str:
    """
    Create a mock screening conversation with simulated ElevenLabs conversation_id.

    This uses the test_conversation_id parameter to skip the real ElevenLabs call
    while still creating the screening_conversations record in the database.
    """
    conversation_id = f"test_{uuid.uuid4().hex[:16]}"

    resp = await client.post(
        "/screening/outbound",
        json={
            "vacancy_id": vacancy_id,
            "channel": "voice",
            "phone_number": "+32412345678",
            "first_name": "Test",
            "last_name": "Kandidaat",
            "is_test": True,
            "test_conversation_id": conversation_id
        }
    )
    assert resp.status_code == 200, f"Failed to create mock conversation: {resp.text}"
    return conversation_id


@pytest.fixture
async def available_slots(client: httpx.AsyncClient) -> dict:
    """Get available time slots for scheduling."""
    resp = await client.post("/api/scheduling/get-time-slots", json={})
    assert resp.status_code == 200, f"Failed to get time slots: {resp.text}"
    return resp.json()
