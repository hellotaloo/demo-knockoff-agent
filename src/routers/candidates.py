"""
Candidates router - handles candidate listing and management.
"""
import uuid
import logging
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, Query, HTTPException

from src.database import get_db_pool
from src.repositories import CandidateRepository
from src.services import ActivityService
from src.models.candidate import (
    CandidateStatus,
    AvailabilityStatus,
    CandidateListResponse,
    CandidateSkillResponse,
    CandidateWithApplicationsResponse,
    CandidateApplicationSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/candidates", tags=["Candidates"])


@router.get("", response_model=list[CandidateListResponse])
async def list_candidates(
    limit: int = Query(50, ge=1, le=100, description="Number of candidates to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    status: Optional[CandidateStatus] = Query(None, description="Filter by status"),
    availability: Optional[AvailabilityStatus] = Query(None, description="Filter by availability"),
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    is_test: Optional[bool] = Query(None, description="Filter by test flag: true for test candidates, false for real ones"),
    sort_by: str = Query("status", description="Sort by: status, name, last_activity, rating, availability"),
    sort_order: str = Query("asc", description="Sort order: asc or desc"),
):
    """
    Get list of candidates with skills, vacancy count, and last activity.
    Used for the candidates overview page.
    Use is_test=true to see test candidates, is_test=false for real ones.
    """
    pool = await get_db_pool()
    repo = CandidateRepository(pool)

    # Get candidates with computed fields
    candidates = await repo.get_list(
        limit=limit,
        offset=offset,
        status=status.value if status else None,
        availability=availability.value if availability else None,
        search=search,
        is_test=is_test,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    if not candidates:
        return []

    # Batch load skills for all candidates
    candidate_ids = [c["id"] for c in candidates]
    all_skills = await repo.get_skills_for_candidates(candidate_ids)

    # Group skills by candidate_id
    skills_by_candidate = defaultdict(list)
    for skill in all_skills:
        skills_by_candidate[skill["candidate_id"]].append(
            CandidateSkillResponse(
                id=str(skill["id"]),
                skill_name=skill["skill_name"],
                skill_code=skill["skill_code"],
                skill_category=skill["skill_category"],
                score=float(skill["score"]) if skill["score"] else None,
                evidence=skill["evidence"],
                source=skill["source"] or "manual",
                created_at=skill["created_at"],
            )
        )

    # Build response
    result = []
    for c in candidates:
        result.append(
            CandidateListResponse(
                id=str(c["id"]),
                phone=c["phone"],
                email=c["email"],
                first_name=c["first_name"],
                last_name=c["last_name"],
                full_name=c["full_name"],
                source=c["source"],
                status=CandidateStatus(c["status"]) if c["status"] else CandidateStatus.NEW,
                status_updated_at=c["status_updated_at"],
                availability=AvailabilityStatus(c["availability"]) if c["availability"] else AvailabilityStatus.UNKNOWN,
                available_from=c["available_from"],
                rating=float(c["rating"]) if c["rating"] else None,
                is_test=c["is_test"] if c["is_test"] is not None else False,
                created_at=c["created_at"],
                updated_at=c["updated_at"],
                skills=skills_by_candidate.get(c["id"], []),
                vacancy_count=c["vacancy_count"],
                last_activity=c["last_activity"],
            )
        )

    return result


@router.get("/{candidate_id}", response_model=CandidateWithApplicationsResponse)
async def get_candidate(candidate_id: uuid.UUID):
    """Get a single candidate with their applications, skills, and activity timeline."""
    pool = await get_db_pool()
    repo = CandidateRepository(pool)

    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Get applications, skills, and timeline
    applications = await repo.get_applications(candidate_id)
    skills = await repo.get_skills(candidate_id)

    # Get activity timeline
    activity_service = ActivityService(pool)
    timeline_response = await activity_service.get_candidate_timeline(str(candidate_id), limit=50)

    return CandidateWithApplicationsResponse(
        id=str(candidate["id"]),
        phone=candidate["phone"],
        email=candidate["email"],
        first_name=candidate["first_name"],
        last_name=candidate["last_name"],
        full_name=candidate["full_name"],
        source=candidate["source"],
        status=CandidateStatus(candidate["status"]) if candidate["status"] else CandidateStatus.NEW,
        status_updated_at=candidate["status_updated_at"],
        availability=AvailabilityStatus(candidate["availability"]) if candidate["availability"] else AvailabilityStatus.UNKNOWN,
        available_from=candidate["available_from"],
        rating=float(candidate["rating"]) if candidate["rating"] else None,
        is_test=candidate["is_test"] if candidate["is_test"] is not None else False,
        created_at=candidate["created_at"],
        updated_at=candidate["updated_at"],
        applications=[
            CandidateApplicationSummary(
                id=str(a["id"]),
                vacancy_id=str(a["vacancy_id"]),
                vacancy_title=a["vacancy_title"],
                vacancy_company=a["vacancy_company"],
                channel=a["channel"],
                status=a["status"],
                qualified=a["qualified"],
                started_at=a["started_at"],
                completed_at=a["completed_at"],
            )
            for a in applications
        ],
        skills=[
            CandidateSkillResponse(
                id=str(s["id"]),
                skill_name=s["skill_name"],
                skill_code=s["skill_code"],
                skill_category=s["skill_category"],
                score=float(s["score"]) if s["score"] else None,
                evidence=s["evidence"],
                source=s["source"] or "manual",
                created_at=s["created_at"],
            )
            for s in skills
        ],
        timeline=timeline_response.activities,
    )


@router.patch("/{candidate_id}/status")
async def update_candidate_status(
    candidate_id: uuid.UUID,
    status: CandidateStatus,
):
    """Update a candidate's status."""
    pool = await get_db_pool()
    repo = CandidateRepository(pool)

    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    await repo.update_status(candidate_id, status.value)

    return {"status": "success", "candidate_id": str(candidate_id), "new_status": status.value}


@router.patch("/{candidate_id}/rating")
async def update_candidate_rating(
    candidate_id: uuid.UUID,
    rating: float = Query(..., ge=0, le=5, description="Rating from 0 to 5"),
):
    """Update a candidate's rating."""
    pool = await get_db_pool()
    repo = CandidateRepository(pool)

    candidate = await repo.get_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    await repo.update_rating(candidate_id, rating)

    return {"status": "success", "candidate_id": str(candidate_id), "new_rating": rating}
