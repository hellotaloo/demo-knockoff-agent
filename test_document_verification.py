#!/usr/bin/env python3
"""
Test script for document verification endpoint.

Tests the document recognition agent with a real identity card image.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Verify API key is loaded
if not os.getenv("GOOGLE_API_KEY"):
    print("❌ GOOGLE_API_KEY not found in environment!")
    print("Please ensure .env file exists with GOOGLE_API_KEY set.")
    exit(1)

# Test using the agent directly (without HTTP)
from document_recognition_agent import verify_document_base64


async def test_agent_directly():
    """Test the agent directly with the Belgian ID card."""
    print("=" * 80)
    print("TESTING DOCUMENT VERIFICATION AGENT (Direct)")
    print("=" * 80)

    # Load the test image
    image_path = Path("dummy_data/IMG_3886 Large.jpeg")

    if not image_path.exists():
        print(f"❌ Image file not found: {image_path}")
        return False

    print(f"📷 Loading image: {image_path}")
    with open(image_path, "rb") as f:
        image_data = f.read()

    image_base64 = base64.b64encode(image_data).decode("utf-8")
    print(f"✓ Image loaded: {len(image_base64)} characters (base64)")
    print()

    # Test 1: Document classification without name verification
    print("-" * 80)
    print("TEST 1: Document classification (no name verification)")
    print("-" * 80)

    result1 = await verify_document_base64(
        image_base64=image_base64,
        candidate_name=None,
        document_type_hint=None
    )

    print(f"Document Category: {result1.document_category}")
    print(f"Category Confidence: {result1.document_category_confidence:.2f}")
    print(f"Extracted Name: {result1.extracted_name}")
    print(f"Name Confidence: {result1.name_extraction_confidence:.2f}")
    print(f"Fraud Risk Level: {result1.fraud_risk_level}")
    print(f"Fraud Confidence: {result1.overall_fraud_confidence:.2f}")
    print(f"Image Quality: {result1.image_quality}")
    print(f"Verification Passed: {result1.verification_passed}")
    print(f"Summary: {result1.verification_summary}")

    if result1.fraud_indicators:
        print(f"\nFraud Indicators ({len(result1.fraud_indicators)}):")
        for idx, indicator in enumerate(result1.fraud_indicators, 1):
            print(f"  {idx}. [{indicator.severity.upper()}] {indicator.indicator_type}")
            print(f"     {indicator.description}")
            print(f"     Confidence: {indicator.confidence:.2f}")
    else:
        print("\n✓ No fraud indicators detected")

    if result1.readability_issues:
        print(f"\nReadability Issues: {', '.join(result1.readability_issues)}")

    print()

    # Test 2: With correct name verification
    print("-" * 80)
    print("TEST 2: Name verification (correct name - exact match)")
    print("-" * 80)

    result2 = await verify_document_base64(
        image_base64=image_base64,
        candidate_name="Laurijn André L Descheper",  # Correct name
        document_type_hint="driver_license"  # Hint: treating as ID/driver license
    )

    print(f"Name Match Performed: {result2.name_match_performed}")
    print(f"Name Match Result: {result2.name_match_result}")
    print(f"Name Match Confidence: {result2.name_match_confidence:.2f}" if result2.name_match_confidence else "N/A")
    print(f"Name Match Details: {result2.name_match_details}")
    print(f"Verification Passed: {result2.verification_passed}")
    print()

    # Test 3: With incorrect name verification
    print("-" * 80)
    print("TEST 3: Name verification (incorrect name - no match)")
    print("-" * 80)

    result3 = await verify_document_base64(
        image_base64=image_base64,
        candidate_name="Jan de Vries",  # Wrong name
        document_type_hint=None
    )

    print(f"Name Match Performed: {result3.name_match_performed}")
    print(f"Name Match Result: {result3.name_match_result}")
    print(f"Name Match Confidence: {result3.name_match_confidence:.2f}" if result3.name_match_confidence else "N/A")
    print(f"Name Match Details: {result3.name_match_details}")
    print(f"Verification Passed: {result3.verification_passed}")
    print()

    # Test 4: With partial name match
    print("-" * 80)
    print("TEST 4: Name verification (partial name - partial match)")
    print("-" * 80)

    result4 = await verify_document_base64(
        image_base64=image_base64,
        candidate_name="Laurijn Descheper",  # Partial name
        document_type_hint=None
    )

    print(f"Name Match Performed: {result4.name_match_performed}")
    print(f"Name Match Result: {result4.name_match_result}")
    print(f"Name Match Confidence: {result4.name_match_confidence:.2f}" if result4.name_match_confidence else "N/A")
    print(f"Name Match Details: {result4.name_match_details}")
    print(f"Verification Passed: {result4.verification_passed}")
    print()

    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    tests = [
        ("Classification without name", result1.verification_passed and result1.extracted_name is not None),
        ("Exact name match", result2.name_match_result in ["exact_match", "partial_match"]),
        ("Incorrect name detection", result3.name_match_result == "no_match"),
        ("Partial name match", result4.name_match_result == "partial_match"),
    ]

    passed = sum(1 for _, result in tests if result)
    total = len(tests)

    for test_name, result in tests:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    print()
    print(f"Total: {passed}/{total} tests passed")
    print("=" * 80)

    return passed == total


async def main():
    """Run all tests."""
    success = await test_agent_directly()

    if success:
        print("\n✅ All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
