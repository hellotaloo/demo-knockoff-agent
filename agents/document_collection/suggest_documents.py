"""
Suggest document types per vacancy using LLM analysis.

Fetches all active vacancies and parent document types, then asks an LLM
to determine which documents should be collected for each vacancy.

Usage:
    python agents/document_collection/suggest_documents.py            # dry run
    python agents/document_collection/suggest_documents.py --save     # save configs to DB
    python agents/document_collection/suggest_documents.py --force    # overwrite existing configs
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

SYSTEM_INSTRUCTION = """Je bent een Belgische HR-compliance expert gespecialiseerd in uitzendarbeid en documentbeheer.
Je taak is om te bepalen welke documenten verzameld moeten worden voor een specifieke vacature.
Analyseer de vacaturetekst en selecteer ENKEL de documenttypes die relevant zijn.
Denk aan wettelijke vereisten, sector-specifieke certificaten, en praktische documenten.
Antwoord ALTIJD in valid JSON."""

PROMPT_TEMPLATE = """## Vacature: {title} ({company})
### Locatie: {location}

### Vacaturetekst:
{description}

### Beschikbare documenttypes:
{doc_types_list}

### Opdracht:
Selecteer welke documenttypes verzameld moeten worden voor deze vacature.
Geef je antwoord als JSON in dit formaat:
{{
  "slugs": ["slug1", "slug2"],
  "reasoning": "Korte uitleg waarom deze documenten nodig zijn."
}}

Belangrijke richtlijnen:
- Selecteer ALLEEN documenten die relevant zijn voor deze specifieke functie
- Identiteitsdocumenten (paspoort, ID-kaart) zijn bijna altijd nodig voor uitzendarbeid
- Werkvergunning is nodig als de functie niet-EU kandidaten kan aantrekken
- Rijbewijs alleen als de functie rijden vereist
- Medische schifting bij fysiek zwaar werk of specifieke sectoren
- VCA/veiligheidsattesten bij bouw, industrie, of logistiek
- Heftruckbrevet alleen bij magazijn/logistiek functies
- Attesten bouw alleen bij bouwsector functies
- Wees selectief: niet elk document is voor elke vacature nodig"""


def build_doc_types_list(doc_types: list) -> str:
    """Format parent document types for the prompt."""
    lines = []
    for dt in doc_types:
        lines.append(f"- {dt['slug']}: {dt['name']} ({dt['category']})")
    return "\n".join(lines)


def parse_llm_response(response_text: str, valid_slugs: set[str]) -> tuple[list[str], str]:
    """Parse LLM JSON response, stripping markdown fences if present."""
    text = response_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    data = json.loads(text)
    slugs = data.get("slugs", [])
    reasoning = data.get("reasoning", "")

    # Validate slugs
    validated = []
    for slug in slugs:
        if slug in valid_slugs:
            validated.append(slug)
        else:
            logger.warning(f"  ⚠ Onbekende slug genegeerd: {slug}")

    return validated, reasoning


async def suggest_for_vacancy(vacancy: dict, doc_types: list, valid_slugs: set[str]) -> dict:
    """Ask the LLM which document types are needed for a vacancy."""
    from src.utils.llm import generate

    prompt = PROMPT_TEMPLATE.format(
        title=vacancy["title"] or "Onbekend",
        company=vacancy["company"] or "Onbekend",
        location=vacancy["location"] or "Onbekend",
        description=vacancy["description"] or "(geen beschrijving)",
        doc_types_list=build_doc_types_list(doc_types),
    )

    response = await generate(
        prompt=prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
    )

    slugs, reasoning = parse_llm_response(response, valid_slugs)
    return {
        "vacancy_id": vacancy["id"],
        "title": vacancy["title"],
        "company": vacancy["company"],
        "slugs": slugs,
        "reasoning": reasoning,
    }


async def main():
    parser = argparse.ArgumentParser(description="Suggest document types per vacancy using LLM")
    parser.add_argument("--save", action="store_true", help="Save configs to database")
    parser.add_argument("--force", action="store_true", help="Overwrite existing configs")
    parser.add_argument("--workspace-id", type=str, default=str(DEFAULT_WORKSPACE_ID))
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from src.database import get_db_pool
    from src.repositories.document_type_repo import DocumentTypeRepository

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    workspace_id = uuid.UUID(args.workspace_id)
    pool = await get_db_pool()

    doc_type_repo = DocumentTypeRepository(pool)

    # Fetch parent document types
    doc_type_rows = await doc_type_repo.list_for_workspace(workspace_id, parents_only=True)
    doc_types = [dict(r) for r in doc_type_rows]
    valid_slugs = {dt["slug"] for dt in doc_types}
    slug_to_doc = {dt["slug"]: dt for dt in doc_types}

    logger.info(f"Geladen: {len(doc_types)} parent documenttypes\n")

    # Fetch active vacancies
    vacancies = await pool.fetch("""
        SELECT id, title, company, location, description, status
        FROM ats.vacancies
        WHERE status NOT IN ('closed', 'filled', 'archived')
        ORDER BY created_at DESC
    """)

    if not vacancies:
        logger.info("Geen actieve vacatures gevonden.")
        return

    logger.info(f"Gevonden: {len(vacancies)} actieve vacatures\n")

    # Process each vacancy
    results = []
    for i, vac in enumerate(vacancies, 1):
        vacancy = dict(vac)
        title = vacancy["title"] or "Onbekend"
        company = vacancy["company"] or ""
        label = f"{title} ({company})" if company else title

        logger.info(f"{'━' * 60}")
        logger.info(f"[{i}/{len(vacancies)}] {label}")

        if not vacancy.get("description"):
            logger.info("  ⏭️  Overgeslagen — geen vacaturetekst\n")
            continue

        try:
            result = await suggest_for_vacancy(vacancy, doc_types, valid_slugs)
            results.append(result)

            # Print results
            logger.info(f"  Documenten ({len(result['slugs'])}):")
            for slug in result["slugs"]:
                dt = slug_to_doc[slug]
                logger.info(f"    ✓ {slug}: {dt['name']} ({dt['category']})")
            logger.info(f"  Redenering: {result['reasoning']}")

            logger.info("  📝 Dry run — suggestie niet opgeslagen")

        except Exception as e:
            logger.error(f"  ❌ Fout: {e}")

        logger.info("")

    # Summary
    logger.info(f"{'━' * 60}")
    logger.info(f"Klaar! {len(results)}/{len(vacancies)} vacatures verwerkt.")
    if not args.save:
        logger.info("Gebruik --save om de resultaten op te slaan in de database.")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
