"""
Smart document & info collection planner.

Analyzes a vacancy + candidate profile to produce a collection plan
with an ordered conversation_flow that the collection agent follows step by step.

This agent ONLY generates the plan. A separate conversation agent handles
the actual WhatsApp interaction with the candidate.

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

# ─── System Instruction ────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = """\
Je bent de document collection planner van een Belgisch uitzendbureau.
Je stelt een gestructureerd verzamelplan op dat een gespreksagent stap voor stap volgt
om documenten en kandidaatgegevens te verzamelen bij de onboarding van een nieuwe kandidaat.

Je maakt ALLEEN het plan. Een andere agent voert het gesprek met de kandidaat.

HET PLAN = conversation_flow:
Je output is een geordende lijst van stappen (conversation_flow) die de gespreksagent sequentieel doorloopt.
Elke stap heeft een type, beschrijving, en optioneel items en voorwaarden (requires).

STAP TYPES:
1. "greeting_and_consent" — Altijd stap 1. Begroeting en toestemming vragen.
2. "identity_verification" — Identiteitsdocument verzamelen. Voeg toe als er GEEN identiteitsdocument op het dossier staat.
   De gespreksagent bepaalt zelf welk document (ID-kaart of paspoort) en of werkvergunning nodig is.
3. "address_collection" — Domicilie- en verblijfsadres verzamelen. Voeg toe als er GEEN adresgegevens op het dossier staan.
   De gespreksagent bepaalt zelf de adres-flow (domicilie → gelijk aan domicilie? → verblijfsadres).
4. "collect_attributes" — Persoonsgegevens opvragen. Bevat een lijst van items met slugs uit de attribuuttypes.
   Voeg ALLEEN attributen toe met collection_method="ask" die nog NIET op het dossier staan.
   Sluit deze slugs ALTIJD uit (worden door de agent afgehandeld): domicile_address, adres_gelijk_aan_domicilie, verblijfs_adres.
5. "medical_screening" — Medisch onderzoek inplannen. ALLEEN toevoegen als de werkpostfiche medical_check=yes aangeeft.
   Heeft altijd requires: ["identity_verification"]. Vermeld de risico's uit de werkpostfiche in details.
6. "contract_signing" — Contract ter ondertekening aanbieden.
   ALLEEN toevoegen als candidacy_stage="offer" EN er een regime is (full, flex, of day).
   Heeft altijd requires: ["identity_verification", "address_collection", "collect_attributes"].

REQUIRES (voorwaarden):
- Een stap met requires wordt pas uitgevoerd als alle genoemde stap-types zijn afgerond.
- Gebruik requires om afhankelijkheden vast te leggen (bv. geen contract zonder identiteitscontrole).

DOCUMENTEN & ATTRIBUTEN:
- Items gemarkeerd als "standaard" zijn ALTIJD nodig voor elke kandidaat. Voeg ze ALTIJD toe (tenzij al op dossier).
- Elk type kan een "Hint" veld hebben met extra context.
- Volg de hint EXACT:
  • "OWNER=AGENCY" → komt NIET in collect_documents of collect_attributes, alleen als apart stap-type als nodig
  • Andere hints beschrijven de conditie (bv. "alleen als de vacature rijden vereist")
- Types die NIET standaard zijn en GEEN hint hebben: analyseer de vacaturetekst om te bepalen of ze relevant zijn.
- Sla items over die de kandidaat AL HEEFT (zie "Bestaande gegevens").
- Attributen met collection_method="document" zijn auto-extracted door de agent — neem ze op in attributes_from_documents, NIET in collect_attributes.

WERKPOSTFICHE:
- Medisch onderzoek wordt NIET door jou beslist. De werkpostfiche bepaalt dit.
- Als werkpostfiche medical_check=yes: voeg "medical_screening" stap toe met requires: ["identity_verification"].
- Als werkpostfiche medical_risks bevat: vermeld de specifieke risico's in details.
- Als werkpostfiche GEEN medical_check bevat: voeg GEEN medical_screening stap toe.

