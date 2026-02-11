"""
Test script for JobBERT-v2 skill extraction from vacancies.

Focused on Belgian/Flemish job market (retail, production, logistics).

Install first:
    pip install sentence-transformers torch

Run:
    python scripts/test_jobbert.py
"""

import torch
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

# Belgian/Flemish skill taxonomy for retail, production, logistics jobs
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

# Sample vacancies based on Taloo test data
SAMPLE_VACANCIES = {
    "kassamedewerker": """
Functie: Kassamedewerker
Locatie: Wevelgem, België

Als kassamedewerker ben je het gezicht van onze winkel. Je staat in voor een vlotte
en vriendelijke afhandeling aan de kassa.

Takenpakket:
- Klanten helpen aan de kassa
- Geld en betaalkaarten verwerken
- Klantvragen beantwoorden
- Winkel netjes houden
- Rekken bijvullen indien nodig

Profiel:
- Je bent klantvriendelijk en sociaal
- Je kan zelfstandig werken
- Flexibel qua uren (ook weekends)
- Ervaring met kassawerk is een plus
- Je spreekt vloeiend Nederlands
""",

    "productieoperator": """
Functie: Productieoperator (2 ploegen)
Locatie: Diest, België

Voor ons productiebedrijf zoeken we een gemotiveerde productieoperator.

Takenpakket:
- Bedienen van productiemachines
- Kwaliteitscontroles uitvoeren
- Veiligheidsvoorschriften naleven
- Productielijn opvolgen
- Kleine technische storingen oplossen

Profiel:
- Technisch inzicht
- Bereid om in 2 ploegen te werken (6h-14h / 14h-22h)
- Ervaring als operator is een plus
- Nauwkeurig en veiligheidsbewust
- Fysiek belastbaar
""",

    "logistiek_supervisor": """
Functie: Logistiek Supervisor
Locatie: Zedelgem, België

Je staat in voor de dagelijkse aansturing van het magazijnteam.

Takenpakket:
- Coördineren van magazijnactiviteiten
- Aansturen van een team van 10 medewerkers
- Planning en prioriteiten bepalen
- KPI's opvolgen en rapporteren
- Optimaliseren van logistieke processen

Profiel:
- Ervaring in logistiek/magazijn (min. 3 jaar)
- Leidinggevende ervaring
- Kennis van WMS systemen
- Vorkheftruck attest is een plus
- Goede communicatieve vaardigheden
- Nederlands en Engels
""",

    "customer_service_portugal": """
Functie: Customer Service Medewerker Portugal
Locatie: Lissabon / Kortrijk

Je behandelt klantvragen voor de Portugese markt.

Takenpakket:
- Beantwoorden van klantvragen via telefoon en email
- Klachten behandelen en oplossen
- Orders opvolgen in ons systeem
- Samenwerken met sales en logistiek

Profiel:
- Vloeiend Portugees (moedertaal niveau)
- Goede kennis Engels
- Ervaring in customer service
- Klantgericht en oplossingsgericht
- Kennis van CRM systemen
""",
}


import re


def split_into_lines(text: str) -> list[str]:
    """Split vacancy text into meaningful lines/sentences."""
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        # Remove bullet points and clean up
        line = re.sub(r"^[-•*]\s*", "", line)
        if line and len(line) > 3:  # Skip empty or very short lines
            lines.append(line)
    return lines


def extract_skills_with_evidence(
    model,
    vacancy_text: str,
    skill_list: list[str],
    threshold: float = 0.3
) -> list[dict]:
    """
    Extract skills from vacancy text with explainability.

    Returns list of dicts with:
        - skill: The matched skill name
        - score: Overall similarity score
        - evidence: The line(s) that caused this skill to match
        - evidence_score: How well the evidence matches the skill
    """
    # Split vacancy into lines for explainability
    lines = split_into_lines(vacancy_text)

    # Encode everything
    vacancy_embedding = model.encode([vacancy_text])
    skill_embeddings = model.encode(skill_list)
    line_embeddings = model.encode(lines) if lines else None

    # Calculate overall similarity
    similarities = cos_sim(vacancy_embedding, skill_embeddings)[0]

    # Extract skills above threshold with evidence
    results = []
    for idx, (skill, score) in enumerate(zip(skill_list, similarities)):
        score_float = float(score)
        if score_float >= threshold:
            # Find best matching line as evidence
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

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def extract_skills(model, vacancy_text: str, skill_list: list[str], threshold: float = 0.3):
    """
    Extract skills from vacancy text (simple version without evidence).

    Returns:
        List of (skill, score) tuples sorted by score
    """
    # Encode vacancy and skills
    vacancy_embedding = model.encode([vacancy_text])
    skill_embeddings = model.encode(skill_list)

    # Calculate similarity
    similarities = cos_sim(vacancy_embedding, skill_embeddings)[0]

    # Extract skills above threshold
    results = []
    for skill, score in zip(skill_list, similarities):
        score_float = float(score)
        if score_float >= threshold:
            results.append((skill, score_float))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def main():
    print("Loading JobBERT-v2 model...")
    print("(First run downloads ~400MB)\n")

    model = SentenceTransformer("TechWolf/JobBERT-v2")

    print("=" * 60)
    print("SKILL EXTRACTION TEST - Belgian Vacancies")
    print("=" * 60)

    # Test each vacancy with explainability
    for vacancy_name, vacancy_text in SAMPLE_VACANCIES.items():
        print(f"\n{'=' * 60}")
        print(f"📄 {vacancy_name.upper().replace('_', ' ')}")
        print("=" * 60)

        skills = extract_skills_with_evidence(model, vacancy_text, SKILL_TAXONOMY, threshold=0.25)

        print(f"\nTop 10 matched skills with evidence:")
        print("-" * 70)
        for item in skills[:10]:
            skill = item["skill"]
            score = item["score"]
            evidence = item["evidence"] or "N/A"
            evidence_score = item["evidence_score"]

            # Truncate evidence if too long
            if len(evidence) > 50:
                evidence = evidence[:47] + "..."

            bar = "█" * int(score * 20)
            print(f"\n  {skill:25} {score:.3f} {bar}")
            print(f"    └─ \"{evidence}\" ({evidence_score:.2f})")

    # Compare job title similarities
    print("\n" + "=" * 60)
    print("JOB TITLE SIMILARITY TEST")
    print("=" * 60)

    job_titles = [
        "Kassamedewerker",
        "Winkelmedewerker",
        "Productieoperator",
        "Machineoperator",
        "Logistiek Supervisor",
        "Magazijnmedewerker",
        "Customer Service Medewerker",
        "Commercieel Binnendienst",
    ]

    embeddings = model.encode(job_titles)
    similarities = cos_sim(embeddings, embeddings)

    print("\nSimilarity matrix:")
    print("-" * 50)

    # Print abbreviated header
    abbrevs = [t[:10] for t in job_titles]
    print(f"{'':22}", end="")
    for abbrev in abbrevs:
        print(f"{abbrev:>11}", end="")
    print()

    # Print matrix
    for i, title in enumerate(job_titles):
        print(f"{title:22}", end="")
        for j in range(len(job_titles)):
            score = float(similarities[i][j])
            print(f"{score:>11.2f}", end="")
        print()

    print("\n" + "=" * 60)
    print("✅ Test complete!")
    print("=" * 60)
    print("\nInterpretation:")
    print("  - Scores > 0.4: Strong skill match")
    print("  - Scores 0.3-0.4: Moderate match")
    print("  - Scores < 0.3: Weak match")
    print("\nNext: Adjust threshold or expand taxonomy as needed")


if __name__ == "__main__":
    main()
