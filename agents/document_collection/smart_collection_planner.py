"""
Smart document & info collection planner.

Analyzes a vacancy + candidate profile to produce an efficient collection plan:
which documents and info to still collect, grouped into conversation steps,
with deadline awareness and contract signing as the final step.

Usage:
    python agents/document_collection/smart_collection_planner.py \
        --vacancy-id <uuid> --candidate-id <uuid>

    python agents/document_collection/smart_collection_planner.py \
        --vacancy-id <uuid> --candidate-phone +32... --start-date 2026-03-19
"""
import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

SYSTEM_INSTRUCTION = """Je bent een vriendelijke digitale assistent van een Belgisch uitzendbureau.
Je doel is om de kandidaat zo vlot en aangenaam mogelijk door de administratie te helpen.
Je bent er om het hen MAKKELIJK te maken, niet om druk te zetten.

KANAAL: Je communiceert met de kandidaat via WhatsApp. Dit betekent:
- Documenten worden verzameld als FOTO'S die de kandidaat met de smartphone maakt en stuurt via WhatsApp
- Gebruik taal als "stuur even een foto van...", "maak een foto van je ID-kaart en stuur die door"
- Houd berichten kort en WhatsApp-vriendelijk (niet te formeel, niet te lang)
- De kandidaat kan ook gewoon tekst typen voor gegevens zoals IBAN, adres, etc.

Toon & stijl:
- Warm, informeel maar professioneel. Denk aan een behulpzame collega, niet een ambtenaar.
- "Ik help je graag om alles in orde te krijgen zodat je vlot kunt starten!"
- Vermijd woorden als "verplicht", "dringend", "moeten". Gebruik liever "nodig hebben", "even regelen", "in orde maken".
- Deadline mag vermeld worden als context ("je start over X dagen, dus laten we dat even in orde brengen"), maar nooit als dreiging.

CONVERSATIESTIJL — ÉÉN ONDERWERP PER BERICHT:
Dit is een conversational AI agent — GEEN formulier. De agent voert een natuurlijk gesprek via WhatsApp.
Elke conversation_group = 1 WhatsApp-bericht = 1 onderwerp/vraag.
De agent wacht op het antwoord van de kandidaat voordat het volgende onderwerp wordt aangesneden.

Vaste volgorde:
1. INTRO — Warm welkomstbericht: feliciteer, vermeld functie + startdatum, leg uit wat je gaat helpen regelen.
   Eindig met: "Als iets niet duidelijk is, help ik je graag verder of schakel ik je door naar de recruiter."
   Dit bericht stelt GEEN vragen — het is puur een warm onthaal.
2. ID-SCAN — Altijd de eerste vraag na het intro. Vraag om een foto van voor- en achterkant van de ID-kaart.
   Eén simpele vraag, niet gecombineerd met andere items.
3. Daarna volgen de andere items, elk als apart bericht:
   - Adresgegevens (straat + postcode + woonplaats mogen samen — het is 1 onderwerp)
   - IBAN apart — leg kort uit waarom je dit vraagt (loonuitbetaling)
   - Noodcontact apart — leg kort uit waarom (veiligheid op het werk)
   - Afspraken (medisch onderzoek) apart met tijdsloten
   - Aanbevolen documenten (diploma, CV) apart
   - Vervoer / overige vragen apart
4. LAATSTE STAP — Contract ondertekening via Yousign

BELANGRIJKE REGELS:
1. Sla items over die de kandidaat AL HEEFT (zie "Bestaande gegevens")
2. Begrijp de relatie tussen info en documenten:
   - nationality/national_register_nr → vereist identiteitsdocument (ID-kaart of paspoort)
   - IBAN → kan als tekst gevraagd worden, bankdocument is optioneel
   - address_city/address_postal_code → kan verbaal, geen document nodig
   - work_eligibility → kan werkvergunning vereisen bij niet-EU
3. Houd rekening met de deadline — prioriteer kritieke items eerst, maar altijd in een behulpzame toon
4. Elk documenttype heeft een "instructie" veld. Als dit gevuld is, volg die instructie EXACT.
   Let vooral op "OWNER=AGENCY" — deze items worden NIET in documents_to_collect gezet!
   Ze horen UITSLUITEND in agent_managed_tasks. De kandidaat hoeft hier niks voor aan te leveren.
   Alleen documenten die de kandidaat zelf moet sturen komen in documents_to_collect (owner=candidate).
5. Items die de agent zelf regelt (OWNER=AGENCY) komen ALLEEN in agent_managed_tasks.
   De kandidaat wordt WEL geïnformeerd als ze ergens naartoe moeten (bv. afspraak arbeidsgeneesheer).
   Voor afspraken: stel 3 tijdsloten voor aan de KANDIDAAT via WhatsApp zodat zij een moment kunnen kiezen.
   Deze afspraak-keuze komt als conversation_group (want de kandidaat moet een slot kiezen).
6. De recruiter krijgt een STATUS UPDATE van jou, zoals een junior recruiter zijn manager informeert:
   "Hey, ik heb de documenten opgevraagd bij [naam], ik plan de medische schifting in, enz."
   NIET een takenlijst — jij doet het werk, de recruiter hoeft alleen op de hoogte te zijn.
7. Alle message_hints moeten WhatsApp-geschikt zijn: kort, informeel, 1 onderwerp per bericht
8. Antwoord ALTIJD in valid JSON"""

