"""
Activity service - handles activity logging and timeline retrieval.
"""
import uuid
import json
from typing import Optional, Any
import asyncpg
from src.repositories.activity_repo import ActivityRepository
from src.models.activity import (
    ActivityEventType,
    ActorType,
    ActivityChannel,
    ActivityResponse,
    TimelineResponse,
    GlobalActivityResponse,
    GlobalActivitiesResponse,
)


class ActivityService:
    """Service for logging and retrieving candidate activities."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = ActivityRepository(pool)

    async def log(
        self,
        candidate_id: str,
        event_type: ActivityEventType,
        actor_type: ActorType = ActorType.SYSTEM,
        application_id: Optional[str] = None,
        vacancy_id: Optional[str] = None,
        channel: Optional[ActivityChannel] = None,
        actor_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        summary: Optional[str] = None
    ) -> str:
        """
        Log an activity for a candidate.

        Args:
            candidate_id: The candidate's UUID
            event_type: Type of event being logged
            actor_type: Who performed the action (candidate, agent, recruiter, system)
            application_id: Optional associated application
            vacancy_id: Optional associated vacancy
            channel: Optional channel (voice, whatsapp, cv, web)
            actor_id: Optional recruiter user ID if actor_type is recruiter
            metadata: Optional dict with event-specific data
            summary: Optional human-readable description

        Returns:
            The created activity ID
        """
        activity_id = await self.repo.create(
            candidate_id=uuid.UUID(candidate_id),
            event_type=event_type.value,
            actor_type=actor_type.value,
            application_id=uuid.UUID(application_id) if application_id else None,
            vacancy_id=uuid.UUID(vacancy_id) if vacancy_id else None,
            channel=channel.value if channel else None,
            actor_id=actor_id,
            metadata=metadata or {},
            summary=summary
        )
        return str(activity_id)

    async def get_candidate_timeline(
        self,
        candidate_id: str,
        event_types: Optional[list[ActivityEventType]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> TimelineResponse:
        """
        Get the activity timeline for a candidate.

        Args:
            candidate_id: The candidate's UUID
            event_types: Optional filter for specific event types
            limit: Max number of activities to return
            offset: Pagination offset

        Returns:
            TimelineResponse with activities and total count
        """
        type_values = [t.value for t in event_types] if event_types else None

        rows, total = await self.repo.list_for_candidate(
            candidate_id=uuid.UUID(candidate_id),
            event_types=type_values,
            limit=limit,
            offset=offset
        )

        activities = [self._row_to_response(row) for row in rows]

        return TimelineResponse(
            candidate_id=candidate_id,
            activities=activities,
            total=total
        )

    async def get_application_timeline(
        self,
        application_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> list[ActivityResponse]:
        """
        Get activities for a specific application.

        Args:
            application_id: The application's UUID
            limit: Max number of activities to return
            offset: Pagination offset

        Returns:
            List of ActivityResponse objects
        """
        rows, _ = await self.repo.list_for_application(
            application_id=uuid.UUID(application_id),
            limit=limit,
            offset=offset
        )

        return [self._row_to_response(row) for row in rows]

    async def get_vacancy_activities(
        self,
        vacancy_id: str,
        event_types: Optional[list[ActivityEventType]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[ActivityResponse]:
        """
        Get activities for a vacancy (across all candidates).

        Args:
            vacancy_id: The vacancy's UUID
            event_types: Optional filter for specific event types
            limit: Max number of activities to return
            offset: Pagination offset

        Returns:
            List of ActivityResponse objects
        """
        type_values = [t.value for t in event_types] if event_types else None

        rows, _ = await self.repo.list_for_vacancy(
            vacancy_id=uuid.UUID(vacancy_id),
            event_types=type_values,
            limit=limit,
            offset=offset
        )

        return [self._row_to_response(row) for row in rows]

    async def get_all_activities(
        self,
        actor_type: Optional[ActorType] = None,
        event_types: Optional[list[ActivityEventType]] = None,
        channel: Optional[ActivityChannel] = None,
        limit: int = 50,
        offset: int = 0
    ) -> GlobalActivitiesResponse:
        """
        Get all activities across the system with optional filtering.

        Args:
            actor_type: Optional filter by actor type (agent, recruiter, candidate, system)
            event_types: Optional filter for specific event types
            channel: Optional filter by channel (voice, whatsapp, cv, web)
            limit: Max number of activities to return
            offset: Pagination offset

        Returns:
            GlobalActivitiesResponse with enriched activities and total count
        """
        type_values = [t.value for t in event_types] if event_types else None

        rows, total = await self.repo.list_all(
            actor_type=actor_type.value if actor_type else None,
            event_types=type_values,
            channel=channel.value if channel else None,
            limit=limit,
            offset=offset
        )

        activities = [self._row_to_global_response(row) for row in rows]

        return GlobalActivitiesResponse(
            activities=activities,
            total=total
        )

    @staticmethod
    def _row_to_global_response(row: asyncpg.Record) -> GlobalActivityResponse:
        """Convert a database row to a GlobalActivityResponse."""
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        # Build candidate name from first/last name
        candidate_name = None
        if row.get("candidate_first_name") or row.get("candidate_last_name"):
            first = row.get("candidate_first_name") or ""
            last = row.get("candidate_last_name") or ""
            candidate_name = f"{first} {last}".strip()

        return GlobalActivityResponse(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            candidate_name=candidate_name,
            application_id=str(row["application_id"]) if row["application_id"] else None,
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            vacancy_title=row.get("vacancy_title"),
            vacancy_company=row.get("vacancy_company"),
            event_type=row["event_type"],
            channel=row["channel"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            metadata=metadata,
            summary=row["summary"],
            created_at=row["created_at"]
        )

    @staticmethod
    def _row_to_response(row: asyncpg.Record) -> ActivityResponse:
        """Convert a database row to an ActivityResponse."""
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        # Build candidate name from first/last name if available (vacancy timeline queries)
        candidate_name = None
        if row.get("candidate_first_name") or row.get("candidate_last_name"):
            first = row.get("candidate_first_name") or ""
            last = row.get("candidate_last_name") or ""
            candidate_name = f"{first} {last}".strip() or None

        return ActivityResponse(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            candidate_name=candidate_name,
            application_id=str(row["application_id"]) if row["application_id"] else None,
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            event_type=row["event_type"],
            channel=row["channel"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            metadata=metadata,
            summary=row["summary"],
            created_at=row["created_at"]
        )
