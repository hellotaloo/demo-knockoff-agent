"""
Prompt templates for the Document Collection Conductor Agent.

All LLM prompt builders are centralised here. The agent module imports
them as needed — no prompt construction lives in agent.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.document_collection.collection.agent import CollectionState

MAX_RETRIES_PER_DOC = 3  # duplicated from agent.py — kept in sync via import

SYSTEM_INSTRUCTION = """\
Je bent een vriendelijke digitale assistent van een Belgisch uitzendbureau.
Je helpt een kandidaat om documenten en gegevens aan te leveren via WhatsApp.

Je voert een doorlopend gesprek. De volledige gespreksgeschiedenis staat hierboven.
Herhaal NOOIT een begroeting of introductie die je al eerder hebt gestuurd.

Stijl:
- Nederlands (Vlaams), warm en behulpzaam. Denk aan een behulpzame collega, niet een ambtenaar.
- Korte, duidelijke berichten — maximaal 3-4 zinnen per bericht.
- Eén vraag of verzoek per bericht.
- Gebruik "nodig hebben", "even regelen", "in orde maken" — NIET "verplicht", "dringend", "moeten".
- Emoji's spaarzaam: 📷 ✅ 👍 zijn OK.
- Je communiceert via WhatsApp: documenten worden als FOTO gestuurd.
- GEEN begroeting halverwege het gesprek. Alleen bij het allereerste bericht.

Regels:
- Schrijf ALLEEN het bericht voor de kandidaat. Geen technische termen, geen JSON.
- Geef concrete tips bij documenten (goed licht, vlakke ondergrond, hele document zichtbaar).
- Bij een mislukte foto: wees pragmatisch. Een foto met wat schittering of lichte hoek is PRIMA.
  Vraag alleen om een nieuwe foto als het echt onleesbaar is.
- Benoem altijd het specifieke document bij naam (niet generiek "je document").
- Dit is GEEN interview. Stel vragen kort en feitelijk — leg NIET uit waarom je iets vraagt.
  Goed: "Heb je eigen vervoer? 🚗"
  Fout: "Voor deze job kan het handig zijn dat je over een eigen wagen beschikt. Ben je in het bezit van een wagen?"
  Gewoon de vraag stellen, geen context of motivatie toevoegen.
- Gebruik **bold** (dubbele sterretjes) rond belangrijke woorden.
- Zeg "genoteerd" in plaats van "geregeld" — je registreert info, je regelt niets."""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _format_fields_text(fields: list[dict]) -> str:
    """Format a list of field labels into natural Dutch text."""
    labels = [f["label"] for f in fields]
    if len(labels) <= 2:
        return " en ".join(labels)
    return ", ".join(labels[:-1]) + f" en {labels[-1]}"


def _first_item_opener(state: CollectionState, item: dict) -> str:
    """Return opener text if this item is the first in its stage queue."""
    # Check stage-specific queues first, fall back to legacy item_queue
    first = None
    if hasattr(state, "document_queue") and state.document_queue:
        first = state.document_queue[0]
    elif hasattr(state, "item_queue") and state.item_queue:
        first = state.item_queue[0]
    if first is item:
        return 'Begin met "Laten we beginnen! 💪" of vergelijkbaar, en stel dan direct de vraag.'
    return "Stel direct de vraag zonder inleiding."


# ─── Prompt Builders ─────────────────────────────────────────────────────────

def build_intro_prompt(state: CollectionState) -> str:
    urgency = ""
    if state.days_remaining <= 5:
        urgency = f"\nBelangrijk: de startdatum nadert snel — nog {state.days_remaining} dagen."

    return f"""Schrijf een kort welkomstbericht voor {state.candidate_name}.
Context: vacature "{state.vacancy_title}"{f' bij {state.company_name}' if state.company_name else ''}.{urgency}

Dit bericht is het allereerste contact. Het volgende bericht (apart) zal de eerste vraag stellen.
Dus houd dit bericht KORT en warm — niet alles uitleggen.

Structuur:
1. Begroeting + felicitatie (1 zin, met emoji)
2. Kort zeggen dat je een paar dingen nodig hebt om het dossier in orde te brengen — max 1 zin. Noem NIET het exacte aantal.

NIET doen:
- Geen lange uitleg over wat je allemaal gaat verzamelen
- Geen exacte aantallen noemen ("4 documenten en 3 gegevens") — te robotisch
- Geen "als iets niet duidelijk is" — dat komt later
- Geen opsomming van documenten
- Niet afsluiten met "laten we beginnen" of iets dergelijks — dat hoort bij het volgende bericht

