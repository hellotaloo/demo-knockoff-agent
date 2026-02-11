"""
Comprehensive vacancy analysis report using JobBERT v3 and ESCO.

Extracts:
- Skills
- Diplomas / Certificates
- Personality traits
- Similarity matrix with other job titles

Run:
    python scripts/vacancy_analysis_report.py
"""

import json
import re
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


# ============================================================
# TAXONOMIES
# ============================================================

# Diplomas and Education (EU/Belgian focus)
DIPLOMA_TAXONOMY = [
    # Secondary education
    "Secondary school diploma",
    "High school diploma",
    "Vocational secondary education",
    "Technical secondary education",
    "General secondary education",
    # Higher education
    "Bachelor's degree",
    "Master's degree",
    "PhD",
    "Associate degree",
    "Professional bachelor",
    # Vocational
    "Vocational training certificate",
    "Apprenticeship certificate",
    "Trade certificate",
    # Specific fields
    "Business administration degree",
    "Engineering degree",
    "IT degree",
    "Logistics degree",
    "Supply chain management degree",
    "Accounting degree",
    "Marketing degree",
    "Human resources degree",
]

# Certificates and Licenses
CERTIFICATE_TAXONOMY = [
    # Driving
    "Driver's license B",
    "Driver's license C",
    "Driver's license CE",
    "Driver's license D",
    "ADR certificate",
    # Warehouse / Logistics
    "Forklift certificate",
    "Forklift license",
    "Reach truck certificate",
    "Warehouse management certification",
    "WMS certification",
    # Safety
    "VCA certification",
    "VCA-VOL certification",
    "First aid certificate",
    "Fire safety certificate",
    "HACCP certification",
    "GMP certification",
    # IT
    "Microsoft Office certification",
    "SAP certification",
    "ERP certification",
    "Project management certification",
    "PMP certification",
    "Scrum certification",
    "ITIL certification",
    # Languages
    "Language certificate English",
    "Language certificate French",
    "Language certificate German",
    "Language certificate Dutch",
]

# Personality Traits and Soft Skills
PERSONALITY_TAXONOMY = [
    # Communication
    "Strong communication skills",
    "Good interpersonal skills",
    "Active listener",
    "Clear communicator",
    "Presentation skills",
    # Leadership
    "Leadership skills",
    "Team leadership",
    "Coaching ability",
    "Motivating others",
    "Decision making",
    # Work style
    "Detail-oriented",
    "Accurate",
    "Organized",
    "Structured approach",
    "Methodical",
    # Problem solving
    "Problem-solving skills",
    "Analytical thinking",
    "Critical thinking",
    "Creative thinking",
    "Solution-oriented",
    # Interpersonal
    "Team player",
    "Collaborative",
    "Customer-oriented",
    "Service-minded",
    "Empathetic",
    # Personal
    "Self-motivated",
    "Independent worker",
    "Proactive",
    "Initiative",
    "Reliable",
    "Punctual",
    "Flexible",
    "Adaptable",
    "Stress-resistant",
    "Works well under pressure",
    # Learning
    "Quick learner",
    "Eager to learn",
    "Open to feedback",
    "Growth mindset",
]

# Job titles for similarity matrix
JOB_TITLES = [
    "Logistics Supervisor",
    "Warehouse Manager",
    "Team Leader Logistics",
    "Operations Manager",
    "Supply Chain Coordinator",
    "Inventory Manager",
    "Shipping Coordinator",
    "Production Supervisor",
    "Logistics Coordinator",
    "Warehouse Operator",
]

# Sample vacancy (English)
SAMPLE_VACANCY = """
Position: Logistics Supervisor
Company: International Manufacturing Company
Location: Zedelgem, Belgium

About the role:
You will be responsible for the daily management and coordination of our warehouse team,
ensuring efficient logistics operations and continuous improvement.

Key Responsibilities:
- Lead and supervise a team of 10-15 warehouse employees
- Coordinate daily warehouse activities and shipment scheduling
- Monitor and report on KPIs including accuracy, productivity and safety
- Optimize logistics processes and implement efficiency improvements
- Manage inventory levels and ensure stock accuracy
- Collaborate with production, sales and transport departments
- Ensure compliance with safety regulations and quality standards
- Train and coach team members on procedures and best practices

Requirements:
- Bachelor's degree in Logistics, Supply Chain or equivalent through experience
- Minimum 3-5 years experience in logistics or warehouse management
- Proven leadership experience managing teams
- Strong knowledge of WMS systems (SAP preferred)
- Forklift certificate is a plus
- Excellent communication and organizational skills
- Analytical mindset with problem-solving abilities
- Fluent in Dutch and English, French is a plus
- Stress-resistant and able to work in a fast-paced environment
- Hands-on mentality with attention to detail

We offer:
- Competitive salary with benefits
- Training and development opportunities
- Dynamic international work environment
"""


