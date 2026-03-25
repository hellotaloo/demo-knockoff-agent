"""
Vacancy Import Service.

Provider-agnostic service that imports vacancies from an external ATS
into the local database. The provider layer (ConnexysProvider, etc.)
handles fetching raw records; this service handles field mapping,
transformation, and upserting into ats.vacancies.

After import, optionally auto-generates pre-screening questions for new
vacancies via the interview generator agent (when auto_generate is enabled).

Uses a background task pattern: POST starts the sync, GET polls for progress.
"""
import asyncio
import html as html_module
import json
import logging
import re
import unicodedata
import uuid as uuid_mod
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
from google.genai import types
from sqlalchemy.exc import IntegrityError
from google.adk.errors.already_exists_error import AlreadyExistsError

from src.services.providers import ATSProvider, get_provider
from src.services.integration_service import PROVIDER_MAPPING_CONFIG
from src.config import SIMULATED_REASONING

logger = logging.getLogger(__name__)

# Regex to extract {{field}} placeholders from mapping templates
TEMPLATE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

# Text sanitization patterns
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# In-memory sync progress (module-level singleton)
# ---------------------------------------------------------------------------

_sync_progress: dict | None = None


def get_sync_progress() -> dict | None:
    """Return current sync progress, or None if no sync has run."""
    return _sync_progress


def clear_sync_progress():
    """Clear sync progress."""
    global _sync_progress
    _sync_progress = None


def _reset_progress():
    """Reset progress to initial state."""
    global _sync_progress
    _sync_progress = {
        "status": "syncing",
        "message": "Vacatures ophalen...",
        "total_fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "unpublished": 0,
        "failed": 0,
    }


def _set_progress_error(message: str):
    global _sync_progress
    if _sync_progress is None:
        _sync_progress = {}
    _sync_progress["status"] = "error"
    _sync_progress["message"] = message


def _set_progress_complete():
    global _sync_progress
    if _sync_progress is None:
        return
    _sync_progress["status"] = "complete"
    _sync_progress["message"] = (
        f"Sync voltooid: {_sync_progress['inserted']} nieuw, "
        f"{_sync_progress['updated']} bijgewerkt, "
        f"{_sync_progress['skipped']} overgeslagen"
    )


