"""
Vacancy service - handles vacancy listing, details, and statistics.
"""
import uuid
from typing import Optional, Tuple
import asyncpg
from markdownify import markdownify as md
from src.repositories import VacancyRepository
from src.models import VacancyResponse, ChannelsResponse, VacancyAgentResponse, VacancyStatsResponse, DashboardStatsResponse
from src.models.vacancy import RecruiterSummary, ClientSummary, ApplicantSummary, OfficeSummary, JobFunctionSummary


class VacancyService:
    """Service for vacancy operations."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = VacancyRepository(pool)
    
    @staticmethod
    def build_applicant_summary(row: asyncpg.Record) -> ApplicantSummary:
        """Build an ApplicantSummary from an application record."""
        return ApplicantSummary(
            id=str(row["id"]),
            name=row["name"],
            phone=row["phone"],
            channel=row["channel"],
            status=row["status"],
            qualified=row["qualified"],
            score=float(row["score"]) if row["score"] is not None else None,
            started_at=row["started_at"],
            completed_at=row["completed_at"]
        )

    @staticmethod
    def _build_agents(row: asyncpg.Record) -> list[VacancyAgentResponse]:
        """Build list of registered agents from vacancy row."""
        agent_types = row.get("agent_types") or []
        agents = []

        for agent_type in agent_types:
            if agent_type == "prescreening":
                agents.append(VacancyAgentResponse(
                    type="prescreening",
                    status=row["agent_status"] if row["has_screening"] else None,
                    total_screenings=row["candidates_count"] if row["has_screening"] else None,
                    qualified_count=row["qualified_count"] if row["has_screening"] else None,
                    qualification_rate=(
                        int(row["qualified_count"] / row["candidates_count"] * 100)
                        if row["has_screening"] and row["candidates_count"] > 0
                        else None
                    ),
                    last_activity_at=row["last_activity_at"] if row["has_screening"] else None,
                ))
            else:
                agents.append(VacancyAgentResponse(type=agent_type))

        return agents

    @staticmethod
    def build_vacancy_response(
        row: asyncpg.Record,
        applicant_rows: list[asyncpg.Record] = None
    ) -> VacancyResponse:
        """
        Build a VacancyResponse model from a database row.

        Args:
            row: The vacancy database row
            applicant_rows: Optional list of applicant records for this vacancy
        """
        # Calculate effective channel states
        voice_active = row["voice_enabled"] or False
        whatsapp_active = row["whatsapp_enabled"] or False
        cv_active = row["cv_enabled"] or False

        # Derive online state: published + at least one channel active
        any_channel_active = voice_active or whatsapp_active or cv_active
        effective_is_online = (row["agent_status"] == "published") and any_channel_active

        # Build recruiter info if present
        recruiter = None
        recruiter_id = row.get("recruiter_id")
        if recruiter_id and row.get("r_id"):
            recruiter = RecruiterSummary(
                id=str(row["r_id"]),
                name=row["r_name"],
                email=row["r_email"],
                phone=row["r_phone"],
                team=row["r_team"],
                role=row["r_role"],
                avatar_url=row["r_avatar_url"]
            )

        # Build client info if present
        client = None
        client_id = row.get("client_id")
        if client_id and row.get("c_id"):
            client = ClientSummary(
                id=str(row["c_id"]),
                name=row["c_name"],
                location=row["c_location"],
                industry=row["c_industry"],
                logo=row["c_logo"]
            )

        # Build office info if present
        office = None
        if row.get("ol_id"):
            office = OfficeSummary(
                id=str(row["ol_id"]),
                name=row["ol_name"],
                address=row["ol_address"] or None,
                email=row["ol_email"],
                phone=row["ol_phone"],
            )

        # Build job function info if present
        job_function = None
        if row.get("jf_id"):
            job_function = JobFunctionSummary(
                id=str(row["jf_id"]),
                name=row["jf_name"],
            )

        # Build applicants list
        applicants = []
        if applicant_rows:
            applicants = [
                VacancyService.build_applicant_summary(app_row)
                for app_row in applicant_rows
            ]

        return VacancyResponse(
            id=str(row["id"]),
            title=row["title"],
            company=row["company"],
            location=row["location"],
            description=md(row["description"]).strip() if row["description"] else None,
            status=row["status"],
            created_at=row["created_at"],
            archived_at=row["archived_at"],
            source=row["source"],
            source_id=row["source_id"],
            start_date=row["start_date"],
            has_screening=row["has_screening"],
            published_at=row["published_at"],
            is_online=effective_is_online,
            channels=ChannelsResponse(
                voice=voice_active,
                whatsapp=whatsapp_active,
                cv=cv_active
            ),
            agents=VacancyService._build_agents(row),
            recruiter=recruiter,
            client=client,
            office=office,
            job_function=job_function,
            applicants=applicants,
            candidates_count=row["candidates_count"],
            completed_count=row["completed_count"],
            qualified_count=row["qualified_count"],
            avg_score=float(row["avg_score"]) if row["avg_score"] is not None else None,
            last_activity_at=row["last_activity_at"]
        )
    
    async def list_vacancies(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[VacancyResponse], int]:
        """
        List vacancies with optional filtering.
        
        Returns:
            Tuple of (vacancy list, total count)
        """
        rows, total = await self.repo.list_with_stats(status, source, limit, offset)
        vacancies = [self.build_vacancy_response(row) for row in rows]
        return vacancies, total
    
    async def get_vacancy(self, vacancy_id: uuid.UUID) -> Optional[VacancyResponse]:
        """Get a single vacancy by ID with stats."""
        row = await self.repo.get_by_id(vacancy_id)
        if not row:
            return None
        return self.build_vacancy_response(row)
    
    async def get_vacancy_stats(self, vacancy_id: uuid.UUID) -> Optional[VacancyStatsResponse]:
        """Get detailed statistics for a vacancy."""
        stats = await self.repo.get_stats(vacancy_id)
        if not stats:
            return None
        
        return VacancyStatsResponse(
            total=stats["total"],
            completed_count=stats["completed_count"],
            qualified_count=stats["qualified_count"],
            voice_count=stats["voice_count"],
            whatsapp_count=stats["whatsapp_count"],
            avg_duration_seconds=int(stats["avg_seconds"]),
            last_application=stats["last_application"]
        )
    
    async def get_dashboard_stats(self) -> DashboardStatsResponse:
        """Get dashboard-level aggregate statistics."""
        stats = await self.repo.get_dashboard_stats()
        
        return DashboardStatsResponse(
            total_applications=stats["total"],
            this_week=stats["this_week"],
            completed=stats["completed_count"],
            qualified=stats["qualified_count"],
            voice_count=stats["voice_count"],
            whatsapp_count=stats["whatsapp_count"],
            cv_count=stats["cv_count"]
        )
