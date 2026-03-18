"""
Candidate repository - handles candidate database operations.
"""
import asyncpg
import uuid
from typing import Optional, List

# Default workspace ID for backwards compatibility
DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


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
        workspace_id: Optional[uuid.UUID] = None,
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
            workspace_id: Workspace ID (defaults to DEFAULT_WORKSPACE_ID)
        """
        # Use default workspace if not provided
        if workspace_id is None:
            workspace_id = DEFAULT_WORKSPACE_ID

        # Test candidates always get a fresh record (same phone is reused across test runs)
        if not is_test:
            # Try to find by phone first (primary identifier)
            if phone:
                existing = await self.get_by_phone(phone)
                if existing:
                    return existing["id"]

            # Try email as fallback
            if email:
                existing = await self.get_by_email(email)
                if existing:
                    if phone and not existing["phone"]:
                        await self.update(existing["id"], phone=phone)
                    return existing["id"]

        # Parse name if first/last not provided
        if not first_name and full_name:
            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else None

        # Create new candidate
        return await self.pool.fetchval(
            """
            INSERT INTO ats.candidates (phone, email, full_name, first_name, last_name, source, is_test, workspace_id)
            VALUES ($1, $2, $3, $4, $5, 'application', $6, $7)
            RETURNING id
            """,
            phone, email, full_name, first_name, last_name, is_test, workspace_id
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
    ) -> tuple[List[asyncpg.Record], int]:
        """
        Get candidates list with vacancy count and last activity.
        Used for the candidates overview page.

        Args:
            is_test: Filter by test flag. True = test candidates only, False = real candidates only, None = all

        Returns:
            Tuple of (rows, total_count)
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

        # Get total count with same filters
        count_query = f"SELECT COUNT(*) FROM ats.candidates c {where_clause}"
        total = await self.pool.fetchval(count_query, *params)

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
                FROM ats.candidacies
                GROUP BY candidate_id
            ) app_stats ON app_stats.candidate_id = c.id
            LEFT JOIN (
                SELECT candidate_id, MAX(created_at) as last_activity
                FROM system.activity_log
                GROUP BY candidate_id
            ) activity ON activity.candidate_id = c.id
            {where_clause}
            ORDER BY {sort_column} {order} {nulls}, c.full_name ASC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        rows = await self.pool.fetch(query, *params)
        return rows, total

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

    async def get_vacancies_for_candidates(self, candidate_ids: List[uuid.UUID]) -> List[asyncpg.Record]:
        """Get linked vacancies (via candidacies) for multiple candidates."""
        if not candidate_ids:
            return []
        return await self.pool.fetch(
            """
            SELECT c.candidate_id, v.id, v.title, v.company, v.is_open_application
            FROM ats.candidacies c
            JOIN ats.vacancies v ON v.id = c.vacancy_id
            WHERE c.candidate_id = ANY($1)
            ORDER BY c.candidate_id, c.created_at DESC
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

    async def get_candidacies(self, candidate_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all candidacies for a candidate with vacancy info and latest application."""
        return await self.pool.fetch(
            """
            SELECT
                c.id,
                c.vacancy_id,
                c.stage,
                c.source,
                c.stage_updated_at,
                c.created_at,
                v.title        AS vacancy_title,
                v.company      AS vacancy_company,
                v.is_open_application AS is_open_application,
                app.id                   AS app_id,
                app.channel              AS app_channel,
                app.status               AS app_status,
                app.qualified            AS app_qualified,
                app.completed_at         AS app_completed_at,
                (
                    SELECT COUNT(*)::int
                    FROM agents.pre_screening_answers
                    WHERE application_id = app.id AND passed IS NOT NULL
                ) AS app_ko_total,
                (
                    SELECT COUNT(*)::int
                    FROM agents.pre_screening_answers
                    WHERE application_id = app.id AND passed = true
                ) AS app_ko_passed,
                (
                    SELECT AVG(score)::int
                    FROM agents.pre_screening_answers
                    WHERE application_id = app.id AND passed IS NULL AND score IS NOT NULL
                ) AS app_score
            FROM ats.candidacies c
            LEFT JOIN ats.vacancies v ON v.id = c.vacancy_id
            LEFT JOIN LATERAL (
                SELECT a.id, a.channel, a.status, a.qualified, a.completed_at
                FROM ats.applications a
                WHERE a.candidacy_id = c.id
                  AND a.status IN ('active', 'completed')
                ORDER BY a.completed_at DESC NULLS LAST
                LIMIT 1
            ) app ON true
            WHERE c.candidate_id = $1
            ORDER BY c.stage_updated_at DESC
            """,
            candidate_id,
        )

    async def get_screening_results(self, application_ids: List[uuid.UUID]) -> dict:
        """
        Get full screening results (application details + answers) for a list of application IDs.
        Returns a dict keyed by application_id.
        """
        if not application_ids:
            return {}

        # Fetch application details
        apps = await self.pool.fetch(
            """
            SELECT id, channel, status, qualified, summary, interaction_seconds,
                   completed_at
            FROM ats.applications
            WHERE id = ANY($1)
            """,
            application_ids,
        )
        apps_by_id = {row["id"]: row for row in apps}

        # Fetch all answers for these applications
        answers = await self.pool.fetch(
            """
            SELECT application_id, question_id, question_text,
                   CASE WHEN passed IS NOT NULL THEN 'knockout' ELSE 'qualification' END AS question_type,
                   answer, passed, score, rating, motivation
            FROM agents.pre_screening_answers
            WHERE application_id = ANY($1)
            ORDER BY application_id, id
            """,
            application_ids,
        )

        # Group answers by application_id
        answers_by_app: dict[uuid.UUID, list] = {}
        ko_stats: dict[uuid.UUID, dict] = {}
        qual_stats: dict[uuid.UUID, dict] = {}

        for a in answers:
            app_id = a["application_id"]
            answers_by_app.setdefault(app_id, []).append(a)

            if a["passed"] is not None:
                stats = ko_stats.setdefault(app_id, {"total": 0, "passed": 0})
                stats["total"] += 1
                if a["passed"]:
                    stats["passed"] += 1
            elif a["score"] is not None:
                stats = qual_stats.setdefault(app_id, {"total": 0, "sum": 0})
                stats["total"] += 1
                stats["sum"] += a["score"]

        # Build result dict
        results = {}
        for app_id, app in apps_by_id.items():
            ko = ko_stats.get(app_id, {"total": 0, "passed": 0})
            qual = qual_stats.get(app_id, {"total": 0, "sum": 0})
            avg_score = int(qual["sum"] / qual["total"]) if qual["total"] > 0 else None

            # Only include answers for completed applications
            app_answers = answers_by_app.get(app_id, []) if app["status"] == "completed" else []

            results[app_id] = {
                "application_id": app_id,
                "channel": app["channel"],
                "status": app["status"],
                "qualified": app["qualified"],
                "summary": app["summary"],
                "interaction_seconds": app["interaction_seconds"] or 0,
                "knockout_passed": ko["passed"],
                "knockout_total": ko["total"],
                "open_questions_score": avg_score,
                "open_questions_total": qual["total"],
                "completed_at": app["completed_at"],
                "answers": app_answers,
            }

        return results

    async def get_document_collections_for_candidate(self, candidate_id: uuid.UUID) -> List[asyncpg.Record]:
        """
        Get document collections for a candidate with per-document upload status.
        Returns collections joined with required documents and their upload statuses.
        """
        # Get collections for this candidate
        collections = await self.pool.fetch(
            """
            SELECT
                dc.id,
                dc.candidate_id,
                dc.vacancy_id,
                dc.application_id,
                dc.status,
                dc.documents_required,
                dc.started_at,
                dc.completed_at,
                COALESCE(jsonb_array_length(dc.documents_required), 0) AS documents_total,
                COALESCE((
                    SELECT COUNT(*)
                    FROM agents.document_collection_uploads u
                    WHERE u.collection_id = dc.id AND u.status = 'verified'
                ), 0) AS documents_collected
            FROM agents.document_collections dc
            WHERE dc.candidate_id = $1
            ORDER BY dc.started_at DESC
            """,
            candidate_id,
        )

        if not collections:
            return []

        # Get uploads for all collections
        collection_ids = [c["id"] for c in collections]
        uploads = await self.pool.fetch(
            """
            SELECT u.collection_id, u.document_type_id, u.status, u.uploaded_at
            FROM agents.document_collection_uploads u
            WHERE u.collection_id = ANY($1)
            ORDER BY u.uploaded_at
            """,
            collection_ids,
        )

        # Get document type info for all referenced types
        doc_type_ids = set()
        for c in collections:
            if c["documents_required"]:
                import json as _json
                docs_req = c["documents_required"] if isinstance(c["documents_required"], list) else _json.loads(c["documents_required"])
                for doc in docs_req:
                    if isinstance(doc, dict) and "document_type_id" in doc:
                        doc_type_ids.add(uuid.UUID(doc["document_type_id"]))
        for u in uploads:
            if u["document_type_id"]:
                doc_type_ids.add(u["document_type_id"])

        doc_types = {}
        if doc_type_ids:
            rows = await self.pool.fetch(
                "SELECT id, name, icon FROM ontology.types_documents WHERE id = ANY($1)",
                list(doc_type_ids),
            )
            doc_types = {row["id"]: row for row in rows}

        # Group uploads by (collection_id, document_type_id) — take the latest/best status
        uploads_by_collection: dict[uuid.UUID, dict[uuid.UUID, dict]] = {}
        for u in uploads:
            coll_id = u["collection_id"]
            dt_id = u["document_type_id"]
            if dt_id is None:
                continue
            uploads_by_collection.setdefault(coll_id, {})
            existing = uploads_by_collection[coll_id].get(dt_id)
            # Keep the most relevant upload (verified > needs_review > rejected > pending)
            status_priority = {"verified": 4, "needs_review": 3, "rejected": 2, "pending": 1}
            if existing is None or status_priority.get(u["status"], 0) > status_priority.get(existing["status"], 0):
                uploads_by_collection[coll_id][dt_id] = {"status": u["status"], "uploaded_at": u["uploaded_at"]}

        # Build result
        result = []
        for c in collections:
            import json as _json
            docs_req = c["documents_required"] if isinstance(c["documents_required"], list) else (_json.loads(c["documents_required"]) if c["documents_required"] else [])
            coll_uploads = uploads_by_collection.get(c["id"], {})

            documents = []
            for doc in docs_req:
                if not isinstance(doc, dict) or "document_type_id" not in doc:
                    continue
                dt_id = uuid.UUID(doc["document_type_id"])
                dt_info = doc_types.get(dt_id, {})
                upload = coll_uploads.get(dt_id)
                documents.append({
                    "document_type_id": str(dt_id),
                    "document_type_name": dt_info.get("name", doc.get("name", "Onbekend")),
                    "icon": dt_info.get("icon"),
                    "status": upload["status"] if upload else "pending",
                    "uploaded_at": upload["uploaded_at"] if upload else None,
                })

            # Determine progress
            collected = int(c["documents_collected"])
            total = int(c["documents_total"])
            if collected == 0:
                progress = "pending"
            elif collected >= total:
                progress = "completed"
            else:
                progress = "in_progress"

            result.append({
                "collection_id": c["id"],
                "vacancy_id": c["vacancy_id"],
                "application_id": c["application_id"],
                "candidate_id": c["candidate_id"],
                "status": c["status"],
                "progress": progress,
                "documents_collected": collected,
                "documents_total": total,
                "documents": documents,
            })

        return result

    async def get_documents(self, candidate_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all documents for a candidate with document type info."""
        return await self.pool.fetch(
            """
            SELECT
                cd.id,
                cd.document_type_id,
                dt.name         AS document_type_name,
                dt.slug         AS document_type_slug,
                cd.document_number,
                cd.expiration_date,
                cd.status,
                cd.verification_passed,
                cd.storage_path,
                cd.notes,
                cd.created_at,
                cd.updated_at
            FROM ats.candidate_documents cd
            JOIN ontology.types_documents dt ON dt.id = cd.document_type_id
            WHERE cd.candidate_id = $1
            ORDER BY cd.created_at DESC
            """,
            candidate_id,
        )
