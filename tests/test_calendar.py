"""Quick test script to verify Google Calendar integration."""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test_calendar():
    # Check env vars
    service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    impersonate_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    print("=" * 50)
    print("Google Calendar Integration Test")
    print("=" * 50)
    print(f"Service Account File: {service_account_file}")
    print(f"Impersonate Email: {impersonate_email}")
    print()

    if not service_account_file:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_FILE not set in .env")
        return

    if not impersonate_email:
        print("ERROR: GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set in .env")
        return

    if not os.path.exists(service_account_file):
        print(f"ERROR: Service account file not found: {service_account_file}")
        return

    print("Environment variables OK!")
    print()

    # Test calendar service
    print("Testing Google Calendar API...")
    try:
        from src.services.google_calendar_service import calendar_service

        slots = await calendar_service.get_available_slots(
            calendar_email=impersonate_email,
            days_ahead=3,
            start_offset_days=1,  # Start from tomorrow for testing
        )

        print(f"SUCCESS! Found {len(slots)} days with available slots:")
        print()
        for slot in slots:
            print(f"  {slot['dutch_date']} ({slot['date']})")
            print(f"    Morning: {slot['morning']}")
            print(f"    Afternoon: {slot['afternoon']}")
            print()

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        print()
        print("Common issues:")
        print("- Domain-wide delegation not configured in Workspace Admin")
        print("- Wrong OAuth scope (need: https://www.googleapis.com/auth/calendar)")
        print("- Service account file path incorrect")
        print("- Email address not in the Workspace domain")

if __name__ == "__main__":
    asyncio.run(test_calendar())
