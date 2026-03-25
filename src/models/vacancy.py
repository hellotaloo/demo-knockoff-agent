"""
Vacancy-related models.
"""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class ChannelsResponse(BaseModel):
    voice: bool = False
    whatsapp: bool = False
    cv: bool = False


class VacancyAgentResponse(BaseModel):
    """An agent registered to a vacancy."""
    type: str  # 'prescreening', 'document_collection', etc.
    status: Optional[str] = None  # 'online', 'offline', None
    # Prescreening-specific stats (optional)
    total_screenings: Optional[int] = None
    qualified_count: Optional[int] = None
    qualification_rate: Optional[int] = None  # Percentage (0-100)
    last_activity_at: Optional[datetime] = None


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


class OfficeSummary(BaseModel):
    """Office location info embedded in vacancy response."""
    id: str
    name: str
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class JobFunctionSummary(BaseModel):
    """Job function info embedded in vacancy response."""
    id: str
    name: str


class ApplicantSummary(BaseModel):
    """Lightweight applicant info embedded in vacancy response."""
    id: str
    name: str
    phone: Optional[str] = None
    channel: str  # voice, whatsapp, cv
    status: str  # active, processing, completed
    qualified: bool
    score: Optional[float] = None  # Average qualification score
    started_at: datetime
    completed_at: Optional[datetime] = None


class VacancyUpdateRequest(BaseModel):
    """Request body for updating vacancy fields."""
    start_date: Optional[date] = None


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
    start_date: Optional[date] = None
    has_screening: bool = False  # True if pre-screening exists
    published_at: Optional[datetime] = None  # When pre-screening was published (None=draft)
    is_online: Optional[bool] = None  # Derived: status=published + any channel active
    channels: ChannelsResponse = ChannelsResponse()  # Voice/WhatsApp channel availability
    agents: list[VacancyAgentResponse] = []  # AI agents registered to this vacancy
    # Recruiter ownership
    recruiter: Optional[RecruiterSummary] = None  # Full recruiter info (includes id)
    # Client/company
    client: Optional[ClientSummary] = None  # Full client info (includes id)
    # Office location
    office: Optional[OfficeSummary] = None  # Office location info
    # Job function
    job_function: Optional[JobFunctionSummary] = None  # Job function/category
    # Applicants
    applicants: list[ApplicantSummary] = []  # Candidates who did pre-screening
    # Application stats
    candidates_count: int = 0  # Total number of applications (excluding test)
    completed_count: int = 0  # Applications with status='completed'
    qualified_count: int = 0  # Applications with qualified=true
    avg_score: Optional[float] = None  # Average qualification score across all applications
    last_activity_at: Optional[datetime] = None  # Most recent application activity


# ---------------------------------------------------------------------------
# Unified agent overview models
# ---------------------------------------------------------------------------


class AgentStatItem(BaseModel):
    """A single stat metric — used in both vacancy rows and dashboard cards."""
    key: str                          # programmatic id (e.g. "candidates_count", "active")
    label: str                        # display label (e.g. "Kandidaten", "Actief")
    value: int = 0                    # numeric value
    description: Optional[str] = None  # sublabel (e.g. "Lopend", "Alle collecties")
    variant: Optional[str] = None     # color variant for dashboard cards (blue/dark/lime/pink)
    icon: Optional[str] = None        # icon name (e.g. "users", "file-check")
    suffix: Optional[str] = None      # e.g. "%" for rates


class AgentVacancyChannels(BaseModel):
    """Enabled screening channels for a vacancy."""
    voice: bool = False
    whatsapp: bool = False
    cv: bool = False


class AgentVacancyResponse(BaseModel):
    """Unified vacancy response for all agent overview pages."""
    id: str
    title: str
    company: str
    location: Optional[str] = None
    status: str                                     # vacancy status (open/closed/filled)
    created_at: datetime
    agent_status: str = "new"                       # "new", "generated", "published", "archived"
    stats: list[AgentStatItem] = []
    channels: Optional[AgentVacancyChannels] = None
    last_activity_at: Optional[datetime] = None
    recruiter: Optional[RecruiterSummary] = None
    client: Optional[ClientSummary] = None


class AgentDashboardStatsResponse(BaseModel):
    """Unified dashboard stats for all agent pages."""
    metrics: list[AgentStatItem] = []


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
    """Lightweight counts for navigation sidebar and view tabs."""
    prescreening: dict[str, int]  # {"new": 7, "generated": 3, "archived": 2}
    preonboarding: dict[str, int]  # {"new": 7, "generated": 0, "archived": 2}
    activities: dict[str, int]  # {"active": 5, "stuck": 2}
    vacancies: dict[str, int] = {}  # {"active": 8, "archived": 0}
    candidates: dict[str, int] = {}  # {"total": 25, "archived": 0}


class VacancyDetailResponse(VacancyResponse):
    """Extended vacancy response with activity timeline."""
    timeline: list["ActivityResponse"] = []


# Import ActivityResponse for type hints (imported here to avoid circular imports)
from src.models.activity import ActivityResponse

# Rebuild models to resolve forward references
VacancyDetailResponse.model_rebuild()
