"""
Seed ats.types_documents from docs/prato_flex_codes.md.

Parses the Prato Flex certificate types (kind 43) and detail types (kind 44)
from the markdown reference and upserts them into the database.

Usage:
    python scripts/seed_prato_flex_document_types.py

Can also be imported and called programmatically:
    from scripts.seed_prato_flex_document_types import seed_prato_flex_document_types
    await seed_prato_flex_document_types(pool, workspace_id)
"""
import asyncio
import re
import uuid
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# ─── Category & metadata mappings for parent types ────────────────────────────
# Maps prato_flex_type_id → (category, icon, is_verifiable, requires_front_back, is_default)

PARENT_TYPE_CONFIG = {
    # Identity documents
    "4":   ("identity",    "book-open",       True,  False, False),  # Paspoort
    "7":   ("identity",    "credit-card",     True,  False, False),  # Voorlopige identiteitskaart
    "101": ("identity",    "id-card",         True,  False, False),  # Verblijfsdocument - vrijstelling
    "102": ("identity",    "id-card",         True,  False, False),  # Verblijfsdocument - bijkomstige
    "805": ("identity",    "hash",            False, False, False),  # BSN-nummer

    # Certificate / work-related
    "1":   ("certificate", "shield-check",    True,  False, False),  # Basisveiligheid VCA
    "3":   ("certificate", "syringe",         True,  False, False),  # Inenting
    "5":   ("certificate", "file-badge",      True,  False, False),  # Werkvergunning
    "6":   ("certificate", "forklift",        True,  False, False),  # Heftruckbrevet
    "8":   ("certificate", "map-pin",         True,  False, False),  # Grensarbeider
    "9":   ("certificate", "file-badge",      True,  False, False),  # Vrijstelling arbeidskaart
    "10":  ("certificate", "car",             True,  True,  False),  # Rijbewijs
    "11":  ("certificate", "heart-pulse",     True,  False, False),  # Medische schifting
    "17":  ("certificate", "clipboard-list",  False, False, False),  # Medische vragenlijst
    "20":  ("certificate", "file-badge",      True,  False, False),  # Arbeidskaart
    "24":  ("certificate", "hard-hat",        True,  False, False),  # Attesten bouw
    "103": ("certificate", "file-badge",      True,  False, False),  # Arbeidskaart (variant)
    "810": ("certificate", "calendar-check",  True,  False, False),  # VakantieAttest
    "811": ("certificate", "shield-alert",    False, False, False),  # Risico's medisch onderzoek

    # Financial
    "12":  ("financial",   "briefcase",       False, False, False),  # Banenplanners
    "13":  ("financial",   "ticket",          False, False, False),  # Dienstencheque
    "14":  ("financial",   "banknote",        False, False, False),  # Voorschot
    "15":  ("financial",   "file-text",       True,  False, False),  # C32-afdruk
    "16":  ("financial",   "calendar",        False, False, False),  # Jobstudent, dagen
    "19":  ("financial",   "mail",            False, False, False),  # Extra mededeling betaling
    "21":  ("financial",   "percent",         False, False, False),  # Recht op vermindering
    "26":  ("financial",   "file-text",       True,  False, False),  # C 3.2 Attest
    "30":  ("financial",   "clock",           False, False, False),  # Uitbetaling overuur
    "800": ("financial",   "calculator",      False, False, False),  # RSZ-verminderingen
    "806": ("financial",   "calendar",        False, False, False),  # Jobstudenten uren contingent
    "812": ("financial",   "percent",         False, False, False),  # BV percentage Flexi

    # Other
    "18":  ("other",       "graduation-cap",  False, False, False),  # Vrijstelling BV schoolverlater
    "25":  ("other",       "file-x",          False, False, False),  # Opzegging vaste job
    "801": ("other",       "utensils",        False, False, False),  # Horeca@Work
    "802": ("other",       "tractor",         False, False, False),  # Gelegenheidsformulier landbouw
    "803": ("other",       "flower-2",        False, False, False),  # Gelegenheidsformulier tuinbouw
    "807": ("other",       "book-open",       False, False, False),  # Vlaams opleidingsverlof
    "808": ("other",       "home",            False, False, False),  # Woonplaatsverklaring
    "809": ("other",       "thermometer",     False, False, False),  # Ziektemelding
    "BV01":("other",       "baby",            False, False, False),  # Borstvoedingsverlof
    "WT01":("other",       "x-circle",        False, False, False),  # Weigering bijkomende tewerkstelling
}


