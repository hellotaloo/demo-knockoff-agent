"""
Test suite for scheduling flow simulation.

Tests the complete scheduling workflow:
1. Get available time slots
2. Save/confirm a slot (creates scheduled_interview)
3. Reschedule to a different slot
4. Update interview notes

Run with: pytest tests/test_scheduling.py -v
"""
import pytest

import httpx


class TestSchedulingFlow:
    """Test the complete scheduling flow: get slots -> save slot -> reschedule."""

    @pytest.mark.asyncio
    async def test_get_time_slots(self, client: httpx.AsyncClient, mock_conversation: str):
        """Test getting available time slots."""
        resp = await client.post(
            "/api/scheduling/get-time-slots",
            json={"conversation_id": mock_conversation}
        )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}, body: {resp.text}"
        data = resp.json()

        # Verify response structure
        assert "slots" in data, "Response should contain 'slots'"
        assert "formatted_text" in data, "Response should contain 'formatted_text'"
        assert len(data["slots"]) > 0, "Should have at least one available slot"

        # Verify slot structure
        first_slot = data["slots"][0]
        assert "date" in first_slot, "Slot should have 'date'"
        assert "dutch_date" in first_slot, "Slot should have 'dutch_date'"
        assert "morning" in first_slot, "Slot should have 'morning' times"
        assert "afternoon" in first_slot, "Slot should have 'afternoon' times"

    @pytest.mark.asyncio
    async def test_save_slot(
        self,
        client: httpx.AsyncClient,
        mock_conversation: str,
        available_slots: dict
    ):
        """Test saving a selected time slot."""
        slots = available_slots["slots"]
        first_slot = slots[0]

        # Pick first available time
        selected_time = (
            first_slot["morning"][0]
            if first_slot["morning"]
            else first_slot["afternoon"][0]
        )

        resp = await client.post(
            "/api/scheduling/save-slot",
            json={
                "conversation_id": mock_conversation,
                "selected_date": first_slot["date"],
                "selected_time": selected_time,
                "selected_slot_text": f"{first_slot['dutch_date']} om {selected_time}",
            }
        )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}, body: {resp.text}"
        data = resp.json()

        assert data["success"] is True, "save-slot should succeed"
        assert data["scheduled_interview_id"] is not None, "Should return interview ID"
        assert data["vacancy_id"] is not None, "Should return vacancy ID"
        assert data["selected_date"] == first_slot["date"], "Should return selected date"
        assert data["selected_time"] == selected_time, "Should return selected time"

    @pytest.mark.asyncio
    async def test_reschedule(
        self,
        client: httpx.AsyncClient,
        mock_conversation: str,
        available_slots: dict
    ):
        """Test rescheduling to a different time slot."""
        slots = available_slots["slots"]
        first_slot = slots[0]

        # First, save an initial slot
        initial_time = (
            first_slot["morning"][0]
            if first_slot["morning"]
            else first_slot["afternoon"][0]
        )

        save_resp = await client.post(
            "/api/scheduling/save-slot",
            json={
                "conversation_id": mock_conversation,
                "selected_date": first_slot["date"],
                "selected_time": initial_time,
            }
        )
        assert save_resp.status_code == 200, f"Setup failed: {save_resp.text}"

        # Now reschedule to a different time
        # Try afternoon if we used morning, or next day, or different morning slot
        if first_slot["afternoon"]:
            new_time = first_slot["afternoon"][0]
            new_date = first_slot["date"]
        elif len(slots) > 1:
            second_slot = slots[1]
            new_date = second_slot["date"]
            new_time = (
                second_slot["morning"][0]
                if second_slot["morning"]
                else second_slot["afternoon"][0]
            )
        else:
            # Fallback: use a different morning slot if available
            new_time = (
                first_slot["morning"][-1]
                if len(first_slot["morning"]) > 1
                else initial_time
            )
            new_date = first_slot["date"]

        resp = await client.post(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/reschedule",
            json={
                "new_date": new_date,
                "new_time": new_time,
                "reason": "Test reschedule - kandidaat niet beschikbaar"
            }
        )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}, body: {resp.text}"
        data = resp.json()

        assert data["success"] is True, "Reschedule should succeed"
        assert data["previous_status"] == "rescheduled", "Previous interview should be marked as rescheduled"
        assert data["new_interview_id"] is not None, "Should create new interview"
        assert data["previous_interview_id"] is not None, "Should return previous interview ID"
        assert data["new_date"] == new_date, "Should return new date"
        assert data["new_time"] == new_time, "Should return new time"

    @pytest.mark.asyncio
    async def test_reschedule_not_found(self, client: httpx.AsyncClient):
        """Test reschedule with non-existent conversation_id returns 404."""
        resp = await client.post(
            "/api/scheduling/interviews/by-conversation/nonexistent_conv_id/reschedule",
            json={
                "new_date": "2026-03-01",
                "new_time": "14u",
            }
        )

        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        assert "No active scheduled interview found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_notes(
        self,
        client: httpx.AsyncClient,
        mock_conversation: str,
        available_slots: dict
    ):
        """Test updating interview notes."""
        slots = available_slots["slots"]
        first_slot = slots[0]

        # First, save a slot so we have an interview to update
        selected_time = (
            first_slot["morning"][0]
            if first_slot["morning"]
            else first_slot["afternoon"][0]
        )

        save_resp = await client.post(
            "/api/scheduling/save-slot",
            json={
                "conversation_id": mock_conversation,
                "selected_date": first_slot["date"],
                "selected_time": selected_time,
            }
        )
        assert save_resp.status_code == 200, f"Setup failed: {save_resp.text}"

        # Update notes
        resp = await client.patch(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/notes",
            json={
                "notes": "Test notities - kandidaat lijkt geschikt voor de functie.",
                "append": False
            }
        )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}, body: {resp.text}"
        data = resp.json()

        assert data["success"] is True, "Update notes should succeed"
        assert data["conversation_id"] == mock_conversation, "Should return conversation_id"
        assert data["scheduled_interview_id"] is not None, "Should return interview ID"

    @pytest.mark.asyncio
    async def test_update_notes_append(
        self,
        client: httpx.AsyncClient,
        mock_conversation: str,
        available_slots: dict
    ):
        """Test appending to interview notes."""
        slots = available_slots["slots"]
        first_slot = slots[0]

        # Save a slot first
        selected_time = (
            first_slot["morning"][0]
            if first_slot["morning"]
            else first_slot["afternoon"][0]
        )

        await client.post(
            "/api/scheduling/save-slot",
            json={
                "conversation_id": mock_conversation,
                "selected_date": first_slot["date"],
                "selected_time": selected_time,
            }
        )

        # Set initial notes
        await client.patch(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/notes",
            json={"notes": "Initial notes.", "append": False}
        )

        # Append additional notes
        resp = await client.patch(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/notes",
            json={"notes": "Additional notes after analysis.", "append": True}
        )

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}, body: {resp.text}"
        assert resp.json()["success"] is True


class TestGetTimeSlotsEdgeCases:
    """Test edge cases for get-time-slots endpoint."""

    @pytest.mark.asyncio
    async def test_get_slots_without_conversation_id(self, client: httpx.AsyncClient):
        """Test getting slots without providing conversation_id."""
        resp = await client.post("/api/scheduling/get-time-slots", json={})

        assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
        data = resp.json()
        assert len(data["slots"]) > 0, "Should return default slots"

    @pytest.mark.asyncio
    async def test_slots_have_correct_format(self, client: httpx.AsyncClient):
        """Test that slots have correct Dutch date format and time format."""
        resp = await client.post("/api/scheduling/get-time-slots", json={})
        data = resp.json()

        for slot in data["slots"]:
            # Date should be YYYY-MM-DD format
            assert len(slot["date"].split("-")) == 3, "Date should be YYYY-MM-DD format"

            # Times should end with 'u' (Dutch hour notation)
            for time in slot["morning"] + slot["afternoon"]:
                assert time.endswith("u"), f"Time '{time}' should end with 'u'"
