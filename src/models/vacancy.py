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
