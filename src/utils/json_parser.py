"""Shared JSON parsing utility for extracting JSON from LLM responses."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_json_response(response_text: str, default: dict | None = None) -> dict:
    """Extract JSON from an LLM response, handling markdown code blocks.

    Tries to extract JSON from:
    1. Markdown code blocks (```json ... ``` or ``` ... ```)
    2. Raw JSON object ({ ... })

    Args:
        response_text: The raw LLM response text.
        default: Fallback dict to return on failure. Defaults to {}.

    Returns:
        Parsed dict, or `default` if extraction/parsing fails.
    """
    if default is None:
        default = {}

    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.error(f"Could not find JSON in response: {response_text[:500]}")
            return default

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}\nJSON string: {json_str[:500]}")
        return default
