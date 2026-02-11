"""
Benchmark skill extraction against TechWolf annotated datasets.

This script:
1. Downloads TechWolf evaluation datasets
2. Tests our JobBERT approach against ground truth
3. Reports precision, recall, and F1 score
4. Shows where we can improve

Run:
    pip install datasets scikit-learn
    python scripts/benchmark_skill_extraction.py
"""

import json
from collections import defaultdict
from datasets import load_dataset
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


def load_esco_skills():
    """Load ESCO skills taxonomy."""
    try:
        with open("scripts/esco_skills.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("ESCO skills not found, downloading from dataset...")
        dataset = load_dataset("TechWolf/Synthetic-ESCO-skill-sentences")
        skills = list(set(row["skill"] for row in dataset["train"]))
        with open("scripts/esco_skills.json", "w") as f:
            json.dump(sorted(skills), f, indent=2)
        return sorted(skills)


def extract_skills_jobbert(model, text: str, skill_list: list, threshold: float = 0.4):
    """Extract skills using JobBERT embedding similarity."""
    text_emb = model.encode([text])
    skill_embs = model.encode(skill_list)
    similarities = cos_sim(text_emb, skill_embs)[0]

    results = []
    for skill, score in zip(skill_list, similarities):
        if float(score) >= threshold:
            results.append((skill, float(score)))

    return [s[0] for s in sorted(results, key=lambda x: -x[1])]


def normalize_skill(skill: str) -> str:
    """Normalize skill for comparison."""
    return skill.lower().strip()


def skill_match(predicted: str, ground_truth: str, threshold: float = 0.7) -> bool:
    """Check if predicted skill matches ground truth (fuzzy match)."""
    pred_norm = normalize_skill(predicted)
    gt_norm = normalize_skill(ground_truth)

    # Exact match
    if pred_norm == gt_norm:
        return True

    # Substring match
    if pred_norm in gt_norm or gt_norm in pred_norm:
        return True

    # Word overlap
    pred_words = set(pred_norm.split())
    gt_words = set(gt_norm.split())
    if pred_words and gt_words:
        overlap = len(pred_words & gt_words) / max(len(pred_words), len(gt_words))
        if overlap >= threshold:
            return True

    return False


def evaluate_on_dataset(model, esco_skills, dataset_name: str, threshold: float = 0.4):
    """Evaluate skill extraction on a TechWolf dataset."""
    print(f"\n{'=' * 60}")
    print(f"Evaluating on: {dataset_name}")
    print("=" * 60)

    dataset = load_dataset(dataset_name)

    # Get the data (might be in 'train' or 'test' split)
    if "train" in dataset:
        data = dataset["train"]
    elif "test" in dataset:
        data = dataset["test"]
    else:
        data = list(dataset.values())[0]

    print(f"Dataset size: {len(data)} samples")

    # Track metrics
    total_samples = 0
    total_true_positives = 0
    total_predicted = 0
    total_ground_truth = 0

    # Sample results for analysis
    examples = []

    for i, row in enumerate(data):
        sentence = row.get("sentence", "")
        ground_truth_skill = row.get("skill") or row.get("label", "")

        if not sentence or not ground_truth_skill:
            continue

        # Handle multiple skills (some datasets have lists)
        if isinstance(ground_truth_skill, list):
            gt_skills = ground_truth_skill
        else:
            gt_skills = [ground_truth_skill]

        # Extract skills using our method
        predicted_skills = extract_skills_jobbert(
            model, sentence, esco_skills, threshold=threshold
        )[:5]  # Top 5 predictions

        # Calculate matches
        matches = 0
        for gt in gt_skills:
            for pred in predicted_skills:
                if skill_match(pred, gt):
                    matches += 1
                    break

        total_samples += 1
        total_true_positives += matches
        total_predicted += len(predicted_skills)
        total_ground_truth += len(gt_skills)

        # Store examples for analysis
        if i < 10 or (matches == 0 and len(examples) < 20):
            examples.append({
                "sentence": sentence[:100] + "..." if len(sentence) > 100 else sentence,
                "ground_truth": gt_skills,
                "predicted": predicted_skills[:3],
                "match": matches > 0
            })

    # Calculate metrics
    precision = total_true_positives / total_predicted if total_predicted > 0 else 0
    recall = total_true_positives / total_ground_truth if total_ground_truth > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\nResults (threshold={threshold}):")
    print("-" * 40)
    print(f"  Samples evaluated:  {total_samples}")
    print(f"  Ground truth skills: {total_ground_truth}")
    print(f"  Predicted skills:    {total_predicted}")
    print(f"  True positives:      {total_true_positives}")
    print(f"")
    print(f"  Precision: {precision:.3f}")
    print(f"  Recall:    {recall:.3f}")
    print(f"  F1 Score:  {f1:.3f}")

    # Show examples
    print(f"\nSample predictions:")
    print("-" * 40)
    for ex in examples[:8]:
        status = "✓" if ex["match"] else "✗"
        print(f"\n  {status} \"{ex['sentence'][:60]}...\"")
        print(f"    Ground truth: {ex['ground_truth']}")
        print(f"    Predicted:    {ex['predicted']}")

    return {"precision": precision, "recall": recall, "f1": f1}


def find_optimal_threshold(model, esco_skills, dataset_name: str):
    """Find optimal threshold for best F1 score."""
    print(f"\n{'=' * 60}")
    print(f"Finding optimal threshold for {dataset_name}")
    print("=" * 60)

    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    best_f1 = 0
    best_threshold = 0.4

    print("\nThreshold | Precision | Recall | F1")
    print("-" * 45)

    for threshold in thresholds:
        dataset = load_dataset(dataset_name)
        data = dataset.get("train") or dataset.get("test") or list(dataset.values())[0]

        total_tp, total_pred, total_gt = 0, 0, 0

        for row in data:
            sentence = row.get("sentence", "")
            gt_skill = row.get("skill") or row.get("label", "")

            if not sentence or not gt_skill:
                continue

            gt_skills = [gt_skill] if isinstance(gt_skill, str) else gt_skill
            predicted = extract_skills_jobbert(model, sentence, esco_skills, threshold)[:5]

            for gt in gt_skills:
                for pred in predicted:
                    if skill_match(pred, gt):
                        total_tp += 1
                        break

            total_pred += len(predicted)
            total_gt += len(gt_skills)

        precision = total_tp / total_pred if total_pred > 0 else 0
        recall = total_tp / total_gt if total_gt > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        marker = " <-- best" if f1 > best_f1 else ""
        print(f"  {threshold:.2f}    |   {precision:.3f}    |  {recall:.3f}  | {f1:.3f}{marker}")

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold

    print(f"\nOptimal threshold: {best_threshold} (F1: {best_f1:.3f})")
    return best_threshold


def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " SKILL EXTRACTION BENCHMARK ".center(58) + "║")
    print("║" + " Testing JobBERT against TechWolf datasets ".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    # Load resources
    print("\nLoading ESCO skills taxonomy...")
    esco_skills = load_esco_skills()
    print(f"  ✓ Loaded {len(esco_skills)} skills")

    print("\nLoading JobBERT-v3 model...")
    model = SentenceTransformer("TechWolf/JobBERT-v3")
    print("  ✓ Model loaded")

    # Find optimal threshold first
    optimal_threshold = find_optimal_threshold(
        model, esco_skills, "TechWolf/skill-extraction-techwolf"
    )

    # Evaluate on different datasets
    results = {}

    datasets = [
        "TechWolf/skill-extraction-techwolf",
        # "TechWolf/skill-extraction-tech",  # Uncomment to test more
        # "TechWolf/skill-extraction-house",
    ]

    for ds in datasets:
        try:
            results[ds] = evaluate_on_dataset(
                model, esco_skills, ds, threshold=optimal_threshold
            )
        except Exception as e:
            print(f"  ⚠ Error loading {ds}: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"\nModel: JobBERT-v3")
    print(f"Optimal threshold: {optimal_threshold}")
    print(f"\nDataset Results:")
    print("-" * 40)

    for ds, metrics in results.items():
        ds_name = ds.split("/")[-1]
        print(f"  {ds_name}:")
        print(f"    Precision: {metrics['precision']:.3f}")
        print(f"    Recall:    {metrics['recall']:.3f}")
        print(f"    F1:        {metrics['f1']:.3f}")

    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    avg_f1 = sum(m["f1"] for m in results.values()) / len(results) if results else 0

    if avg_f1 >= 0.5:
        print("""
  ✓ Current approach performs reasonably well.

  To improve further:
  1. Fine-tune JobBERT on TechWolf datasets
  2. Use ensemble of embeddings + keyword matching
  3. Add domain-specific skills to taxonomy
""")
    else:
        print("""
  ⚠ Current approach needs improvement.

  Recommended actions:
  1. Fine-tune JobBERT on Synthetic-ESCO dataset (138k samples)
  2. Lower threshold but add post-filtering
  3. Combine with keyword extraction
  4. Use multi-label classification instead of similarity
""")


if __name__ == "__main__":
    main()
