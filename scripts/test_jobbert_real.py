"""
Test JobBERT-v2 with a real vacancy from the database.

Run:
    python scripts/test_jobbert_real.py
"""

import asyncio
import asyncpg
import os
import re
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

# Load environment variables
load_dotenv()

# Skill taxonomy
SKILL_TAXONOMY = [
    # Retail / Winkel
    "Kassa", "Kassawerk", "Klantenservice", "Verkoop", "Winkelervaring",
    "Rekken vullen", "Voorraadbeheer", "Winkelinrichting", "Klantvriendelijk",

    # Bakkerij / Horeca
    "Bakkerij", "Brood bakken", "Patisserie", "Horeca", "Voedingssector",
    "HACCP", "Voedselveiligheid", "Hygiëne",

    # Productie / Operator
    "Machineoperator", "Productielijn", "Productiewerk", "Operator",
    "Kwaliteitscontrole", "Veiligheidsvoorschriften", "GMP",
    "Technisch inzicht", "Onderhoud machines", "Montage",
    "Menginstallatie", "Procesoperator", "Chemische productie",

    # Ploegensysteem
    "Ploegensysteem", "2 ploegen", "3 ploegen", "Volcontinue",
    "Flexibele uren", "Weekendwerk", "Nachtwerk",

    # Logistiek
    "Vorkheftruck", "Reachtruck", "Magazijnwerk", "Orderpicking",
    "Inventory", "Planning", "Distributie", "Supply chain",
    "Logistiek supervisor", "Teamleider logistiek", "WMS",

    # Commercieel / Binnendienst
    "Commercieel", "Binnendienst", "Offertes", "Orderverwerking",
    "Technisch commercieel", "B2B verkoop", "Accountbeheer",
    "Telefonisch contact", "CRM",

    # Customer Service
    "Customer service", "Klantencontact", "Klachtenbehandeling",
    "Helpdesk", "Ticketing", "After sales",

    # Talen
    "Nederlands", "Frans", "Engels", "Duits", "Portugees", "Spaans",
    "Meertalig", "Tweetalig",

    # Soft skills
    "Communicatie", "Teamwork", "Flexibiliteit", "Zelfstandig werken",
    "Stressbestendigheid", "Klantgericht", "Nauwkeurig", "Punctueel",
    "Leidinggeven", "Coachen", "Probleemoplossend",

    # Certificaten / Rijbewijzen
    "Rijbewijs B", "Rijbewijs C", "Rijbewijs CE",
    "Vorkheftruck attest", "VCA", "VCA-VOL",

    # IT / Admin
    "MS Office", "Excel", "ERP", "SAP", "Outlook",
    "Administratie", "Facturatie",
]


def split_into_lines(text: str) -> list[str]:
    """Split vacancy text into meaningful lines/sentences."""
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        line = re.sub(r"^[-•*]\s*", "", line)
        if line and len(line) > 3:
            lines.append(line)
    return lines


def extract_skills_with_evidence(
    model,
    vacancy_text: str,
    skill_list: list[str],
    threshold: float = 0.3
) -> list[dict]:
    """Extract skills with explainability."""
    lines = split_into_lines(vacancy_text)

    vacancy_embedding = model.encode([vacancy_text])
    skill_embeddings = model.encode(skill_list)
    line_embeddings = model.encode(lines) if lines else None

    similarities = cos_sim(vacancy_embedding, skill_embeddings)[0]

    results = []
    for idx, (skill, score) in enumerate(zip(skill_list, similarities)):
        score_float = float(score)
        if score_float >= threshold:
            evidence = None
            evidence_score = 0.0

            if line_embeddings is not None:
                skill_emb = skill_embeddings[idx].reshape(1, -1)
                line_similarities = cos_sim(skill_emb, line_embeddings)[0]
                best_line_idx = int(line_similarities.argmax())
                evidence = lines[best_line_idx]
                evidence_score = float(line_similarities[best_line_idx])

            results.append({
                "skill": skill,
                "score": score_float,
                "evidence": evidence,
                "evidence_score": evidence_score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


async def fetch_vacancies(limit: int = 5):
    """Fetch recent vacancies from database."""
    db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")

    if not db_url:
        raise ValueError("DATABASE_URL not set in environment")

    conn = await asyncpg.connect(db_url)

    try:
        rows = await conn.fetch("""
            SELECT id, title, company, location, description
            FROM ats.vacancies
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)
        return rows
    finally:
        await conn.close()


async def main():
    print("Loading JobBERT-v2 model...")
    model = SentenceTransformer("TechWolf/JobBERT-v2")

    print("\nFetching vacancies from database...")
    vacancies = await fetch_vacancies(limit=5)

    if not vacancies:
        print("No vacancies found in database!")
        return

    print(f"Found {len(vacancies)} vacancies\n")

    for vacancy in vacancies:
        title = vacancy["title"]
        company = vacancy["company"] or "N/A"
        location = vacancy["location"] or "N/A"
        description = vacancy["description"] or ""

        print("=" * 70)
        print(f"📄 {title}")
        print(f"   Company: {company} | Location: {location}")
        print("=" * 70)

        if not description:
            print("  ⚠️  No description available\n")
            continue

        # Show first 200 chars of description
        preview = description[:200].replace("\n", " ")
        if len(description) > 200:
            preview += "..."
        print(f"\nDescription preview:\n  {preview}\n")

        # Extract skills
        skills = extract_skills_with_evidence(
            model, description, SKILL_TAXONOMY, threshold=0.30
        )

        print(f"Top 8 matched skills:")
        print("-" * 70)

        for item in skills[:8]:
            skill = item["skill"]
            score = item["score"]
            evidence = item["evidence"] or "N/A"
            evidence_score = item["evidence_score"]

            if len(evidence) > 55:
                evidence = evidence[:52] + "..."

            bar = "█" * int(score * 20)
            print(f"\n  {skill:25} {score:.3f} {bar}")
            print(f"    └─ \"{evidence}\" ({evidence_score:.2f})")

        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
