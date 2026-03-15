"""
Handler for identity_verification step (HARDCODED).

Sub-state machine:
  ask_id → waiting_id → (ask_work_permit → waiting_work_permit →) done

EU/EEA/Swiss passport → work_eligibility = true, skip work permits.
Non-EU passport → ask for one of: prato_5, prato_101, prato_102, prato_9, prato_20.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from agents.document_collection.collection.rules import WORK_PERMIT_SLUGS

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

_SKIP_PATTERNS = re.compile(
    r"(?i)(heb ik niet|niet bij me|kan ik later|overslaan|skip|sla over|later sturen)",
)


def _simulate_verification(message: str) -> dict | None:
    """Check for simulation markers in text."""
    if "--eu-id--" in message:
        return {
            "passed": True, "resolved_slug": "id_card", "eu_citizen": True,
            "summary": "EU/EER identiteitskaart geverifieerd (simulatie).",
        }
    if "--eu-pass--" in message:
        return {
            "passed": True, "resolved_slug": "passport", "eu_citizen": True,
            "summary": "EU/EER paspoort geverifieerd (simulatie).",
        }
    if "--non-eu-pass--" in message:
        return {
            "passed": True, "resolved_slug": "passport", "eu_citizen": False,
            "summary": "Niet-EU paspoort geverifieerd (simulatie).",
        }
    if "--img-success--" in message:
        return {"passed": True, "summary": "Document geverifieerd (simulatie)."}
    if "--img-fail--" in message:
        return {"passed": False, "summary": "Document niet leesbaar (simulatie)."}
    return None


async def enter_identity(agent: DocumentCollectionAgent, step: dict) -> str:
    """Ask for ID card or passport."""
    agent.state.identity_phase = "ask_id"
    return await agent._say(
        f"""Vraag {agent.state.candidate_name} om een identiteitsdocument.
De kandidaat mag kiezen: de voor- en achterkant van je **identiteitskaart** of een foto van je **paspoort**.

Gebruik **bold** rond de gevraagde items.
Voorbeeld: "Kan je een foto van je **identiteitskaart** of **paspoort** sturen? 📷"
Kort en direct. Max 1 zin."""
    )


async def handle_identity(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Process identity verification messages."""
    state = agent.state
    phase = state.identity_phase

    if phase in ("ask_id", "waiting_id"):
        return await _handle_id_phase(agent, message, has_image)
    elif phase == "ask_work_permit":
        return await _handle_work_permit_ask(agent, message, has_image)
    elif phase == "waiting_work_permit":
        return await _handle_work_permit_waiting(agent, message, has_image)
    elif phase == "done":
        return await agent._advance_step()

    return await agent._advance_step()


async def _handle_id_phase(agent: DocumentCollectionAgent, message: str, has_image: bool) -> str:
    state = agent.state

    if _SKIP_PATTERNS.search(message):
        state.skipped_items.append({"slug": "identity", "type": "identity_verification", "skip_reason": "candidate_skipped"})
        return await agent._advance_step()

    verification = _simulate_verification(message)
    if not verification and has_image:
        verification = {"passed": True, "summary": "Document ontvangen."}

    if not verification:
        return await agent._say(
            """De kandidaat heeft een tekstbericht gestuurd, maar je wacht op een FOTO van een identiteitsdocument.
Herinner vriendelijk dat je een foto van de **identiteitskaart** of **paspoort** nodig hebt. 📷
Max 1-2 zinnen."""
        )

    if not verification["passed"]:
        slug = verification.get("resolved_slug", "identity")
        retries = state.retry_counts.get(slug, 0) + 1
        state.retry_counts[slug] = retries
        if retries >= MAX_RETRIES:
            state.skipped_items.append({"slug": "identity", "type": "identity_verification", "skip_reason": "max_retries"})
            return await agent._advance_step()
        return await agent._say(
            f"""De foto van het identiteitsdocument was niet duidelijk genoeg.
Poging {retries}/{MAX_RETRIES}.
Vraag vriendelijk om een nieuwe foto. Max 2 zinnen."""
        )

    # Verification passed
    resolved_slug = verification.get("resolved_slug", "id_card")
    doc_type = agent.type_cache.get_doc_type(resolved_slug) if agent.type_cache else None
    scan_mode = (doc_type or {}).get("scan_mode", "single") if doc_type else ("front_back" if resolved_slug == "id_card" else "single")

    # Check if we need the back side
    if scan_mode == "front_back" and not state.waiting_for_back:
        state.collected_documents[resolved_slug] = {
            "status": "front_verified",
            "sides_collected": ["front"],
            "verification": verification,
        }
        state.waiting_for_back = resolved_slug
        state.identity_phase = "waiting_id"
        return await agent._say(
            f"""Voorkant van het identiteitsdocument is goed ontvangen ✅
Vraag nu om de **achterkant**.
Voorbeeld: "Kan je nu ook de **achterkant** doorsturen?"
Kort en vriendelijk, max 1 zin."""
        )

    if state.waiting_for_back == resolved_slug:
        # Back side received
        existing = state.collected_documents.get(resolved_slug, {})
        sides = existing.get("sides_collected", [])
        sides.append("back")
        state.collected_documents[resolved_slug] = {
            "status": "verified",
            "sides_collected": sides,
            "verification": verification,
        }
        state.waiting_for_back = None
    else:
        # Single scan — fully verified
        state.collected_documents[resolved_slug] = {
            "status": "verified",
            "sides_collected": ["single"],
            "verification": verification,
        }

    # Set EU citizenship
    if "eu_citizen" in verification:
        state.eu_citizen = verification["eu_citizen"]

    # Auto-extract attributes from identity document
    if state.eu_citizen is True:
        state.work_eligibility = True
        state.collected_attributes["work_eligibility"] = {"value": True}
        state.identity_phase = "done"
        logger.info("EU citizen — work_eligibility=true, skipping work permits")
        return await agent._advance_step()
    elif state.eu_citizen is False:
        # Non-EU — need work permit
        state.identity_phase = "ask_work_permit"
        return await agent._say(
            f"""Het identiteitsdocument is goed ontvangen ✅
De kandidaat heeft een niet-EU paspoort. Vraag nu om een **werkvergunning** of **verblijfsdocument**.

De kandidaat mag kiezen uit: **werkvergunning**, **verblijfsdocument**, of **vrijstelling arbeidskaart**.
Kort en direct. Max 2 zinnen."""
        )
    else:
        # EU citizen status unknown from image (real verification without simulation marker)
        state.identity_phase = "done"
        return await agent._advance_step()