PROMPT_TEMPLATE = """## Vacature: {title} ({company})
### Locatie: {location}

### Vacaturetekst:
{description}

### Deadline:
Startdatum: {start_date} (nog {days_remaining} dagen)

### Beschikbare documenttypes (ouders):
{doc_types_list}

### Beschikbare attribuuttypes:
{attr_types_list}

### Bestaande gegevens van de kandidaat:
#### Documenten op dossier:
{existing_docs}

#### Attributen op dossier:
{existing_attrs}

### Kandidaat info:
Naam: {candidate_name}

### Opdracht:
Analyseer de vacature en maak een verzamelplan. BELANGRIJK: elke conversation_group is 1 WhatsApp-bericht over 1 onderwerp.
De agent wacht op het antwoord voordat het volgende bericht gestuurd wordt. Dit is een GESPREK, geen formulier.

Geef je antwoord als JSON:
{{
  "intro_message": "Warm welkomstbericht: feliciteer, vermeld functie + startdatum, leg uit dat je helpt met administratie. STEL GEEN VRAGEN in dit bericht — het is puur een warm onthaal.",
  "documents_to_collect": [
    {{"slug": "doc_slug", "name": "Naam", "reason": "Waarom nodig", "priority": "required|recommended"}}
  ],
  "attributes_to_collect": [
    {{"slug": "attr_slug", "name": "Naam", "reason": "Waarom nodig", "collection_method": "ask|document"}}
  ],
  "conversation_steps": [
    {{
      "step": 1,
      "topic": "Kort onderwerp (bv. 'ID-scan', 'Adresgegevens', 'IBAN')",
      "items": ["slug1"],
      "message": "Het exacte WhatsApp-bericht. Kort, warm, 1 onderwerp. De agent wacht op antwoord na dit bericht.",
      "proposed_slots": ["tijdslot1", "tijdslot2"]
    }}
  ],
  "agent_managed_tasks": [
    {{
      "slug": "doc_slug",
      "action": "Wat de agent zelf regelt (bv. medisch onderzoek inplannen)",
      "candidate_message": "Wat je de kandidaat hierover vertelt via WhatsApp",
      "proposed_slots": ["2026-03-14 09:00", "2026-03-14 14:00", "2026-03-17 10:00"]
    }}
  ],
  "recruiter_notification": "Status update van de agent naar het team (Teams-bericht). Toon als een junior recruiter die zijn manager informeert. NIET een takenlijst.",
  "already_complete": ["slug1", "slug2"],
  "final_step": {{
    "action": "contract_signing",
    "message": "Warm bericht wanneer alles compleet is en contract klaarstaat via Yousign"
  }},
  "summary": "Korte samenvatting voor de admin (3-4 regels, Nederlands). Wat gaat de agent doen? Hoeveel documenten/gegevens? Welke prioriteiten? Wordt er een afspraak ingepland? Eindigt met contract of dossier-voorbereiding? Dit wordt getoond in de UI zodat de recruiter in één oogopslag ziet wat het plan is.",
  "deadline_note": "Samenvatting (behulpzame toon)"
}}

Richtlijnen:
- Identiteitsdocumenten zijn bijna altijd nodig voor uitzendarbeid
- Werkvergunning bij niet-EU kandidaten
- Rijbewijs alleen als de functie rijden vereist
- VCA bij bouw/industrie/logistiek
- Wees selectief: niet elk document/attribuut is voor elke vacature nodig

CONVERSATIE-FLOW (conversation_steps):
- Elke stap = 1 WhatsApp-bericht = 1 onderwerp. De agent WACHT op antwoord voor het volgende bericht.
- Stap 1 is ALTIJD de ID-scan (foto voor- en achterkant). Nooit gecombineerd met andere vragen.
- Adresgegevens (straat, postcode, woonplaats) mogen samen in 1 bericht — het is 1 onderwerp.
- IBAN is een apart bericht — leg kort uit waarom (loonuitbetaling).
- Noodcontact is een apart bericht — leg kort uit waarom (veiligheid op het werk).
- Afspraken (medisch onderzoek) zijn een apart bericht met tijdsloten.
- Aanbevolen documenten (diploma, CV) mogen samen in 1 bericht.
- Elk bericht is kort, warm en stelt maximaal 1 vraag. Denk WhatsApp, niet e-mail.

- agent_managed_tasks bevat wat de agent ZELF doet achter de schermen (boeken, invullen, opvolgen)
  De kandidaat wordt enkel geïnformeerd als ze ergens naartoe moeten (bv. afspraak arbeidsgeneesheer)
- recruiter_notification: schrijf een INFORMEEL status update bericht (voor Teams) alsof je een collega bijpraat
  Toon: "Hey team, voor [naam] ([functie], start [datum]): ik heb de documenten opgevraagd, de medische schifting staat ingepland op [datum], [status van andere items]."
  NIET: "□ doe dit □ doe dat" — de agent doet het werk, de recruiter wordt alleen geïnformeerd
- Eindig altijd met contract ondertekening via Yousign (final_step)
- Alle berichten in een warme, behulpzame toon — je bent er om het makkelijk te maken!
- intro_message is het EERSTE bericht (geen vragen!) dat de kandidaat ontvangt via WhatsApp. Maak het persoonlijk en positief!
  Voorbeeld: "Hey {candidate_name}! 🎉 Goed nieuws — over {days_remaining} dagen start je als {title} bij {company}! Om alles vlot te laten verlopen, help ik je even met de administratie. Ik stel je een paar vragen en vraag enkele documenten op. Heel simpel: je kunt gewoon foto's sturen via WhatsApp. Als iets niet duidelijk is, help ik je graag verder of schakel ik je door naar de recruiter."
- Alle berichten zijn WhatsApp-berichten: kort, informeel, 1 onderwerp per bericht"""