CONTRACT:
- Bij candidacy_stage="offer" en regime "full" of "flex": voeg "contract_signing" stap toe.
- Bij candidacy_stage="offer" en regime "day": voeg "contract_signing" stap toe met description die vermeldt dat het dagcontract automatisch wordt gegenereerd.
- Als candidacy_stage NIET "offer" is, of er geen regime is: voeg GEEN contract_signing stap toe.

PRIORITEIT VELDEN (voor items in collect_attributes):
- "required": verplicht voor de opstart. Items gemarkeerd als [standaard] zijn ALTIJD priority "required".
- "recommended": aanbevolen maar niet blokkerend. Alleen voor items die NIET [standaard] zijn.

OPTIONELE DOCUMENTEN:
- Voeg GEEN "collect_documents" stap toe. Optionele documenten worden in deze fase niet verzameld.

GOAL (verplicht veld in de output):
- "placement-collect": als candidacy_stage="offer" — actieve plaatsing, documenten verzamelen en contract tekenen.
- "prequalification-collect": in alle andere gevallen — kandidaatprofiel opbouwen voor toekomstige matching.

URGENTIE & SAMENVATTING:
- Vermeld ALTIJD de startdatum en het aantal resterende dagen in de summary.
- Als er minder dan 5 werkdagen resten: benadruk de urgentie.
- Schrijf de summary vanuit eerste persoon ("Ik zal...").
- Tel het realistisch aantal stappen en items.
- Vermeld of dit een nieuwe kandidaat is of een bestaande kandidaat.
- Vermeld de candidacy_stage in de context.

Antwoord ALTIJD in valid JSON. Geen markdown codeblocks, geen uitleg buiten de JSON."""

# ─── Prompt Template ───────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """\
## Vacature: {title} ({company})
Locatie: {location}

### Vacaturetekst:
{description}

### Startdatum: {start_date} (nog {days_remaining} dagen)

### Plaatsing:
Regime: {regime_label}
Candidacy stage: {candidacy_stage}
{contract_note}

### Werkpostfiche:
{werkpostfiche_section}

### Beschikbare documenttypes:
{doc_types_list}

### Beschikbare attribuuttypes:
{attr_types_list}

### Kandidaat: {candidate_name}
Status: {candidate_status}

Documenten op dossier:
{existing_docs}

Attributen op dossier:
{existing_attrs}

### Opdracht:
Analyseer de vacature en het kandidaatprofiel. Maak een verzamelplan als JSON:

{{
  "goal": "placement-collect|prequalification-collect",
  "context": {{
    "vacancy": "{title}",
    "company": "{company}",
    "location": "{location}",
    "start_date": "{start_date}",
    "days_remaining": {days_remaining},
    "regime": "{regime_value}",
    "candidate": "{candidate_name}",
    "candidate_status": "new|existing",
    "candidacy_stage": "{candidacy_stage}",
    "candidacy_context": "Korte uitleg over de fase van de kandidaat"
  }},
  "identity_verification": {{
    "needed": true,
    "reason": "Waarom identiteitscontrole nodig is"
  }},
  "work_eligibility_verification": {{
    "needed": true,
    "reason": "Waarom arbeidstoegang gecontroleerd moet worden"
  }},
  "address_needed": {{
    "needed": true,
    "reason": "Waarom adresgegevens nodig zijn"
  }},
  "conversation_flow": [
    {{
      "step": 1,
      "type": "greeting_and_consent",
      "description": "Begroeting en toestemming vragen."
    }},
    {{
      "step": 2,
      "type": "identity_verification",
      "description": "Identiteitsdocument verzamelen en arbeidstoegang vaststellen.",
      "reason": "Waarom nodig"
    }},
    {{
      "step": 3,
      "type": "address_collection",
      "description": "Domicilie- en verblijfsadres verzamelen.",
      "reason": "Waarom nodig"
    }},
    {{
      "step": 4,
      "type": "collect_attributes",
      "description": "Persoonsgegevens opvragen.",
      "items": [
        {{"slug": "attr_slug", "method": "ask", "priority": "required|recommended", "reason": "Waarom nodig"}}
      ]
    }},
    {{
      "step": 5,
      "type": "medical_screening",
      "description": "Medisch onderzoek inplannen.",
      "requires": ["identity_verification"],
      "details": "Risico's uit werkpostfiche"
    }},
    {{
      "step": 6,
      "type": "contract_signing",
      "description": "Contract ter ondertekening aanbieden.",
      "requires": ["identity_verification", "address_collection", "collect_attributes"]
    }}
  ],
  "attributes_from_documents": [
    {{"slug": "attr_slug", "reason": "Waarom nodig"}}
  ],
  "already_known": {{
    "documents": ["slug1"],
    "attributes": ["slug1"]
  }},
  "summary": "Korte samenvatting (3-4 regels, Nederlands). Wie, wat, hoeveel stappen, urgentie."
}}

