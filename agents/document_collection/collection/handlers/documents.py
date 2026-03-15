"""
Handler for collect_documents step (GENERIC).

Loops through step["items"] using state.step_item_index.
Loads document type definitions from TypeCache at runtime.
Handles front/back scanning, retry logic, and skip detection.
Recommended documents can be skipped more easily.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

_SKIP_PATTERNS = re.compile(
    r"(?i)(heb ik niet|niet bij me|kan ik later|overslaan|skip|sla over|later sturen|doe ik later)",
)

_SKIP_LENIENT = re.compile(
    r"(?i)(nee\b|neen\b|sorry|nee sorry|niet nodig|hoeft niet)",
)


def _simulate_verification(message: str) -> dict | None:
    """Check for simulation markers."""
    if "--img-success--" in message:
        return {"passed": True, "summary": "Document geverifieerd (simulatie)."}
    if "--img-fail--" in message:
        return {"passed": False, "summary": "Document niet leesbaar (simulatie)."}
    # Identity markers also work here (e.g. if someone sends --eu-id-- during doc phase)
    if "--eu-id--" in message:
        return {"passed": True, "resolved_slug": "id_card", "summary": "ID-kaart (simulatie)."}
    if "--eu-pass--" in message:
        return {"passed": True, "resolved_slug": "passport", "summary": "Paspoort (simulatie)."}
    return None


def _get_current_item(agent: DocumentCollectionAgent, step: dict) -> dict | None:
    items = step.get("items", [])
    idx = agent.state.step_item_index
    if idx < len(items):
        return items[idx]
    return None


def _build_item_from_cache(agent: DocumentCollectionAgent, item: dict) -> dict:
    """Enrich a plan item (slug only) with type definition from cache."""
    slug = item.get("slug", "")
    enriched = {"slug": slug, "name": slug, "type": "document"}

    if agent.type_cache:
        doc_type = agent.type_cache.get_doc_type(slug)
        if doc_type:
            enriched["name"] = doc_type["name"]
            enriched["scan_mode"] = doc_type.get("scan_mode", "single")
            enriched["requires_front_back"] = doc_type.get("requires_front_back", False)
            enriched["is_verifiable"] = doc_type.get("is_verifiable", False)
            if doc_type.get("ai_hint"):
                enriched["ai_hint"] = doc_type["ai_hint"]

    # Plan-level overrides
    if item.get("priority"):
        enriched["priority"] = item["priority"]
    if item.get("reason"):
        enriched["reason"] = item["reason"]

    return enriched


async def enter_documents(agent: DocumentCollectionAgent, step: dict) -> str:
    """Generate the first document request."""
    agent.state.step_item_index = 0
    item = _get_current_item(agent, step)
    if not item:
        return await agent._advance_step()

    enriched = _build_item_from_cache(agent, item)
    return await _ask_document(agent, enriched)


async def handle_documents(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Process document collection messages."""
    state = agent.state
    item = _get_current_item(agent, step)
    if not item:
        return await agent._advance_step()

    enriched = _build_item_from_cache(agent, item)
    slug = enriched["slug"]
    is_recommended = enriched.get("priority") == "recommended"

    # Check if waiting for back side
    if state.waiting_for_back == slug:
        return await _handle_back_side(agent, message, has_image, enriched, step)

    # Check skip intent
    if _SKIP_PATTERNS.search(message) or (is_recommended and _SKIP_LENIENT.search(message)):
        state.skipped_items.append({
            "slug": slug, "type": "document",
            "name": enriched["name"],
            "skip_reason": "candidate_skipped",
        })
        return await _advance_to_next_item(agent, step, enriched, skipped=True)

    # Check for verification
    verification = _simulate_verification(message)
    if not verification and has_image:
        verification = {"passed": True, "summary": "Document ontvangen."}

    if not verification:
        return await agent._say(
            f"""De kandidaat heeft een tekstbericht gestuurd, maar je wacht op een FOTO van **{enriched['name']}**.
Herinner vriendelijk dat je een foto nodig hebt. 📷
De kandidaat kan ook "overslaan" zeggen als het document nu niet beschikbaar is.
Max 2 zinnen."""
        )

    if not verification["passed"]:
        retries = state.retry_counts.get(slug, 0) + 1
        state.retry_counts[slug] = retries
        if retries >= MAX_RETRIES:
            state.skipped_items.append({
                "slug": slug, "type": "document",
                "name": enriched["name"],
                "skip_reason": "max_retries",
            })
            return await _advance_to_next_item(agent, step, enriched, skipped=True)
        return await agent._say(
            f"""De foto van **{enriched['name']}** was niet duidelijk genoeg.
Poging {retries}/{MAX_RETRIES}.
Vraag vriendelijk om een nieuwe foto. Max 2 zinnen."""
        )

    # Verification passed
    scan_mode = enriched.get("scan_mode", "single")
    if scan_mode == "front_back":
        state.collected_documents[slug] = {
            "status": "front_verified",
            "sides_collected": ["front"],
            "verification": verification,
        }
        state.waiting_for_back = slug
        return await agent._say(
            f"""Voorkant van **{enriched['name']}** is goed ontvangen ✅
Vraag nu om de **achterkant**.
Kort en vriendelijk, max 1 zin."""
        )

    # Single scan — fully verified
    state.collected_documents[slug] = {
        "status": "verified",
        "sides_collected": ["single"],
        "verification": verification,
    }
    return await _advance_to_next_item(agent, step, enriched)