Max 2 zinnen. Luchtig."""


def build_ask_document_prompt(item: dict, state: CollectionState) -> str:
    scan_mode = item.get("scan_mode", "single")
    side_instruction = "Vraag om een foto van de VOORKANT." if scan_mode == "front_back" else "Vraag om een duidelijke foto."
    opener = _first_item_opener(state, item)

    return f"""Vraag {state.candidate_name} om een foto van: {item['name']}
{side_instruction}

{opener}
Gebruik **bold** rond het gevraagde item.
Voorbeeld: "Laten we beginnen! 💪 Kan je een foto van je **identiteitskaart** sturen? 📷"
Kort en direct. Geen tips. Max 1 zin (+ opener als eerste item)."""


def build_ask_document_group_prompt(item: dict, state: CollectionState) -> str:
    alternatives = item.get("alternatives", [])

    alt_descriptions = []
    for alt in alternatives:
        if alt.get("scan_mode") == "front_back":
            alt_descriptions.append(f"de voor- en achterkant van je {alt['name'].lower()}")
        else:
            alt_descriptions.append(f"een foto van je {alt['name'].lower()}")
    options_text = " of ".join(alt_descriptions)

    opener = _first_item_opener(state, item)

    return f"""Vraag {state.candidate_name} om een identiteitsdocument.
De kandidaat mag kiezen: {options_text}.

{opener}
Gebruik **bold** rond de gevraagde items.
Voorbeeld: "Laten we beginnen! 💪 Kan je een foto van je **identiteitskaart** of **paspoort** sturen? 📷"
Kort en direct. Geen tips. Max 1 zin (+ opener als eerste item)."""


def build_ask_back_prompt(item: dict) -> str:
    return f"""Voorkant van {item['name']} is goed ontvangen ✅
Vraag nu om de **achterkant**.
Voorbeeld: "Kan je nu ook de **achterkant** doorsturen?"
Kort en vriendelijk, max 1 zin."""


def build_ask_attribute_prompt(item: dict, state: CollectionState | None = None) -> str:
    reason = f" ({item['reason']})" if item.get("reason") else ""
    first_queue = None
    if state:
        if hasattr(state, "candidate_info_queue") and state.candidate_info_queue:
            first_queue = state.candidate_info_queue
        elif hasattr(state, "item_queue") and state.item_queue:
            first_queue = state.item_queue
    is_first = first_queue and first_queue[0] is item
    opener = '\nBegin met "Laten we beginnen! 💪" en stel dan de vraag.' if is_first else ""

    hint_line = f"\nInstructie: {item['ai_hint']}" if item.get("ai_hint") else ""

    fields = item.get("fields")
    if fields:
        fields_text = _format_fields_text(fields)
        return f"""Vraag de kandidaat naar: {item['name']}{reason}{opener}{hint_line}
Dit is een gestructureerd gegeven. Vraag naar: {fields_text}.
Combineer alles in ÉÉN vraag. Gebruik **bold** rond **{item['name']}**.
Voorbeeld: "Kan je de **naam** en het **telefoonnummer** van je **noodcontact** doorgeven?"
Kort en direct. Max 1-2 zinnen."""

    return f"""Vraag de kandidaat naar: {item['name']}{reason}{opener}{hint_line}
Gebruik **bold** rond het sleutelwoord.
Kort en direct. Max 1 zin."""


def build_verify_success_prompt(item: dict, next_item: dict | None) -> str:
    if next_item:
        next_type = "foto" if next_item["type"] in ("document", "document_group") else "tekst"
        hint_line = f"\nInstructie voor volgende vraag: {next_item['ai_hint']}" if next_item.get("ai_hint") else ""
        fields_line = ""
        if next_item.get("fields"):
            fields_text = _format_fields_text(next_item["fields"])
            fields_line = f"\nVraag specifiek naar: {fields_text}. Combineer in ÉÉN vraag."
        return f"""STAP 1: Bevestig kort dat **{item['name']}** volledig in orde is ✅ (ALLE velden zijn ontvangen, niets mist).
STAP 2: Ga over naar een NIEUW onderwerp: **{next_item['name']}** ({next_type}).{hint_line}{fields_line}

BELANGRIJK: **{item['name']}** is AFGEROND. Vraag NIETS meer over {item['name'].lower()}.
Het volgende item is iets ANDERS: **{next_item['name']}**.
Gebruik **bold** rond het nieuwe item. Max 2 zinnen."""
    return f"""**{item['name']}** is volledig in orde ✅ (ALLE velden ontvangen).
