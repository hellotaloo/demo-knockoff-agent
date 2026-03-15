"""
Shared LLM helper with automatic Gemini → OpenAI fallback.

All direct LLM calls should go through `generate()` instead of calling
google.genai.Client directly. On transient Gemini errors (503, 429),
it falls back to OpenAI automatically.

Usage:
    from src.utils.llm import generate

    # Simple text prompt
    text = await generate("What is 2+2?")

    # With system instruction and config
    text = await generate(
        prompt="Analyze this text...",
        system_instruction="You are an expert analyst.",
        temperature=0.1,
        max_output_tokens=2048,
    )

    # Multi-part content (Gemini-style Content objects)
    from google.genai import types
    text = await generate(
        contents=[
            types.Content(role="user", parts=[types.Part(text="instruction")]),
            types.Content(role="user", parts=[types.Part(text="data")]),
        ],
        temperature=0.1,
    )
"""
import logging
import os
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Gemini model defaults
DEFAULT_MODEL = "gemini-2.5-flash"

# OpenAI fallback model
FALLBACK_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4.1-mini")

# Gemini error codes that trigger fallback
_FALLBACK_ERROR_CODES = {429, 503}
_FALLBACK_ERROR_STRINGS = {"UNAVAILABLE", "RESOURCE_EXHAUSTED", "rate limit", "high demand", "overloaded"}


def _should_fallback(error: Exception) -> bool:
    """Check if a Gemini error should trigger OpenAI fallback."""
    error_str = str(error)
    # Check for known error codes/strings
    for s in _FALLBACK_ERROR_STRINGS:
        if s.lower() in error_str.lower():
            return True
    # Check for HTTP status codes in the error
    for code in _FALLBACK_ERROR_CODES:
        if str(code) in error_str:
            return True
    return False


async def _call_gemini(
    contents,
    model: str,
    system_instruction: Optional[str],
    temperature: Optional[float],
    max_output_tokens: Optional[int],
    thinking_budget: Optional[int],
) -> str:
    """Call Gemini API and return text response."""
    from google import genai
    from google.genai import types

    client = genai.Client()

    config_kwargs = {}
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    if system_instruction is not None:
        config_kwargs["system_instruction"] = system_instruction
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            include_thoughts=True,
            thinking_budget=thinking_budget,
        )

    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    response = await client.aio.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    # Extract text, skipping thinking parts
    text = ""
    if response and response.candidates:
        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if getattr(part, "thought", False):
                continue
            if hasattr(part, "text") and part.text:
                text += part.text

        # Warn if response was truncated by max_output_tokens
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason and str(finish_reason) == "MAX_TOKENS":
            logger.warning(f"[LLM] Response truncated (MAX_TOKENS): {text[-80:]!r}...")

    return text


async def _call_openai(
    contents,
    prompt: Optional[str],
    system_instruction: Optional[str],
    temperature: Optional[float],
    max_output_tokens: Optional[int],
    model: str,
) -> str:
    """Call OpenAI API as fallback. Converts Gemini-style inputs to OpenAI format."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI()

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    # Convert contents to OpenAI messages
    if prompt and isinstance(prompt, str):
        messages.append({"role": "user", "content": prompt})
    elif contents:
        if isinstance(contents, str):
            messages.append({"role": "user", "content": contents})
        elif isinstance(contents, list):
            # Gemini Content objects → OpenAI messages
            for content in contents:
                if hasattr(content, "role") and hasattr(content, "parts"):
                    text_parts = []
                    for part in content.parts:
                        if hasattr(part, "text") and part.text:
                            text_parts.append(part.text)
                    if text_parts:
                        role = "user" if content.role == "user" else "assistant"
                        messages.append({"role": role, "content": "\n".join(text_parts)})
                elif isinstance(content, str):
                    messages.append({"role": "user", "content": content})
        else:
            # Single Content object
            if hasattr(contents, "parts"):
                text_parts = [p.text for p in contents.parts if hasattr(p, "text") and p.text]
                if text_parts:
                    messages.append({"role": "user", "content": "\n".join(text_parts)})

    kwargs = {"model": model, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        kwargs["max_tokens"] = max_output_tokens

    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def generate(
    prompt: Optional[str] = None,
    *,
    contents=None,
    model: str = DEFAULT_MODEL,
    system_instruction: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
    fallback_model: Optional[str] = None,
) -> str:
    """
    Generate text using Gemini with automatic OpenAI fallback.

    Args:
        prompt: Simple text prompt (alternative to contents)
        contents: Gemini-style Content objects or string
        model: Gemini model name (default: gemini-2.5-flash)
        system_instruction: System instruction for the model
        temperature: Generation temperature
        max_output_tokens: Max tokens in response
        thinking_budget: Gemini thinking budget (ignored for OpenAI fallback)
        fallback_model: Override the default OpenAI fallback model

    Returns:
        Generated text response
    """
    # Prepare contents
    if prompt and not contents:
        contents = prompt

    # Try Gemini first
    try:
        return await _call_gemini(
            contents=contents,
            model=model,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
        )
    except Exception as e:
        if not _should_fallback(e):
            raise

        fb_model = fallback_model or FALLBACK_MODEL
        logger.warning(f"⚠️ LLM FALLBACK ACTIVE — Gemini {model} unavailable ({e}), using OpenAI {fb_model}")

        return await _call_openai(
            contents=contents,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            model=fb_model,
        )