BELANGRIJK:
- Laat stappen WEG die niet van toepassing zijn (bv. geen medical_screening als werkpostfiche dat niet vereist).
- Voeg GEEN collect_documents stap toe — optionele documenten worden niet verzameld.
- Pas de step-nummers aan zodat ze opeenvolgend zijn.
- Items in collect_attributes bevatten ALLEEN slugs, geen velddefinities."""


# ─── Helpers ────────────────────────────────────────────────────────────────────

# Slugs handled by the agent — excluded from planner output
IDENTITY_DOC_SLUGS = {"id_card", "passport"}
WORK_PERMIT_SLUGS = {"prato_5", "prato_9", "prato_20", "prato_101", "prato_102"}
HARDCODED_DOC_SLUGS = IDENTITY_DOC_SLUGS | WORK_PERMIT_SLUGS
HARDCODED_ATTR_SLUGS = {"domicile_address", "domicilie_adres", "adres_gelijk_aan_domicilie", "verblijfs_adres"}


def get_ai_instructions(dt: dict) -> str | None:
    """Extract AI instructions from verification_config.additional_instructions."""
    vc = dt.get("verification_config")
    if vc and isinstance(vc, dict):
        return vc.get("additional_instructions")
    if vc and isinstance(vc, str):
        import json as _json
        try:
            return _json.loads(vc).get("additional_instructions")
        except (ValueError, AttributeError):
            pass
    return None


def build_doc_types_list(doc_types: list, only_default: bool = True) -> str:
    """Build document types list for the LLM prompt, excluding hardcoded types.

    Args:
        doc_types: List of document type dicts.
        only_default: If True, only include is_default (standaard) document types.
    """
    lines = []
    for dt in doc_types:
        if dt["slug"] in HARDCODED_DOC_SLUGS:
            continue
        if only_default and not dt.get("is_default"):
            continue
        parts = [dt['category']]
        line = f"- {dt['slug']}: {dt['name']} ({', '.join(parts)})"
        if dt.get("is_default"):
            line += " [standaard]"
        if dt.get("description"):
            line += f"\n  Beschrijving: {dt['description']}"
        if dt.get("ai_hint"):
            line += f"\n  Hint: {dt['ai_hint']}"
        else:
            instructions = get_ai_instructions(dt)
            if instructions:
                line += f"\n  Hint: {instructions}"
        lines.append(line)
    return "\n".join(lines) or "(geen)"


def build_attr_types_list(attr_types: list) -> str:
    """Build attribute types list for the LLM prompt, excluding hardcoded types."""
    lines = []
    for at in attr_types:
        if at["slug"] in HARDCODED_ATTR_SLUGS:
            continue
        parts = [at['data_type'], at['category']]
        if at.get("collected_by"):
            parts.append(f"collection_method={at['collected_by']}")
        line = f"- {at['slug']}: {at['name']} ({', '.join(parts)})"
        if at.get("is_default"):
            line += " [standaard]"
        if at.get("description"):
            line += f"\n  Beschrijving: {at['description']}"
        if at.get("ai_hint"):
            line += f"\n  Hint: {at['ai_hint']}"
        lines.append(line)
    return "\n".join(lines) or "(geen)"


def build_existing_docs(docs: list) -> str:
    if not docs:
        return "Geen documenten op dossier."
    lines = []
    for d in docs:
        status = d.get("status", "unknown")
        verified = "V" if d.get("verification_passed") else "O"
        lines.append(f"- {d['document_type_slug']}: {d['document_type_name']} [{status}] {verified}")
    return "\n".join(lines)


def build_existing_attrs(attrs: list) -> str:
    if not attrs:
        return "Geen attributen op dossier."
    lines = []
    for a in attrs:
        verified = "V" if a.get("verified") else "O"
        value = a.get("value", "")
        if len(value) > 50:
            value = value[:47] + "..."
        lines.append(f"- {a['type_slug']}: {a['type_name']} = \"{value}\" {verified}")
    return "\n".join(lines)


def build_werkpostfiche_section(params: list) -> str:
    """Build werkpostfiche context for the LLM prompt."""
    if not params:
        return "Geen werkpostfiche ingesteld. Voeg GEEN medisch onderzoek toe."

    lines = []
    medical_check = False
    medical_risks = []

    for p in params:
        key = p.get("param_key", "")
        value = p.get("param_value", "")

        if key == "medical_check" and value == "yes":
            medical_check = True
        elif key == "medical_risks":
            try:
                medical_risks = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass

    if medical_check:
        lines.append("- Medisch onderzoek: VEREIST (verplicht gezondheidstoezicht)")
        if medical_risks:
            risk_names = [r.get("name", "?") for r in medical_risks]
            lines.append(f"- Risico's: {', '.join(risk_names)}")
        else:
            lines.append("- Risico's: niet gespecificeerd")
    else:
        lines.append("- Medisch onderzoek: NIET vereist. Voeg GEEN medisch onderzoek toe.")

    return "\n".join(lines)


def parse_response(response_text: str) -> dict:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    plan = json.loads(text)

    # Basic validation
    if "conversation_flow" not in plan:
        raise ValueError("Plan missing 'conversation_flow' field")
    if not isinstance(plan["conversation_flow"], list):
        raise ValueError("'conversation_flow' must be a list")

    return plan


# ─── Core Plan Generation ──────────────────────────────────────────────────────

async def generate_collection_plan(
    pool,
    vacancy_id: uuid.UUID,
    candidate_id: uuid.UUID,
    workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
    start_date: date | None = None,
    regime: str | None = None,
    candidacy_stage: str = "offer",
    is_new_candidate: bool = True,
) -> dict:
    """
    Generate a smart collection plan for a candidate + vacancy.

    Returns a plan with conversation_flow — an ordered list of steps
    that the collection agent follows sequentially.

    Args:
        pool: asyncpg connection pool
        vacancy_id: The vacancy UUID
        candidate_id: The candidate UUID
        workspace_id: Workspace UUID (default: DEFAULT_WORKSPACE_ID)
        start_date: Expected start date (default: 7 days from now)
        regime: Employment regime (full, flex, day)
        candidacy_stage: Current candidacy stage (offer, qualified, etc.)
        is_new_candidate: Whether this is a new candidate with no prior dossier

    Returns:
        dict with conversation_flow, context, summary, etc.

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
    doc_type_rows, attr_type_rows, existing_attr_rows, existing_doc_rows, werkpostfiche_rows = await asyncio.gather(
        doc_type_repo.list_for_workspace(workspace_id, parents_only=True),
        attr_type_repo.list_for_workspace(workspace_id),
        attr_repo.list_for_candidate(candidate_id),
        candidate_repo.get_documents(candidate_id),
        pool.fetch(
            "SELECT param_key, param_value FROM ats.workstation_sheets WHERE vacancy_id = $1",
            vacancy_id,
        ),
    )

    doc_types = [dict(r) for r in doc_type_rows]
    attr_types = [dict(r) for r in attr_type_rows]
    existing_attrs = [dict(r) for r in existing_attr_rows]
    existing_docs = [dict(r) for r in existing_doc_rows]
    werkpostfiche_params = [dict(r) for r in werkpostfiche_rows]

    logger.info(f"Context: {len(doc_types)} doc types, {len(attr_types)} attr types, "
                f"candidate has {len(existing_docs)} docs + {len(existing_attrs)} attrs, "
                f"werkpostfiche has {len(werkpostfiche_params)} params")

    # Build regime context
    regime_labels = {"full": "Voltijds", "flex": "Flex", "day": "Dagcontract"}
    regime_label = regime_labels.get(regime, "Onbekend") if regime else "Niet opgegeven"

    if not regime or candidacy_stage != "offer":
        contract_note = (
            "GEEN CONTRACT: De kandidaat zit niet in de aanbod-fase of er is geen plaatsing. "
            "Verzamel enkel documenten om het dossier voor te bereiden. "
            "Voeg GEEN contract_signing stap toe."
        )
    elif regime == "day":
        contract_note = (
            "DAGCONTRACT: Het contract wordt automatisch gegenereerd en voor aanvang "
            "ter ondertekening verstuurd via Yousign. "
            "Voeg een contract_signing stap toe met requires: [\"identity_verification\", \"address_collection\", \"collect_attributes\"]."
        )
    else:
        contract_note = (
            "CONTRACT: Na het verzamelen van alle documenten wordt het contract gegenereerd "
            "en via Yousign ter ondertekening verstuurd. "
            "Voeg een contract_signing stap toe met requires: [\"identity_verification\", \"address_collection\", \"collect_attributes\"]."
        )

    # Build candidate status line
    if is_new_candidate:
        candidate_status = "Nieuwe kandidaat — geen bestaand dossier"
    elif existing_docs or existing_attrs:
        candidate_status = "Bestaande kandidaat — dossier gedeeltelijk ingevuld"
    else:
        candidate_status = "Bestaande kandidaat"

    # Build prompt
    prompt = PROMPT_TEMPLATE.format(
        title=vacancy["title"] or "Onbekend",
        company=vacancy["company"] or "Onbekend",
        location=vacancy["location"] or "Onbekend",
        description=vacancy["description"] or "(geen beschrijving)",
        start_date=start_date.isoformat(),
        days_remaining=days_remaining,
        candidate_name=candidate_name,
        candidate_status=candidate_status,
        regime_label=regime_label,
        regime_value=regime or "none",
        candidacy_stage=candidacy_stage,
        contract_note=contract_note,
        werkpostfiche_section=build_werkpostfiche_section(werkpostfiche_params),
        doc_types_list=build_doc_types_list(doc_types),
        attr_types_list=build_attr_types_list(attr_types),
        existing_docs=build_existing_docs(existing_docs),
        existing_attrs=build_existing_attrs(existing_attrs),
    )

    response = await generate(
        prompt=prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0,
        thinking_budget=2048,
    )

    plan = parse_response(response)

    # Count items in conversation_flow for logging
    flow = plan.get("conversation_flow", [])
    doc_items = sum(len(s.get("items", [])) for s in flow if s.get("type") == "collect_documents")
    attr_items = sum(len(s.get("items", [])) for s in flow if s.get("type") == "collect_attributes")

    logger.info(f"Collection plan generated: "
                f"{len(flow)} steps, {doc_items} docs, {attr_items} attrs")

    return plan


