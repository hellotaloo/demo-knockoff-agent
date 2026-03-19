"""
Clients router - handles client listing for the Klanten overview.
"""
import logging
from fastapi import APIRouter, Depends, Query
from typing import Optional

from src.auth.dependencies import AuthContext, require_workspace
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["Clients"])


@router.get("")
async def list_clients(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, description="Search by name, location, or industry"),
    ctx: AuthContext = Depends(require_workspace),
):
    """List all clients for the current workspace with vacancy/candidate counts."""
    pool = await get_db_pool()

    conditions = ["c.workspace_id = $1"]
    params = [ctx.workspace_id]
    param_idx = 2

    if search:
        conditions.append(f"(c.name ILIKE ${param_idx} OR c.location ILIKE ${param_idx} OR c.industry ILIKE ${param_idx})")
        params.append(f"%{search}%")
        param_idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}"

    count_query = f"SELECT COUNT(*) FROM ats.clients c {where_clause}"
    total = await pool.fetchval(count_query, *params)

    query = f"""
        SELECT
            c.id, c.name, c.location, c.industry, c.logo,
            c.contact_name, c.contact_email, c.contact_phone,
            c.website, c.notes,
            c.created_at, c.updated_at,
            COALESCE(v_stats.active_vacancies, 0) as active_vacancies,
            COALESCE(v_stats.total_candidates, 0) as total_candidates
        FROM ats.clients c
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled')) as active_vacancies,
                (SELECT COUNT(DISTINCT cd.candidate_id)
                 FROM ats.candidacies cd
                 WHERE cd.vacancy_id IN (SELECT v2.id FROM ats.vacancies v2 WHERE v2.client_id = c.id)
                ) as total_candidates
            FROM ats.vacancies v
            WHERE v.client_id = c.id
        ) v_stats ON true
        {where_clause}
        ORDER BY c.name ASC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])

    rows = await pool.fetch(query, *params)

    items = [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "location": r["location"],
            "industry": r["industry"],
            "logo": r["logo"],
            "contact_name": r["contact_name"],
            "contact_email": r["contact_email"],
            "contact_phone": r["contact_phone"],
            "website": r["website"],
            "notes": r["notes"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "active_vacancies": r["active_vacancies"],
            "total_candidates": r["total_candidates"],
        }
        for r in rows
    ]

    return {"items": items, "total": total, "limit": limit, "offset": offset}