def get_ai_instructions(dt: dict) -> str | None:
    """Extract AI instructions from verification_config.additional_instructions."""
    vc = dt.get("verification_config")
    if vc and isinstance(vc, dict):
        return vc.get("additional_instructions")
    # verification_config is stored as jsonb, asyncpg may return it as a string
    if vc and isinstance(vc, str):
        import json as _json
        try:
            return _json.loads(vc).get("additional_instructions")
        except (ValueError, AttributeError):
            pass
    return None


def build_doc_types_list(doc_types: list) -> str:
    lines = []
    for dt in doc_types:
        line = f"- {dt['slug']}: {dt['name']} ({dt['category']})"
        instructions = get_ai_instructions(dt)
        if instructions:
            line += f"\n  Instructie: {instructions}"
        lines.append(line)
    return "\n".join(lines) or "(geen)"


def build_attr_types_list(attr_types: list) -> str:
    lines = []
    for at in attr_types:
        lines.append(f"- {at['slug']}: {at['name']} ({at['data_type']}, {at['category']})")
    return "\n".join(lines) or "(geen)"


def build_existing_docs(docs: list) -> str:
    if not docs:
        return "Geen documenten op dossier."
    lines = []
    for d in docs:
        status = d.get("status", "unknown")
        verified = "✓" if d.get("verification_passed") else "○"
        lines.append(f"- {d['document_type_slug']}: {d['document_type_name']} [{status}] {verified}")
    return "\n".join(lines)