# ─── CLI ────────────────────────────────────────────────────────────────────────

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

    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        start_date = date.today() + timedelta(days=7)

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

    # Auto-fetch regime and candidacy stage from placement/candidacy
    placement = await pool.fetchrow(
        "SELECT regime, start_date FROM ats.placements WHERE candidate_id = $1 AND vacancy_id = $2",
        candidate_id, vacancy_id,
    )
    regime = placement["regime"] if placement else None
    if placement and placement["start_date"]:
        start_date = placement["start_date"]
    if regime:
        logger.info(f"Auto-detected regime from placement: {regime}")

    # Auto-fetch candidacy stage
    candidacy = await pool.fetchrow(
        "SELECT stage FROM ats.candidacies WHERE candidate_id = $1 AND vacancy_id = $2 ORDER BY created_at DESC LIMIT 1",
        candidate_id, vacancy_id,
    )
    candidacy_stage = candidacy["stage"] if candidacy else "unknown"
    logger.info(f"Candidacy stage: {candidacy_stage}")

    try:
        plan = await generate_collection_plan(
            pool=pool,
            vacancy_id=vacancy_id,
            candidate_id=candidate_id,
            workspace_id=workspace_id,
            start_date=start_date,
            regime=regime,
            candidacy_stage=candidacy_stage,
        )
    except ValueError as e:
        logger.error(str(e))
        await pool.close()
        return

    print(json.dumps(plan, indent=2, ensure_ascii=False))
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