def split_into_lines(text: str) -> list[str]:
    """Split text into meaningful lines."""
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        line = re.sub(r"^[-•*]\s*", "", line)
        if line and len(line) > 3:
            lines.append(line)
    return lines


def extract_with_evidence(model, text, taxonomy, threshold=0.35, top_n=10):
    """Extract items from taxonomy with evidence."""
    lines = split_into_lines(text)

    text_emb = model.encode([text])
    tax_embs = model.encode(taxonomy)
    line_embs = model.encode(lines) if lines else None

    similarities = cos_sim(text_emb, tax_embs)[0]

    results = []
    for idx, (item, score) in enumerate(zip(taxonomy, similarities)):
        score_float = float(score)
        if score_float >= threshold:
            evidence = None
            evidence_score = 0.0

            if line_embs is not None:
                item_emb = tax_embs[idx].reshape(1, -1)
                line_sims = cos_sim(item_emb, line_embs)[0]
                best_idx = int(line_sims.argmax())
                evidence = lines[best_idx]
                evidence_score = float(line_sims[best_idx])

            results.append({
                "item": item,
                "score": score_float,
                "evidence": evidence,
                "evidence_score": evidence_score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def print_section(title: str, results: list, show_evidence: bool = True):
    """Print a formatted section."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)

    if not results:
        print("  No matches found above threshold.")
        return

    for item in results:
        name = item["item"]
        score = item["score"]
        evidence = item.get("evidence", "")
        ev_score = item.get("evidence_score", 0)

        if len(name) > 40:
            name = name[:37] + "..."

        bar = "█" * int(score * 25)
        print(f"\n  {name:40} {score:.3f} {bar}")

        if show_evidence and evidence:
            if len(evidence) > 55:
                evidence = evidence[:52] + "..."
            print(f"    └─ \"{evidence}\" ({ev_score:.2f})")


def get_similarity_results(model, vacancy_title: str, job_titles: list) -> list:
    """Get similarity results between vacancy and job titles."""
    all_titles = [vacancy_title] + job_titles
    embeddings = model.encode(all_titles)
    similarities = cos_sim(embeddings, embeddings)

    vacancy_sims = [(title, float(similarities[0][i+1]))
                    for i, title in enumerate(job_titles)]
    vacancy_sims.sort(key=lambda x: -x[1])
    return vacancy_sims


def print_similarity_matrix(model, vacancy_title: str, job_titles: list):
    """Print similarity matrix between vacancy and job titles."""
    print(f"\n{'=' * 70}")
    print("  JOB TITLE SIMILARITY MATRIX")
    print("=" * 70)

    vacancy_sims = get_similarity_results(model, vacancy_title, job_titles)

    print(f"\n  Similarity of '{vacancy_title}' to other roles:\n")

    for title, score in vacancy_sims:
        bar = "█" * int(score * 30)
        color = "🟢" if score > 0.7 else "🟡" if score > 0.5 else "🔴"
        print(f"  {color} {title:30} {score:.3f} {bar}")


def generate_markdown_report(
    vacancy_title: str,
    company: str,
    location: str,
    skills: list,
    diplomas: list,
    certificates: list,
    personality: list,
    similarity_results: list,
    output_file: str = "scripts/vacancy_report.md"
):
    """Generate a Markdown report file."""
    from datetime import datetime

    md = []
    md.append(f"# Vacancy Analysis Report")
    md.append(f"")
    md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    md.append(f"**Model:** JobBERT v3 + ESCO Taxonomy")
    md.append(f"")
    md.append(f"---")
    md.append(f"")
    md.append(f"## Vacancy Details")
    md.append(f"")
    md.append(f"| Field | Value |")
    md.append(f"|-------|-------|")
    md.append(f"| **Position** | {vacancy_title} |")
    md.append(f"| **Company** | {company} |")
    md.append(f"| **Location** | {location} |")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Skills section (with score bar like Job Title Similarity)
    md.append(f"## Required Skills (ESCO)")
    md.append(f"")
    md.append(f"| Skill | Score | Evidence |")
    md.append(f"|-------|-------|----------|")
    for item in skills:
        skill = item["item"]
        score = item["score"]
        bar = "█" * int(score * 10)  # 0–10 blocks for 0.0–1.0
        evidence = item.get("evidence", "N/A") or "N/A"
        ev_score = item.get("evidence_score", 0)
        if len(evidence) > 50:
            evidence = evidence[:47] + "..."
        md.append(f"| {skill} | {score:.3f} {bar} | \"{evidence}\" ({ev_score:.2f}) |")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Education section
    md.append(f"## Education / Diplomas")
    md.append(f"")
    if diplomas:
        md.append(f"| Diploma | Score | Evidence |")
        md.append(f"|---------|-------|----------|")
        for item in diplomas:
            name = item["item"]
            score = item["score"]
            evidence = item.get("evidence", "N/A") or "N/A"
            ev_score = item.get("evidence_score", 0)
            if len(evidence) > 50:
                evidence = evidence[:47] + "..."
            md.append(f"| {name} | {score:.3f} | \"{evidence}\" ({ev_score:.2f}) |")
    else:
        md.append(f"*No specific education requirements detected.*")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Certificates section
    md.append(f"## Certificates / Licenses")
    md.append(f"")
    if certificates:
        md.append(f"| Certificate | Score | Evidence |")
        md.append(f"|-------------|-------|----------|")
        for item in certificates:
            name = item["item"]
            score = item["score"]
            evidence = item.get("evidence", "N/A") or "N/A"
            ev_score = item.get("evidence_score", 0)
            if len(evidence) > 50:
                evidence = evidence[:47] + "..."
            md.append(f"| {name} | {score:.3f} | \"{evidence}\" ({ev_score:.2f}) |")
    else:
        md.append(f"*No specific certificates detected.*")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Personality section
    md.append(f"## Personality Traits")
    md.append(f"")
    md.append(f"> **Note:** JobBERT is optimized for hard skills. Soft skill scores are typically lower.")
    md.append(f"")
    if personality:
        md.append(f"| Trait | Score | Evidence |")
        md.append(f"|-------|-------|----------|")
        for item in personality:
            name = item["item"]
            score = item["score"]
            evidence = item.get("evidence", "N/A") or "N/A"
            ev_score = item.get("evidence_score", 0)
            if len(evidence) > 50:
                evidence = evidence[:47] + "..."
            md.append(f"| {name} | {score:.3f} | \"{evidence}\" ({ev_score:.2f}) |")
    else:
        md.append(f"*No personality traits detected above threshold.*")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Similarity matrix section
    md.append(f"## Job Title Similarity")
    md.append(f"")
    md.append(f"Similarity of **{vacancy_title}** to other roles:")
    md.append(f"")
    md.append(f"| Job Title | Similarity | Match Level |")
    md.append(f"|-----------|------------|-------------|")
    for title, score in similarity_results:
        level = "🟢 High" if score > 0.7 else "🟡 Medium" if score > 0.5 else "🔴 Low"
        bar = "█" * int(score * 10)
        md.append(f"| {title} | {score:.3f} {bar} | {level} |")
    md.append(f"")
    md.append(f"---")
    md.append(f"")

    # Summary section
    md.append(f"## Summary")
    md.append(f"")
    md.append(f"| Category | Matches |")
    md.append(f"|----------|---------|")
    md.append(f"| Skills (ESCO) | {len(skills)} |")
    md.append(f"| Education | {len(diplomas)} |")
    md.append(f"| Certificates | {len(certificates)} |")
    md.append(f"| Personality Traits | {len(personality)} |")
    md.append(f"")
    md.append(f"### Most Similar Roles")
    md.append(f"")
    for i, (title, score) in enumerate(similarity_results[:3], 1):
        md.append(f"{i}. **{title}** ({score:.2f})")
    md.append(f"")
    md.append(f"---")
    md.append(f"")
    md.append(f"*Report generated using [TechWolf/JobBERT-v3](https://huggingface.co/TechWolf/JobBERT-v3) and ESCO taxonomy.*")

    # Write to file
    with open(output_file, "w") as f:
        f.write("\n".join(md))

    return output_file


def main():
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " VACANCY ANALYSIS REPORT ".center(68) + "║")
    print("║" + " Using JobBERT v3 + ESCO ".center(68) + "║")
    print("╚" + "═" * 68 + "╝")

    # Load ESCO skills
    print("\nLoading resources...")
    try:
        with open("scripts/esco_skills.json") as f:
            esco_skills = json.load(f)
        print(f"  ✓ ESCO skills loaded: {len(esco_skills)}")
    except FileNotFoundError:
        print("  ⚠ ESCO skills not found, using basic skill list")
        esco_skills = [
            "warehouse management", "logistics", "team leadership",
            "inventory management", "supply chain", "forklift operation",
            "WMS systems", "KPI reporting", "process optimization"
        ]

    # Load model
    print("\nLoading JobBERT-v3 model...")
    model = SentenceTransformer("TechWolf/JobBERT-v3")
    print("  ✓ Model loaded")

    # Show vacancy summary
    print("\n" + "─" * 70)
    print("  VACANCY: Logistics Supervisor")
    print("  COMPANY: International Manufacturing Company")
    print("  LOCATION: Zedelgem, Belgium")
    print("─" * 70)

    # 1. Skills extraction
    print("\n⏳ Extracting skills...")
    skills = extract_with_evidence(
        model, SAMPLE_VACANCY, esco_skills,
        threshold=0.42, top_n=12
    )
    print_section("REQUIRED SKILLS (ESCO)", skills)

    # 2. Diplomas extraction
    print("\n⏳ Extracting education requirements...")
    diplomas = extract_with_evidence(
        model, SAMPLE_VACANCY, DIPLOMA_TAXONOMY,
        threshold=0.35, top_n=8
    )
    print_section("EDUCATION / DIPLOMAS", diplomas)

    # 3. Certificates extraction
    print("\n⏳ Extracting certificates...")
    certificates = extract_with_evidence(
        model, SAMPLE_VACANCY, CERTIFICATE_TAXONOMY,
        threshold=0.35, top_n=8
    )
    print_section("CERTIFICATES / LICENSES", certificates)

    # 4. Personality traits extraction
    # Note: JobBERT scores lower on soft skills (model trained for hard skills)
    print("\n⏳ Extracting personality traits...")
    print("   (Note: JobBERT optimized for hard skills, soft skill scores are lower)")
    personality = extract_with_evidence(
        model, SAMPLE_VACANCY, PERSONALITY_TAXONOMY,
        threshold=0.18, top_n=10  # Lower threshold for soft skills
    )
    print_section("PERSONALITY TRAITS (lower scores expected)", personality)

    # 5. Similarity matrix
    print("\n⏳ Computing job similarity matrix...")
    similarity_results = get_similarity_results(model, "Logistics Supervisor", JOB_TITLES[1:])
    print_similarity_matrix(model, "Logistics Supervisor", JOB_TITLES[1:])

    # 6. Generate Markdown report
    print("\n⏳ Generating Markdown report...")
    output_file = generate_markdown_report(
        vacancy_title="Logistics Supervisor",
        company="International Manufacturing Company",
        location="Zedelgem, Belgium",
        skills=skills,
        diplomas=diplomas,
        certificates=certificates,
        personality=personality,
        similarity_results=similarity_results,
        output_file="scripts/vacancy_report.md"
    )
    print(f"  ✓ Report saved to: {output_file}")

    # Summary
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " SUMMARY ".center(68) + "║")
    print("╚" + "═" * 68 + "╝")

    print(f"""
  Skills extracted:        {len(skills):>3} (threshold: 0.42)
  Education matches:       {len(diplomas):>3} (threshold: 0.35)
  Certificates matches:    {len(certificates):>3} (threshold: 0.35)
  Personality traits:      {len(personality):>3} (threshold: 0.18, lower for soft skills)

  Most similar roles:
    1. {similarity_results[0][0]} ({similarity_results[0][1]:.2f})
    2. {similarity_results[1][0]} ({similarity_results[1][1]:.2f})
    3. {similarity_results[2][0]} ({similarity_results[2][1]:.2f})

  📄 Markdown report: {output_file}

  ✅ Analysis complete!
""")


if __name__ == "__main__":
    main()
