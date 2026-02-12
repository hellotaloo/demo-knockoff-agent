"""
Candidate repository - handles candidate database operations.
"""
import asyncpg
import uuid
from typing import Optional, List


class CandidateRepository:
    """Repository for candidate database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_by_id(self, candidate_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a candidate by ID."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.candidates WHERE id = $1",
            candidate_id
        )

    async def get_by_phone(self, phone: str) -> Optional[asyncpg.Record]:
        """Get a candidate by phone number."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.candidates WHERE phone = $1",
            phone
        )

    async def get_by_email(self, email: str) -> Optional[asyncpg.Record]:
        """Get a candidate by email."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.candidates WHERE email = $1 LIMIT 1",
            email
        )

    async def find_or_create(
        self,
        full_name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_test: bool = False,
    ) -> uuid.UUID:
        """
        Find existing candidate by phone/email or create new one.
        Returns candidate ID.

        Args:
            full_name: Candidate's full name
            phone: Phone number (primary identifier)
            email: Email address (fallback identifier)
            first_name: First name (optional, parsed from full_name if not provided)
            last_name: Last name (optional, parsed from full_name if not provided)
            is_test: Flag indicating this is a test candidate (admin testing)
        """
        # Try to find by phone first (primary identifier)
        if phone:
            existing = await self.get_by_phone(phone)
            if existing:
                # Update name if it changed
                if existing["full_name"] != full_name:
                    await self.update(existing["id"], full_name=full_name)
                return existing["id"]

        # Try email as fallback
        if email:
            existing = await self.get_by_email(email)
            if existing:
                # Update phone if we now have it
                if phone and not existing["phone"]:
                    await self.update(existing["id"], phone=phone, full_name=full_name)
                return existing["id"]

        # Parse name if first/last not provided
        if not first_name and full_name:
            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else None

        # Create new candidate
        return await self.pool.fetchval(
            """
            INSERT INTO ats.candidates (phone, email, full_name, first_name, last_name, source, is_test)
            VALUES ($1, $2, $3, $4, $5, 'application', $6)
            RETURNING id
            """,
            phone, email, full_name, first_name, last_name, is_test
        )

    async def update(
        self,
        candidate_id: uuid.UUID,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> None:
        """Update candidate information."""
        updates = []
        params = []
        param_idx = 1

        if phone is not None:
            updates.append(f"phone = ${param_idx}")
            params.append(phone)
            param_idx += 1

        if email is not None:
            updates.append(f"email = ${param_idx}")
            params.append(email)
            param_idx += 1

        if full_name is not None:
            updates.append(f"full_name = ${param_idx}")
            params.append(full_name)
            param_idx += 1

        if first_name is not None:
            updates.append(f"first_name = ${param_idx}")
            params.append(first_name)
            param_idx += 1

        if last_name is not None:
            updates.append(f"last_name = ${param_idx}")
            params.append(last_name)
            param_idx += 1

        if not updates:
            return

        params.append(candidate_id)
        await self.pool.execute(
            f"UPDATE ats.candidates SET {', '.join(updates)}, updated_at = NOW() WHERE id = ${param_idx}",
            *params
        )

    async def list_all(self, limit: int = 100, offset: int = 0) -> List[asyncpg.Record]:
        """List all candidates with pagination."""
        return await self.pool.fetch(
            """
            SELECT * FROM ats.candidates
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset
        )

    async def count(self) -> int:
        """Get total candidate count."""
        return await self.pool.fetchval("SELECT COUNT(*) FROM ats.candidates")

    async def search(self, query: str, limit: int = 20) -> List[asyncpg.Record]:
        """Search candidates by name, phone, or email."""
        search_pattern = f"%{query}%"
        return await self.pool.fetch(
            """
            SELECT * FROM ats.candidates
            WHERE full_name ILIKE $1
               OR phone ILIKE $1
               OR email ILIKE $1
            ORDER BY full_name
            LIMIT $2
            """,
            search_pattern, limit
        )

    async def get_applications(self, candidate_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all applications for a candidate."""
        return await self.pool.fetch(
            """
            SELECT a.*, v.title as vacancy_title, v.company as vacancy_company
            FROM ats.applications a
            JOIN ats.vacancies v ON v.id = a.vacancy_id
            WHERE a.candidate_id = $1
            ORDER BY a.started_at DESC
            """,
            candidate_id
        )

    async def get_list(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        availability: Optional[str] = None,
        search: Optional[str] = None,
        is_test: Optional[bool] = None,
        sort_by: str = "status",
        sort_order: str = "asc"
    ) -> List[asyncpg.Record]:
        """
        Get candidates list with vacancy count and last activity.
        Used for the candidates overview page.

        Args:
            is_test: Filter by test flag. True = test candidates only, False = real candidates only, None = all
        """
        # Build WHERE clause
        conditions = []
        params = []
        param_idx = 1

        if status:
            conditions.append(f"c.status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if availability:
            conditions.append(f"c.availability = ${param_idx}")
            params.append(availability)
            param_idx += 1

        if search:
            conditions.append(f"(c.full_name ILIKE ${param_idx} OR c.email ILIKE ${param_idx} OR c.phone ILIKE ${param_idx})")
            params.append(f"%{search}%")
            param_idx += 1

        if is_test is not None:
            conditions.append(f"c.is_test = ${param_idx}")
            params.append(is_test)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Build ORDER BY clause
        sort_map = {
            "status": "c.status",
            "name": "c.full_name",
            "last_activity": "last_activity",
            "rating": "c.rating",
            "created_at": "c.created_at",
            "availability": "c.availability"
        }
        sort_column = sort_map.get(sort_by, "c.status")
        order = "DESC" if sort_order.lower() == "desc" else "ASC"
        nulls = "NULLS LAST" if order == "DESC" else "NULLS FIRST"

        params.extend([limit, offset])

        query = f"""
            SELECT
                c.*,
                COALESCE(app_stats.vacancy_count, 0) as vacancy_count,
                COALESCE(activity.last_activity, c.updated_at) as last_activity
            FROM ats.candidates c
            LEFT JOIN (
                SELECT candidate_id, COUNT(DISTINCT vacancy_id) as vacancy_count
                FROM ats.applications
                GROUP BY candidate_id
            ) app_stats ON app_stats.candidate_id = c.id
            LEFT JOIN (
                SELECT candidate_id, MAX(created_at) as last_activity
                FROM ats.agent_activities
                GROUP BY candidate_id
            ) activity ON activity.candidate_id = c.id
            {where_clause}
            ORDER BY {sort_column} {order} {nulls}, c.full_name ASC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        return await self.pool.fetch(query, *params)

    async def get_skills(self, candidate_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all skills for a candidate."""
        return await self.pool.fetch(
            """
            SELECT * FROM ats.candidate_skills
            WHERE candidate_id = $1
            ORDER BY score DESC NULLS LAST, skill_name
            """,
            candidate_id
        )

    async def get_skills_for_candidates(self, candidate_ids: List[uuid.UUID]) -> List[asyncpg.Record]:
        """Get skills for multiple candidates (batch load)."""
        if not candidate_ids:
            return []
        return await self.pool.fetch(
            """
            SELECT * FROM ats.candidate_skills
            WHERE candidate_id = ANY($1)
            ORDER BY candidate_id, score DESC NULLS LAST, skill_name
            """,
            candidate_ids
        )

    async def add_skill(
        self,
        candidate_id: uuid.UUID,
        skill_name: str,
        skill_code: Optional[str] = None,
        skill_category: Optional[str] = None,
        score: Optional[float] = None,
        evidence: Optional[str] = None,
        source: str = "manual"
    ) -> uuid.UUID:
        """Add a skill to a candidate (upsert)."""
        return await self.pool.fetchval(
            """
            INSERT INTO ats.candidate_skills
            (candidate_id, skill_name, skill_code, skill_category, score, evidence, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (candidate_id, skill_name) DO UPDATE SET
                skill_code = EXCLUDED.skill_code,
                skill_category = EXCLUDED.skill_category,
                score = EXCLUDED.score,
                evidence = EXCLUDED.evidence,
                source = EXCLUDED.source
            RETURNING id
            """,
            candidate_id, skill_name, skill_code, skill_category, score, evidence, source
        )

    async def remove_skill(self, candidate_id: uuid.UUID, skill_name: str) -> bool:
        """Remove a skill from a candidate."""
        result = await self.pool.execute(
            "DELETE FROM ats.candidate_skills WHERE candidate_id = $1 AND skill_name = $2",
            candidate_id, skill_name
        )
        return result == "DELETE 1"

    async def update_status(self, candidate_id: uuid.UUID, status: str) -> None:
        """Update candidate status and status_updated_at."""
        await self.pool.execute(
            """
            UPDATE ats.candidates
            SET status = $1, status_updated_at = NOW(), updated_at = NOW()
            WHERE id = $2
            """,
            status, candidate_id
        )

    async def update_availability(self, candidate_id: uuid.UUID, availability: str, available_from=None) -> None:
        """Update candidate availability."""
        await self.pool.execute(
            """
            UPDATE ats.candidates
            SET availability = $1, available_from = $2, updated_at = NOW()
            WHERE id = $3
            """,
            availability, available_from, candidate_id
        )

    async def update_rating(self, candidate_id: uuid.UUID, rating: float) -> None:
        """Update candidate rating."""
        await self.pool.execute(
            """
            UPDATE ats.candidates
            SET rating = $1, updated_at = NOW()
            WHERE id = $2
            """,
            rating, candidate_id
        )
