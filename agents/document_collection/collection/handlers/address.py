"""
Handler for address_collection step (HARDCODED).

Sub-state machine:
  ask_domicile → ask_same → (ask_verblijf →) done

Uses Google Maps geocoding for structured address extraction.
Address field specs are loaded from TypeCache.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from agents.document_collection.collection.rules import ADDRESS_GEOCODE_SLUGS, geocode_address

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent

logger = logging.getLogger(__name__)

_YES = re.compile(r"(?i)(ja|yes|yep|klopt|juist|inderdaad|correct|dat klopt|zeker|👍)")
_NO = re.compile(r"(?i)(nee|neen|no|niet|anders|verschillend|ander adres)")


def _get_address_fields(agent: DocumentCollectionAgent, slug: str) -> list[dict]:
    """Get address fields from TypeCache, with sensible defaults."""
    if agent.type_cache:
        attr_type = agent.type_cache.get_attr_type(slug)
        if attr_type and attr_type.get("fields"):
            return attr_type["fields"]
    return [
        {"key": "street", "type": "text", "label": "Straat", "required": True},
        {"key": "number", "type": "text", "label": "Nummer", "required": True},
        {"key": "stad", "type": "text", "label": "Stad", "required": True},
        {"key": "postcode", "type": "text", "label": "Postcode", "required": True},
        {"key": "country", "type": "text", "label": "Land", "required": False},
    ]


async def enter_address(agent: DocumentCollectionAgent, step: dict) -> str:
    """Start address collection — ask for domicile address."""
    agent.state.address_phase = "ask_domicile"
    return await agent._say(
        f"""Vraag {agent.state.candidate_name} naar het **domicilieadres** (officieel adres).
Voorbeeld: "Wat is je officiële **domicilieadres**? (straat, nummer, postcode en stad)"
Kort en direct. Max 1 zin."""
    )


async def handle_address(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Process address collection messages."""
    state = agent.state
    phase = state.address_phase

    if phase == "ask_domicile":
        return await _handle_domicile(agent, message)
    elif phase == "ask_same":
        return await _handle_same_question(agent, message)
    elif phase == "ask_verblijf":
        return await _handle_verblijf(agent, message)
    elif phase == "done":
        return await agent._advance_step()

    return await agent._advance_step()


async def _handle_domicile(agent: DocumentCollectionAgent, message: str) -> str:
    state = agent.state
    slug = "domicile_address"
    fields = _get_address_fields(agent, slug)

    # Try geocoding first
    geocoded = await geocode_address(message)
    if geocoded:
        field_keys = {f["key"] for f in fields}
        value = {k: v for k, v in geocoded.items() if k in field_keys and v}
        missing = [f["key"] for f in fields if f.get("required", True) and not value.get(f["key"])]

        if not missing:
            state.collected_attributes[slug] = {"value": value}
            state.partial_attributes.pop(slug, None)
            logger.info(f"[ADDR] domicile_address geocoded: {value}")
            state.address_phase = "ask_same"
            return await agent._say(
                f"""Domicilieadres is genoteerd ✅
Vraag nu: "Is je **verblijfsadres** hetzelfde als je domicilieadres?"
Max 1 zin."""
            )
        else:
            state.partial_attributes[slug] = value
            missing_labels = [f["label"] for f in fields if f["key"] in missing]
            return await agent._say(
                f"""Bedankt! Maar voor het **domicilieadres** mis ik nog: **{' en '.join(missing_labels)}**.
Vraag specifiek naar de ontbrekende info. Max 1-2 zinnen."""
            )

    # LLM extraction fallback
    existing_partial = state.partial_attributes.get(slug)
    result = await agent._extract_attribute(slug, "Domicilie adres", message, fields=fields, partial=existing_partial)

    if result.get("valid") and isinstance(result.get("value"), dict):
        value = agent._merge_partial(slug, result["value"])
        missing = [f["key"] for f in fields if f.get("required", True) and not value.get(f["key"])]
        if not missing:
            state.collected_attributes[slug] = {"value": value}
            state.partial_attributes.pop(slug, None)
            state.address_phase = "ask_same"
            return await agent._say(
                f"""Domicilieadres is genoteerd ✅
Vraag nu: "Is je **verblijfsadres** hetzelfde als je domicilieadres?"
Max 1 zin."""
            )
        state.partial_attributes[slug] = value
        missing_labels = [f["label"] for f in fields if f["key"] in missing]
        return await agent._say(
            f"""Bedankt! Maar voor het **domicilieadres** mis ik nog: **{' en '.join(missing_labels)}**.
Vraag specifiek naar de ontbrekende info. Max 1-2 zinnen."""
        )

    # Partial with missing fields
    if result.get("value") and isinstance(result["value"], dict):
        value = agent._merge_partial(slug, result["value"])
        state.partial_attributes[slug] = value
        missing = result.get("missing_fields", [f["key"] for f in fields if f.get("required", True)])
        missing_labels = [f["label"] for f in fields if f["key"] in missing]
        return await agent._say(
            f"""Bedankt! Maar voor het **domicilieadres** mis ik nog: **{' en '.join(missing_labels)}**.
Vraag specifiek. Max 1-2 zinnen."""
        )

    return await agent._say(
        """Het antwoord was niet duidelijk genoeg om een adres te herkennen.
Vraag opnieuw naar het **domicilieadres** met straat, nummer, postcode en stad.
Max 2 zinnen."""
    )


