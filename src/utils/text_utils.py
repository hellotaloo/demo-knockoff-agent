"""
Text utility functions for agent response processing.
"""
import re


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
