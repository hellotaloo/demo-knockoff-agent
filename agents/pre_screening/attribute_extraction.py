"""
LLM-based candidate attribute extraction from conversation transcripts.

Takes any text (full transcript, single Q&A, etc.) and extracts candidate
attribute values using Gemini, guided by the attribute type descriptions.
"""
import json
import logging
import uuid
from typing import Optional

from src.utils.json_parser import parse_json_response

import asyncpg

from src.repositories.candidate_attribute_repo import CandidateAttributeRepository
from src.repositories.candidate_attribute_type_repo import CandidateAttributeTypeRepository

logger = logging.getLogger(__name__)


EXTRACTION_INSTRUCTION = """Je bent een expert in het extraheren van kandidaatgegevens uit gesprekken en teksten.

Je taak is om specifieke kenmerken van een kandidaat te identificeren en te extraheren uit de aangeleverde tekst.

## REGELS
1. Extraheer attributen waarvoor je bewijs of sterke aanwijzingen vindt in de tekst
2. De tekst is typisch een transcript van een sollicitatiegesprek — gebruik de CONTEXT van vragen en antwoorden om informatie af te leiden
3. Als de agent een vraag stelt die overeenkomt met een attribuut beschrijving, en de kandidaat antwoordt, gebruik dat antwoord
4. Voor "select" types: kies de best passende optie uit de aangeboden opties (gebruik de "value", niet het "label")
5. Voor "multi_select" types: geef een komma-gescheiden lijst van values uit de aangeboden opties
6. Voor "boolean" types: gebruik "true" of "false" — "ja" = "true", "nee" = "false"
7. Voor "date" types: gebruik YYYY-MM-DD formaat
8. Voor "number" types: gebruik alleen cijfers (geen eenheden, geen tekst)
9. Gebruik de beschrijving van elk attribuut als leidraad voor wat je moet zoeken
10. Als een attribuut totaal NIET in de tekst aan bod komt, neem het NIET op

## OUTPUT FORMAAT
Antwoord ALLEEN met een JSON object:

```json
{
  "extracted": [
    {
      "slug": "attribute_slug",
      "value": "de geextraheerde waarde"
    }
  ]
}
```

Als je GEEN attributen kunt extraheren, antwoord met:
```json
{
  "extracted": []
}
```
"""


def _build_prompt(attribute_types: list[asyncpg.Record], text: str) -> str:
    """Build the user prompt with attribute catalog and input text."""
    type_lines = []
    for t in attribute_types:
        line = f"- slug: {t['slug']}\n  naam: {t['name']}\n  type: {t['data_type']}"
        if t["description"]:
            line += f"\n  beschrijving: {t['description']}"
        if t["options"]:
            opts = t["options"] if isinstance(t["options"], list) else json.loads(t["options"])
            option_strs = [f"{o['value']} ({o['label']})" for o in opts]
            line += f"\n  opties: {', '.join(option_strs)}"
        type_lines.append(line)

    types_section = "\n".join(type_lines)

    return f"""Extraheer kandidaatkenmerken uit de volgende tekst.

## BESCHIKBARE ATTRIBUTEN
{types_section}

## TEKST
{text}

Geef je extractie als JSON."""


def _validate_value(value: str, data_type: str, options: Optional[list]) -> bool:
    """Validate an extracted value against its attribute type constraints."""
    if not value:
        return False

    if data_type == "boolean":
        return value.lower() in ("true", "false")

    if data_type == "number":
        try:
            float(value)
            return True
        except ValueError:
            return False

    if data_type == "date":
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))

    if data_type == "select" and options:
        opts = options if isinstance(options, list) else json.loads(options)
        valid_values = {o["value"] for o in opts}
        return value in valid_values

    if data_type == "multi_select" and options:
        opts = options if isinstance(options, list) else json.loads(options)
        valid_values = {o["value"] for o in opts}
        selected = [v.strip() for v in value.split(",")]
        return all(v in valid_values for v in selected)

    # text — anything goes
    return True


