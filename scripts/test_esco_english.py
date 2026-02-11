"""
Test JobBERT v3 with English vacancy and ESCO skills.

Run:
    python scripts/test_esco_english.py
"""

import json
import re
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


# English translated vacancy
VACANCY_EN = """
Position: Logistics Supervisor
Location: Zedelgem, Belgium

You are responsible for the daily management of the warehouse team.

Tasks:
- Coordinating warehouse activities
- Managing a team of 10 employees
- Setting planning and priorities
- Monitoring and reporting KPIs
- Optimizing logistics processes

Profile:
- Experience in logistics/warehouse (min. 3 years)
- Leadership experience
- Knowledge of WMS systems
- Forklift certificate is a plus
- Good communication skills
- Dutch and English
"""


def split_into_lines(text: str) -> list[str]:
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        line = re.sub(r"^[-•*]\s*", "", line)
        if line and len(line) > 3:
            lines.append(line)
    return lines


def extract_skills_with_evidence(model, vacancy_text, skill_list, threshold=0.3):
    """Extract skills with evidence."""
    lines = split_into_lines(vacancy_text)

    vacancy_emb = model.encode([vacancy_text])
    skill_embs = model.encode(skill_list)
    line_embs = model.encode(lines) if lines else None

    similarities = cos_sim(vacancy_emb, skill_embs)[0]

    results = []
    for idx, (skill, score) in enumerate(zip(skill_list, similarities)):
        score_float = float(score)
        if score_float >= threshold:
            evidence = None
            evidence_score = 0.0

            if line_embs is not None:
                skill_emb = skill_embs[idx].reshape(1, -1)
                line_sims = cos_sim(skill_emb, line_embs)[0]
                best_idx = int(line_sims.argmax())
                evidence = lines[best_idx]
                evidence_score = float(line_sims[best_idx])

            results.append({
                "skill": skill,
                "score": score_float,
                "evidence": evidence,
                "evidence_score": evidence_score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def main():
    # Load ESCO skills
    print("Loading ESCO skills...")
    with open("scripts/esco_skills.json") as f:
        all_skills = json.load(f)

    print(f"Total ESCO skills: {len(all_skills)}")

    # Filter to relevant categories for logistics/warehouse
    relevant_keywords = [
        "logistics", "warehouse", "team", "manage", "lead", "supervis",
        "coordinate", "plan", "kpi", "report", "forklift", "communicate",
        "optimis", "optimiz", "inventory", "supply chain", "shipping"
    ]

    filtered_skills = [
        s for s in all_skills
        if any(kw in s.lower() for kw in relevant_keywords)
    ]
    print(f"Filtered skills (logistics-related): {len(filtered_skills)}")

    # Load model
    print("\nLoading JobBERT-v3...")
    model = SentenceTransformer("TechWolf/JobBERT-v3")

    # Test with filtered skills
    print("\n" + "=" * 70)
    print("ESCO Skill Extraction - Logistics Supervisor (English)")
    print("=" * 70)

    skills = extract_skills_with_evidence(
        model, VACANCY_EN, filtered_skills, threshold=0.35
    )

    print(f"\nTop 15 matched ESCO skills:")
    print("-" * 70)

    for item in skills[:15]:
        skill = item["skill"]
        score = item["score"]
        evidence = item["evidence"] or "N/A"
        evidence_score = item["evidence_score"]

        if len(skill) > 40:
            skill_display = skill[:37] + "..."
        else:
            skill_display = skill

        if len(evidence) > 45:
            evidence = evidence[:42] + "..."

        bar = "█" * int(score * 20)
        print(f"\n  {skill_display:40} {score:.3f} {bar}")
        print(f"    └─ \"{evidence}\" ({evidence_score:.2f})")

    # Also test with full ESCO (sampling for speed)
    print("\n" + "=" * 70)
    print("Full ESCO Test (13k skills)")
    print("=" * 70)

    skills_full = extract_skills_with_evidence(
        model, VACANCY_EN, all_skills, threshold=0.45
    )

    print(f"\nTop 15 matched skills (threshold=0.45):")
    print("-" * 70)

    for item in skills_full[:15]:
        skill = item["skill"]
        score = item["score"]

        if len(skill) > 50:
            skill_display = skill[:47] + "..."
        else:
            skill_display = skill

        bar = "█" * int(score * 20)
        print(f"  {skill_display:50} {score:.3f} {bar}")

    print("\n✅ Test complete!")


if __name__ == "__main__":
    main()
