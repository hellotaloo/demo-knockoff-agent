"""
Text utility functions for agent response processing.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


def clean_response_text(message: str) -> str:
    """
    Remove any accidental tool call text from agent responses.

    Sometimes the model includes the function call syntax in its response text.
    This strips that out before sending to the user.

    Args:
        message: The agent's response message

    Returns:
        str: Cleaned message without tool call syntax
    """
    # Remove conversation_complete(...) calls from the text
    cleaned = re.sub(
        r'conversation_complete\s*\([^)]*\)\s*',
        '',
        message,
        flags=re.IGNORECASE
    )
    # Clean up any resulting double newlines or leading/trailing whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def extract_json_from_response(response_text: str) -> dict:
    """
    Extract and parse JSON from an LLM response that may contain markdown code blocks.

    Tries markdown code blocks first, then falls back to raw JSON object detection.

    Returns:
        Parsed JSON dict, or empty dict on error.
    """
    # Try markdown code blocks first
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.error(f"Could not find JSON in response: {response_text[:500]}")
            return {}

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}\nJSON string: {json_str[:500]}")
        return {}