async def extract_and_save_attributes(
    text: str,
    candidate_id: uuid.UUID,
    workspace_id: uuid.UUID,
    pool: asyncpg.Pool,
    source: str = "pre_screening",
    source_session_id: Optional[str] = None,
    collected_by: Optional[str] = None,
    category: Optional[str] = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Extract candidate attributes from text using Gemini and optionally save them.

    Args:
        text: Input text (transcript, Q&A, any conversation text)
        candidate_id: Target candidate
        workspace_id: Workspace for attribute type lookup
        pool: Database connection pool
        source: Attribution source (e.g. "pre_screening", "cv_analysis")
        source_session_id: Optional session/conversation ID
        collected_by: Filter attribute types by collected_by field
        category: Filter attribute types by category
        dry_run: If True, extract but don't save to DB

    Returns:
        List of extracted attributes: [{"slug": ..., "value": ..., "attribute_type_id": ...}]
    """
    # 1. Fetch attribute types
    type_repo = CandidateAttributeTypeRepository(pool)
    attr_types = await type_repo.list_for_workspace(
        workspace_id, category=category, collected_by=collected_by
    )

    if not attr_types:
        logger.warning(f"No attribute types found for workspace {workspace_id} (collected_by={collected_by}, category={category})")
        return []

    # Build slug -> record map for validation
    type_by_slug = {t["slug"]: t for t in attr_types}

    logger.info(f"Extracting attributes from {len(text)} chars text, {len(attr_types)} attribute types available")

    # 2. Build prompt and call Gemini
    prompt = _build_prompt(attr_types, text)

    from src.utils.llm import generate

    response_text = await generate(
        prompt=f"{EXTRACTION_INSTRUCTION}\n\n{prompt}",
        temperature=0.1,
        max_output_tokens=2048,
    )

    if not response_text:
        logger.error("Empty response from Gemini for attribute extraction")
        return []

    # 3. Parse response
    parsed = parse_json_response(response_text)
    if not parsed:
        logger.error(f"Failed to parse extraction response: {response_text[:500]}")
        return []

    extracted_raw = parsed.get("extracted", [])
    logger.info(f"LLM extracted {len(extracted_raw)} raw attributes")

    # 4. Validate and save
    results = []
    attr_repo = CandidateAttributeRepository(pool)

    for item in extracted_raw:
        slug = item.get("slug", "")
        value = str(item.get("value", "")).strip()

        attr_type = type_by_slug.get(slug)
        if not attr_type:
            logger.warning(f"Unknown attribute slug from LLM: {slug}")
            continue

        if not _validate_value(value, attr_type["data_type"], attr_type["options"]):
            logger.warning(f"Invalid value for {slug} (type={attr_type['data_type']}): {value}")
            continue

        # Normalize boolean values
        if attr_type["data_type"] == "boolean":
            value = value.lower()

        if not dry_run:
            await attr_repo.upsert(
                candidate_id=candidate_id,
                attribute_type_id=attr_type["id"],
                value=value,
                source=source,
                source_session_id=source_session_id,
                verified=False,
            )

        results.append({
            "slug": slug,
            "value": value,
            "attribute_type_id": str(attr_type["id"]),
            "data_type": attr_type["data_type"],
            "name": attr_type["name"],
        })

    logger.info(f"Attribute extraction complete: {len(results)} valid attributes {'(dry run)' if dry_run else 'saved'}")

    # Log activity for each extracted attribute
    if results and not dry_run:
        from src.services.activity_service import ActivityService
        from src.models.activity import ActivityEventType, ActorType

        activity_service = ActivityService(pool)
        for attr in results:
            await activity_service.log(
                candidate_id=str(candidate_id),
                event_type=ActivityEventType.ATTRIBUTE_EXTRACTED,
                actor_type=ActorType.AGENT,
                metadata={
                    "slug": attr["slug"],
                    "value": attr["value"],
                    "data_type": attr["data_type"],
                    "source": source,
                },
                summary=f"Kenmerk '{attr['name']}' toegewezen: {attr['value']}"
            )

    return results
