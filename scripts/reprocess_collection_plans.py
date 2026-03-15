"""
Re-generate collection plans for all active document collections.

Useful after updating the planner system instruction or prompt template.
Only regenerates the plan — does NOT reset conversation state or agent_state.

Usage:
    python scripts/reprocess_collection_plans.py
    python scripts/reprocess_collection_plans.py --dry-run   # preview without updating
"""
import asyncio
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.database import get_db_pool
from agents.document_collection.smart_collection_planner import generate_collection_plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def reprocess_all():
    dry_run = "--dry-run" in sys.argv

    pool = await get_db_pool()

    # Fetch all active collections
    rows = await pool.fetch(
        """
        SELECT id, workspace_id, vacancy_id, candidate_id, candidacy_id,
               candidate_name, collection_plan
        FROM agents.document_collections
        WHERE status = 'active'
        ORDER BY updated_at DESC
        """
    )

    if not rows:
        logger.info("No active collections found.")
        await pool.close()
        return

    logger.info(f"Found {len(rows)} active collection(s)")

    # Look up placement info per candidacy for regime/start_date
    for row in rows:
        collection_id = row["id"]
        candidate_name = row["candidate_name"]
        vacancy_id = row["vacancy_id"]
        candidate_id = row["candidate_id"]
        workspace_id = row["workspace_id"]

        logger.info(f"\n{'='*60}")
        logger.info(f"Collection {collection_id} — {candidate_name}")

        if not vacancy_id or not candidate_id:
            logger.warning(f"  Skipping: missing vacancy_id or candidate_id")
            continue

        # Get placement info for regime/start_date
        placement = await pool.fetchrow(
            """
            SELECT start_date, regime
            FROM ats.placements
            WHERE candidate_id = $1 AND vacancy_id = $2
            ORDER BY created_at DESC LIMIT 1
            """,
            candidate_id, vacancy_id,
        )

        start_date = placement["start_date"] if placement else None
        regime = placement["regime"] if placement else None

        try:
            plan = await generate_collection_plan(
                pool=pool,
                vacancy_id=vacancy_id,
                candidate_id=candidate_id,
                workspace_id=workspace_id,
                start_date=start_date,
                regime=regime,
            )
        except Exception as e:
            logger.error(f"  Failed to generate plan: {e}")
            continue

        steps = plan.get("conversation_flow", [])
        attrs_from_docs = plan.get("attributes_from_documents", [])
        logger.info(f"  New plan: {len(steps)} steps, {len(attrs_from_docs)} auto-extract attrs")
        logger.info(f"  Steps: {[s['type'] for s in steps]}")
        logger.info(f"  Summary: {plan.get('summary', '—')}")

        # Extract document slugs from conversation_flow for documents_required
        doc_slugs = []
        for step in steps:
            if step.get("type") == "collect_documents":
                for item in step.get("items", []):
                    doc_slugs.append({"slug": item["slug"], "priority": item.get("priority", "required")})

        if dry_run:
            logger.info(f"  [DRY RUN] Would update collection_plan, documents_required, and clear agent_state")
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            continue

        # Update collection_plan and documents_required, clear agent_state
        # (old agent_state format is incompatible with new conversation_flow agent)
        await pool.execute(
            """
            UPDATE agents.document_collections
            SET collection_plan = $1::jsonb,
                documents_required = $2::jsonb,
                agent_state = NULL,
                updated_at = now()
            WHERE id = $3
            """,
            json.dumps(plan),
            json.dumps(doc_slugs),
            collection_id,
        )
        logger.info(f"  Updated (agent_state cleared).")

    logger.info(f"\n{'='*60}")
    logger.info(f"Done. {'(dry run — nothing updated)' if dry_run else ''}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(reprocess_all())
