"""
Handler for identity_verification step (HARDCODED).

Sub-state machine:
  ask_id → waiting_id → (ask_work_permit → waiting_work_permit →) done

EU/EEA/Swiss passport → work_eligibility = true, skip work permits.
Non-EU passport → ask for one of: prato_5, prato_101, prato_102, prato_9, prato_20.

Uses Gemini vision for real document verification and auto-detection of
document type (id_card, passport, driver_license).
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

# EU/EEA + Swiss nationalities for auto-detection (words + ISO 3166-1 alpha-3 codes)
_EU_NATIONALITIES = {
    # ISO 3166-1 alpha-3 codes
    "bel", "nld", "deu", "fra", "ita", "esp", "prt", "pol", "rou", "bgr",
    "hrv", "grc", "cze", "svk", "svn", "est", "lva", "ltu", "fin", "swe",
    "dnk", "irl", "aut", "lux", "mlt", "cyp", "hun",
    "nor", "isl", "lie", "che",  # EEA + Switzerland
    # Common nationality words (NL, EN, FR, DE)
    "belg", "belgian", "belgisch", "belge",
    "nederland", "dutch", "nederlands", "néerlandais",
    "duits", "german", "deutsch", "allemand",
    "frans", "french", "français", "française",
    "italiaans", "italian", "italiano", "italien",
    "spaans", "spanish", "español", "espagnol",
    "portugees", "portuguese", "português", "portugais",
    "pools", "polish", "polski", "polonais",
    "roemeens", "romanian", "român", "roumain",
    "bulgaars", "bulgarian", "bulgare",
    "kroatisch", "croatian", "croate",
    "grieks", "greek", "grec",
    "tsjechisch", "czech", "tchèque",
    "slovaaks", "slovak", "slovaque",
    "sloveens", "slovenian", "slovène",
    "estlands", "estonian", "estonien",
    "lets", "latvian", "letton",
    "litouws", "lithuanian", "lituanien",
    "fins", "finnish", "finlandais",
    "zweeds", "swedish", "suédois",
    "deens", "danish", "danois",
    "iers", "irish", "irlandais",
    "oostenrijks", "austrian", "autrichien",
    "luxemburgs", "luxembourgish", "luxembourgeois",
    "maltees", "maltese", "maltais",
    "cypriotisch", "cypriot", "chypriote",
    "hongaars", "hungarian", "hongrois",
    # EEA + Switzerland
    "noors", "norwegian", "norvégien",
    "ijslands", "icelandic", "islandais",
    "liechtenstein",
    "zwitsers", "swiss", "suisse",
}


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


def _detect_eu_from_nationality(nationality: str | None) -> bool | None:
    """Detect EU/EEA citizenship from nationality string. Returns None if uncertain."""
    if not nationality:
        return None
    normalized = nationality.strip().lower()
    return normalized in _EU_NATIONALITIES


async def _verify_identity_image(agent: DocumentCollectionAgent) -> dict:
    """Run real document verification for identity documents via Gemini vision."""
    from agents.document_collection.recognition.agent import verify_document

    image_data = agent.pending_image_data

    # Get extraction fields — try id_card first (most common), will auto-detect anyway
    extract_fields = None
    if agent.type_cache:
        for slug in ("id_card", "passport"):
            doc_type = agent.type_cache.get_doc_type(slug)
            if doc_type and doc_type.get("verification_config"):
                extract_fields = doc_type["verification_config"].get("extract_fields")
                break

    # Available identity document types for classification
    available_types = [
        {"slug": "id_card", "name": "ID-kaart / Identiteitskaart"},
        {"slug": "passport", "name": "Paspoort"},
        {"slug": "driver_license", "name": "Rijbewijs"},
    ]

    result = await verify_document(
        image_data=image_data,
        candidate_name=agent.state.candidate_name,
        document_type_hint=None,  # Let it auto-detect
        extract_fields=extract_fields,
        available_types=available_types,
    )

    verification = {
        "passed": result.verification_passed,
        "summary": result.verification_summary,
        "resolved_slug": result.document_category,
        "extracted_fields": result.extracted_fields,
        "image_quality": result.image_quality,
        "fraud_risk_level": result.fraud_risk_level,
    }

    if result.feedback_message:
        verification["feedback_message"] = result.feedback_message
    if result.extracted_name:
        verification["extracted_name"] = result.extracted_name

    # Determine EU citizenship from extracted nationality
    nationality = (result.extracted_fields or {}).get("nationality")
    eu_status = _detect_eu_from_nationality(nationality)
    if eu_status is not None:
        verification["eu_citizen"] = eu_status

    logger.info(f"[IDENTITY] Verified: passed={result.verification_passed}, "
                f"category={result.document_category}, quality={result.image_quality}, "
                f"nationality={nationality}, eu={eu_status}")

    return verification


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
    if not verification and has_image and agent.pending_image_data:
        verification = await _verify_identity_image(agent)
    elif not verification and has_image:
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
        feedback = verification.get("feedback_message", "De foto van het identiteitsdocument was niet duidelijk genoeg.")
        return await agent._say(
            f"""{feedback}
