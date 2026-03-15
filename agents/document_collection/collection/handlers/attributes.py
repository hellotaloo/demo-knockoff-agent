"""
Handler for collect_attributes step (GENERIC).

Loops through step["items"] using state.step_item_index.
Loads field definitions from TypeCache at runtime.
Handles multi-field attributes with partial progress tracking.
Special case: IBAN validation via rules.validate_iban().
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from agents.document_collection.collection.rules import validate_iban, validate_phone

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent

logger = logging.getLogger(__name__)

_SKIP_PATTERNS = re.compile(
    r"(?i)(heb ik niet|niet bij me|kan ik later|overslaan|skip|sla over|later sturen|doe ik later)",
)


def _get_current_item(agent: DocumentCollectionAgent, step: dict) -> dict | None:
    """Get current item from step's item list."""
    items = step.get("items", [])
    idx = agent.state.step_item_index
    if idx < len(items):
        return items[idx]
    return None


def _build_item_from_cache(agent: DocumentCollectionAgent, item: dict) -> dict:
    """Enrich a plan item (slug only) with type definition from cache."""
    slug = item.get("slug", "")
    enriched = {"slug": slug, "name": slug, "type": "attribute"}

    if agent.type_cache:
        attr_type = agent.type_cache.get_attr_type(slug)
        if attr_type:
            enriched["name"] = attr_type["name"]
            if attr_type.get("fields"):
                enriched["fields"] = attr_type["fields"]
            if attr_type.get("ai_hint"):
                enriched["ai_hint"] = attr_type["ai_hint"]

    # Plan-level overrides
    if item.get("reason"):
        enriched["reason"] = item["reason"]

    return enriched


async def enter_attributes(agent: DocumentCollectionAgent, step: dict) -> str:
    """Generate the first attribute request."""
    agent.state.step_item_index = 0
    item = _get_current_item(agent, step)
    if not item:
        return await agent._advance_step()

    enriched = _build_item_from_cache(agent, item)
    return await _ask_attribute(agent, enriched)


