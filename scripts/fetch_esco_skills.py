"""
Fetch ESCO skills from TechWolf dataset.

Run:
    pip install datasets
    python scripts/fetch_esco_skills.py
"""

from datasets import load_dataset
import json


def main():
    print("Loading TechWolf Synthetic-ESCO-skill-sentences dataset...")
    print("(This downloads ~19MB on first run)\n")

    dataset = load_dataset("TechWolf/Synthetic-ESCO-skill-sentences")
    train_data = dataset["train"]

    print(f"Total entries: {len(train_data)}")

    # Extract unique skills
    skills = set()
    for example in train_data:
        skills.add(example["skill"])

    skills = sorted(skills)
    print(f"Unique ESCO skills: {len(skills)}")

    # Show some examples
    print("\n" + "=" * 60)
    print("Sample ESCO Skills (first 50)")
    print("=" * 60)
    for skill in skills[:50]:
        print(f"  - {skill}")

    # Categorize by common patterns
    print("\n" + "=" * 60)
    print("Skills containing common keywords")
    print("=" * 60)

    keywords = {
        "customer": [],
        "manage": [],
        "communicate": [],
        "technical": [],
        "software": [],
        "safety": [],
        "quality": [],
        "team": [],
        "logistics": [],
        "production": [],
    }

    for skill in skills:
        skill_lower = skill.lower()
        for keyword in keywords:
            if keyword in skill_lower:
                keywords[keyword].append(skill)
                break

    for keyword, matched in keywords.items():
        if matched:
            print(f"\n{keyword.upper()} ({len(matched)} skills):")
            for s in matched[:5]:
                print(f"    - {s}")
            if len(matched) > 5:
                print(f"    ... and {len(matched) - 5} more")

    # Save to JSON for later use
    output_file = "scripts/esco_skills.json"
    with open(output_file, "w") as f:
        json.dump(skills, f, indent=2)

    print(f"\n✅ Saved {len(skills)} skills to {output_file}")


if __name__ == "__main__":
    main()