async def _handle_work_permit_ask(agent: DocumentCollectionAgent, message: str, has_image: bool) -> str:
    """First message after asking for work permit."""
    state = agent.state

    if _SKIP_PATTERNS.search(message):
        state.skipped_items.append({"slug": "work_permit", "type": "identity_verification", "skip_reason": "candidate_skipped"})
        state.identity_phase = "done"
        return await agent._advance_step()

    verification = _simulate_verification(message)
    if not verification and has_image:
        verification = {"passed": True, "summary": "Document ontvangen."}

    if not verification:
        state.identity_phase = "waiting_work_permit"
        return await agent._say(
            """Je wacht op een foto van een werkvergunning of verblijfsdocument.
Herinner vriendelijk dat je een foto nodig hebt. 📷
Max 1-2 zinnen."""
        )

    return await _process_work_permit(agent, verification)


async def _handle_work_permit_waiting(agent: DocumentCollectionAgent, message: str, has_image: bool) -> str:
    state = agent.state

    if _SKIP_PATTERNS.search(message):
        state.skipped_items.append({"slug": "work_permit", "type": "identity_verification", "skip_reason": "candidate_skipped"})
        state.identity_phase = "done"
        return await agent._advance_step()

    verification = _simulate_verification(message)
    if not verification and has_image:
        verification = {"passed": True, "summary": "Document ontvangen."}

    if not verification:
        return await agent._say(
            """Je wacht nog op een foto van een werkvergunning of verblijfsdocument.
Herinner vriendelijk. 📷 Max 1 zin."""
        )

    return await _process_work_permit(agent, verification)


async def _process_work_permit(agent: DocumentCollectionAgent, verification: dict) -> str:
    state = agent.state

    if not verification["passed"]:
        retries = state.retry_counts.get("work_permit", 0) + 1
        state.retry_counts["work_permit"] = retries
        if retries >= MAX_RETRIES:
            state.skipped_items.append({"slug": "work_permit", "type": "identity_verification", "skip_reason": "max_retries"})
            state.identity_phase = "done"
            return await agent._advance_step()
        return await agent._say(
            f"""De foto van het werkvergunningdocument was niet duidelijk genoeg.
Poging {retries}/{MAX_RETRIES}.
Vraag vriendelijk om een nieuwe foto. Max 2 zinnen."""
        )

    # Work permit verified
    resolved_slug = verification.get("resolved_slug", "prato_5")
    state.collected_documents[resolved_slug] = {
        "status": "verified",
        "sides_collected": ["single"],
        "verification": verification,
    }
    state.work_eligibility = True
    state.collected_attributes["work_eligibility"] = {"value": True}
    state.identity_phase = "done"
    logger.info(f"Work permit verified ({resolved_slug}) — work_eligibility=true")
    return await agent._advance_step()