def build_existing_attrs(attrs: list) -> str:
    if not attrs:
        return "Geen attributen op dossier."
    lines = []
    for a in attrs:
        verified = "✓" if a.get("verified") else "○"
        value = a.get("value", "")
        # Truncate long values
        if len(value) > 50:
            value = value[:47] + "..."
        lines.append(f"- {a['type_slug']}: {a['type_name']} = \"{value}\" {verified}")
    return "\n".join(lines)


def parse_response(response_text: str) -> dict:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


def generate_markdown(plan: dict, vacancy, candidate_name: str, start_date: date, days_remaining: int) -> str:
    """Generate a structured markdown report from the collection plan."""
    lines = [
        f"# Verzamelplan: {vacancy['title']} ({vacancy['company']})",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Kandidaat** | {candidate_name} |",
        f"| **Vacature** | {vacancy['title']} |",
        f"| **Bedrijf** | {vacancy['company']} |",
        f"| **Locatie** | {vacancy['location']} |",
        f"| **Startdatum** | {start_date} (nog {days_remaining} dagen) |",
        f"| **Kanaal** | WhatsApp |",
        f"",
    ]

    # Intro message
    intro = plan.get("intro_message")
    if intro:
        lines.append("## Welkomstbericht (WhatsApp)")
        lines.append(f"> {intro}")
        lines.append("")

    # Already complete
    complete = plan.get("already_complete", [])
    if complete:
        lines.append("## Al compleet")
        for item in complete:
            lines.append(f"- [x] {item}")
        lines.append("")

    # Documents from candidate
    docs = plan.get("documents_to_collect", [])
    if docs:
        lines.append("## Documenten van kandidaat")
        for d in docs:
            priority = "**NODIG**" if d.get("priority") == "required" else "aanbevolen"
            lines.append(f"- [ ] **{d.get('name', '?')}** (`{d.get('slug', '?')}`) — {priority}")
            lines.append(f"  - {d.get('reason', '')}")
        lines.append("")

    # Attributes to collect
    attrs = plan.get("attributes_to_collect", [])
    if attrs:
        lines.append("## Informatie te verzamelen")
        for a in attrs:
            method = "💬 vragen" if a.get("collection_method") == "ask" else "📄 uit document"
            lines.append(f"- [ ] **{a.get('name', '?')}** (`{a.get('slug', '?')}`) — {method}")
            lines.append(f"  - {a.get('reason', '')}")
        lines.append("")

    # Conversation flow
    steps = plan.get("conversation_steps", [])
    if steps:
        lines.append("## Gesprek (WhatsApp)")
        lines.append("*Elk bericht = 1 onderwerp. De agent wacht op antwoord voor het volgende bericht.*")
        lines.append("")
        for s in steps:
            step_nr = s.get("step", "?")
            topic = s.get("topic", "?")
            items = s.get("items", [])
            lines.append(f"### Bericht {step_nr}: {topic}")
            if items:
                lines.append(f"**Items:** {', '.join(items)}")
                lines.append("")
            lines.append(f"> {s.get('message', '')}")
            if s.get("proposed_slots"):
                lines.append(f"")
                lines.append(f"📅 **Kies een moment:** {', '.join(s['proposed_slots'])}")
            lines.append("")

    # Agent managed tasks
    agent_tasks = plan.get("agent_managed_tasks", [])
    if agent_tasks:
        lines.append("## Agent regelt (achter de schermen)")
        for a in agent_tasks:
            lines.append(f"- [ ] **{a.get('slug', '?')}** — {a.get('action', '')}")
            if a.get("proposed_slots"):
                lines.append(f"  - 📅 Tijdsloten: {', '.join(a['proposed_slots'])}")
            if a.get("candidate_message"):
                lines.append(f"  - 💬 Aan kandidaat: *\"{a['candidate_message']}\"*")
        lines.append("")

    # Recruiter notification
    recruiter_msg = plan.get("recruiter_notification")
    if recruiter_msg:
        lines.append("## Status update voor recruiter (Teams)")
        lines.append(f"> {recruiter_msg}")
        lines.append("")

    # Final step
    final = plan.get("final_step")
    if final:
        lines.append("## Laatste stap: Contract ondertekening")
        lines.append(f"> {final.get('message', '') or final.get('message_hint', '')}")
        lines.append("")

    # Deadline & reasoning
    deadline_note = plan.get("deadline_note")
    if deadline_note:
        lines.append(f"---")
        lines.append(f"⏰ **{deadline_note}**")
        lines.append("")

    summary = plan.get("summary")
    if summary:
        lines.append(f"## Samenvatting")
        lines.append(f"{summary}")

    return "\n".join(lines)


