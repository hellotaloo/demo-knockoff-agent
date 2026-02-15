"""
Test script for the calendar refactoring.

Tests:
1. Import verification - all modules import correctly
2. Voice agent helpers - TTS formatting (Dutch words)
3. WhatsApp agent helpers - compact formatting
4. Google Calendar service - actual API calls (if credentials available)

Run with: python test_calendar_refactor.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


def test_imports():
    """Test that all imports work correctly."""
    print("\n" + "=" * 60)
    print("TEST 1: Import Verification")
    print("=" * 60)

    errors = []

    # Test voice agent imports
    try:
        from pre_screening_voice_agent.calendar_helpers import (
            get_time_slots_for_voice,
            schedule_interview,
            _time_to_words,
            _convert_times_to_words,
        )
        print("✓ pre_screening_voice_agent.calendar_helpers imports OK")
    except ImportError as e:
        errors.append(f"✗ pre_screening_voice_agent.calendar_helpers: {e}")
        print(errors[-1])

    # Test voice agent __init__
    try:
        from pre_screening_voice_agent import get_time_slots_for_voice, schedule_interview
        print("✓ pre_screening_voice_agent __init__ exports OK")
    except ImportError as e:
        errors.append(f"✗ pre_screening_voice_agent __init__: {e}")
        print(errors[-1])

    # Test WhatsApp agent imports
    try:
        from pre_screening_whatsapp_agent.calendar_helpers import (
            get_time_slots_for_whatsapp,
            get_slots_for_specific_day,
            TimeSlot,
            SlotData,
        )
        print("✓ pre_screening_whatsapp_agent.calendar_helpers imports OK")
    except ImportError as e:
        errors.append(f"✗ pre_screening_whatsapp_agent.calendar_helpers: {e}")
        print(errors[-1])

    # Test scheduling service imports
    try:
        from src.services.scheduling_service import (
            SchedulingService,
            scheduling_service,
            ScheduleResult,
        )
        print("✓ src.services.scheduling_service imports OK")
    except ImportError as e:
        errors.append(f"✗ src.services.scheduling_service: {e}")
        print(errors[-1])

    # Test google calendar service imports
    try:
        from src.services.google_calendar_service import (
            GoogleCalendarService,
            calendar_service,
            TIMEZONE,
        )
        print("✓ src.services.google_calendar_service imports OK")
    except ImportError as e:
        errors.append(f"✗ src.services.google_calendar_service: {e}")
        print(errors[-1])

    # Test services __init__ exports
    try:
        from src.services import (
            SchedulingService,
            scheduling_service,
            GoogleCalendarService,
            calendar_service,
        )
        print("✓ src.services __init__ exports OK")
    except ImportError as e:
        errors.append(f"✗ src.services __init__: {e}")
        print(errors[-1])

    # Test router imports (these use lazy imports, so just check files exist)
    try:
        from src.routers import scheduling, vapi
        print("✓ src.routers.scheduling and vapi imports OK")
    except ImportError as e:
        errors.append(f"✗ src.routers: {e}")
        print(errors[-1])

    if errors:
        print(f"\n❌ Import test FAILED with {len(errors)} error(s)")
        return False
    else:
        print("\n✅ All imports successful")
        return True


def test_voice_formatting():
    """Test voice TTS formatting (Dutch words)."""
    print("\n" + "=" * 60)
    print("TEST 2: Voice Agent Formatting (TTS)")
    print("=" * 60)

    from pre_screening_voice_agent.calendar_helpers import _time_to_words, _convert_times_to_words

    errors = []

    # Test individual time conversion
    test_cases = [
        ("8 uur", "acht uur"),
        ("9 uur", "negen uur"),
        ("10 uur", "tien uur"),
        ("11 uur", "elf uur"),
        ("12 uur", "twaalf uur"),
        ("14 uur", "veertien uur"),
        ("17 uur", "zeventien uur"),
    ]

    print("\nTesting _time_to_words():")
    for input_time, expected in test_cases:
        result = _time_to_words(input_time)
        if result == expected:
            print(f"  ✓ '{input_time}' -> '{result}'")
        else:
            errors.append(f"  ✗ '{input_time}' -> '{result}' (expected '{expected}')")
            print(errors[-1])

    # Test batch conversion
    print("\nTesting _convert_times_to_words():")
    input_list = ["9 uur", "10 uur", "14 uur"]
    expected_list = ["negen uur", "tien uur", "veertien uur"]
    result_list = _convert_times_to_words(input_list)

    if result_list == expected_list:
        print(f"  ✓ {input_list} -> {result_list}")
    else:
        errors.append(f"  ✗ {input_list} -> {result_list} (expected {expected_list})")
        print(errors[-1])

    if errors:
        print(f"\n❌ Voice formatting test FAILED with {len(errors)} error(s)")
        return False
    else:
        print("\n✅ Voice formatting tests passed")
        return True


def test_whatsapp_models():
    """Test WhatsApp agent models."""
    print("\n" + "=" * 60)
    print("TEST 3: WhatsApp Agent Models")
    print("=" * 60)

    from pre_screening_whatsapp_agent.calendar_helpers import TimeSlot, SlotData

    errors = []

    # Test TimeSlot model (has morning/afternoon, not times)
    print("\nTesting TimeSlot model:")
    try:
        slot = TimeSlot(
            date="2025-01-20",
            dutch_date="Ma 20/01",
            morning=["9u", "10u"],
            afternoon=["14u", "16u"],
        )
        print(f"  ✓ TimeSlot created: date={slot.date}, dutch_date={slot.dutch_date}")
        print(f"    morning={slot.morning}, afternoon={slot.afternoon}")
    except Exception as e:
        errors.append(f"  ✗ TimeSlot creation failed: {e}")
        print(errors[-1])

    # Test SlotData model (has formatted_text, not has_availability)
    print("\nTesting SlotData model:")
    try:
        slot_data = SlotData(
            slots=[slot],
            formatted_text="📅 **Ma 20/01:** 9u, 10u, 14u, 16u",
        )
        print(f"  ✓ SlotData created")
        print(f"    formatted_text='{slot_data.formatted_text}'")
        print(f"    slots count={len(slot_data.slots)}")
    except Exception as e:
        errors.append(f"  ✗ SlotData creation failed: {e}")
        print(errors[-1])

    if errors:
        print(f"\n❌ WhatsApp models test FAILED with {len(errors)} error(s)")
        return False
    else:
        print("\n✅ WhatsApp models tests passed")
        return True


async def test_calendar_service():
    """Test actual Google Calendar API calls (requires credentials)."""
    print("\n" + "=" * 60)
    print("TEST 4: Google Calendar Service (Live API)")
    print("=" * 60)

    # Check for credentials
    service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    impersonate_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    if not service_account_file:
        print("\n⚠ GOOGLE_SERVICE_ACCOUNT_FILE not set - skipping live API tests")
        return None

    if not impersonate_email:
        print("\n⚠ GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set - skipping live API tests")
        return None

    print(f"\nUsing calendar: {impersonate_email}")
    print(f"Service account: {service_account_file}")

    from src.services.google_calendar_service import calendar_service

    errors = []

    # Test get_quick_slots
    print("\nTesting calendar_service.get_quick_slots():")
    try:
        slots = await calendar_service.get_quick_slots(
            calendar_email=impersonate_email,
            num_days=2,
            start_offset_days=1,
            max_times_per_day=3,
        )
        print(f"  ✓ Got {len(slots)} day(s) of availability")
        for slot in slots[:2]:  # Show first 2
            print(f"    - {slot.get('dutch_date', slot.get('date'))}: {slot.get('times', [])}")
    except Exception as e:
        errors.append(f"  ✗ get_quick_slots failed: {e}")
        print(errors[-1])

    # Test get_slots_for_date
    print("\nTesting calendar_service.get_slots_for_date():")
    try:
        tomorrow = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        slot = await calendar_service.get_slots_for_date(
            calendar_email=impersonate_email,
            target_date=tomorrow,
        )
        if slot:
            print(f"  ✓ Got slots for {tomorrow}")
            print(f"    Morning: {slot.get('morning', [])}")
            print(f"    Afternoon: {slot.get('afternoon', [])}")
        else:
            print(f"  ✓ No availability for {tomorrow} (this is valid)")
    except Exception as e:
        errors.append(f"  ✗ get_slots_for_date failed: {e}")
        print(errors[-1])

    if errors:
        print(f"\n❌ Calendar service test FAILED with {len(errors)} error(s)")
        return False
    else:
        print("\n✅ Calendar service tests passed")
        return True


async def test_voice_agent_helpers():
    """Test voice agent helper functions (live API)."""
    print("\n" + "=" * 60)
    print("TEST 5: Voice Agent Helpers (Live API)")
    print("=" * 60)

    impersonate_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    if not impersonate_email:
        print("\n⚠ GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set - skipping")
        return None

    from pre_screening_voice_agent.calendar_helpers import get_time_slots_for_voice

    errors = []

    # Test get_time_slots_for_voice (default 3 days)
    print("\nTesting get_time_slots_for_voice() - default:")
    try:
        result = await get_time_slots_for_voice()
        print(f"  ✓ has_availability: {result.get('has_availability')}")
        print(f"    formatted: '{result.get('formatted')}'")
        print(f"    slots count: {len(result.get('slots', []))}")

        # Verify times are in Dutch words
        for slot in result.get("slots", [])[:1]:
            times = slot.get("times", [])
            if times and any("uur" in t for t in times):
                # Check if it's words not numbers
                sample = times[0]
                if any(word in sample for word in ["tien", "elf", "negen", "acht"]):
                    print(f"    ✓ Times in Dutch words: {times}")
                else:
                    print(f"    ⚠ Times may not be in Dutch words: {times}")
    except Exception as e:
        errors.append(f"  ✗ get_time_slots_for_voice failed: {e}")
        print(errors[-1])

    # Test with specific date
    print("\nTesting get_time_slots_for_voice() - specific date:")
    try:
        target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        result = await get_time_slots_for_voice(specific_date=target_date)
        print(f"  ✓ Requested date: {target_date}")
        print(f"    has_availability: {result.get('has_availability')}")
        print(f"    formatted: '{result.get('formatted')}'")
    except Exception as e:
        errors.append(f"  ✗ get_time_slots_for_voice (specific date) failed: {e}")
        print(errors[-1])

    if errors:
        print(f"\n❌ Voice agent helpers test FAILED with {len(errors)} error(s)")
        return False
    else:
        print("\n✅ Voice agent helpers tests passed")
        return True


async def test_whatsapp_agent_helpers():
    """Test WhatsApp agent helper functions (live API)."""
    print("\n" + "=" * 60)
    print("TEST 6: WhatsApp Agent Helpers (Live API)")
    print("=" * 60)

    impersonate_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    if not impersonate_email:
        print("\n⚠ GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set - skipping")
        return None

    from pre_screening_whatsapp_agent.calendar_helpers import (
        get_time_slots_for_whatsapp,
        get_slots_for_specific_day,
    )

    errors = []

    # Test get_time_slots_for_whatsapp
    print("\nTesting get_time_slots_for_whatsapp():")
    try:
        result = await get_time_slots_for_whatsapp()
        has_slots = len(result.slots) > 0
        print(f"  ✓ has slots: {has_slots}")
        print(f"    formatted_text: '{result.formatted_text}'")
        print(f"    slots count: {len(result.slots)}")

        # Verify times are in compact format (e.g., "10u")
        for slot in result.slots[:1]:
            all_times = slot.morning + slot.afternoon
            if all_times:
                sample = all_times[0]
                if sample.endswith("u") and " " not in sample:
                    print(f"    ✓ Times in compact format: morning={slot.morning}, afternoon={slot.afternoon}")
                else:
                    print(f"    ⚠ Times may not be compact: {all_times}")
    except Exception as e:
        errors.append(f"  ✗ get_time_slots_for_whatsapp failed: {e}")
        print(errors[-1])

    # Test get_slots_for_specific_day (takes day name, not date)
    print("\nTesting get_slots_for_specific_day():")
    try:
        # Get next Wednesday
        result = await get_slots_for_specific_day("woensdag")
        has_slots = len(result.slots) > 0
        print(f"  ✓ Requested day: woensdag")
        print(f"    has slots: {has_slots}")
        print(f"    formatted_text: '{result.formatted_text}'")
    except Exception as e:
        errors.append(f"  ✗ get_slots_for_specific_day failed: {e}")
        print(errors[-1])

    if errors:
        print(f"\n❌ WhatsApp agent helpers test FAILED with {len(errors)} error(s)")
        return False
    else:
        print("\n✅ WhatsApp agent helpers tests passed")
        return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CALENDAR REFACTORING TEST SUITE")
    print("=" * 60)

    results = []

    # Test 1: Imports
    results.append(("Imports", test_imports()))

    # Test 2: Voice formatting
    results.append(("Voice Formatting", test_voice_formatting()))

    # Test 3: WhatsApp models
    results.append(("WhatsApp Models", test_whatsapp_models()))

    # Test 4-6: Live API tests (may be skipped)
    results.append(("Calendar Service", await test_calendar_service()))
    results.append(("Voice Helpers", await test_voice_agent_helpers()))
    results.append(("WhatsApp Helpers", await test_whatsapp_agent_helpers()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        if result is True:
            print(f"  ✅ {name}: PASSED")
            passed += 1
        elif result is False:
            print(f"  ❌ {name}: FAILED")
            failed += 1
        else:
            print(f"  ⚠ {name}: SKIPPED")
            skipped += 1

    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")

    if failed > 0:
        print("\n❌ Some tests FAILED")
        sys.exit(1)
    else:
        print("\n✅ All tests PASSED")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
