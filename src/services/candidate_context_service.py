"""
Candidate Context Service - aggregates candidate information for agent context injection.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
import asyncpg

from src.models.candidate_context import (
    CandidateContext,
    TrustLevel,
    PreferredChannel,
    ScheduledInterview,
    KnownQualification,
    ApplicationSummary,
    SameRecruiterVacancy,
    CommunicationPreferences,
    AvailabilityInfo,
)
from src.repositories.candidate_repo import CandidateRepository
from src.repositories.activity_repo import ActivityRepository


class CandidateContextService:
    """
    Service for collecting and aggregating candidate context.

    This service gathers all relevant information about a candidate
    to provide rich context to agents during interactions.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.candidate_repo = CandidateRepository(pool)
        self.activity_repo = ActivityRepository(pool)

    async def get_context(
        self,
        candidate_id: str,
        current_vacancy_id: Optional[str] = None,
    ) -> Optional[CandidateContext]:
        """
        Get complete context for a candidate.

        Args:
            candidate_id: The candidate's UUID
            current_vacancy_id: Optional current vacancy ID to determine same-recruiter context

        Returns:
            CandidateContext with all aggregated information, or None if candidate not found
        """
        candidate_uuid = uuid.UUID(candidate_id)

        # Get base candidate info
        candidate = await self.candidate_repo.get_by_id(candidate_uuid)
        if not candidate:
            return None

        # Get current vacancy's recruiter if provided
        current_recruiter_id = None
        if current_vacancy_id:
            current_recruiter_id = await self._get_vacancy_recruiter(uuid.UUID(current_vacancy_id))

        # Gather all context data in parallel where possible
        skills = await self.candidate_repo.get_skills(candidate_uuid)
        applications = await self.candidate_repo.get_applications(candidate_uuid)
        scheduled_interviews = await self._get_scheduled_interviews(candidate_uuid)
        communication_prefs = await self._get_communication_preferences(candidate_uuid)
        activity_summary = await self._generate_activity_summary(candidate_uuid)

        # Calculate trust level
        trust_level = self._calculate_trust_level(candidate, applications)

        # Process applications with recruiter context
        application_summaries = await self._build_application_summaries(
            applications, current_recruiter_id
        )

        # Get same recruiter vacancies if we have a current vacancy
        same_recruiter_vacancies = []
        if current_recruiter_id and current_vacancy_id:
            same_recruiter_vacancies = await self._get_same_recruiter_vacancies(
                current_recruiter_id, current_vacancy_id
            )

        # Build known qualifications from skills
        known_qualifications = [
            KnownQualification(
                skill_name=skill["skill_name"],
                skill_category=skill["skill_category"],
                score=float(skill["score"]) if skill["score"] else None,
                evidence=skill["evidence"],
                source=skill["source"],
            )
            for skill in skills
        ]

        # Calculate application statistics
        completed = [a for a in applications if a["status"] == "completed"]
        qualified = [a for a in completed if a["qualified"]]
        qualification_rate = len(qualified) / len(completed) if completed else None

        # Calculate days since last interaction
        last_interaction, days_since = await self._get_last_interaction(candidate_uuid)

        # Build availability info
        availability = AvailabilityInfo(
            status=candidate["availability"] or "unknown",
            available_from=candidate["available_from"],
        )

        return CandidateContext(
            candidate_id=str(candidate["id"]),
            full_name=candidate["full_name"],
            phone=candidate["phone"],
            email=candidate["email"],
            trust_level=trust_level,
            status=candidate["status"] or "new",
            rating=float(candidate["rating"]) if candidate["rating"] else None,
            scheduled_interviews=scheduled_interviews,
            has_upcoming_interview=len(scheduled_interviews) > 0,
            known_qualifications=known_qualifications,
            application_history=application_summaries,
            total_applications=len(applications),
            completed_applications=len(completed),
            qualification_rate=qualification_rate,
            same_recruiter_vacancies=same_recruiter_vacancies,
            has_same_recruiter_vacancies=len(same_recruiter_vacancies) > 0,
            communication=communication_prefs,
            availability=availability,
            activity_summary=activity_summary,
            last_interaction=last_interaction,
            days_since_last_interaction=days_since,
            current_vacancy_id=current_vacancy_id,
        )

    async def get_context_by_phone(
        self,
        phone: str,
        current_vacancy_id: Optional[str] = None,
    ) -> Optional[CandidateContext]:
        """
        Get context for a candidate by phone number.

        Args:
            phone: Phone number in E.164 format
            current_vacancy_id: Optional current vacancy ID

        Returns:
            CandidateContext or None if not found
        """
        candidate = await self.candidate_repo.get_by_phone(phone)
        if not candidate:
            return None
        return await self.get_context(str(candidate["id"]), current_vacancy_id)

    def _calculate_trust_level(
        self,
        candidate: asyncpg.Record,
        applications: List[asyncpg.Record],
    ) -> TrustLevel:
        """
        Calculate trust level based on candidate history.

        Trust levels:
        - NEW: No completed screenings
        - ACTIVE: Has ongoing applications
        - TRUSTED: Multiple completions, high qualification rate
        - INACTIVE: No activity in 30+ days
        """
        if not applications:
            return TrustLevel.NEW

        completed = [a for a in applications if a["status"] == "completed"]
        active = [a for a in applications if a["status"] in ("active", "processing")]
        qualified = [a for a in completed if a["qualified"]]

        # Check for inactivity
        if candidate.get("status_updated_at"):
            days_inactive = (datetime.utcnow() - candidate["status_updated_at"].replace(tzinfo=None)).days
            if days_inactive > 30 and not active:
                return TrustLevel.INACTIVE

        # Check for trusted status
        if len(completed) >= 2:
            qual_rate = len(qualified) / len(completed) if completed else 0
            if qual_rate >= 0.5:  # 50%+ qualification rate
                return TrustLevel.TRUSTED

        # Has active applications
        if active:
            return TrustLevel.ACTIVE

        # Has completed but not yet trusted
        if completed:
            return TrustLevel.ACTIVE

        return TrustLevel.NEW

    async def _get_scheduled_interviews(
        self,
        candidate_id: uuid.UUID,
    ) -> List[ScheduledInterview]:
        """Get future scheduled interviews for a candidate."""
        rows = await self.pool.fetch(
            """
            SELECT
                aa.id,
                aa.application_id,
                aa.vacancy_id,
                aa.metadata,
                aa.created_at,
                v.title as vacancy_title,
                v.company as vacancy_company,
                v.recruiter_id,
                r.name as recruiter_name
            FROM ats.agent_activities aa
            JOIN ats.vacancies v ON v.id = aa.vacancy_id
            LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
            WHERE aa.candidate_id = $1
              AND aa.event_type IN ('INTERVIEW_SCHEDULED', 'INTERVIEW_CONFIRMED', 'INTERVIEW_RESCHEDULED')
              AND aa.metadata->>'scheduled_at' IS NOT NULL
              AND (aa.metadata->>'scheduled_at')::timestamp > NOW()
            ORDER BY (aa.metadata->>'scheduled_at')::timestamp ASC
            """,
            candidate_id
        )

        interviews = []
        for row in rows:
            metadata = row["metadata"] or {}
            scheduled_at_str = metadata.get("scheduled_at")
            if scheduled_at_str:
                try:
                    scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
                except ValueError:
                    continue

                interviews.append(ScheduledInterview(
                    application_id=str(row["application_id"]) if row["application_id"] else "",
                    vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else "",
                    vacancy_title=row["vacancy_title"] or "",
                    vacancy_company=row["vacancy_company"] or "",
                    recruiter_id=str(row["recruiter_id"]) if row["recruiter_id"] else None,
                    recruiter_name=row["recruiter_name"],
                    scheduled_at=scheduled_at,
                    status=metadata.get("status", "scheduled"),
                ))

        return interviews

    async def _get_vacancy_recruiter(self, vacancy_id: uuid.UUID) -> Optional[uuid.UUID]:
        """Get the recruiter ID for a vacancy."""
        result = await self.pool.fetchval(
            "SELECT recruiter_id FROM ats.vacancies WHERE id = $1",
            vacancy_id
        )
        return result

    async def _build_application_summaries(
        self,
        applications: List[asyncpg.Record],
        current_recruiter_id: Optional[uuid.UUID],
    ) -> List[ApplicationSummary]:
        """Build application summaries with recruiter context."""
        summaries = []

        for app in applications:
            # Get recruiter info for this application's vacancy
            recruiter_info = await self.pool.fetchrow(
                """
                SELECT v.recruiter_id, r.name as recruiter_name
                FROM ats.vacancies v
                LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
                WHERE v.id = $1
                """,
                app["vacancy_id"]
            )

            same_recruiter = False
            recruiter_id = None
            recruiter_name = None

            if recruiter_info:
                recruiter_id = recruiter_info["recruiter_id"]
                recruiter_name = recruiter_info["recruiter_name"]
                if current_recruiter_id and recruiter_id:
                    same_recruiter = recruiter_id == current_recruiter_id

            summaries.append(ApplicationSummary(
                application_id=str(app["id"]),
                vacancy_id=str(app["vacancy_id"]),
                vacancy_title=app["vacancy_title"],
                vacancy_company=app["vacancy_company"],
                recruiter_id=str(recruiter_id) if recruiter_id else None,
                recruiter_name=recruiter_name,
                channel=app["channel"] or "unknown",
                status=app["status"] or "active",
                qualified=app["qualified"],
                overall_score=app.get("overall_score"),
                started_at=app["started_at"],
                completed_at=app["completed_at"],
                same_recruiter_as_current=same_recruiter,
            ))

        return summaries

    async def _get_same_recruiter_vacancies(
        self,
        recruiter_id: uuid.UUID,
        exclude_vacancy_id: str,
    ) -> List[SameRecruiterVacancy]:
        """Get other open vacancies by the same recruiter."""
        rows = await self.pool.fetch(
            """
            SELECT id, title, company, location, status
            FROM ats.vacancies
            WHERE recruiter_id = $1
              AND id != $2
              AND status = 'open'
            ORDER BY created_at DESC
            LIMIT 10
            """,
            recruiter_id,
            uuid.UUID(exclude_vacancy_id)
        )

        return [
            SameRecruiterVacancy(
                vacancy_id=str(row["id"]),
                title=row["title"],
                company=row["company"],
                location=row["location"],
                status=row["status"],
            )
            for row in rows
        ]

    async def _get_communication_preferences(
        self,
        candidate_id: uuid.UUID,
    ) -> CommunicationPreferences:
        """Derive communication preferences from activity history."""
        # Count interactions by channel
        channel_counts = await self.pool.fetch(
            """
            SELECT channel, COUNT(*) as count
            FROM ats.agent_activities
            WHERE candidate_id = $1
              AND channel IS NOT NULL
              AND event_type IN ('MESSAGE_RECEIVED', 'CALL_COMPLETED', 'SCREENING_COMPLETED')
            GROUP BY channel
            """,
            candidate_id
        )

        whatsapp_count = 0
        voice_count = 0

        for row in channel_counts:
            if row["channel"] == "whatsapp":
                whatsapp_count = row["count"]
            elif row["channel"] == "voice":
                voice_count = row["count"]

        # Determine preferred channel
        preferred = PreferredChannel.UNKNOWN
        if whatsapp_count > voice_count:
            preferred = PreferredChannel.WHATSAPP
        elif voice_count > whatsapp_count:
            preferred = PreferredChannel.VOICE

        # Calculate average response time (for WhatsApp messages)
        avg_response = await self.pool.fetchval(
            """
            SELECT AVG(
                EXTRACT(EPOCH FROM (
                    (metadata->>'responded_at')::timestamp -
                    (metadata->>'sent_at')::timestamp
                )) / 60
            )
            FROM ats.agent_activities
            WHERE candidate_id = $1
              AND event_type = 'MESSAGE_RECEIVED'
              AND metadata->>'responded_at' IS NOT NULL
              AND metadata->>'sent_at' IS NOT NULL
            """,
            candidate_id
        )

        # Get total counts
        totals = await self.pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'MESSAGE_RECEIVED') as messages,
                COUNT(*) FILTER (WHERE event_type = 'CALL_COMPLETED') as calls
            FROM ats.agent_activities
            WHERE candidate_id = $1
            """,
            candidate_id
        )

        # Get most recent channel interaction
        last_channel_row = await self.pool.fetchrow(
            """
            SELECT channel, created_at
            FROM ats.agent_activities
            WHERE candidate_id = $1
              AND channel IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            candidate_id
        )

        last_channel = last_channel_row["channel"] if last_channel_row else None
        last_channel_at = last_channel_row["created_at"] if last_channel_row else None

        return CommunicationPreferences(
            preferred_channel=preferred,
            last_channel=last_channel,
            last_channel_at=last_channel_at,
            avg_response_time_minutes=float(avg_response) if avg_response else None,
            total_messages_received=totals["messages"] if totals else 0,
            total_calls_completed=totals["calls"] if totals else 0,
            language="nl",  # Default to Dutch
        )

    async def _generate_activity_summary(
        self,
        candidate_id: uuid.UUID,
    ) -> Optional[str]:
        """Generate a human-readable activity summary in Dutch."""
        # Get recent key activities
        activities = await self.pool.fetch(
            """
            SELECT event_type, channel, summary, created_at, metadata
            FROM ats.agent_activities
            WHERE candidate_id = $1
              AND event_type IN (
                'SCREENING_STARTED', 'SCREENING_COMPLETED', 'QUALIFIED', 'DISQUALIFIED',
                'INTERVIEW_SCHEDULED', 'INTERVIEW_COMPLETED', 'CV_ANALYZED'
              )
            ORDER BY created_at DESC
            LIMIT 5
            """,
            candidate_id
        )

        if not activities:
            return None

        # Build summary lines
        lines = []
        for activity in activities:
            event = activity["event_type"]
            channel = activity["channel"]
            created = activity["created_at"]
            date_str = created.strftime("%d/%m/%Y")

            channel_str = ""
            if channel == "whatsapp":
                channel_str = " via WhatsApp"
            elif channel == "voice":
                channel_str = " via telefoon"

            if event == "SCREENING_STARTED":
                lines.append(f"• {date_str}: Screening gestart{channel_str}")
            elif event == "SCREENING_COMPLETED":
                lines.append(f"• {date_str}: Screening afgerond{channel_str}")
            elif event == "QUALIFIED":
                lines.append(f"• {date_str}: Gekwalificeerd")
            elif event == "DISQUALIFIED":
                lines.append(f"• {date_str}: Niet gekwalificeerd")
            elif event == "INTERVIEW_SCHEDULED":
                lines.append(f"• {date_str}: Gesprek ingepland")
            elif event == "INTERVIEW_COMPLETED":
                lines.append(f"• {date_str}: Gesprek afgerond")
            elif event == "CV_ANALYZED":
                lines.append(f"• {date_str}: CV geanalyseerd")

        return "\n".join(lines) if lines else None

    async def _get_last_interaction(
        self,
        candidate_id: uuid.UUID,
    ) -> tuple[Optional[datetime], Optional[int]]:
        """Get the last interaction timestamp and days since."""
        last = await self.pool.fetchval(
            """
            SELECT MAX(created_at)
            FROM ats.agent_activities
            WHERE candidate_id = $1
            """,
            candidate_id
        )

        if not last:
            return None, None

        days = (datetime.utcnow() - last.replace(tzinfo=None)).days
        return last, days