async def _handle_same_question(agent: DocumentCollectionAgent, message: str) -> str:
    state = agent.state

    # Check if user sent an actual address instead of yes/no
    geocoded = await geocode_address(message)
    if geocoded:
        # User gave a different address — interpret as "neen"
        state.collected_attributes["adres_gelijk_aan_domicilie"] = {"value": "neen"}
        slug = "verblijfs_adres"
        fields = _get_address_fields(agent, slug)
        field_keys = {f["key"] for f in fields}
        value = {k: v for k, v in geocoded.items() if k in field_keys and v}
        missing = [f["key"] for f in fields if f.get("required", True) and not value.get(f["key"])]
        if not missing:
            state.collected_attributes[slug] = {"value": value}
            logger.info(f"[ADDR] verblijfs_adres auto-collected from geocoded answer: {value}")
            state.address_phase = "done"
            return await agent._advance_step()
        state.partial_attributes[slug] = value
        state.address_phase = "ask_verblijf"
        missing_labels = [f["label"] for f in fields if f["key"] in missing]
        return await agent._say(
            f"""Genoteerd! Voor je **verblijfsadres** mis ik nog: **{' en '.join(missing_labels)}**.
Max 1-2 zinnen."""
        )

    if _YES.search(message):
        state.collected_attributes["adres_gelijk_aan_domicilie"] = {"value": "ja"}
        # Copy domicile to verblijfs
        domicile = state.collected_attributes.get("domicile_address")
        if domicile:
            state.collected_attributes["verblijfs_adres"] = {"value": domicile["value"]}
            logger.info("[ADDR] Copied domicile to verblijfs_adres (same address)")
        state.address_phase = "done"
        return await agent._advance_step()

    if _NO.search(message):
        state.collected_attributes["adres_gelijk_aan_domicilie"] = {"value": "neen"}
        state.address_phase = "ask_verblijf"
        return await agent._say(
            f"""Vraag {agent.state.candidate_name} naar het **verblijfsadres** (waar je effectief woont).
Voorbeeld: "Wat is je **verblijfsadres**? (straat, nummer, postcode en stad)"
Kort en direct. Max 1 zin."""
        )

    # Ambiguous
    return await agent._say(
        """Ik kon niet duidelijk opmaken of je verblijfsadres hetzelfde is als je domicilieadres.
Vraag opnieuw: "Is je **verblijfsadres** hetzelfde als je domicilieadres? (ja/nee)"
Max 1 zin."""
    )


async def _handle_verblijf(agent: DocumentCollectionAgent, message: str) -> str:
    state = agent.state
    slug = "verblijfs_adres"
    fields = _get_address_fields(agent, slug)

    # Try geocoding
    geocoded = await geocode_address(message)
    if geocoded:
        field_keys = {f["key"] for f in fields}
        value = {k: v for k, v in geocoded.items() if k in field_keys and v}
        missing = [f["key"] for f in fields if f.get("required", True) and not value.get(f["key"])]
        if not missing:
            state.collected_attributes[slug] = {"value": value}
            state.partial_attributes.pop(slug, None)
            logger.info(f"[ADDR] verblijfs_adres geocoded: {value}")
            state.address_phase = "done"
            return await agent._advance_step()
        state.partial_attributes[slug] = value
        missing_labels = [f["label"] for f in fields if f["key"] in missing]
        return await agent._say(
            f"""Bedankt! Maar voor het **verblijfsadres** mis ik nog: **{' en '.join(missing_labels)}**.
Max 1-2 zinnen."""
        )

    # LLM extraction
    existing_partial = state.partial_attributes.get(slug)
    result = await agent._extract_attribute(slug, "Verblijfsadres", message, fields=fields, partial=existing_partial)

    if result.get("valid") and isinstance(result.get("value"), dict):
        value = agent._merge_partial(slug, result["value"])
        missing = [f["key"] for f in fields if f.get("required", True) and not value.get(f["key"])]
        if not missing:
            state.collected_attributes[slug] = {"value": value}
            state.partial_attributes.pop(slug, None)
            state.address_phase = "done"
            return await agent._advance_step()
        state.partial_attributes[slug] = value
        missing_labels = [f["label"] for f in fields if f["key"] in missing]
        return await agent._say(
            f"""Bedankt! Maar voor het **verblijfsadres** mis ik nog: **{' en '.join(missing_labels)}**.
Max 1-2 zinnen."""
        )

    if result.get("value") and isinstance(result["value"], dict):
        value = agent._merge_partial(slug, result["value"])
        state.partial_attributes[slug] = value
        missing = result.get("missing_fields", [f["key"] for f in fields if f.get("required", True)])
        missing_labels = [f["label"] for f in fields if f["key"] in missing]
        return await agent._say(
            f"""Bedankt! Maar voor het **verblijfsadres** mis ik nog: **{' en '.join(missing_labels)}**.
Max 1-2 zinnen."""
        )

    return await agent._say(
        """Het antwoord was niet duidelijk genoeg om een adres te herkennen.
Vraag opnieuw naar het **verblijfsadres** met straat, nummer, postcode en stad.
Max 2 zinnen."""
    )
