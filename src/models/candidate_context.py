"""
Candidate Context models for agent context injection.
"""
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class TrustLevel(str, Enum):
    """Candidate trust level based on interaction history."""
    NEW = "new"              # No completed screenings
    ACTIVE = "active"        # Has ongoing applications
    TRUSTED = "trusted"      # Multiple completions, high qualification rate
    INACTIVE = "inactive"    # No activity in 30+ days


class PreferredChannel(str, Enum):
    """Preferred communication channel."""
    WHATSAPP = "whatsapp"
    VOICE = "voice"
    UNKNOWN = "unknown"


class ScheduledInterview(BaseModel):
    """A scheduled interview for the candidate."""
    application_id: str
    vacancy_id: str
    vacancy_title: str
    vacancy_company: str
    recruiter_id: Optional[str] = None
    recruiter_name: Optional[str] = None
    scheduled_at: datetime
    status: str  # scheduled, confirmed, completed, cancelled, no_show


class KnownQualification(BaseModel):
    """A known qualification/skill from previous screenings."""
    skill_name: str
    skill_category: Optional[str] = None
    score: Optional[float] = Field(None, ge=0, le=1)
    evidence: Optional[str] = None
    source: str  # cv_analysis, screening, manual


class ApplicationSummary(BaseModel):
    """Summary of a past application."""
    application_id: str
    vacancy_id: str
    vacancy_title: str
    vacancy_company: str
    recruiter_id: Optional[str] = None
    recruiter_name: Optional[str] = None
    channel: str  # voice, whatsapp, cv, web
    status: str  # active, processing, completed, abandoned
    qualified: Optional[bool] = None
    overall_score: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    same_recruiter_as_current: bool = False


class SameRecruiterVacancy(BaseModel):
    """Another open vacancy by the same recruiter."""
    vacancy_id: str
    title: str
    company: str
    location: Optional[str] = None
    status: str  # concept, open, on_hold, filled, closed


class CommunicationPreferences(BaseModel):
    """Candidate communication preferences derived from history."""
    preferred_channel: PreferredChannel = PreferredChannel.UNKNOWN
    last_channel: Optional[str] = None  # Most recent channel: voice, whatsapp, cv, web
    last_channel_at: Optional[datetime] = None
    avg_response_time_minutes: Optional[float] = None
    total_messages_received: int = 0
    total_calls_completed: int = 0
    language: str = "nl"  # Default to Dutch


class AvailabilityInfo(BaseModel):
    """Candidate availability information."""
    status: str  # available, unavailable, unknown
    available_from: Optional[date] = None
    notice_period_days: Optional[int] = None
    work_type: Optional[str] = None  # fulltime, parttime, freelance


