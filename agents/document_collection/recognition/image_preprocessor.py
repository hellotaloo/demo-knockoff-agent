"""
Image Preprocessing for Document Recognition

Automatically detects, crops, and straightens identity documents from photos.
Uses OpenCV for edge detection and perspective transformation.
"""

import cv2
import numpy as np
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# Standard ID card aspect ratios (ISO 7810 ID-1: 85.6mm x 54mm = 1.586:1)
ID_CARD_ASPECT_RATIO = 85.6 / 54.0  # ≈ 1.586
DRIVER_LICENSE_ASPECT_RATIO = 85.6 / 54.0  # Same as ID card

# Output dimensions (maintain aspect ratio)
OUTPUT_WIDTH = 856  # pixels (10x actual size in mm)
OUTPUT_HEIGHT = 540  # pixels


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Order corner points in consistent order: top-left, top-right, bottom-right, bottom-left.

    Args:
        pts: Array of 4 corner points

    Returns:
        Ordered array of points
    """
    rect = np.zeros((4, 2), dtype=np.float32)

    # Top-left point has smallest sum, bottom-right has largest sum
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    # Top-right has smallest difference, bottom-left has largest difference
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect


def detect_document_contour(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Detect document edges using contour detection.

    Args:
        image: Input image (BGR format)

    Returns:
        Array of 4 corner points, or None if not found
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Apply adaptive thresholding for better edge detection
    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )

    # Find edges using Canny
    edges = cv2.Canny(thresh, 50, 150)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Sort contours by area (largest first)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    # Look for rectangular contour (4 corners)
    for contour in contours[:10]:  # Check top 10 largest contours
        # Approximate the contour to a polygon
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)

        # If we found a 4-sided polygon
        if len(approx) == 4:
            # Check if area is significant (at least 20% of image)
            image_area = image.shape[0] * image.shape[1]
            contour_area = cv2.contourArea(approx)

            if contour_area > 0.2 * image_area:
                return approx.reshape(4, 2)

    return None


def apply_perspective_transform(
    image: np.ndarray,
    corners: np.ndarray,
    width: int = OUTPUT_WIDTH,
    height: int = OUTPUT_HEIGHT,
    skip_ordering: bool = False
) -> np.ndarray:
    """
    Apply perspective transformation to straighten document.

    Args:
        image: Input image
        corners: Array of 4 corner points (expected order: top-left, top-right, bottom-right, bottom-left)
        width: Output width
        height: Output height
        skip_ordering: If True, trust the input corner order and skip reordering

    Returns:
        Transformed image
    """
    # Order the corners (unless they're already correctly ordered from AI)
    if skip_ordering:
        rect = corners
        logger.debug("Skipping corner reordering (AI-provided corners)")
    else:
        rect = order_points(corners)
        logger.debug("Reordering corners using mathematical approach")

    # Destination points (perfect rectangle)
    dst = np.array([
        [0, 0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0, height - 1]
    ], dtype=np.float32)

    # Calculate perspective transformation matrix
    matrix = cv2.getPerspectiveTransform(rect, dst)

    # Apply transformation
    warped = cv2.warpPerspective(image, matrix, (width, height))

    return warped


async def preprocess_document_image_ai(
    image_bytes: bytes,
    aspect_ratio: float = ID_CARD_ASPECT_RATIO,
    output_width: int = OUTPUT_WIDTH
) -> Tuple[bytes, bool]:
    """
    Preprocess document image using AI-powered detection.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG)
        aspect_ratio: Expected aspect ratio of document
        output_width: Desired output width in pixels

    Returns:
        Tuple of (processed_image_bytes, preprocessing_applied)
    """
    try:
        from document_recognition_agent.document_detector import detect_document_bounds

        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            logger.warning("Failed to decode image")
            return image_bytes, False

        original_height, original_width = image.shape[:2]
        logger.info(f"Original image size: {original_width}x{original_height}")

        # Use AI to detect document bounds
        bounds = await detect_document_bounds(image_bytes)

        if bounds and bounds.confidence > 0.7:
            logger.info(f"AI detection successful (confidence: {bounds.confidence:.2%})")

            # Convert normalized coordinates to pixel coordinates
            # AI returns correctly ordered corners: top-left, top-right, bottom-right, bottom-left
            corners = np.array([
                [bounds.top_left[0] * original_width, bounds.top_left[1] * original_height],
                [bounds.top_right[0] * original_width, bounds.top_right[1] * original_height],
                [bounds.bottom_right[0] * original_width, bounds.bottom_right[1] * original_height],
                [bounds.bottom_left[0] * original_width, bounds.bottom_left[1] * original_height]
            ], dtype=np.float32)

            logger.info(f"Corner coordinates (pixels):")
            logger.info(f"  Top-Left: ({corners[0][0]:.1f}, {corners[0][1]:.1f})")
            logger.info(f"  Top-Right: ({corners[1][0]:.1f}, {corners[1][1]:.1f})")
            logger.info(f"  Bottom-Right: ({corners[2][0]:.1f}, {corners[2][1]:.1f})")
            logger.info(f"  Bottom-Left: ({corners[3][0]:.1f}, {corners[3][1]:.1f})")

            # Calculate actual detected document dimensions
            # Width: average of top and bottom widths
            top_width = np.sqrt((corners[1][0] - corners[0][0])**2 + (corners[1][1] - corners[0][1])**2)
            bottom_width = np.sqrt((corners[2][0] - corners[3][0])**2 + (corners[2][1] - corners[3][1])**2)
            detected_width = (top_width + bottom_width) / 2

            # Height: average of left and right heights
            left_height = np.sqrt((corners[3][0] - corners[0][0])**2 + (corners[3][1] - corners[0][1])**2)
            right_height = np.sqrt((corners[2][0] - corners[1][0])**2 + (corners[2][1] - corners[1][1])**2)
            detected_height = (left_height + right_height) / 2

            # Calculate detected aspect ratio
            detected_aspect_ratio = detected_width / detected_height
            logger.info(f"Detected document dimensions: {detected_width:.1f}x{detected_height:.1f} (aspect ratio: {detected_aspect_ratio:.3f})")

            # Use detected aspect ratio for output dimensions
            output_height = int(output_width / detected_aspect_ratio)
            logger.info(f"Output dimensions: {output_width}x{output_height} (maintaining detected aspect ratio)")

            # Apply perspective transformation (skip reordering since AI corners are already correct)
            processed = apply_perspective_transform(image, corners, output_width, output_height, skip_ordering=True)

            # Encode back to JPEG
            _, buffer = cv2.imencode('.jpg', processed, [cv2.IMWRITE_JPEG_QUALITY, 95])
            processed_bytes = buffer.tobytes()

            logger.info(f"✅ AI-powered crop successful: {output_width}x{output_height}")
            return processed_bytes, True

        else:
            logger.info("⚠️ AI detection failed or low confidence, using basic processing")
            return _basic_preprocessing(image, output_width, aspect_ratio)

    except Exception as e:
        logger.error(f"Error in AI preprocessing: {e}", exc_info=True)
        return image_bytes, False


def _basic_preprocessing(image: np.ndarray, output_width: int, aspect_ratio: float) -> Tuple[bytes, bool]:
    """Fallback: basic resize and rotation."""
    try:
        original_height, original_width = image.shape[:2]

        # Auto-rotate if needed
        if original_height > original_width and aspect_ratio > 1.0:
            logger.info("Rotating portrait image to landscape")
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

        # Resize while maintaining aspect ratio
        height_ratio = image.shape[0] / image.shape[1]
        new_height = int(output_width * height_ratio)
        resized = cv2.resize(image, (output_width, new_height), interpolation=cv2.INTER_LANCZOS4)

        # Encode
        _, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 95])
        processed_bytes = buffer.tobytes()

        logger.info(f"Applied basic preprocessing: {output_width}x{new_height}")
        return processed_bytes, False

    except Exception as e:
        logger.error(f"Error in basic preprocessing: {e}", exc_info=True)
        # Return encoded original
        _, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return buffer.tobytes(), False


def preprocess_document_image(
    image_bytes: bytes,
    aspect_ratio: float = ID_CARD_ASPECT_RATIO,
    output_width: int = OUTPUT_WIDTH
) -> Tuple[bytes, bool]:
    """
    DEPRECATED: Use preprocess_document_image_ai instead.

    This synchronous version uses OpenCV edge detection which is less reliable.
    Kept for backward compatibility.
    """
    try:
        # Decode image from bytes
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            logger.warning("Failed to decode image")
            return image_bytes, False

        original_height, original_width = image.shape[:2]
        logger.info(f"Original image size: {original_width}x{original_height}")

        # Try OpenCV edge detection (less reliable)
        corners = detect_document_contour(image)

        if corners is not None:
            logger.info("Document contour detected, applying perspective transform")
            output_height = int(output_width / aspect_ratio)
            processed = apply_perspective_transform(image, corners, output_width, output_height)
            _, buffer = cv2.imencode('.jpg', processed, [cv2.IMWRITE_JPEG_QUALITY, 95])
            return buffer.tobytes(), True
        else:
            logger.info("⚠️ Document contour not detected, using basic processing")
            return _basic_preprocessing(image, output_width, aspect_ratio)

    except Exception as e:
        logger.error(f"Error preprocessing image: {e}", exc_info=True)
        return image_bytes, False


def preprocess_base64_image(
    image_base64: str,
    aspect_ratio: float = ID_CARD_ASPECT_RATIO,
    output_width: int = OUTPUT_WIDTH
) -> Tuple[str, bool]:
    """
    Convenience wrapper for base64-encoded images.

    Args:
        image_base64: Base64-encoded image string
        aspect_ratio: Expected aspect ratio of document
        output_width: Desired output width in pixels

    Returns:
        Tuple of (processed_image_base64, preprocessing_applied)
    """
    import base64

    try:
        # Decode from base64
        image_bytes = base64.b64decode(image_base64)

        # Process
        processed_bytes, applied = preprocess_document_image(
            image_bytes, aspect_ratio, output_width
        )

        # Encode back to base64
        processed_base64 = base64.b64encode(processed_bytes).decode()

        return processed_base64, applied

    except Exception as e:
        logger.error(f"Error preprocessing base64 image: {e}")
        return image_base64, False