class VacancyImportService:
    """Provider-agnostic vacancy import service."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def sync(self, workspace_id: UUID, full: bool = False) -> None:
        """
        Main sync entry point. Runs as a background task.

        1. Find active ATS connection for workspace
        2. Resolve provider + mapping
        3. Fetch raw records via provider
        4. Transform and upsert each record
        """
        _reset_progress()

        try:
            # Load the active ATS connection
            connection = await self._get_active_connection(workspace_id)
            if not connection:
                _set_progress_error("Geen actieve integratie gevonden voor deze workspace")
                return

            provider_slug = connection["slug"]
            try:
                credentials = json.loads(connection["credentials"]) if isinstance(connection["credentials"], str) else connection["credentials"]
                settings = json.loads(connection["settings"]) if isinstance(connection["settings"], str) else (connection["settings"] or {})
            except (json.JSONDecodeError, TypeError) as e:
                _set_progress_error(f"Ongeldige integratie-instellingen: {e}")
                return

            # Resolve the field mapping (custom or default)
            mapping = self._get_active_mapping(settings, provider_slug)

            # Get provider and fetch records (incremental: only since last sync)
            provider: ATSProvider = get_provider(provider_slug)
            last_synced_at = None if full else settings.get("last_synced_at")
            if last_synced_at:
                logger.info(f"Incremental sync since {last_synced_at}")
            else:
                logger.info("Full sync (no last_synced_at)")
            _update_progress(message="Vacatures ophalen van extern systeem...")

            raw_records = await provider.fetch_vacancies(credentials, settings, mapping, since=last_synced_at)
            _update_progress(total_fetched=len(raw_records), message=f"{len(raw_records)} vacatures opgehaald, importeren...")

            # Transform and upsert each record
            newly_inserted: list[dict] = []  # Track new vacancies for auto-generation

            async with self.pool.acquire() as conn:
                default_office_id = await self._get_default_office_location_id(conn, workspace_id)

                for record in raw_records:
                    try:
                        vacancy_data = self._transform_record(record, mapping)

                        # Filter: check sync_filter and is_online flags from ATS
                        sync_filter = vacancy_data.pop("sync_filter", None)
                        is_online_ats = vacancy_data.pop("is_online", None)
                        should_unpublish = (sync_filter is False) or (is_online_ats is False)

                        if should_unpublish:
                            # If vacancy already exists in TALOO, archive it and take agents offline
                            source_id = vacancy_data.get("source_id")
                            existing = await conn.fetchrow(
                                "SELECT id, status FROM ats.vacancies WHERE source = $1 AND source_id = $2 AND workspace_id = $3",
                                provider_slug, source_id, workspace_id,
                            )
                            if existing and existing["status"] not in ("closed", "filled"):
                                await self._archive_vacancy(conn, existing["id"])
                                _update_progress(unpublished=(_sync_progress or {}).get("unpublished", 0) + 1)
                            else:
                                _update_progress(skipped=(_sync_progress or {}).get("skipped", 0) + 1)
                            continue

                        # Ensure recruiter exists
                        recruiter_id = None
                        recruiter_email = vacancy_data.pop("recruiter_email", None)
                        recruiter_name = vacancy_data.pop("recruiter_name", None)
                        recruiter_phone = vacancy_data.pop("recruiter_phone", None)
                        recruiter_role = vacancy_data.pop("recruiter_role", None)
                        if recruiter_email:
                            recruiter_id = await self._ensure_recruiter(
                                conn, workspace_id, recruiter_email,
                                name=recruiter_name or None,
                                phone=recruiter_phone or None,
                                role=recruiter_role or None,
                            )

                        # Ensure client exists
                        client_id = None
                        company = vacancy_data.get("company")
                        if company:
                            client_id = await self._ensure_client(conn, workspace_id, company)

                        # Ensure office location exists (from Connexys data or fallback to default)
                        office_location_id = default_office_id
                        office_name = vacancy_data.pop("office_name", None)
                        office_email = vacancy_data.pop("office_email", None)
                        office_phone = vacancy_data.pop("office_phone", None)
                        office_address = vacancy_data.pop("office_address", None)
                        office_source_id = vacancy_data.pop("office_source_id", None)
                        office_spoken_name = vacancy_data.pop("office_spoken_name", None)
                        if office_name:
                            office_location_id = await self._ensure_office_location(
                                conn, workspace_id, provider_slug,
                                name=office_name,
                                email=office_email or None,
                                phone=office_phone or None,
                                address=office_address or None,
                                source_id=office_source_id or None,
                                spoken_name=office_spoken_name or None,
                            )

                        # Upsert the vacancy
                        action, vacancy_id = await self._upsert_vacancy(
                            conn, workspace_id, provider_slug,
                            vacancy_data, recruiter_id, client_id, office_location_id,
                        )

                        if action == "inserted":
                            _update_progress(inserted=(_sync_progress or {}).get("inserted", 0) + 1)
                            newly_inserted.append({
                                "id": str(vacancy_id),
                                "title": vacancy_data.get("title", ""),
                                "description": vacancy_data.get("description", ""),
                            })
                        elif action == "reopened":
                            from src.events import emit
                            await emit("vacancy_reopened", pool=self.pool, vacancy_id=vacancy_id)
                            _update_progress(updated=(_sync_progress or {}).get("updated", 0) + 1)
                        elif action == "updated":
                            _update_progress(updated=(_sync_progress or {}).get("updated", 0) + 1)

                    except Exception as e:
                        logger.error(f"Failed to import record {record.get('Id', '?')}: {e}")
                        _update_progress(failed=(_sync_progress or {}).get("failed", 0) + 1)

            # Save last_synced_at for incremental sync next time
            await self._save_last_synced_at(connection["id"], settings)

            _set_progress_complete()

            # Phase 2: Auto-generate pre-screening questions for new vacancies
            if newly_inserted:
                await self._auto_generate_pre_screenings(workspace_id, newly_inserted)

        except Exception as e:
            logger.error(f"Vacancy sync failed: {e}", exc_info=True)
            _set_progress_error(f"Sync mislukt: {str(e)}")

    # =========================================================================
    # Connection & Mapping
    # =========================================================================

    async def _get_active_connection(self, workspace_id: UUID) -> Optional[asyncpg.Record]:
        """Find the active ATS integration connection for this workspace."""
        return await self.pool.fetchrow("""
            SELECT
                ic.id, ic.credentials, ic.settings,
                i.slug
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.workspace_id = $1
              AND ic.is_active = true
              AND i.slug != 'microsoft'
            LIMIT 1
        """, workspace_id)

    async def _save_last_synced_at(self, connection_id: UUID, settings: dict):
        """Persist the sync timestamp in the connection settings for incremental sync."""
        settings["last_synced_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self.pool.execute(
            "UPDATE system.integration_connections SET settings = $1 WHERE id = $2",
            json.dumps(settings), connection_id,
        )

    @staticmethod
    def _get_active_mapping(settings: dict, provider_slug: str) -> dict:
        """Get the active field mapping: custom from settings, or provider default.

        Always merges the default mapping as a base so that system fields
        (like office_source_id) are included even if the user hasn't
        configured them in the UI.
        """
        config = PROVIDER_MAPPING_CONFIG.get(provider_slug, {})
        default = config.get("default_mapping", {})
        custom = settings.get("field_mapping", {}).get("mappings")
        if custom:
            # Default first, then custom overrides
            merged = {**default, **custom}
            return merged
        return default

    # =========================================================================
    # Field Mapping & Transformation
    # =========================================================================

    @staticmethod
    def _resolve_template(template: str, record: dict) -> str:
        """
        Resolve {{Field.Name}} placeholders from a record dict.

        Handles nested fields like Owner.Email by traversing the dict.
        Returns empty string for None values.
        """
        def replacer(match):
            field_path = match.group(1)
            value = _get_nested_value(record, field_path)
            return str(value) if value is not None else ""
        return TEMPLATE_PATTERN.sub(replacer, template).strip()

    # Fields that contain HTML content (should preserve tags but sanitize)
    HTML_FIELDS = {"description"}

    @classmethod
    def _transform_record(cls, record: dict, mapping: dict) -> dict:
        """
        Apply the full field mapping to a raw record.

        Returns a dict with keys matching Taloo vacancy fields.
        Handles type coercion for dates and booleans.
        Sanitizes text to remove control characters, null bytes, etc.
        """
        result = {}
        for target_field, config in mapping.items():
            template = config.get("template", "")
            if not template:
                continue
            value = cls._resolve_template(template, record)
            if value:
                value = _clean_text(value, is_html=target_field in cls.HTML_FIELDS)
            result[target_field] = value

        # Type coercion
        if "start_date" in result:
            result["start_date"] = _parse_date(result["start_date"])
        if "sync_filter" in result:
            result["sync_filter"] = _parse_boolean(result["sync_filter"])
        if "is_online" in result:
            # ATS is_online maps to should_unpublish logic, parse as boolean
            result["is_online"] = _parse_boolean(result["is_online"])

        return result

    # =========================================================================
    # Database Operations
    # =========================================================================

    @staticmethod
    async def _upsert_vacancy(
        conn: asyncpg.Connection,
        workspace_id: UUID,
        source: str,
        data: dict,
        recruiter_id: Optional[UUID],
        client_id: Optional[UUID],
        office_location_id: Optional[UUID],
    ) -> tuple[str, Optional[UUID]]:
        """
        Insert or update a vacancy by source + source_id.

        Returns (action, vacancy_id) where action is "inserted" or "updated".
        """
        source_id = data.get("source_id")
        if not source_id:
            raise ValueError("source_id is required for vacancy upsert")

        existing = await conn.fetchrow(
            "SELECT id, status FROM ats.vacancies WHERE source = $1 AND source_id = $2 AND workspace_id = $3",
            source, source_id, workspace_id,
        )

        if existing:
            was_archived = existing["status"] in ("closed", "filled")
            await conn.execute("""
                UPDATE ats.vacancies SET
                    title = $2, company = $3, location = $4, description = $5,
                    start_date = $6, recruiter_id = $7, client_id = $8,
                    office_location_id = $9, job_url_website = $10,
                    status = 'open'
                WHERE id = $1
            """,
                existing["id"],
                data.get("title"), data.get("company"), data.get("location"),
                data.get("description"), data.get("start_date"),
                recruiter_id, client_id, office_location_id,
                data.get("job_url_website"),
            )
            return ("reopened" if was_archived else "updated"), existing["id"]
        else:
            row = await conn.fetchrow("""
                INSERT INTO ats.vacancies
                    (title, company, location, description, status, source, source_id,
                     start_date, recruiter_id, client_id, workspace_id, office_location_id,
                     job_url_website)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING id
            """,
                data.get("title"), data.get("company"), data.get("location"),
                data.get("description"), "open", source, source_id,
                data.get("start_date"), recruiter_id, client_id,
                workspace_id, office_location_id,
                data.get("job_url_website"),
            )

            # Register default agents for new vacancies
            await conn.execute("""
                INSERT INTO ats.vacancy_agents (vacancy_id, agent_type, status)
                VALUES ($1, 'document_collection', 'generated')
                ON CONFLICT (vacancy_id, agent_type) DO NOTHING
            """, row["id"])

            return "inserted", row["id"]

    async def _archive_vacancy(self, conn: asyncpg.Connection, vacancy_id: UUID):
        """Archive vacancy and emit event for agents to handle their own cleanup."""
        from src.events import emit

        await conn.execute(
            "UPDATE ats.vacancies SET status = 'closed' WHERE id = $1",
            vacancy_id,
        )
        await emit("vacancy_archived", pool=self.pool, vacancy_id=vacancy_id)

    @staticmethod
    async def _ensure_recruiter(
        conn: asyncpg.Connection,
        workspace_id: UUID,
        email: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
    ) -> UUID:
        """Lookup recruiter by email, or create if not found. Updates name/phone/role on existing."""
        existing = await conn.fetchrow(
            "SELECT id FROM ats.recruiters WHERE email = $1", email,
        )
        if existing:
            # Update fields that may have changed
            await conn.execute("""
                UPDATE ats.recruiters
                SET name = COALESCE($2, name),
                    phone = COALESCE($3, phone),
                    role = COALESCE($4, role)
                WHERE id = $1
            """, existing["id"], name, phone, role)
            return existing["id"]

        row = await conn.fetchrow("""
            INSERT INTO ats.recruiters (name, email, phone, role, is_active)
            VALUES ($1, $2, $3, $4, true)
            RETURNING id
        """, name or email, email, phone, role)
        return row["id"]

    @staticmethod
    async def _ensure_client(
        conn: asyncpg.Connection, workspace_id: UUID, company_name: str,
    ) -> UUID:
        """Lookup client by name, or create if not found."""
        existing = await conn.fetchrow(
            "SELECT id FROM ats.clients WHERE name = $1 AND workspace_id = $2",
            company_name, workspace_id,
        )
        if existing:
            return existing["id"]

        row = await conn.fetchrow("""
            INSERT INTO ats.clients (name, workspace_id)
            VALUES ($1, $2)
            RETURNING id
        """, company_name, workspace_id)
        return row["id"]

    @staticmethod
    async def _ensure_office_location(
        conn: asyncpg.Connection,
        workspace_id: UUID,
        source: str,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        address: Optional[str] = None,
        source_id: Optional[str] = None,
        spoken_name: Optional[str] = None,
    ) -> UUID:
        """Lookup office location by source + source_id, or by name. Create if not found."""
        # Clean up address (template may produce "  ,  " when fields are empty)
        if address:
            address = ", ".join(part.strip() for part in address.split(",") if part.strip())
            if not address:
                address = None

        # Try to find by source_id first (most reliable)
        if source_id:
            existing = await conn.fetchrow(
                "SELECT id FROM ats.office_locations WHERE workspace_id = $1 AND source = $2 AND source_id = $3",
                workspace_id, source, source_id,
            )
            if existing:
                # Update fields that may have changed
                await conn.execute("""
                    UPDATE ats.office_locations
                    SET name = $2, email = $3, phone = $4, address = COALESCE($5, address),
                        spoken_name = COALESCE($6, spoken_name),
                        updated_at = now()
                    WHERE id = $1
                """, existing["id"], name, email, phone, address, spoken_name)
                return existing["id"]

        # Fallback: match by name within workspace
        existing = await conn.fetchrow(
            "SELECT id FROM ats.office_locations WHERE workspace_id = $1 AND name = $2",
            workspace_id, name,
        )
        if existing:
            await conn.execute("""
                UPDATE ats.office_locations
                SET email = COALESCE($2, email), phone = COALESCE($3, phone),
                    address = COALESCE($4, address),
                    source = COALESCE($5, source), source_id = COALESCE($6, source_id),
                    spoken_name = COALESCE($7, spoken_name),
                    updated_at = now()
                WHERE id = $1
            """, existing["id"], email, phone, address, source, source_id, spoken_name)
            return existing["id"]

        # Create new office location
        row = await conn.fetchrow("""
            INSERT INTO ats.office_locations (workspace_id, name, address, email, phone, source, source_id, spoken_name)
            VALUES ($1, $2, COALESCE($3, ''), $4, $5, $6, $7, $8)
            RETURNING id
        """, workspace_id, name, address, email, phone, source, source_id, spoken_name)
        return row["id"]

    @staticmethod
    async def _get_default_office_location_id(conn: asyncpg.Connection, workspace_id: UUID) -> Optional[UUID]:
        """Look up the default office location for a workspace."""
        row = await conn.fetchrow(
            "SELECT id FROM ats.office_locations WHERE workspace_id = $1 AND is_default = true LIMIT 1",
            workspace_id,
        )
        return row["id"] if row else None

    # =========================================================================
    # Auto-generate pre-screening questions
    # =========================================================================

    async def _is_auto_generate_enabled(self, workspace_id: UUID) -> bool:
        """Check if auto-generate is enabled in the pre_screening agent config."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT settings FROM agents.agent_config "
                "WHERE workspace_id = $1 AND config_type = 'pre_screening' AND is_active = true "
                "LIMIT 1",
                workspace_id,
            )
        if not row:
            return True  # Default: enabled

        settings = row["settings"]
        if isinstance(settings, str):
            settings = json.loads(settings)
        return settings.get("publishing", {}).get("auto_generate", True)

    MAX_CONCURRENT_GENERATIONS = 3

    async def _auto_generate_pre_screenings(
        self, workspace_id: UUID, newly_inserted: list[dict]
    ) -> None:
        """
        Auto-generate pre-screening questions for newly imported vacancies.

        Checks the auto_generate setting, then for each new vacancy that
        doesn't already have a pre-screening, creates a workflow and runs
        the interview generator agent.

        Vacancies are processed concurrently (up to MAX_CONCURRENT_GENERATIONS)
        so that slow generations or human-in-the-loop review gates don't block
        the rest of the batch.
        """
        auto_generate = await self._is_auto_generate_enabled(workspace_id)
        if not auto_generate:
            logger.info(
                f"Auto-generate disabled — skipping question generation for "
                f"{len(newly_inserted)} new vacancies"
            )
            return

        from src.workflows.orchestrator import get_orchestrator
        orchestrator = await get_orchestrator()

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_GENERATIONS)
        counters = {"generated": 0, "failed": 0, "skipped": 0}
        lock = asyncio.Lock()

        async def _process_one(vac: dict) -> None:
            async with semaphore:
                # Re-check setting — stop if toggled off mid-run
                if not await self._is_auto_generate_enabled(workspace_id):
                    logger.info("Auto-generate disabled mid-run — skipping remaining vacancies")
                    return

                vacancy_id = vac["id"]

                # Skip if pre-screening was already generated (e.g. manually via frontend)
                async with self.pool.acquire() as conn:
                    existing_ps = await conn.fetchrow(
                        "SELECT id FROM agents.pre_screenings WHERE vacancy_id = $1",
                        UUID(vacancy_id),
                    )
                if existing_ps:
                    logger.info(f"Skipping generation for {vacancy_id} — pre-screening already exists")
                    async with lock:
                        counters["skipped"] += 1
                    return

                # Create vacancy_setup workflow
                try:
                    # Register prescreening agent as 'generating'
                    from src.repositories import VacancyRepository
                    vacancy_repo = VacancyRepository(self.pool)
                    await vacancy_repo.ensure_agent_registered(UUID(vacancy_id), "prescreening", status="generating")

                    workflow_id = await orchestrator.create_workflow(
                        workflow_type="vacancy_setup",
                        context={
                            "vacancy_id": vacancy_id,
                            "vacancy_title": vac["title"],
                            "source": "ats_import",
                        },
                        initial_step="generating",
                        workspace_id=workspace_id,
                    )

                    result = await self._generate_pre_screening(
                        vacancy_id=UUID(vacancy_id),
                        vacancy_title=vac["title"],
                        vacancy_description=vac["description"],
                        workflow_id=workflow_id,
                        workspace_id=workspace_id,
                    )

                    async with lock:
                        if result.get("success"):
                            counters["generated"] += 1
                        else:
                            counters["failed"] += 1
                            logger.warning(
                                f"Failed to generate pre-screening for {vac['title']}: "
                                f"{result.get('error', 'unknown')}"
                            )
                except Exception as e:
                    async with lock:
                        counters["failed"] += 1
                    logger.error(f"Error generating pre-screening for {vacancy_id}: {e}")

        # Run all vacancies concurrently (bounded by semaphore)
        tasks = [_process_one(vac) for vac in newly_inserted]
        gather_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any unexpected exceptions that slipped past the try/except
        for i, r in enumerate(gather_results):
            if isinstance(r, Exception):
                logger.error(f"Unexpected error in vacancy generation task {i}: {r}")

        logger.info(
            f"Auto-generate complete: {counters['generated']} generated, "
            f"{counters['failed']} failed, {counters['skipped']} skipped "
            f"out of {len(newly_inserted)} new vacancies"
        )

    async def _generate_pre_screening(
        self,
        vacancy_id: UUID,
        vacancy_title: str,
        vacancy_description: str,
        workflow_id: str | None = None,
        workspace_id: UUID | None = None,
    ) -> dict:
        """
        Generate pre-screening questions for a vacancy using the interview
        generator agent, save them to the database, and fire questions_saved
        on the vacancy_setup workflow.

        Returns dict with success status and question count.
        """
        from src.dependencies import get_session_manager
        from src.repositories.pre_screening_repo import PreScreeningRepository
        from src.workflows.orchestrator import get_orchestrator

        try:
            session_manager = get_session_manager()
        except RuntimeError:
            logger.warning(f"SessionManager not available, skipping generation for {vacancy_id}")
            return {"success": False, "error": "session_manager_not_available"}

        session_id = str(uuid_mod.uuid4())

        try:
            # 1. Create ADK session
            try:
                await session_manager.interview_session_service.create_session(
                    app_name="interview_question_generator",
                    user_id="ats_import",
                    session_id=session_id,
                )
            except (IntegrityError, AlreadyExistsError):
                logger.info(f"Session {session_id} already exists, continuing")

            # 2. Run the interview generator agent
            content = types.Content(
                role="user",
                parts=[types.Part(text=vacancy_description)],
            )

            interview = None
            async for event in session_manager.interview_runner.run_async(
                user_id="ats_import",
                session_id=session_id,
                new_message=content,
            ):
                if event.is_final_response():
                    session = await session_manager.interview_session_service.get_session(
                        app_name="interview_question_generator",
                        user_id="ats_import",
                        session_id=session_id,
                    )
                    if session:
                        interview = session.state.get("interview", {})
                        if isinstance(interview, str):
                            interview = json.loads(interview)

            if not interview or not interview.get("knockout_questions"):
                logger.warning(f"No interview generated for vacancy {vacancy_id}")
                return {"success": False, "error": "no_questions_generated"}

            # 3. Save questions to database
            ps_repo = PreScreeningRepository(self.pool)
            pre_screening_id = await ps_repo.upsert(
                vacancy_id=vacancy_id,
                intro=interview.get("intro", ""),
                knockout_failed_action=interview.get("knockout_failed_action", ""),
                final_action=interview.get("final_action", ""),
                knockout_questions=interview.get("knockout_questions", []),
                qualification_questions=interview.get("qualification_questions", []),
                approved_ids=interview.get("approved_ids", []),
                display_title=interview.get("display_title"),
            )

            ko_count = len(interview.get("knockout_questions", []))
            qual_count = len(interview.get("qualification_questions", []))
            total_questions = ko_count + qual_count

            logger.info(
                f"Generated {total_questions} questions for vacancy {vacancy_id} "
                f"({ko_count} knockout, {qual_count} qualification)"
            )

            # 4. Fire questions_saved on the vacancy_setup workflow
            orchestrator = await get_orchestrator()

            if workflow_id:
                await orchestrator.handle_event(workflow_id, "questions_saved", {
                    "pre_screening_id": str(pre_screening_id),
                    "vacancy_id": str(vacancy_id),
                })

            logger.info(
                f"Vacancy setup workflow {workflow_id[:8] if workflow_id else '?'} "
                f"started for {vacancy_title}"
            )

            return {"success": True, "questions_count": total_questions}

        except Exception as e:
            logger.error(f"Failed to generate pre-screening for vacancy {vacancy_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # Clean up the ADK session
            try:
                await session_manager.interview_session_service.delete_session(
                    app_name="interview_question_generator",
                    user_id="ats_import",
                    session_id=session_id,
                )
            except Exception:
                pass


# =============================================================================
# Helpers
# =============================================================================

def _clean_text(value: str, *, is_html: bool = False) -> str:
    """
    Sanitize text from external ATS systems.

    Removes null bytes, control characters, decodes HTML entities, and
    normalizes unicode. For plain-text fields (is_html=False), also strips
    HTML tags and collapses whitespace. For HTML fields (description),
    preserves tags but still cleans control chars and entities.
    """
    if not value:
        return value
    # Unicode NFC normalization (prevents duplicate entries from different byte representations)
    value = unicodedata.normalize("NFC", value)
    # Remove null bytes and control characters (keep \t, \n, \r)
    value = _CONTROL_CHAR_RE.sub("", value)
    # Decode HTML entities (handles double-encoded like &amp;amp; on first pass)
    value = html_module.unescape(value)
    if not is_html:
        # Strip HTML tags from plain-text fields
        value = _HTML_TAG_RE.sub("", value)
        # Collapse whitespace
        value = _MULTI_SPACE_RE.sub(" ", value)
        value = value.strip()
    else:
        # For HTML fields, just collapse excessive newlines
        value = _MULTI_NEWLINE_RE.sub("\n\n", value)
        value = value.strip()
    return value


def _get_nested_value(record: dict, field_path: str):
    """Resolve a dotted field path like 'Owner.Email' from a nested dict."""
    parts = field_path.split(".")
    current = record
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _parse_date(value: str) -> Optional[date]:
    """Parse an ISO date string to a date object. Returns None on failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _parse_boolean(value) -> Optional[bool]:
    """Parse a boolean value from various representations."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _update_progress(**kwargs):
    """Update specific fields in the sync progress dict."""
    global _sync_progress
    if _sync_progress is None:
        return
    _sync_progress.update(kwargs)