async def generate_collection_plan(
    pool,
    vacancy_id: uuid.UUID,
    candidate_id: uuid.UUID,
    workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
    start_date: date | None = None,
) -> dict:
    """
    Generate a smart collection plan for a candidate + vacancy.

    This is the core planner logic, callable from services and CLI.

    Args:
        pool: asyncpg connection pool
        vacancy_id: The vacancy UUID
        candidate_id: The candidate UUID
        workspace_id: Workspace UUID (default: DEFAULT_WORKSPACE_ID)
        start_date: Expected start date (default: 7 days from now)

    Returns:
        dict with the full collection plan JSON (intro_message, documents_to_collect,
        conversation_steps, summary, etc.)

    Raises:
        ValueError: If candidate or vacancy not found
    """
    from src.repositories.candidate_repo import CandidateRepository
    from src.repositories.candidate_attribute_repo import CandidateAttributeRepository
    from src.repositories.candidate_attribute_type_repo import CandidateAttributeTypeRepository
    from src.repositories.document_type_repo import DocumentTypeRepository
    from src.utils.llm import generate

    if start_date is None:
        start_date = date.today() + timedelta(days=7)
    days_remaining = (start_date - date.today()).days

    candidate_repo = CandidateRepository(pool)
    attr_repo = CandidateAttributeRepository(pool)
    attr_type_repo = CandidateAttributeTypeRepository(pool)
    doc_type_repo = DocumentTypeRepository(pool)

    # Resolve candidate
    candidate = await candidate_repo.get_by_id(candidate_id)
    if not candidate:
        raise ValueError(f"Candidate not found: {candidate_id}")

    candidate_name = candidate.get("full_name") or "Onbekend"

    # Fetch vacancy
    vacancy = await pool.fetchrow(
        "SELECT id, title, company, location, description FROM ats.vacancies WHERE id = $1",
        vacancy_id,
    )
    if not vacancy:
        raise ValueError(f"Vacancy not found: {vacancy_id}")

    logger.info(f"Generating collection plan: {candidate_name} × {vacancy['title']} ({vacancy['company']})")

    # Fetch all context in parallel
    doc_type_rows, attr_type_rows, existing_attr_rows, existing_doc_rows = await asyncio.gather(
        doc_type_repo.list_for_workspace(workspace_id, parents_only=True),
        attr_type_repo.list_for_workspace(workspace_id),
        attr_repo.list_for_candidate(candidate_id),
        candidate_repo.get_documents(candidate_id),
    )

    doc_types = [dict(r) for r in doc_type_rows]
    attr_types = [dict(r) for r in attr_type_rows]
    existing_attrs = [dict(r) for r in existing_attr_rows]
    existing_docs = [dict(r) for r in existing_doc_rows]

    logger.info(f"Context: {len(doc_types)} doc types, {len(attr_types)} attr types, "
                f"candidate has {len(existing_docs)} docs + {len(existing_attrs)} attrs")

    # Build prompt
    prompt = PROMPT_TEMPLATE.format(
        title=vacancy["title"] or "Onbekend",
        company=vacancy["company"] or "Onbekend",
        location=vacancy["location"] or "Onbekend",
        description=vacancy["description"] or "(geen beschrijving)",
        start_date=start_date.isoformat(),
        days_remaining=days_remaining,
        candidate_name=candidate_name,
        doc_types_list=build_doc_types_list(doc_types),
        attr_types_list=build_attr_types_list(attr_types),
        existing_docs=build_existing_docs(existing_docs),
        existing_attrs=build_existing_attrs(existing_attrs),
    )

    response = await generate(
        prompt=prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
    )

    plan = parse_response(response)

    logger.info(f"Collection plan generated: {len(plan.get('conversation_steps', []))} steps, "
                f"{len(plan.get('documents_to_collect', []))} docs to collect")

    return plan


