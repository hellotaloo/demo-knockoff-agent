"""
Manual verification test for scheduling flow.

This test runs a single complete flow that you can verify in Google Calendar:
1. Create appointment (10u)
2. Update notes (simulates post-interview processing)
3. Reschedule to new time (14u)
4. Cancel the appointment

Run with: pytest tests/test_scheduling_manual.py -v -s

The -s flag shows print output so you can see the flow.
Check your Google Calendar to verify:
- After step 1: One event at 10:00
- After step 3: Old event at 10:00 should be gone, new event at 14:00
- After step 4: No events should remain

Set MANUAL_CONFIRM=1 to pause between steps for manual calendar verification.
"""
import os
import pytest
import httpx


def wait_for_confirmation(message: str):
    """Wait for user to press Enter to continue."""
    if os.environ.get("MANUAL_CONFIRM") == "1":
        input(f"\n>>> {message} Press Enter to continue...")
    else:
        print(f"\n>>> {message}")


class TestSchedulingManualVerification:
    """
    Single flow test for manual calendar verification.

    Run this test and check your Google Calendar to verify events are created,
    updated, and cancelled correctly.
    """

    @pytest.mark.asyncio
    async def test_complete_scheduling_lifecycle(
        self,
        client: httpx.AsyncClient,
        mock_conversation: str,
        available_slots: dict
    ):
        """
        Test the complete scheduling lifecycle:
        Create -> Update Notes -> Reschedule -> Cancel
        """
        print("\n" + "=" * 70)
        print("SCHEDULING LIFECYCLE TEST - Manual Calendar Verification")
        print("=" * 70)
        print(f"Conversation ID: {mock_conversation}")

        slots = available_slots["slots"]
        first_slot = slots[0]

        # =================================================================
        # STEP 1: Create appointment at 10u
        # =================================================================
        print("\n" + "-" * 70)
        print("STEP 1: Create appointment")
        print("-" * 70)

        initial_time = "10u"
        initial_date = first_slot["date"]

        print(f"  Date: {initial_date}")
        print(f"  Time: {initial_time}")
        print(f"  Slot text: {first_slot['dutch_date']} om {initial_time}")

        resp = await client.post(
            "/api/scheduling/save-slot",
            json={
                "conversation_id": mock_conversation,
                "selected_date": initial_date,
                "selected_time": initial_time,
                "selected_slot_text": f"{first_slot['dutch_date']} om {initial_time}",
                "candidate_name": "Test Kandidaat Lifecycle",
            }
        )

        assert resp.status_code == 200, f"Save slot failed: {resp.text}"
        save_data = resp.json()
        assert save_data["success"] is True
        interview_id = save_data["scheduled_interview_id"]
        print(f"  Result: ✅ Created")
        print(f"  Interview ID: {interview_id}")
        print(f"  >>> CHECK CALENDAR: Should see 'Interview - Test Kandidaat Lifecycle' at {initial_time}")

        wait_for_confirmation(f"Verify calendar has event at {initial_time}.")

        # =================================================================
        # STEP 2: Update notes (simulates post-interview processing)
        # =================================================================
        print("\n" + "-" * 70)
        print("STEP 2: Update notes (post-interview processing)")
        print("-" * 70)

        notes = """Kandidaat samenvatting:
- Beschikbaar voor voltijds werk
- 3 jaar ervaring in vergelijkbare functie
- Goede communicatievaardigheden
- Geschikt voor de rol"""

        resp = await client.patch(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/notes",
            json={"notes": notes, "append": False}
        )

        assert resp.status_code == 200, f"Update notes failed: {resp.text}"
        notes_data = resp.json()
        assert notes_data["success"] is True
        print(f"  Result: ✅ Notes updated")
        print(f"  >>> Calendar event unchanged")

        wait_for_confirmation("Notes updated. Calendar should be unchanged.")

        # =================================================================
        # STEP 3: Reschedule to 14u
        # =================================================================
        print("\n" + "-" * 70)
        print("STEP 3: Reschedule to new time")
        print("-" * 70)

        new_time = "14u"
        new_date = first_slot["date"]

        print(f"  Old time: {initial_date} {initial_time}")
        print(f"  New time: {new_date} {new_time}")

        resp = await client.post(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/reschedule",
            json={
                "new_date": new_date,
                "new_time": new_time,
                "new_slot_text": f"{first_slot['dutch_date']} om {new_time}",
                "reason": "Kandidaat heeft ochtend vergadering"
            }
        )

        assert resp.status_code == 200, f"Reschedule failed: {resp.text}"
        reschedule_data = resp.json()
        assert reschedule_data["success"] is True
        assert reschedule_data["previous_status"] == "rescheduled"
        new_interview_id = reschedule_data["new_interview_id"]
        print(f"  Result: ✅ Rescheduled")
        print(f"  Old interview: {reschedule_data['previous_interview_id']} -> rescheduled")
        print(f"  New interview: {new_interview_id}")
        print(f"  >>> CHECK CALENDAR: Old event at {initial_time} should be GONE")
        print(f"  >>> CHECK CALENDAR: New event at {new_time} should be visible")

        wait_for_confirmation(f"Verify: old event at {initial_time} GONE, new event at {new_time} visible.")

        # =================================================================
        # STEP 4: Cancel the appointment
        # =================================================================
        print("\n" + "-" * 70)
        print("STEP 4: Cancel appointment")
        print("-" * 70)

        resp = await client.post(
            f"/api/scheduling/interviews/by-conversation/{mock_conversation}/cancel",
            json={"reason": "Kandidaat heeft andere job gevonden"}
        )

        assert resp.status_code == 200, f"Cancel failed: {resp.text}"
        cancel_data = resp.json()
        assert cancel_data["success"] is True
        print(f"  Result: ✅ Cancelled")
        print(f"  Interview: {cancel_data['interview_id']} -> cancelled")
        print(f"  Calendar event cancelled: {cancel_data['calendar_event_cancelled']}")
        print(f"  >>> CHECK CALENDAR: Event at {new_time} should be GONE")

        wait_for_confirmation(f"Verify: event at {new_time} is GONE. Calendar should be empty.")

        # =================================================================
        # SUMMARY
        # =================================================================
        print("\n" + "=" * 70)
        print("TEST COMPLETE - Please verify in Google Calendar:")
        print("=" * 70)
        print(f"  Date checked: {first_slot['dutch_date']} ({first_slot['date']})")
        print(f"  Expected: NO events for 'Test Kandidaat Lifecycle'")
        print("=" * 70 + "\n")
