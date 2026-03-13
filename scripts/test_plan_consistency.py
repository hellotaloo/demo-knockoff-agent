"""Run plan generation N times and compare outputs for consistency."""
import asyncio
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CANDIDATE_ID = uuid.UUID("ff6a8d8e-5902-48a0-b222-bd090309fdc9")
VACANCY_ID = uuid.UUID("34cec365-5ae8-4ec1-bc50-1d3485bff35a")
NUM_RUNS = 10


async def main():
    from src.database import get_db_pool
    from agents.document_collection.smart_collection_planner import generate_collection_plan

    pool = await get_db_pool()
    start_date = date.today() + timedelta(days=7)

    plans = []
    for i in range(NUM_RUNS):
        print(f"\n{'='*60}")
        print(f"RUN {i+1}/{NUM_RUNS}")
        print(f"{'='*60}")
        try:
            plan = await generate_collection_plan(
                pool=pool,
                vacancy_id=VACANCY_ID,
                candidate_id=CANDIDATE_ID,
                start_date=start_date,
            )
            plans.append(plan)

            docs = sorted([d["slug"] if isinstance(d, dict) else d for d in plan.get("documents_to_collect", [])])
            attrs = sorted([a["slug"] if isinstance(a, dict) else a for a in plan.get("attributes_to_collect", [])])
            tasks = sorted([t["slug"] if isinstance(t, dict) else t for t in plan.get("agent_managed_tasks", [])])
            steps = len(plan.get("conversation_steps", []))

            print(f"  Documents ({len(docs)}): {docs}")
            print(f"  Attributes ({len(attrs)}): {attrs}")
            print(f"  Tasks ({len(tasks)}): {tasks}")
            print(f"  Conversation steps: {steps}")
        except Exception as e:
            print(f"  ERROR: {e}")
            plans.append(None)

    # Compare
    print(f"\n{'='*60}")
    print("CONSISTENCY ANALYSIS")
    print(f"{'='*60}")

    valid_plans = [p for p in plans if p is not None]
    print(f"Successful runs: {len(valid_plans)}/{NUM_RUNS}")

    if not valid_plans:
        print("No valid plans to compare.")
        await pool.close()
        return

    # Extract keys for comparison
    def extract_keys(plan):
        docs = tuple(sorted([d["slug"] if isinstance(d, dict) else d for d in plan.get("documents_to_collect", [])]))
        attrs = tuple(sorted([a["slug"] if isinstance(a, dict) else a for a in plan.get("attributes_to_collect", [])]))
        tasks = tuple(sorted([t["slug"] if isinstance(t, dict) else t for t in plan.get("agent_managed_tasks", [])]))
        return docs, attrs, tasks

    signatures = [extract_keys(p) for p in valid_plans]

    # Check document consistency
    all_doc_sets = [s[0] for s in signatures]
    unique_doc_sets = set(all_doc_sets)
    print(f"\nUnique document sets: {len(unique_doc_sets)}")
    for i, ds in enumerate(unique_doc_sets):
        count = all_doc_sets.count(ds)
        print(f"  Set {i+1} ({count}x): {list(ds)}")

    # Check attribute consistency
    all_attr_sets = [s[1] for s in signatures]
    unique_attr_sets = set(all_attr_sets)
    print(f"\nUnique attribute sets: {len(unique_attr_sets)}")
    for i, a_s in enumerate(unique_attr_sets):
        count = all_attr_sets.count(a_s)
        print(f"  Set {i+1} ({count}x): {list(a_s)}")

    # Check task consistency
    all_task_sets = [s[2] for s in signatures]
    unique_task_sets = set(all_task_sets)
    print(f"\nUnique task sets: {len(unique_task_sets)}")
    for i, ts in enumerate(unique_task_sets):
        count = all_task_sets.count(ts)
        print(f"  Set {i+1} ({count}x): {list(ts)}")

    # Overall
    unique_signatures = set(signatures)
    print(f"\nOverall unique plans: {len(unique_signatures)}/{len(valid_plans)}")
    if len(unique_signatures) == 1:
        print("✅ FULLY CONSISTENT — all runs produced identical structure")
    else:
        print("⚠️  INCONSISTENT — plans differ across runs")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