Bevestig ALLEEN dit kort. Vraag niets anders. STRIKT 1 zin, daarna STOP."""


def build_verify_fail_prompt(item: dict, retry: int) -> str:
    return f"""De foto van **{item['name']}** was niet duidelijk genoeg.
Poging {retry}/{MAX_RETRIES_PER_DOC}.
Vraag vriendelijk om een nieuwe foto. Geef een korte tip waarom het mislukte.
Max 2 zinnen."""


def build_skip_prompt(item: dict, next_item: dict | None = None) -> str:
    if next_item:
        next_type = next_item["type"]
        if next_type == "document_group":
            alternatives = next_item.get("alternatives", [])
            next_desc = " of ".join(f"**{a['name']}**" for a in alternatives)
        else:
            next_desc = f"**{next_item['name']}**"
        return f"""De kandidaat heeft aangegeven dat {item['name']} nu niet beschikbaar is.
Bevestig kort dat dit geen probleem is en dat je er later op terugkomt.
Vraag dan METEEN door naar het volgende: {next_desc}.
Combineer in max 2-3 zinnen. Vriendelijk, geen druk.
Schrijf ALLEEN over {item['name']} en {next_item['name']} — noem GEEN andere items."""
    return f"""De kandidaat heeft aangegeven dat {item['name']} nu niet beschikbaar is.
Bevestig dat dit geen probleem is en dat je er later op terugkomt.
Max 1-2 zinnen. Vriendelijk, geen druk."""


def build_skipped_review_prompt(item: dict) -> str:
    if item["type"] == "document":
        return f"""Je komt terug op een eerder overgeslagen item:
{item['name']} — de kandidaat had dit eerder niet bij de hand.
Vraag of het nu beschikbaar is. Als het een document is, vraag om een foto.
Max 2 zinnen. Vriendelijk."""
    return f"""Je komt terug op een eerder overgeslagen gegeven:
{item['name']}
Vraag of de kandidaat dit nu kan doorgeven.
Max 2 zinnen. Vriendelijk."""


def build_closing_prompt(state: CollectionState) -> str:
    collected_docs = [slug for slug, v in state.collected_documents.items() if v.get("status") == "verified"]
    collected_attrs = list(state.collected_attributes.keys())
    skipped = [i["name"] for i in state.skipped_items if i.get("permanently_skipped")]

    parts = []
    if collected_docs:
        parts.append(f"Documenten ontvangen: {', '.join(collected_docs)}")
    if collected_attrs:
        parts.append(f"Gegevens ontvangen: {', '.join(collected_attrs)}")

    skipped_note = ""
    if skipped:
        skipped_note = f"\nEr zijn nog items die niet verzameld konden worden: {', '.join(skipped)}. Een medewerker zal hiervoor contact opnemen."

    return f"""Sluit het gesprek af. Bedank {state.candidate_name} hartelijk.
Samenvatting: {'; '.join(parts) if parts else 'Alle items verwerkt.'}{skipped_note}
Max 3 zinnen. Warme afsluiting."""


def build_waiting_for_image_prompt(item: dict) -> str:
    return f"""De kandidaat heeft een tekstbericht gestuurd, maar je wacht op een FOTO van {item['name']}.
Herinner vriendelijk dat je een foto nodig hebt. Geef een tip.
De kandidaat kan ook "overslaan" zeggen als het document nu niet beschikbaar is.
Max 2 zinnen."""


def build_attribute_unclear_prompt(item: dict) -> str:
    fields = item.get("fields")
    if fields:
        fields_text = _format_fields_text(fields)
        return f"""Het antwoord van de kandidaat was niet duidelijk genoeg om {item['name']} te bepalen.
Ik heb nodig: {fields_text}.
Vraag opnieuw, specifieker. Geef een voorbeeld.
Max 2 zinnen."""
    return f"""Het antwoord van de kandidaat was niet duidelijk genoeg om {item['name']} te bepalen.
Vraag opnieuw, specifieker. Geef een voorbeeld van wat je verwacht.
Max 2 zinnen."""


# ─── Consent Prompts ────────────────────────────────────────────────────────

def build_consent_prompt(state: CollectionState) -> str:
    company = state.company_name or "het uitzendbureau"
    return f"""Vraag {state.candidate_name} om toestemming voor de verwerking van persoonlijke gegevens.

Context: je gaat documenten en gegevens verzamelen voor het dossier bij {company}.
De kandidaat moet akkoord gaan voordat je verder kan.

Structuur:
1. Kort uitleggen dat je persoonsgegevens en documenten gaat verwerken voor het dossier.
2. Vraag of de kandidaat hiermee akkoord gaat.