async def main():
    parser = argparse.ArgumentParser(description="Smart document & info collection planner")
    parser.add_argument("--vacancy-id", required=True, type=str)
    parser.add_argument("--candidate-id", type=str, default=None)
    parser.add_argument("--candidate-phone", type=str, default=None)
    parser.add_argument("--start-date", type=str, default=None, help="YYYY-MM-DD, default: 7 days from now")
    parser.add_argument("--workspace-id", type=str, default=str(DEFAULT_WORKSPACE_ID))
    args = parser.parse_args()

    if not args.candidate_id and not args.candidate_phone:
        parser.error("Provide either --candidate-id or --candidate-phone")

    from dotenv import load_dotenv
    load_dotenv()

    from src.database import get_db_pool
    from src.repositories.candidate_repo import CandidateRepository

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    workspace_id = uuid.UUID(args.workspace_id)
    vacancy_id = uuid.UUID(args.vacancy_id)

    # Parse start date
    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        start_date = date.today() + timedelta(days=7)
    days_remaining = (start_date - date.today()).days

    pool = await get_db_pool()

    # Resolve candidate by phone if needed
    if args.candidate_id:
        candidate_id = uuid.UUID(args.candidate_id)
    else:
        candidate_repo = CandidateRepository(pool)
        candidate = await candidate_repo.get_by_phone(args.candidate_phone)
        if not candidate:
            logger.error("Kandidaat niet gevonden.")
            await pool.close()
            return
        candidate_id = candidate["id"]

    try:
        plan = await generate_collection_plan(
            pool=pool,
            vacancy_id=vacancy_id,
            candidate_id=candidate_id,
            workspace_id=workspace_id,
            start_date=start_date,
        )
    except ValueError as e:
        logger.error(str(e))
        await pool.close()
        return

    # Fetch vacancy + candidate for display
    vacancy = await pool.fetchrow(
        "SELECT id, title, company, location, description FROM ats.vacancies WHERE id = $1",
        vacancy_id,
    )
    candidate_repo = CandidateRepository(pool)
    candidate = await candidate_repo.get_by_id(candidate_id)
    candidate_name = candidate.get("full_name") or "Onbekend"

    # Print the plan
    logger.info(f"{'━' * 70}")
    logger.info(f"VERZAMELPLAN — {vacancy['title']} ({vacancy['company']})")
    logger.info(f"Kandidaat: {candidate_name}")
    logger.info(f"Deadline: {start_date} (nog {days_remaining} dagen)")
    logger.info(f"{'━' * 70}\n")

    # Intro message
    intro = plan.get("intro_message")
    if intro:
        logger.info(f"📱 Welkomstbericht (WhatsApp):")
        logger.info(f"   \"{intro}\"")
        logger.info("")

    # Already complete
    complete = plan.get("already_complete", [])
    if complete:
        logger.info(f"✅ Al compleet ({len(complete)}):")
        for item in complete:
            logger.info(f"   ✓ {item}")
        logger.info("")

    # Documents to collect
    docs = plan.get("documents_to_collect", [])
    if docs:
        logger.info(f"📄 Documenten van kandidaat ({len(docs)}):")
        for d in docs:
            priority = "⚠️" if d.get("priority") == "required" else "○"
            logger.info(f"   {priority} {d.get('slug', '?')}: {d.get('name', '?')}")
            logger.info(f"     {d.get('reason', '-')}")
        logger.info("")

    # Attributes to collect
    attrs = plan.get("attributes_to_collect", [])
    if attrs:
        logger.info(f"📋 Informatie te verzamelen ({len(attrs)}):")
        for a in attrs:
            method = "💬" if a.get("collection_method") == "ask" else "📄"
            logger.info(f"   {method} {a.get('slug', '?')}: {a.get('name', '?')}")
            logger.info(f"     Reden: {a.get('reason', '-')}")
        logger.info("")

    # Conversation steps
    steps = plan.get("conversation_steps", [])
    if steps:
        logger.info(f"💬 Gesprek ({len(steps)} berichten):")
        for s in steps:
            step_nr = s.get("step", "?")
            topic = s.get("topic", "?")
            items = s.get("items", [])
            logger.info(f"\n   Bericht {step_nr}: {topic}")
            if items:
                logger.info(f"   Items: {', '.join(items)}")
            logger.info(f"   💬 \"{s.get('message', '')}\"")
            if s.get("proposed_slots"):
                logger.info(f"   📅 Tijdsloten: {', '.join(s['proposed_slots'])}")
        logger.info("")

    # Agent managed tasks
    agent_tasks = plan.get("agent_managed_tasks", [])
    if agent_tasks:
        logger.info(f"🤖 Agent regelt achter de schermen ({len(agent_tasks)}):")
        for a in agent_tasks:
            logger.info(f"   → {a.get('slug', '?')}: {a.get('action', '?')}")
            if a.get("proposed_slots"):
                logger.info(f"     📅 Tijdsloten: {', '.join(a['proposed_slots'])}")
            if a.get("candidate_message"):
                logger.info(f"     💬 Aan kandidaat: \"{a['candidate_message']}\"")
        logger.info("")

    # Recruiter notification
    recruiter_msg = plan.get("recruiter_notification")
    if recruiter_msg:
        logger.info(f"📨 Status update voor recruiter (Teams):")
        logger.info(f"   \"{recruiter_msg}\"")
        logger.info("")

    # Final step
    final = plan.get("final_step")
    if final:
        logger.info(f"🎉 Laatste stap: {final.get('action', 'contract_signing')}")
        logger.info(f"   💬 \"{final.get('message', '') or final.get('message_hint', '')}\"")
        logger.info("")

    # Deadline note
    deadline_note = plan.get("deadline_note")
    if deadline_note:
        logger.info(f"⏰ {deadline_note}")
        logger.info("")

    # Summary
    summary = plan.get("summary")
    if summary:
        logger.info(f"📋 Samenvatting (voor UI):")
        logger.info(f"   {summary}")

    logger.info(f"\n{'━' * 70}")

    # Export to markdown
    md = generate_markdown(plan, vacancy, candidate_name, start_date, days_remaining)
    plans_dir = Path(__file__).parent / "plans"
    plans_dir.mkdir(exist_ok=True)

    safe_title = (vacancy["title"] or "vacancy").replace(" ", "_").replace("/", "-")[:30]
    safe_name = (candidate_name).replace(" ", "_")[:20]
    md_filename = f"{safe_title}_{safe_name}_{date.today().isoformat()}.md"
    md_path = plans_dir / md_filename

    md_path.write_text(md, encoding="utf-8")
    logger.info(f"\n📝 Plan opgeslagen: {md_path}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
