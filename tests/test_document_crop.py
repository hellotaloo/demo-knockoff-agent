#!/usr/bin/env python3
"""
Test script for document cropping and AI detection.

Usage:
    python test_document_crop.py path/to/image.jpg
"""
import sys
import asyncio
from pathlib import Path
import os

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from document_recognition_agent.image_preprocessor import preprocess_document_image_ai


async def test_crop(image_path: str):
    """Test document cropping on a single image."""
    print("=" * 80)
    print("🧪 DOCUMENT CROP TEST")
    print("=" * 80)
    print(f"Input image: {image_path}")
    print("")

    # Read image
    with open(image_path, 'rb') as f:
        image_bytes = f.read()

    print(f"Image size: {len(image_bytes)} bytes")
    print("")

    # Process with AI detection
    print("Running AI detection and cropping...")
    print("-" * 80)

    processed_bytes, preprocessing_applied = await preprocess_document_image_ai(image_bytes)

    print("")
    print("-" * 80)

    if preprocessing_applied:
        print("✅ AI detection and cropping successful!")
    else:
        print("⚠️  AI detection failed, used basic preprocessing")

    # Save output
    input_path = Path(image_path)
    output_path = input_path.parent / f"{input_path.stem}_cropped{input_path.suffix}"

    with open(output_path, 'wb') as f:
        f.write(processed_bytes)

    print("")
    print(f"💾 Saved cropped image to: {output_path}")
    print("=" * 80)
    print("")
    print("👉 Compare the original and cropped images to verify the result")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_document_crop.py path/to/image.jpg")
        sys.exit(1)

    image_path = sys.argv[1]

    if not Path(image_path).exists():
        print(f"Error: File not found: {image_path}")
        sys.exit(1)

    asyncio.run(test_crop(image_path))


if __name__ == "__main__":
    main()