Poging {retries}/{MAX_RETRIES}.
Vraag vriendelijk om een nieuwe foto. Max 2 zinnen."""
        )

    # Verification passed
    resolved_slug = verification.get("resolved_slug", "id_card")
    # Map recognized categories to valid identity slugs
    if resolved_slug not in ("id_card", "passport", "driver_license"):
        resolved_slug = "id_card"  # Default fallback

    doc_type = agent.type_cache.get_doc_type(resolved_slug) if agent.type_cache else None
    scan_mode = (doc_type or {}).get("scan_mode", "single") if doc_type else ("front_back" if resolved_slug == "id_card" else "single")

    doc_data = {
        "verification": verification,
    }
    if verification.get("extracted_fields"):
        doc_data["extracted_fields"] = verification["extracted_fields"]

    # Check if we need the back side
    if scan_mode == "front_back" and not state.waiting_for_back:
        doc_data["status"] = "front_verified"
        doc_data["sides_collected"] = ["front"]
        state.collected_documents[resolved_slug] = doc_data
        state.waiting_for_back = resolved_slug
        state.identity_phase = "waiting_id"
        return await agent._say(
            f"""Voorkant van het identiteitsdocument is goed ontvangen ✅
Vraag nu om de **achterkant**.
Voorbeeld: "Kan je nu ook de **achterkant** doorsturen?"
Kort en vriendelijk, max 1 zin."""
        )

    if state.waiting_for_back == resolved_slug:
        # Back side received — merge extracted fields
        existing = state.collected_documents.get(resolved_slug, {})
        sides = existing.get("sides_collected", [])
        sides.append("back")
        existing_fields = existing.get("extracted_fields", {})
        back_fields = verification.get("extracted_fields", {})
        merged_fields = {**existing_fields, **{k: v for k, v in back_fields.items() if v}}
        doc_data["status"] = "verified"
        doc_data["sides_collected"] = sides
        doc_data["extracted_fields"] = merged_fields if merged_fields else None
        state.collected_documents[resolved_slug] = doc_data
        state.waiting_for_back = None
    else:
        # Single scan — fully verified
        doc_data["status"] = "verified"
        doc_data["sides_collected"] = ["single"]
        state.collected_documents[resolved_slug] = doc_data

    # Auto-populate attributes_from_documents with extracted fields
    extracted = doc_data.get("extracted_fields") or {}
    if extracted:
        # Map recognition field names → attribute slugs
        field_to_slug = {
            "date_of_birth": "date_of_birth",
            "nationality": "nationality",
            "national_registry_number": "national_register_nr",
            "holder_name": "holder_name",
            "expiry_date": "expiry_date",
            "document_number": "document_number",
        }
        for field_key, attr_slug in field_to_slug.items():
            value = extracted.get(field_key)
            if value and any(afd.get("slug") == attr_slug for afd in state.attributes_from_documents):
                state.collected_attributes[attr_slug] = {"value": value}
                logger.info(f"[IDENTITY] Auto-extracted {attr_slug}={value}")

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
        # EU citizen status unknown from image (no nationality extracted)
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
    if not verification and has_image and agent.pending_image_data:
        verification = await _verify_identity_image(agent)
    elif not verification and has_image:
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
    if not verification and has_image and agent.pending_image_data:
        verification = await _verify_identity_image(agent)
    elif not verification and has_image:
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
        feedback = verification.get("feedback_message", "De foto van het werkvergunningdocument was niet duidelijk genoeg.")
        return await agent._say(
            f"""{feedback}
Poging {retries}/{MAX_RETRIES}.
Vraag vriendelijk om een nieuwe foto. Max 2 zinnen."""
        )

    # Work permit verified
    resolved_slug = verification.get("resolved_slug", "prato_5")
    doc_data = {
        "status": "verified",
        "sides_collected": ["single"],
        "verification": verification,
    }
    if verification.get("extracted_fields"):
        doc_data["extracted_fields"] = verification["extracted_fields"]

    state.collected_documents[resolved_slug] = doc_data
    state.work_eligibility = True
    state.collected_attributes["work_eligibility"] = {"value": True}
    state.identity_phase = "done"
    logger.info(f"Work permit verified ({resolved_slug}) — work_eligibility=true")
    return await agent._advance_step()