async def handle_attributes(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Process attribute collection messages."""
    state = agent.state
    item = _get_current_item(agent, step)
    if not item:
        return await agent._advance_step()

    enriched = _build_item_from_cache(agent, item)
    slug = enriched["slug"]
    fields = enriched.get("fields")

    # Check skip intent
    if _SKIP_PATTERNS.search(message):
        state.partial_attributes.pop(slug, None)
        state.skipped_items.append({
            "slug": slug, "type": "attribute",
            "name": enriched["name"],
            "skip_reason": "candidate_skipped",
        })
        return await _advance_to_next_item(agent, step, enriched)

    # Extract value
    existing_partial = state.partial_attributes.get(slug)
    result = await agent._extract_attribute(
        slug, enriched["name"], message,
        fields=fields, partial=existing_partial,
        ai_hint=enriched.get("ai_hint"),
    )

    if result.get("valid") and result.get("value"):
        value = result["value"]

        if fields:
            # Structured attribute — must be a dict
            if not isinstance(value, dict):
                logger.warning(f"[ATTR] {slug}: expected dict, got {type(value).__name__}")
                return await agent._say(
                    f"""Het antwoord was niet duidelijk genoeg om **{enriched['name']}** te bepalen.
Vraag opnieuw, specifieker. Max 2 zinnen."""
                )

            value = agent._merge_partial(slug, value)
            missing = [f["key"] for f in fields if f.get("required", True) and not value.get(f["key"])]
            if missing:
                state.partial_attributes[slug] = value
                missing_labels = [f["label"] for f in fields if f["key"] in missing]
                return await agent._say(
                    f"""Bedankt! Maar voor **{enriched['name']}** mis ik nog: **{' en '.join(missing_labels)}**.
Vraag specifiek naar de ontbrekende info. Max 1-2 zinnen."""
                )

        state.partial_attributes.pop(slug, None)

        # IBAN validation
        if slug == "iban" and isinstance(value, str):
            iban_result = validate_iban(value)
            if not iban_result.valid:
                return await agent._say(
                    f"""De kandidaat gaf "{value}" als IBAN maar dit is geen geldig IBAN-nummer.
Vraag vriendelijk om het opnieuw te controleren en nog eens te sturen.
Max 1-2 zinnen."""
                )
            if not iban_result.is_sepa:
                return await agent._say(
                    f"""De kandidaat gaf een geldig IBAN ({iban_result.formatted}) maar dit is geen SEPA-rekeningnummer.
Voor de verloning is een SEPA-bankrekening vereist.
Leg dit vriendelijk uit en vraag om een ander rekeningnummer. Max 2 zinnen."""
                )
            if not iban_result.is_belgian:
                state.review_flags.append({
                    "slug": "iban", "flag": "non_belgian_iban",
                    "reason": f"SEPA-conform maar niet Belgisch ({iban_result.country_code}): {iban_result.formatted}",
                })
            value = iban_result.formatted

        # Phone validation — normalize to E.164
        if fields and isinstance(value, dict):
            phone_keys = [f["key"] for f in fields if f.get("type") == "phone"]
            for pk in phone_keys:
                if value.get(pk):
                    phone_result = validate_phone(value[pk])
                    if not phone_result.valid:
                        state.partial_attributes[slug] = value
                        return await agent._say(
                            f"""Het telefoonnummer "{value[pk]}" lijkt niet geldig.
Vraag de kandidaat om het nummer opnieuw te controleren. Max 1-2 zinnen."""
                        )
                    value[pk] = phone_result.formatted

        state.collected_attributes[slug] = {"value": value}
        return await _advance_to_next_item(agent, step, enriched)

    # Partial extraction with missing fields
    if fields and result.get("value") and isinstance(result["value"], dict):
        value = agent._merge_partial(slug, result["value"])
        state.partial_attributes[slug] = value
        still_missing = [k for k in result.get("missing_fields", []) if not value.get(k)]
        if not still_missing:
            state.partial_attributes.pop(slug, None)
            state.collected_attributes[slug] = {"value": value}
            return await _advance_to_next_item(agent, step, enriched)
        missing_labels = [f["label"] for f in fields if f["key"] in still_missing]
        return await agent._say(
            f"""Bedankt! Maar voor **{enriched['name']}** mis ik nog: **{' en '.join(missing_labels)}**.
Vraag specifiek. Max 1-2 zinnen."""
        )

    # Unclear
    hint = f"\nInstructie: {enriched['ai_hint']}" if enriched.get("ai_hint") else ""
    return await agent._say(
        f"""Het antwoord was niet duidelijk genoeg om **{enriched['name']}** te bepalen.{hint}
Vraag opnieuw, specifieker. Geef een voorbeeld. Max 2 zinnen."""
    )


async def _ask_attribute(agent: DocumentCollectionAgent, enriched: dict) -> str:
    """Generate prompt to ask for an attribute."""
    fields = enriched.get("fields")
    hint = f"\nInstructie: {enriched['ai_hint']}" if enriched.get("ai_hint") else ""
    reason = f" ({enriched['reason']})" if enriched.get("reason") else ""

    if fields:
        labels = [f["label"] for f in fields]
        fields_text = " en ".join(labels) if len(labels) <= 2 else ", ".join(labels[:-1]) + f" en {labels[-1]}"
        return await agent._say(
            f"""Vraag de kandidaat naar: **{enriched['name']}**{reason}{hint}
Dit is een gestructureerd gegeven. Vraag naar: {fields_text}.
Combineer alles in ÉÉN vraag. Kort en direct. Max 1-2 zinnen."""
        )

    return await agent._say(
        f"""Vraag de kandidaat naar: **{enriched['name']}**{reason}{hint}
Gebruik **bold** rond het sleutelwoord. Kort en direct. Max 1 zin."""
    )


async def _advance_to_next_item(agent: DocumentCollectionAgent, step: dict, completed_item: dict) -> str:
    """Move to next item in this step, or advance to next step."""
    state = agent.state
    state.step_item_index += 1
    confirm = f"Oké, {completed_item['name'].lower()} is genoteerd! ✅"

    next_item = _get_current_item(agent, step)
    if next_item:
        # Skip already-collected items
        while next_item and next_item.get("slug") in state.collected_attributes:
            state.step_item_index += 1
            next_item = _get_current_item(agent, step)

        if next_item:
            enriched = _build_item_from_cache(agent, next_item)
            next_request = await _ask_attribute(agent, enriched)
            return confirm + "\n\n" + next_request

    # All items done
    advance_msg = await agent._advance_step()
    return confirm + "\n\n" + advance_msg
