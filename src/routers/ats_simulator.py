"""
ATS Simulator router.

Simulates an external Applicant Tracking System (e.g., Salesforce) API.
Serves fixture data through realistic REST endpoints.
This is NOT a Taloo endpoint — it pretends to be a third-party ATS.
"""
import hashlib
import logging
from fastapi import APIRouter, Query
from fixtures import load_vacancies, load_recruiters, load_clients
from src.models.ats_simulator import (
    ATSVacancy,
    ATSRecruiter,
    ATSClient,
    ATSVacancyListResponse,
    ATSRecruiterListResponse,
    ATSClientListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ats-simulator", tags=["ATS Simulator"])


@router.get("/api/v1/vacancies", response_model=ATSVacancyListResponse)
async def list_vacancies(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: str | None = Query(None, description="Filter by status: active, inactive, draft"),
):
    """List all vacancies in the ATS system."""
    raw = load_vacancies()

    vacancies = []
    for v in raw:
        vacancies.append(ATSVacancy(
            external_id=v["source_id"],
            title=v["title"],
            company_name=v["company"],
            work_location=v.get("location"),
            description_html=v.get("description"),
            status="active" if v["status"] == "open" else v["status"],
            recruiter_email=v.get("recruiter_email"),
            client_name=v.get("client_name"),
        ))

    if status:
        vacancies = [v for v in vacancies if v.status == status]

    total = len(vacancies)
    start = (page - 1) * page_size
    end = start + page_size
    page_data = vacancies[start:end]

    return ATSVacancyListResponse(
        data=page_data,
        total_count=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
    )


@router.get("/api/v1/recruiters", response_model=ATSRecruiterListResponse)
async def list_recruiters(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """List all recruiters in the ATS system."""
    raw = load_recruiters()

    recruiters = []
    for r in raw:
        ext_id = f"rec-{hashlib.md5(r['email'].encode()).hexdigest()[:8]}"
        recruiters.append(ATSRecruiter(
            external_id=ext_id,
            full_name=r["name"],
            email=r.get("email"),
            phone_number=r.get("phone"),
            department=r.get("team"),
            job_title=r.get("role"),
            photo_url=r.get("avatar_url"),
            active=r.get("is_active", True),
        ))

    total = len(recruiters)
    start = (page - 1) * page_size
    end = start + page_size

    return ATSRecruiterListResponse(
        data=recruiters[start:end],
        total_count=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
    )


@router.get("/api/v1/clients", response_model=ATSClientListResponse)
async def list_clients(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """List all clients/companies in the ATS system."""
    raw = load_clients()

    clients = []
    for c in raw:
        ext_id = f"cli-{hashlib.md5(c['name'].encode()).hexdigest()[:8]}"
        clients.append(ATSClient(
            external_id=ext_id,
            company_name=c["name"],
            headquarters=c.get("location"),
            sector=c.get("industry"),
            logo_url=c.get("logo"),
        ))

    total = len(clients)
    start = (page - 1) * page_size
    end = start + page_size

    return ATSClientListResponse(
        data=clients[start:end],
        total_count=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
    )