class CandidateContext(BaseModel):
    """
    Complete context about a candidate for agent injection.

    This aggregates all relevant information about a candidate
    to help agents make informed decisions.
    """
    # Core identification
    candidate_id: str
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None

    # Trust and status
    trust_level: TrustLevel = TrustLevel.NEW
    status: str  # new, qualified, active, placed, inactive
    rating: Optional[float] = Field(None, ge=0, le=5)

    # Scheduled interviews (future)
    scheduled_interviews: List[ScheduledInterview] = []
    has_upcoming_interview: bool = False

    # Known qualifications
    known_qualifications: List[KnownQualification] = []

    # Application history
    application_history: List[ApplicationSummary] = []
    total_applications: int = 0
    completed_applications: int = 0
    qualification_rate: Optional[float] = None  # % of completed apps that qualified

    # Same recruiter context
    same_recruiter_vacancies: List[SameRecruiterVacancy] = []
    has_same_recruiter_vacancies: bool = False

    # Communication preferences
    communication: CommunicationPreferences = Field(default_factory=CommunicationPreferences)

    # Availability
    availability: AvailabilityInfo = Field(default_factory=lambda: AvailabilityInfo(status="unknown"))

    # Activity summary (human-readable)
    activity_summary: Optional[str] = None
    last_interaction: Optional[datetime] = None
    days_since_last_interaction: Optional[int] = None

    # Context generation metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    current_vacancy_id: Optional[str] = None  # The vacancy context was generated for

    def to_agent_prompt(self) -> str:
        """
        Convert context to a formatted string for agent system prompt injection.
        Returns Dutch (Flemish) formatted context.
        """
        lines = []
        lines.append("## Kandidaat Context")
        lines.append("")
        lines.append(f"**Naam:** {self.full_name}")
        lines.append(f"**Status:** {self.status}")
        lines.append(f"**Vertrouwensniveau:** {self.trust_level.value}")

        if self.rating:
            lines.append(f"**Beoordeling:** {self.rating}/5")

        # Scheduled interviews
        if self.has_upcoming_interview:
            lines.append("")
            lines.append("### Geplande Gesprekken")
            for interview in self.scheduled_interviews:
                lines.append(f"- {interview.vacancy_title} ({interview.vacancy_company}) - {interview.scheduled_at.strftime('%d/%m/%Y %H:%M')}")

        # Known qualifications
        if self.known_qualifications:
            lines.append("")
            lines.append("### Bekende Kwalificaties")
            for qual in self.known_qualifications[:10]:  # Limit to top 10
                score_str = f" ({qual.score:.0%})" if qual.score else ""
                lines.append(f"- {qual.skill_name}{score_str}")

        # Application history summary
        if self.application_history:
            lines.append("")
            lines.append("### Sollicitatie Geschiedenis")
            lines.append(f"- Totaal sollicitaties: {self.total_applications}")
            lines.append(f"- Afgerond: {self.completed_applications}")
            if self.qualification_rate is not None:
                lines.append(f"- Kwalificatie percentage: {self.qualification_rate:.0%}")

            # Recent applications
            recent = self.application_history[:3]
            if recent:
                lines.append("")
                lines.append("**Recente sollicitaties:**")
                for app in recent:
                    status_str = "✓ Gekwalificeerd" if app.qualified else ("✗ Niet gekwalificeerd" if app.qualified is False else "In behandeling")
                    same_recruiter = " (zelfde recruiter)" if app.same_recruiter_as_current else ""
                    lines.append(f"- {app.vacancy_title}{same_recruiter}: {status_str}")

        # Same recruiter vacancies
        if self.has_same_recruiter_vacancies:
            lines.append("")
            lines.append("### Andere Vacatures Zelfde Recruiter")
            for vacancy in self.same_recruiter_vacancies[:5]:
                lines.append(f"- {vacancy.title} ({vacancy.company})")

        # Communication preferences
        has_comm_info = (
            self.communication.preferred_channel != PreferredChannel.UNKNOWN
            or self.communication.last_channel
        )
        if has_comm_info:
            lines.append("")
            lines.append("### Communicatie Voorkeuren")
            channel_map = {"whatsapp": "WhatsApp", "voice": "Telefoon", "web": "Portaal", "cv": "CV Upload"}
            if self.communication.last_channel:
                last_nl = channel_map.get(self.communication.last_channel, self.communication.last_channel)
                lines.append(f"- Laatste kanaal: {last_nl}")
            if self.communication.preferred_channel != PreferredChannel.UNKNOWN:
                pref_nl = channel_map.get(self.communication.preferred_channel.value, "Onbekend")
                lines.append(f"- Voorkeur kanaal: {pref_nl}")
            if self.communication.avg_response_time_minutes:
                lines.append(f"- Gemiddelde reactietijd: {self.communication.avg_response_time_minutes:.0f} minuten")

        # Availability
        if self.availability.status != "unknown":
            lines.append("")
            lines.append("### Beschikbaarheid")
            status_nl = {"available": "Beschikbaar", "unavailable": "Niet beschikbaar"}.get(self.availability.status, "Onbekend")
            lines.append(f"- Status: {status_nl}")
            if self.availability.available_from:
                lines.append(f"- Beschikbaar vanaf: {self.availability.available_from.strftime('%d/%m/%Y')}")

        # Activity summary
        if self.activity_summary:
            lines.append("")
            lines.append("### Activiteit Samenvatting")
            lines.append(self.activity_summary)

        if self.days_since_last_interaction is not None:
            lines.append(f"- Laatste interactie: {self.days_since_last_interaction} dagen geleden")

        return "\n".join(lines)
