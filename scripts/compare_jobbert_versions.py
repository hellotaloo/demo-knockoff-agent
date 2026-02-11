"""
Compare JobBERT v2 vs v3 on Dutch vacancy text.

Run:
    python scripts/compare_jobbert_versions.py
"""

from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

# Test vacancy in Dutch
VACANCY_TEXT = """
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
"""

# Skills to test (mix of Dutch and English)
TEST_SKILLS = [
    # Dutch skills
    "Logistiek supervisor",
    "Teamleider logistiek",
    "Leidinggeven",
    "Magazijnwerk",
    "Vorkheftruck",
    "Planning",
    "Communicatie",
    # English equivalents
    "Logistics supervisor",
    "Team leader logistics",
    "Leadership",
    "Warehouse management",
    "Forklift",
    "Planning",
    "Communication",
]


def test_model(model_name: str):
    """Test a model on the vacancy."""
    print(f"\nLoading {model_name}...")
    model = SentenceTransformer(model_name)

    # Encode
    vacancy_emb = model.encode([VACANCY_TEXT])
    skill_embs = model.encode(TEST_SKILLS)

    # Calculate similarities
    similarities = cos_sim(vacancy_emb, skill_embs)[0]

    print(f"\nResults for {model_name}:")
    print("-" * 50)

    for skill, score in sorted(zip(TEST_SKILLS, similarities), key=lambda x: -x[1]):
        score_float = float(score)
        bar = "█" * int(score_float * 30)
        print(f"  {skill:25} {score_float:.3f} {bar}")


def main():
    print("=" * 60)
    print("JobBERT v2 vs v3 Comparison on Dutch Vacancy")
    print("=" * 60)

    # Test both models
    test_model("TechWolf/JobBERT-v2")
    test_model("TechWolf/JobBERT-v3")

    print("\n" + "=" * 60)
    print("Comparison complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
