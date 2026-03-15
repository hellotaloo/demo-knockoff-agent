"""
Handler for closing step.

Generates a summary of everything collected and provides recruiter contact info.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent


async def enter_closing(agent: DocumentCollectionAgent, step: dict) -> str:
    """Generate the closing message."""
    state = agent.state

    collected_docs = [slug for slug, v in state.collected_documents.items() if v.get("status") == "verified"]
    collected_attrs = list(state.collected_attributes.keys())
    skipped = [i.get("name", i.get("slug", "")) for i in state.skipped_items]

    parts = []
    if collected_docs:
        parts.append(f"Documenten ontvangen: {', '.join(collected_docs)}")
    if collected_attrs:
        parts.append(f"Gegevens ontvangen: {', '.join(collected_attrs)}")

    skipped_note = ""
    if skipped:
        skipped_note = f"\nEr zijn nog items die niet verzameld konden worden: {', '.join(skipped)}. Een medewerker zal hiervoor contact opnemen."

    recruiter_info = ""
    if state.recruiter_name:
        recruiter_info = f"\nNoem **{state.recruiter_name}** als contactpersoon voor verdere vragen"
        if state.recruiter_email:
            recruiter_info += f" ({state.recruiter_email})"
        elif state.recruiter_phone:
            recruiter_info += f" ({state.recruiter_phone})"
        recruiter_info += "."

    closing_msg = await agent._say(
        f"""Sluit het gesprek af. Bedank {state.candidate_name} hartelijk.
Samenvatting: {'; '.join(parts) if parts else 'Alle items verwerkt.'}{skipped_note}{recruiter_info}
Max 3 zinnen. Warme afsluiting."""
    )

    # Mark closing as complete — conversation is done
    state.completed_steps.append("closing")
    state.current_step_index = len(state.conversation_flow)

    return closing_msg


async def handle_closing(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Handle any messages after closing — conversation is done."""
    return "Bedankt! Je dossier is volledig. Tot binnenkort! 👍"