Voorbeeld: "Om je dossier in orde te brengen, verwerk ik een aantal **persoonlijke gegevens** en **documenten**. Ga je hiermee akkoord? 👍"
Max 2 zinnen. Vriendelijk en duidelijk."""


def build_consent_refused_prompt(state: CollectionState) -> str:
    return f"""De kandidaat heeft geen toestemming gegeven voor de verwerking van gegevens.

Leg vriendelijk uit dat je zonder toestemming het dossier niet kan verwerken.
Zeg dat een medewerker contact zal opnemen om dit persoonlijk te bespreken.
Max 2 zinnen. Begripvol, geen druk."""


# ─── Task Prompts ────────────────────────────────────────────────────────────

def build_task_ask_availability_prompt(task: dict, state: CollectionState) -> str:
    description = task.get("action", task.get("name", "taak"))
    return f"""Informeer {state.candidate_name} over het **medisch onderzoek** dat ingepland moet worden.

Context: {description}

Vraag wanneer de kandidaat beschikbaar is.
Geef een voorbeeld van hoe ze hun beschikbaarheid kunnen doorgeven.
Voorbeeld: "Wanneer zou je beschikbaar zijn voor je **medisch onderzoek**? Bv. 'volgende week maandag en dinsdag, tussen 8u en 17u' 📋"
Max 2-3 zinnen. Vriendelijk."""


def build_task_scheduled_prompt(task: dict) -> str:
    return f"""De beschikbaarheid voor **{task.get('name', 'de taak')}** is genoteerd ✅

Bevestig dat je de beschikbaarheid hebt doorgegeven en dat de kandidaat hierover nog bericht krijgt.
Voorbeeld: "Genoteerd! We gaan een afspraak voor je **medisch onderzoek** regelen. Je hoort hier nog van ons. 👍"
Max 1-2 zinnen."""


def build_task_contract_prompt(task: dict, state: CollectionState) -> str:
    start_date_text = f" (startdatum: {state.start_date})" if state.start_date else ""
    return f"""Informeer {state.candidate_name} dat het **contract** klaarligt om te ondertekenen{start_date_text}.

Stuur een bericht dat het contract beschikbaar is via de link.
Voorbeeld: "Je **contract** staat klaar! 📝 Je kan het bekijken en ondertekenen via deze link: [contract link]. Laat me weten als het ondertekend is!"
Max 2 zinnen. Enthousiast maar professioneel."""


def build_task_contract_signed_prompt(task: dict, state: CollectionState) -> str:
    start_info = f" Je start op **{state.start_date}**." if state.start_date else ""
    recruiter_info = ""
    if state.recruiter_name:
        recruiter_info = f"\nNoem **{state.recruiter_name}** als contactpersoon voor verdere vragen"
        if state.recruiter_email:
            recruiter_info += f" ({state.recruiter_email})"
        elif state.recruiter_phone:
            recruiter_info += f" ({state.recruiter_phone})"
        recruiter_info += "."

    return f"""Het **contract** is ondertekend! 🎉

Feliciteer {state.candidate_name} hartelijk met de ondertekening van het contract.{start_info}{recruiter_info}
Bevestig dat er verder contact volgt voor de praktische details.
Max 3 zinnen. Warm en enthousiast."""


def build_tasks_blocked_prompt(state: CollectionState) -> str:
    """When required items are still missing after skipped review, tasks cannot proceed."""
    return f"""Er zijn nog een aantal documenten of gegevens die we niet konden verzamelen.

Leg aan {state.candidate_name} uit dat een medewerker contact zal opnemen om de ontbrekende items persoonlijk te bespreken.
Zeg dat dit geen probleem is en dat alles in orde komt.
Max 2 zinnen. Geruststelling, geen druk."""


# ─── Stage Transition Prompts ────────────────────────────────────────────────

def build_stage_transition_prompt(completed_stage: str, next_stage_name: str) -> str:
    stage_descriptions = {
        "documents": "documenten",
        "candidate_info": "persoonlijke gegevens",
        "tasks": "taken",
        "additional_info": "aanvullende informatie",
    }
    completed_desc = stage_descriptions.get(completed_stage, completed_stage)
    next_desc = stage_descriptions.get(next_stage_name, next_stage_name)

    return f"""Alle {completed_desc} zijn verzameld ✅
Maak een korte overgang naar het volgende onderdeel: {next_desc}.
Max 1 zin. Luchtig en positief.
Voorbeeld: "Top, alle documenten zijn binnen! 📄 Nu nog een paar gegevens. 👇" """
