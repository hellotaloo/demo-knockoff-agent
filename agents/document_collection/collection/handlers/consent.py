"""
Handler for greeting_and_consent step.

On enter: hardcoded intro message based on goal (no LLM needed).
On message: detect yes/no, advance or refuse.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent

_CONSENT_YES = re.compile(
    r"(?i)(ja|akkoord|ok|oké|okay|goed|prima|geen probleem|dat is goed|mee eens|in orde|👍|yep|yes|sure)",
)

_CONSENT_NO = re.compile(
    r"(?i)(nee|niet akkoord|weiger|geen toestemming|niet mee eens|neen|no)",
)


_DUTCH_MONTHS = [
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def _format_date_nl(iso_date: str) -> str:
    """Format ISO date (2026-03-29) to Dutch (29 maart 2026)."""
    try:
        from datetime import date as _date
        d = _date.fromisoformat(iso_date)
        return f"{d.day} {_DUTCH_MONTHS[d.month]} {d.year}"
    except (ValueError, IndexError):
        return iso_date


def _build_intro_messages(state) -> list[str]:
    """Build deterministic welcome messages based on goal. Returns 2 bubbles."""
    name = state.candidate_name or "daar"
    first_name = name.split()[0] if name else "daar"
    company = state.company_name or ""
    vacancy = state.vacancy_title or ""
    start_date = _format_date_nl(state.start_date) if state.start_date else ""
    goal = state.context.get("goal", "placement-collect")

    # ── Bubble 1: greeting ──
    if goal == "placement-collect":
        date_part = f" op **{start_date}**" if start_date else " binnenkort"
        greeting = f"Hoi {first_name}, proficiat met je nieuwe opdracht! 🎉"
        if vacancy and company:
            greeting += f"\nJe start{date_part} als **{vacancy}** bij **{company}**."
        elif vacancy:
            greeting += f"\nJe start{date_part} als **{vacancy}**."
        else:
            greeting += f"\nJe start{date_part}."
    else:
        if company:
            greeting = f"Hoi {first_name}, leuk dat je interesse hebt in **{company}**! 👋"
        else:
            greeting = f"Hoi {first_name}, leuk dat je interesse hebt! 👋"
        greeting += (
            "\nWe kijken ernaar uit om je te matchen met de ideale job."
        )

    # ── Bubble 2: consent request ──
    if goal == "placement-collect":
        consent = (
            "Om je dossier voor je opstart correct te verwerken, hebben we nog enkele "
            "**persoonlijke gegevens** en **documenten** nodig in het kader van je tewerkstelling.\n\n"
            "✅ **Kan je bevestigen dat je akkoord bent om deze gegevens via WhatsApp te delen?**"
        )
    else:
        consent = (
            "Om je profiel in orde te brengen, hebben we nog enkele "
            "**persoonlijke gegevens** nodig.\n\n"
            "✅ **Kan je bevestigen dat je akkoord bent om deze gegevens via WhatsApp te delen?**"
        )

    return [greeting, consent]


async def enter_consent(agent: DocumentCollectionAgent, step: dict) -> list[str]:
    """Hardcoded intro + consent as two separate messages (no LLM call)."""
    return _build_intro_messages(agent.state)


async def handle_consent(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Process consent response."""
    state = agent.state

    if _CONSENT_YES.search(message):
        state.consent_given = True
        return await agent._advance_step()

    if _CONSENT_NO.search(message):
        state.consent_refusal_count += 1
        if state.consent_refusal_count >= 2:
            # Close conversation
            response = await agent._say(
                f"""De kandidaat heeft geen toestemming gegeven voor de verwerking van gegevens.
Leg vriendelijk uit dat je zonder toestemming het dossier niet kan verwerken.
Zeg dat een medewerker contact zal opnemen om dit persoonlijk te bespreken.
Max 2 zinnen. Begripvol, geen druk."""
            )
            state.current_step_index = len(state.conversation_flow)  # skip to end
            return response

        return await agent._say(
            f"""De kandidaat twijfelt over de toestemming.
Leg nogmaals kort uit waarom het nodig is (dossier in orde brengen) en vraag opnieuw.
Max 2 zinnen. Geen druk."""
        )

    # Ambiguous
    return await agent._say(
        f"""De kandidaat gaf een onduidelijk antwoord op de toestemmingsvraag.
Vraag opnieuw of de kandidaat akkoord gaat. Geef een kort voorbeeld: "ja" of "nee".
Max 1-2 zinnen."""
    )