async def _handle_back_side(
    agent: DocumentCollectionAgent, message: str, has_image: bool,
    enriched: dict, step: dict,
) -> str:
    state = agent.state
    slug = enriched["slug"]

    if _SKIP_PATTERNS.search(message):
        state.waiting_for_back = None
        state.skipped_items.append({
            "slug": slug, "type": "document",
            "name": enriched["name"],
            "skip_reason": "back_skipped",
        })
        return await _advance_to_next_item(agent, step, enriched, skipped=True)

    verification = _simulate_verification(message)
    if not verification and has_image:
        verification = {"passed": True, "summary": "Achterkant ontvangen."}

    if not verification:
        return await agent._say(
            f"""Je wacht nog op de **achterkant** van **{enriched['name']}**.
Herinner vriendelijk. 📷 Max 1 zin."""
        )

    if not verification["passed"]:
        retries = state.retry_counts.get(slug, 0) + 1
        state.retry_counts[slug] = retries
        if retries >= MAX_RETRIES:
            state.waiting_for_back = None
            state.skipped_items.append({
                "slug": slug, "type": "document",
                "name": enriched["name"],
                "skip_reason": "max_retries",
            })
            return await _advance_to_next_item(agent, step, enriched, skipped=True)
        return await agent._say(
            f"""De foto van de achterkant was niet duidelijk genoeg.
Poging {retries}/{MAX_RETRIES}. Vraag om een nieuwe foto. Max 2 zinnen."""
        )

    # Back side verified
    existing = state.collected_documents.get(slug, {})
    sides = existing.get("sides_collected", [])
    sides.append("back")
    state.collected_documents[slug] = {
        "status": "verified",
        "sides_collected": sides,
        "verification": verification,
    }
    state.waiting_for_back = None
    return await _advance_to_next_item(agent, step, enriched)


async def _ask_document(agent: DocumentCollectionAgent, enriched: dict) -> str:
    """Generate prompt to ask for a document."""
    scan_mode = enriched.get("scan_mode", "single")
    side_instruction = "Vraag om een foto van de **voorkant**." if scan_mode == "front_back" else "Vraag om een duidelijke foto."

    return await agent._say(
        f"""Vraag {agent.state.candidate_name} om een foto van: **{enriched['name']}**
{side_instruction}
Kort en direct. Max 1 zin."""
    )


async def _advance_to_next_item(
    agent: DocumentCollectionAgent, step: dict,
    completed_item: dict, skipped: bool = False,
) -> str:
    state = agent.state
    state.step_item_index += 1
    state.waiting_for_back = None

    if skipped:
        confirm = f"Geen probleem, we slaan {completed_item['name'].lower()} even over. 👍"
    else:
        confirm = f"Oké, {completed_item['name'].lower()} is ontvangen! ✅"

    next_item = _get_current_item(agent, step)
    # Skip already-collected items
    while next_item and next_item.get("slug") in state.collected_documents:
        state.step_item_index += 1
        next_item = _get_current_item(agent, step)

    if next_item:
        enriched = _build_item_from_cache(agent, next_item)
        next_request = await _ask_document(agent, enriched)
        return confirm + "\n\n" + next_request

    # All items done
    advance_msg = await agent._advance_step()
    return confirm + "\n\n" + advance_msg