def parse_prato_flex_markdown(md_path: str) -> tuple[list[dict], dict[str, list[dict]]]:
    """
    Parse prato_flex_codes.md and return:
      - parent_types: list of {id, description}
      - children_by_parent: dict mapping parent_type_id -> [{id, description}, ...]
    """
    with open(md_path, "r") as f:
        content = f.read()

    # Parse parent types (kind 43)
    parent_section = content.split("## Certificate Types (kind 43)")[1].split("## Certificate Detail Types (kind 44)")[0]
    parent_types = []
    for match in re.finditer(r"\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|", parent_section):
        type_id = match.group(1).strip()
        desc = match.group(2).strip()
        if type_id in ("ID", "-----", "---"):
            continue
        parent_types.append({"id": type_id, "description": desc})

    # Parse child/detail types (kind 44) grouped by parent
    children_by_parent: dict[str, list[dict]] = {}
    detail_section = content.split("## Certificate Detail Types (kind 44)")[1]

    # Split by "### Type X:" headers
    type_blocks = re.split(r"### Type (\d+):", detail_section)
    # type_blocks[0] is preamble, then alternating: type_id, block_content
    for i in range(1, len(type_blocks), 2):
        parent_type_id = type_blocks[i].strip()
        block = type_blocks[i + 1] if i + 1 < len(type_blocks) else ""
        children = []
        for match in re.finditer(r"\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|", block):
            child_id = match.group(1).strip()
            child_desc = match.group(2).strip()
            if child_id in ("ID", "-----", "---"):
                continue
            children.append({"id": child_id, "description": child_desc})
        children_by_parent[parent_type_id] = children

    return parent_types, children_by_parent


def make_slug(prato_type_id: str, description: str) -> str:
    """Create a URL-safe slug from the Prato type ID and description."""
    return f"prato_{prato_type_id}"


async def seed_prato_flex_document_types(pool, workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID) -> dict:
    """
    Seed Prato Flex certificate types into ats.types_documents.

    Uses ON CONFLICT (workspace_id, slug) DO UPDATE to be idempotent.

    Returns:
        Dict with counts of parents and children created/updated.
    """
    md_path = os.path.join(os.path.dirname(__file__), "..", "docs", "prato_flex_codes.md")
    parent_types, children_by_parent = parse_prato_flex_markdown(md_path)

    parents_upserted = 0
    children_upserted = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            # First ensure the 7 basic defaults exist (from seed_document_type_defaults)
            try:
                await conn.execute("SELECT ats.seed_document_type_defaults($1)", workspace_id)
            except Exception:
                pass  # Function may not exist yet

            # Track parent slug -> DB id for linking children
            parent_slug_to_id: dict[str, uuid.UUID] = {}

            # Upsert parent types
            for sort_order, pt in enumerate(parent_types):
                type_id = pt["id"]
                desc = pt["description"]
                slug = make_slug(type_id, desc)

                config = PARENT_TYPE_CONFIG.get(type_id, ("other", "file", False, False, False))
                category, icon, is_verifiable, requires_front_back, is_default = config

                row = await conn.fetchrow("""
                    INSERT INTO ats.types_documents
                        (workspace_id, slug, name, category, icon,
                         is_verifiable, requires_front_back, is_default,
                         sort_order, prato_flex_type_id, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true)
                    ON CONFLICT (workspace_id, slug)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        icon = COALESCE(ats.types_documents.icon, EXCLUDED.icon),
                        is_verifiable = EXCLUDED.is_verifiable,
                        requires_front_back = EXCLUDED.requires_front_back,
                        sort_order = EXCLUDED.sort_order,
                        prato_flex_type_id = EXCLUDED.prato_flex_type_id,
                        is_active = true,
                        updated_at = NOW()
                    RETURNING id
                """,
                    workspace_id, slug, desc, category, icon,
                    is_verifiable, requires_front_back, is_default,
                    sort_order, type_id,
                )
                parent_slug_to_id[type_id] = row["id"]
                parents_upserted += 1

            # Upsert child/detail types
            for parent_type_id, children in children_by_parent.items():
                parent_db_id = parent_slug_to_id.get(parent_type_id)
                if not parent_db_id:
                    logger.warning(f"Parent type {parent_type_id} not found in DB, skipping children")
                    continue

                # Get parent category for children
                parent_config = PARENT_TYPE_CONFIG.get(parent_type_id, ("other", "file", False, False, False))
                parent_category = parent_config[0]

                for sort_order, child in enumerate(children):
                    child_id = child["id"]
                    child_desc = child["description"]
                    child_slug = f"prato_{parent_type_id}_{child_id}"

                    row = await conn.fetchrow("""
                        INSERT INTO ats.types_documents
                            (workspace_id, slug, name, category,
                             parent_id, prato_flex_type_id, prato_flex_detail_type_id,
                             sort_order, is_active)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, true)
                        ON CONFLICT (workspace_id, slug)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            category = EXCLUDED.category,
                            parent_id = EXCLUDED.parent_id,
                            prato_flex_type_id = EXCLUDED.prato_flex_type_id,
                            prato_flex_detail_type_id = EXCLUDED.prato_flex_detail_type_id,
                            sort_order = EXCLUDED.sort_order,
                            is_active = true,
                            updated_at = NOW()
                        RETURNING id
                    """,
                        workspace_id, child_slug, child_desc, parent_category,
                        parent_db_id, parent_type_id, child_id,
                        sort_order,
                    )
                    children_upserted += 1

    logger.info(f"Prato Flex seed complete: {parents_upserted} parents, {children_upserted} children")
    return {
        "parents_upserted": parents_upserted,
        "children_upserted": children_upserted,
    }


async def main():
    """Run as standalone script."""
    from dotenv import load_dotenv
    load_dotenv()

    from src.database import get_db_pool

    logging.basicConfig(level=logging.INFO)

    pool = await get_db_pool()
    result = await seed_prato_flex_document_types(pool)
    print(f"Done! {result['parents_upserted']} parent types, {result['children_upserted']} child types seeded.")


if __name__ == "__main__":
    asyncio.run(main())
