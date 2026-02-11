#!/usr/bin/env python3
"""
Simple test to verify document collection endpoints are registered and working.
"""

import httpx
import json


BASE_URL = "http://localhost:8080"


def test_endpoints_registered():
    """Test that document collection endpoints are registered"""

    print("=" * 80)
    print("DOCUMENT COLLECTION ENDPOINT REGISTRATION TEST")
    print("=" * 80)

    # Test 1: Health check
    print("\n[1/4] Testing health endpoint...")
    resp = httpx.get(f"{BASE_URL}/health", timeout=5)
    if resp.status_code == 200:
        print(f"✅ Health check passed: {resp.json()}")
    else:
        print(f"❌ Health check failed: {resp.status_code}")
        return

    # Test 2: Check OpenAPI docs for our endpoint
    print("\n[2/4] Checking if /documents/collect is in OpenAPI schema...")
    resp = httpx.get(f"{BASE_URL}/openapi.json", timeout=5)
    if resp.status_code == 200:
        openapi = resp.json()
        if "/documents/collect" in openapi.get("paths", {}):
            print("✅ /documents/collect endpoint is registered")
            endpoint_info = openapi["paths"]["/documents/collect"]
            print(f"   Methods: {list(endpoint_info.keys())}")
        else:
            print("❌ /documents/collect endpoint NOT found in OpenAPI schema")
            print("   Available document-related endpoints:")
            for path in openapi.get("paths", {}).keys():
                if "document" in path.lower():
                    print(f"   - {path}")
    else:
        print(f"❌ Failed to fetch OpenAPI schema: {resp.status_code}")

    # Test 3: Check webhook endpoint
    print("\n[3/4] Checking if /webhook/documents is in OpenAPI schema...")
    if resp.status_code == 200:
        if "/webhook/documents" in openapi.get("paths", {}):
            print("✅ /webhook/documents endpoint is registered")
        else:
            print("❌ /webhook/documents endpoint NOT found in OpenAPI schema")
            print("   Available webhook endpoints:")
            for path in openapi.get("paths", {}).keys():
                if "webhook" in path.lower():
                    print(f"   - {path}")

    # Test 4: Test document verify endpoint (from first POC)
    print("\n[4/4] Testing /documents/verify endpoint...")
    resp = httpx.post(
        f"{BASE_URL}/documents/verify",
        json={
            "image_base64": "fake_base64",
            "candidate_name": "Test",
            "save_verification": False
        },
        timeout=10
    )
    # We expect this to fail gracefully (400/422) due to invalid base64
    if resp.status_code in [400, 422]:
        print(f"✅ /documents/verify endpoint exists and validates input")
        print(f"   Status: {resp.status_code} (expected validation error)")
    elif resp.status_code == 200:
        print(f"✅ /documents/verify endpoint works")
    else:
        print(f"⚠️  /documents/verify returned unexpected status: {resp.status_code}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("✅ Server is running")
    print("Check above for endpoint registration status")


if __name__ == "__main__":
    try:
        test_endpoints_registered()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
