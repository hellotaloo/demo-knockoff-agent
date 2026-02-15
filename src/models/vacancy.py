"""
Vacancy-related models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ChannelsResponse(BaseModel):
    voice: bool = False
    whatsapp: bool = False
    cv: bool = False


class AgentStatusResponse(BaseModel):
    """Status of an individual AI agent."""
    exists: bool = False  # True if agent is generated/configured
    status: Optional[str] = None  # "online" | "offline" | null (not published)


class AgentsResponse(BaseModel):
    """AI agents status for a vacancy."""
    prescreening: AgentStatusResponse = AgentStatusResponse()
    preonboarding: AgentStatusResponse = AgentStatusResponse()
    insights: AgentStatusResponse = AgentStatusResponse()


class RecruiterSummary(BaseModel):
    """Recruiter info embedded in vacancy response."""
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    team: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None


class ClientSummary(BaseModel):
    """Client info embedded in vacancy response."""
    id: str
    name: str
    location: Optional[str] = None
    industry: Optional[str] = None
    logo: Optional[str] = None


class VacancyResponse(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str] = None
    description: Optional[str] = None
    status: str
    created_at: datetime
    archived_at: Optional[datetime] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    has_screening: bool = False  # True if pre-screening exists
    is_online: Optional[bool] = None  # None=draft/unpublished, True=online, False=offline
    channels: ChannelsResponse = ChannelsResponse()  # Voice/WhatsApp channel availability
    agents: AgentsResponse = AgentsResponse()  # AI agents enabled for this vacancy
    # Recruiter ownership
    recruiter_id: Optional[str] = None  # Foreign key to recruiters table
    recruiter: Optional[RecruiterSummary] = None  # Full recruiter info
    # Client/company
    client_id: Optional[str] = None  # Foreign key to clients table
    client: Optional[ClientSummary] = None  # Full client info
    # Application stats
    candidates_count: int = 0  # Total number of applications (excluding test)
    completed_count: int = 0  # Applications with status='completed'
    qualified_count: int = 0  # Applications with qualified=true
    last_activity_at: Optional[datetime] = None  # Most recent application activity


class VacancyStatsResponse(BaseModel):
    vacancy_id: str
    total_applications: int
    completed_count: int  # Applications with status='completed'
    completion_rate: int
    qualified_count: int  # Applications with qualified=true
    qualification_rate: int
    channel_breakdown: dict[str, int]
    avg_interaction_seconds: int
    last_application_at: Optional[datetime] = None


class DashboardStatsResponse(BaseModel):
    """Dashboard-level aggregate statistics across all vacancies."""
    total_prescreenings: int  # Total applications
    total_prescreenings_this_week: int  # Applications started this week
    completed_count: int
    completion_rate: int  # Percentage
    qualified_count: int
    qualification_rate: int  # Percentage of completed
    channel_breakdown: dict[str, int]  # voice, whatsapp, cv


class NavigationCountsResponse(BaseModel):
    """Lightweight counts for navigation sidebar."""
    prescreening: dict[str, int]  # {"new": 7, "generated": 3, "archived": 2}
    preonboarding: dict[str, int]  # {"new": 7, "generated": 0, "archived": 2}


class VacancyDetailResponse(VacancyResponse):
    """Extended vacancy response with activity timeline."""
    timeline: list["ActivityResponse"] = []


# Import ActivityResponse for type hints (imported here to avoid circular imports)
from src.models.activity import ActivityResponse

# Rebuild models to resolve forward references
VacancyDetailResponse.model_rebuild()
