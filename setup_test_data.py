#!/usr/bin/env python3
"""
Quick setup script to create test data for document collection testing.
"""

import asyncio
import httpx
import base64
from pathlib import Path


BASE_URL = "http://localhost:8080"


async def setup_test_data():
    """Create test vacancy and application for document collection testing"""

    print("=" * 80)
    print("DOCUMENT COLLECTION TEST DATA SETUP")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if vacancies exist
        print("\n[1/3] Checking for existing vacancies...")
        resp = await client.get(f"{BASE_URL}/vacancies?limit=1")

        if resp.status_code != 200:
            print(f"❌ Failed to fetch vacancies: {resp.status_code}")
            return

        data = resp.json()
        items = data.get("items", [])

        if items:
            vacancy_id = items[0]["id"]
            print(f"✅ Using existing vacancy: {vacancy_id}")
        else:
            print("⚠️  No vacancies found.")
            print("   Please create a vacancy first via the API or web interface.")
            print("\n   Example curl command:")
            print('   curl -X POST "http://localhost:8080/vacancies" \\')
            print('     -H "Content-Type: application/json" \\')
            print('     -d \'{"title": "Test Vacancy", "company": "Test Co", ...}\'')
            return

        # Check for applications
        print(f"\n[2/3] Checking for applications...")
        resp = await client.get(f"{BASE_URL}/vacancies/{vacancy_id}/applications")

        if resp.status_code != 200:
            print(f"❌ Failed to fetch applications: {resp.status_code}")
            return

        applications = resp.json()

        if applications:
            application_id = applications[0]["id"]
            candidate_name = applications[0].get("candidate_name", "Unknown")
            candidate_phone = applications[0].get("candidate_phone", "No phone")
            print(f"✅ Using existing application: {application_id}")
            print(f"   Candidate: {candidate_name}")
            print(f"   Phone: {candidate_phone}")
        else:
            print("⚠️  No applications found for this vacancy.")
            print("   You can create one via CV application endpoint.")

            # Try to create one if we have a test image
            test_image = Path("dummy_data/IMG_3886 Large.jpeg")
            if test_image.exists():
                print(f"\n   Found test image: {test_image}")
                print("   Creating test application...")

                with open(test_image, "rb") as f:
                    cv_base64 = base64.b64encode(f.read()).decode()

                resp = await client.post(
                    f"{BASE_URL}/vacancies/{vacancy_id}/cv-application",
                    json={
                        "cv_base64": cv_base64,
                        "candidate_name": "Test Kandidaat",
                        "candidate_email": "test@taloo.be",
                        "candidate_phone": "+32412345678"
                    }
                )

                if resp.status_code == 200:
                    application_id = resp.json()["id"]
                    print(f"✅ Created test application: {application_id}")
                else:
                    print(f"❌ Failed to create application: {resp.status_code}")
                    print(resp.text)
                    return
            else:
                print(f"   No test image found at {test_image}")
                return

        # Test document collection endpoint
        print(f"\n[3/3] Testing document collection endpoint...")
        resp = await client.post(
            f"{BASE_URL}/documents/collect",
            json={"application_id": application_id}
        )

        if resp.status_code == 200:
            result = resp.json()
            print("✅ Document collection initiated successfully!")
            print(f"   Conversation ID: {result['conversation_id']}")
            print(f"\n   Opening message:")
            print(f"   {result['opening_message'][:200]}...")
        else:
            print(f"❌ Failed to initiate document collection: {resp.status_code}")
            print(resp.text)
            return

        # Print Postman setup info
        print("\n" + "=" * 80)
        print("POSTMAN SETUP")
        print("=" * 80)
        print("\n✅ You can now test in Postman with these values:")
        print(f"\n   Base URL: {BASE_URL}")
        print(f"   Vacancy ID: {vacancy_id}")
        print(f"   Application ID: {application_id}")
        print("\n📋 Quick test request:")
        print(f"""
POST {BASE_URL}/documents/collect
Content-Type: application/json

{{
  "application_id": "{application_id}"
}}
        """)

        print("\n📖 See POSTMAN_DOCUMENT_COLLECTION_SETUP.md for full guide")


if __name__ == "__main__":
    try:
        asyncio.run(setup_test_data())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
