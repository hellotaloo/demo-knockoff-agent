"""
Handler for medical_screening and contract_signing steps.

Medical screening: ask candidate for availability, schedule task.
Contract signing: create Yousign signature request, present signing link.
"""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING

from agents.document_collection.collection.rules import schedule_task

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import DocumentCollectionAgent

logger = logging.getLogger(__name__)

_DAY_NAMES_NL = ["ma", "di", "woe", "do", "vr", "za", "zo"]


def _format_date_eu(iso_date: str) -> str:
    """Format ISO date (2026-03-23) to European style: ma 23/03/26."""
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        day_name = _DAY_NAMES_NL[dt.weekday()]
        return f"{day_name} {dt.strftime('%d/%m/%y')}"
    except (ValueError, TypeError):
        return iso_date


def _make_dummy_contract_pdf(candidate_name: str, vacancy_title: str, start_date: str, company_name: str = "") -> bytes:
    """Generate a minimal valid PDF with dummy contract text — no external libs needed."""
    employer = company_name or "de werkgever"
    content = textwrap.dedent(f"""\
        ARBEIDSOVEREENKOMST

        Tussen {employer} en {candidate_name}
        wordt de volgende arbeidsovereenkomst gesloten.

        Functie   : {vacancy_title}
        Startdatum: {start_date or 'Nader te bepalen'}
        Loon      : Volgens barema

        De kandidaat verklaart kennis genomen te hebben van het
        arbeidsreglement en gaat akkoord met de bepalingen van
        deze overeenkomst.

        Handtekening kandidaat:
    """)

    lines = content.split("\n")
    stream_lines = ["BT", "/F1 12 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "")
        stream_lines.append(f"({safe}) Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines)
    stream_bytes = stream.encode("latin-1", errors="replace")

    objects = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    objects[3] = (
        b"<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 595 842] "
        b"/Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects[4] = b"<< /Length " + str(len(stream_bytes)).encode() + b" >>\nstream\n" + stream_bytes + b"\nendstream"
    objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    body = b"%PDF-1.4\n"
    offsets = {}
    for obj_id, obj_data in objects.items():
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n".encode() + obj_data + b"\nendobj\n"

    xref_offset = len(body)
    body += b"xref\n"
    body += f"0 {len(objects) + 1}\n".encode()
    body += b"0000000000 65535 f \n"
    for obj_id in range(1, len(objects) + 1):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()

    body += (
        b"trailer\n"
        b"<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF"
    )
    return body


async def _create_contract_signing(agent: DocumentCollectionAgent) -> str | None:
    """Create a Yousign signature request and return the signing URL."""
    from src.services.yousign_service import YousignService

    state = agent.state
    candidate_name = state.candidate_name
    candidate_phone = state.context.get("candidate_phone", "")

    if not candidate_phone:
        logger.warning("[CONTRACT] No candidate_phone in state context, skipping Yousign")
        return None

    # Split name into first/last
    parts = candidate_name.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else parts[0]

    # Generate dummy contract PDF
    pdf_bytes = _make_dummy_contract_pdf(
        candidate_name=candidate_name,
        vacancy_title=state.vacancy_title,
        start_date=state.start_date,
        company_name=state.company_name,
    )

    service = YousignService()
    result = await service.create_signature_request(
        pdf_bytes=pdf_bytes,
        pdf_filename="arbeidsovereenkomst.pdf",
        signer_first_name=first_name,
        signer_last_name=last_name,
        signer_email=f"candidate+{state.collection_id[:8]}@taloo.be",
        signer_phone=candidate_phone,
        request_name=f"Contract {candidate_name} — {state.vacancy_title}",
    )

    if result.success:
        # Store IDs in state for webhook handling later
        state.context["yousign_request_id"] = result.request_id
        state.context["yousign_signer_id"] = result.signer_id
        state.context["yousign_signing_url"] = result.signing_url
        logger.info(f"[CONTRACT] Signature request created: {result.request_id}")
        return result.signing_url

    logger.error(f"[CONTRACT] Failed to create signature request: {result.error}")
    return None


async def enter_task(agent: DocumentCollectionAgent, step: dict) -> str:
    """Generate the opening message for a task step."""
    step_type = step.get("type", "")

    if step_type == "contract_signing":
        start_date_text = f" voor een start op **{_format_date_eu(agent.state.start_date)}**" if agent.state.start_date else ""

        # Create Yousign signature request
        signing_url = await _create_contract_signing(agent)

        if signing_url:
            msg = f"Goed nieuws! Je **contract**{start_date_text} staat klaar om digitaal te ondertekenen. 📝\n\n👉 [Onderteken hier]({signing_url})"
            agent.state.last_agent_message = msg
            return msg

        # Fallback if Yousign fails
        msg = f"Je **contract** wordt klaargemaakt{start_date_text}! 📝 Je ontvangt binnenkort een link om het digitaal te ondertekenen."
        agent.state.last_agent_message = msg
        return msg

    # Medical screening or other interactive task
    description = step.get("description", "")
    risks_text = ""
    if step.get("risks"):
        risks_text = f"\nRisico's: {', '.join(step['risks'])}"

    return await agent._say(
        f"""Informeer {agent.state.candidate_name} over het **medisch onderzoek** dat ingepland moet worden.
{f'Context: {description}' if description else ''}{risks_text}

Vraag wanneer de kandidaat beschikbaar is.
Voorbeeld: "Wanneer zou je beschikbaar zijn voor je **medisch onderzoek**? Bv. 'volgende week maandag en dinsdag, tussen 8u en 17u' 📋"
Max 2-3 zinnen. Vriendelijk."""
    )


async def handle_task(agent: DocumentCollectionAgent, message: str, has_image: bool, step: dict) -> str:
    """Process task-related messages."""
    step_type = step.get("type", "")

    if step_type == "contract_signing":
        return await _handle_contract(agent, message, step)

    return await _handle_interactive_task(agent, message, step)


async def _handle_contract(agent: DocumentCollectionAgent, message: str, step: dict) -> str:
    state = agent.state

    if "--signed--" in message:
        start_info = f" Je start op **{_format_date_eu(state.start_date)}**." if state.start_date else ""
        recruiter_info = ""
        if state.recruiter_name:
            recruiter_info = f"\nNoem **{state.recruiter_name}** als contactpersoon"
            if state.recruiter_email:
                recruiter_info += f" ({state.recruiter_email})"
            recruiter_info += "."

        response = await agent._say(
            f"""Het **contract** is ondertekend! 🎉
Feliciteer {state.candidate_name} hartelijk.{start_info}{recruiter_info}
Bevestig dat er verder contact volgt voor de praktische details.
Max 3 zinnen. Warm en enthousiast."""
        )
        return response + "\n\n" + await agent._advance_step()

    # Not signed yet — remind with link if available
    signing_url = state.context.get("yousign_signing_url", "")
    if signing_url:
        msg = f"Je **contract** is nog niet ondertekend. [Onderteken hier]({signing_url})"
    else:
        msg = "Je **contract** is nog niet ondertekend. Je ontvangt binnenkort een nieuwe link."
    agent.state.last_agent_message = msg
    return msg


async def _handle_interactive_task(agent: DocumentCollectionAgent, message: str, step: dict) -> str:
    """Handle medical screening or other interactive tasks."""
    state = agent.state
    task_slug = step.get("type", "task")

    # Collect availability and schedule
    await schedule_task(
        task_slug=task_slug,
        task_name=step.get("description", task_slug),
        availability=message,
        collection_id=state.collection_id,
    )

    response = await agent._say(
        f"""De beschikbaarheid voor het **medisch onderzoek** is genoteerd ✅
Bevestig dat je de beschikbaarheid hebt doorgegeven en dat de kandidaat hierover nog bericht krijgt.
Max 1-2 zinnen."""
    )

    return response + "\n\n" + await agent._advance_step()
