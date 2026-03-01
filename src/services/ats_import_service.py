"""
ATS Import Service.

Fetches vacancy, recruiter, and client data from an external ATS API
and imports it into the Taloo database.

After each vacancy is imported, triggers the vacancy_setup workflow
which generates pre-screening questions via the interview generator agent,
analyzes them, and auto-publishes.

Uses a background task pattern: POST starts the import, GET polls for progress.
"""
import asyncio
import json
import logging
import uuid as uuid_mod
from uuid import UUID

import httpx
import asyncpg
from google.genai import types
from sqlalchemy.exc import IntegrityError
from google.adk.errors.already_exists_error import AlreadyExistsError

from src.models.ats_simulator import (
    ATSVacancy,
    ATSRecruiter,
    ATSClient,
    ATSImportResult,
)
from src.config import ATS_SIMULATOR_URL, SIMULATED_REASONING

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory import progress (module-level singleton)
# ---------------------------------------------------------------------------

_import_progress: dict | None = None


def get_import_progress() -> dict | None:
    """Return current import progress, or None if no import has run."""
    return _import_progress


def clear_import_progress():
    """Clear import progress (called on reset)."""
    global _import_progress
    _import_progress = None


def _reset_progress():
    """Reset progress to initial state."""
    global _import_progress
    _import_progress = {
        "status": "importing",
        "message": "Vacatures importeren...",
        "vacancies": [],
    }


def _set_progress_error(message: str):
    global _import_progress
    if _import_progress is None:
        _import_progress = {}
    _import_progress["status"] = "error"
    _import_progress["message"] = message


def _set_progress_queue(vacancies: list[dict]):
    global _import_progress
    if _import_progress is None:
        return
    _import_progress["status"] = "generating"
    _import_progress["message"] = "Pre-screening vragen genereren..."
    _import_progress["vacancies"] = vacancies


def _update_vacancy_progress(vacancy_id: str, status: str, questions_count: int | None = None, activity: str | None = None):
    global _import_progress
    if _import_progress is None:
        return
    for v in _import_progress["vacancies"]:
        if v["id"] == vacancy_id:
            v["status"] = status
            if questions_count is not None:
                v["questions_count"] = questions_count
            if activity is not None:
                v["activity"] = activity
            break


def _update_vacancy_activity(vacancy_id: str, activity: str):
    """Update just the activity text for a vacancy (without changing status)."""
    global _import_progress
    if _import_progress is None:
        return
    for v in _import_progress["vacancies"]:
        if v["id"] == vacancy_id:
            v["activity"] = activity
            break


def _set_progress_complete(total: int, published: int, failed: int):
    global _import_progress
    if _import_progress is None:
        return
    _import_progress["status"] = "complete"
    _import_progress["total"] = total
    _import_progress["published"] = published
    _import_progress["failed"] = failed


class ATSImportService:
    """Service for importing data from an external ATS system."""

    def __init__(self, pool: asyncpg.Pool, ats_base_url: str | None = None):
        self.pool = pool
        self.ats_base_url = (ats_base_url or ATS_SIMULATOR_URL).rstrip("/")

    async def import_all(self, workspace_id: UUID) -> ATSImportResult:
        """
        Full import: fetch recruiters, clients, and vacancies from the ATS
        and insert them into the database.

        Returns import result with counts and created IDs.
        """
        result = ATSImportResult()

        async with httpx.AsyncClient(timeout=30.0) as client:
            recruiter_email_to_id = await self._import_recruiters(client, workspace_id, result)
            client_name_to_id = await self._import_clients(client, workspace_id, result)
            await self._import_vacancies(
                client, workspace_id, recruiter_email_to_id, client_name_to_id, result
            )

        logger.info(
            f"ATS import complete: {result.recruiters_imported} recruiters, "
            f"{result.clients_imported} clients, {result.vacancies_imported} vacancies"
        )
        return result

    async def import_and_generate(self, workspace_id: UUID):
        """
        Background import: imports ATS data, then generates pre-screenings
        for each vacancy one by one. Updates in-memory progress throughout.

        This method is meant to be run as an asyncio background task.
        """
        _reset_progress()
        result = ATSImportResult()
        imported_vacancies: list[dict] = []

        # Phase 1: Import all ATS data
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                recruiter_email_to_id = await self._import_recruiters(client, workspace_id, result)
                client_name_to_id = await self._import_clients(client, workspace_id, result)

                raw_vacancies = await self._fetch_all_pages(client, "/api/v1/vacancies")

                async with self.pool.acquire() as conn:
                    office_location_id = await self._get_default_office_location_id(conn, workspace_id)

                    for vac_data in raw_vacancies:
                        vac = ATSVacancy(**vac_data)

                        existing = await conn.fetchval(
                            "SELECT id FROM ats.vacancies WHERE source_id = $1 AND workspace_id = $2",
                            vac.external_id, workspace_id,
                        )

                        if existing:
                            continue

                        internal_status = self._map_vacancy_status(vac.status)
                        recruiter_id = recruiter_email_to_id.get(vac.recruiter_email) if vac.recruiter_email else None
                        client_id = client_name_to_id.get(vac.client_name) if vac.client_name else None

                        row = await conn.fetchrow("""
                            INSERT INTO ats.vacancies
                            (title, company, location, description, status, source, source_id,
                             recruiter_id, client_id, workspace_id, office_location_id)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                            RETURNING id
                        """, vac.title, vac.company_name, vac.work_location,
                            vac.description_html, internal_status,
                            "ats_import", vac.external_id,
                            recruiter_id, client_id, workspace_id, office_location_id)

                        result.vacancies_imported += 1
                        imported_vacancies.append({
                            "id": str(row["id"]),
                            "title": vac.title,
                            "description": vac.description_html or "",
                        })

        except Exception as e:
            logger.error(f"ATS import failed: {e}")
            _set_progress_error(str(e))
            return

        if not imported_vacancies:
            _set_progress_complete(total=0, published=0, failed=0)
            return

        # Phase 2: Set up the queue and create workflows upfront for all vacancies.
        # This allows the manual "Genereren" button in the frontend to find the
        # existing workflow via find_by_context() and fire events on it.
        from src.workflows.orchestrator import get_orchestrator
        orchestrator = await get_orchestrator()

        vacancy_workflow_map: dict[str, str] = {}  # vacancy_id → workflow_id

        _set_progress_queue([
            {"id": v["id"], "title": v["title"], "status": "queued"}
            for v in imported_vacancies
        ])

        for vac in imported_vacancies:
            workflow_id = await orchestrator.create_workflow(
                workflow_type="vacancy_setup",
                context={
                    "vacancy_id": vac["id"],
                    "vacancy_title": vac["title"],
                    "source": "ats_import",
                },
                initial_step="generating",
            )
            vacancy_workflow_map[vac["id"]] = workflow_id

        logger.info(f"Created {len(vacancy_workflow_map)} vacancy_setup workflows upfront")

        published_count = 0
        failed_count = 0

        for vac in imported_vacancies:
            vacancy_id = vac["id"]

            # Skip if pre-screening was already generated (e.g. manually via frontend).
            # When the user saves manually, save_pre_screening finds the workflow we
            # created above and fires questions_saved, advancing it to complete.
            async with self.pool.acquire() as conn:
                existing_ps = await conn.fetchrow(
                    "SELECT id, status FROM ats.pre_screenings WHERE vacancy_id = $1",
                    UUID(vacancy_id),
                )
            if existing_ps:
                logger.info(f"Skipping generation for {vacancy_id} — pre-screening already exists")
                questions_count = 0
                async with self.pool.acquire() as conn:
                    questions_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM ats.pre_screening_questions WHERE pre_screening_id = $1",
                        existing_ps["id"],
                    )
                published_count += 1
                _update_vacancy_progress(
                    vacancy_id, "published",
                    questions_count=questions_count,
                    activity="Gepubliceerd",
                )
                continue

            _update_vacancy_progress(vacancy_id, "generating", activity="Vacaturetekst analyseren...")

            gen_result = await self._generate_pre_screening(
                vacancy_id=UUID(vacancy_id),
                vacancy_title=vac["title"],
                vacancy_description=vac["description"],
                workflow_id=vacancy_workflow_map[vacancy_id],
            )

            if gen_result.get("success"):
                published_count += 1
                _update_vacancy_progress(
                    vacancy_id, "published",
                    questions_count=gen_result.get("questions_count", 0),
                    activity="Gepubliceerd",
                )
            else:
                failed_count += 1
                _update_vacancy_progress(vacancy_id, "failed", activity="Generatie mislukt")

        _set_progress_complete(
            total=len(imported_vacancies),
            published=published_count,
            failed=failed_count,
        )

        logger.info(
            f"ATS import + generation complete: {len(imported_vacancies)} vacancies, "
            f"{published_count} published, {failed_count} failed"
        )

    async def _generate_pre_screening(
        self,
        vacancy_id: UUID,
        vacancy_title: str,
        vacancy_description: str,
        workflow_id: str | None = None,
    ) -> dict:
        """
        Generate pre-screening questions for a vacancy using the interview generator agent,
        save them to the database, and fire questions_saved on the vacancy_setup workflow.

        The workflow should already exist (created upfront in import_and_generate).

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

        # Create a unique ADK session for this generation
        session_id = str(uuid_mod.uuid4())

        try:
            # 1. Create ADK session
            try:
                await session_manager.interview_session_service.create_session(
                    app_name="interview_generator",
                    user_id="ats_import",
                    session_id=session_id,
                )
            except (IntegrityError, AlreadyExistsError):
                logger.info(f"Session {session_id} already exists, continuing")

            # 2. Run the interview generator agent with simulated reasoning messages
            vid = str(vacancy_id)

            # Background task: cycle through reasoning messages while agent runs
            reasoning_done = asyncio.Event()

            async def _simulate_reasoning():
                while not reasoning_done.is_set():
                    for msg in SIMULATED_REASONING:
                        if reasoning_done.is_set():
                            return
                        _update_vacancy_activity(vid, msg)
                        await asyncio.sleep(3.0)

            reasoning_task = asyncio.create_task(_simulate_reasoning())

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
                        app_name="interview_generator",
                        user_id="ats_import",
                        session_id=session_id,
                    )
                    if session:
                        interview = session.state.get("interview", {})
                        if isinstance(interview, str):
                            interview = json.loads(interview)

            if not interview or not interview.get("knockout_questions"):
                reasoning_done.set()
                await reasoning_task
                logger.warning(f"No interview generated for vacancy {vacancy_id}")
                return {"success": False, "error": "no_questions_generated"}

            # 3. Save questions to database via PreScreeningRepository
            ps_repo = PreScreeningRepository(self.pool)
            pre_screening_id = await ps_repo.upsert(
                vacancy_id=vacancy_id,
                intro=interview.get("intro", ""),
                knockout_failed_action=interview.get("knockout_failed_action", ""),
                final_action=interview.get("final_action", ""),
                knockout_questions=interview.get("knockout_questions", []),
                qualification_questions=interview.get("qualification_questions", []),
                approved_ids=interview.get("approved_ids", []),
            )

            ko_count = len(interview.get("knockout_questions", []))
            qual_count = len(interview.get("qualification_questions", []))
            total_questions = ko_count + qual_count

            logger.info(
                f"Generated {total_questions} questions for vacancy {vacancy_id} "
                f"({ko_count} knockout, {qual_count} qualification)"
            )

            # 4. Fire questions_saved on the existing vacancy_setup workflow
            orchestrator = await get_orchestrator()

            if not workflow_id:
                # Fallback: find or create workflow (shouldn't happen in normal flow)
                workflow = await orchestrator.find_by_context("vacancy_id", str(vacancy_id))
                if workflow:
                    workflow_id = workflow["id"]
                else:
                    workflow_id = await orchestrator.create_workflow(
                        workflow_type="vacancy_setup",
                        context={
                            "vacancy_id": str(vacancy_id),
                            "vacancy_title": vacancy_title,
                            "source": "ats_import",
                        },
                        initial_step="generating",
                    )

            await orchestrator.handle_event(workflow_id, "questions_saved", {
                "pre_screening_id": str(pre_screening_id),
                "vacancy_id": str(vacancy_id),
            })

            # Stop reasoning messages now that everything is done
            reasoning_done.set()
            await reasoning_task
            _update_vacancy_activity(vid, "Kandidaat-reacties simuleren...")

            logger.info(
                f"Vacancy setup workflow {workflow_id[:8]} started for {vacancy_title}"
            )

            return {"success": True, "questions_count": total_questions}

        except Exception as e:
            logger.error(f"Failed to generate pre-screening for vacancy {vacancy_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # Clean up the ADK session
            try:
                await session_manager.interview_session_service.delete_session(
                    app_name="interview_generator",
                    user_id="ats_import",
                    session_id=session_id,
                )
            except Exception:
                pass

    async def _fetch_all_pages(self, http_client: httpx.AsyncClient, endpoint: str) -> list[dict]:
        """Fetch all pages from a paginated ATS endpoint."""
        all_items = []
        page = 1

        while True:
            response = await http_client.get(
                f"{self.ats_base_url}{endpoint}",
                params={"page": page, "page_size": 50},
            )
            response.raise_for_status()
            data = response.json()

            all_items.extend(data["data"])

            if not data["has_more"]:
                break
            page += 1

        return all_items

    async def _import_recruiters(
        self, http_client: httpx.AsyncClient, workspace_id: UUID, result: ATSImportResult
    ) -> dict[str, UUID]:
        """Import recruiters from ATS. Returns email->db_id mapping."""
        email_to_id: dict[str, UUID] = {}

        try:
            raw_recruiters = await self._fetch_all_pages(http_client, "/api/v1/recruiters")
            logger.info(f"Fetched {len(raw_recruiters)} recruiters from ATS")

            async with self.pool.acquire() as conn:
                for rec_data in raw_recruiters:
                    rec = ATSRecruiter(**rec_data)

                    # Check if recruiter already exists by email
                    existing = None
                    if rec.email:
                        existing = await conn.fetchrow(
                            "SELECT id FROM ats.recruiters WHERE email = $1", rec.email
                        )

                    if existing:
                        email_to_id[rec.email] = existing["id"]
                    else:
                        row = await conn.fetchrow("""
                            INSERT INTO ats.recruiters (name, email, phone, team, role, avatar_url, is_active)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            RETURNING id
                        """, rec.full_name, rec.email, rec.phone_number,
                            rec.department, rec.job_title, rec.photo_url, rec.active)

                        if rec.email:
                            email_to_id[rec.email] = row["id"]
                        result.recruiters_imported += 1

        except Exception as e:
            logger.error(f"Failed to import recruiters from ATS: {e}")
            result.errors.append(f"Recruiter import failed: {str(e)}")

        return email_to_id

    async def _import_clients(
        self, http_client: httpx.AsyncClient, workspace_id: UUID, result: ATSImportResult
    ) -> dict[str, UUID]:
        """Import clients from ATS. Returns name->db_id mapping."""
        name_to_id: dict[str, UUID] = {}

        try:
            raw_clients = await self._fetch_all_pages(http_client, "/api/v1/clients")
            logger.info(f"Fetched {len(raw_clients)} clients from ATS")

            async with self.pool.acquire() as conn:
                for cli_data in raw_clients:
                    cli = ATSClient(**cli_data)

                    existing = await conn.fetchrow(
                        "SELECT id FROM ats.clients WHERE name = $1 AND workspace_id = $2",
                        cli.company_name, workspace_id,
                    )

                    if existing:
                        name_to_id[cli.company_name] = existing["id"]
                    else:
                        row = await conn.fetchrow("""
                            INSERT INTO ats.clients (name, location, industry, logo, workspace_id)
                            VALUES ($1, $2, $3, $4, $5)
                            RETURNING id
                        """, cli.company_name, cli.headquarters, cli.sector,
                            cli.logo_url, workspace_id)

                        name_to_id[cli.company_name] = row["id"]
                        result.clients_imported += 1

        except Exception as e:
            logger.error(f"Failed to import clients from ATS: {e}")
            result.errors.append(f"Client import failed: {str(e)}")

        return name_to_id

    async def _get_default_office_location_id(self, conn, workspace_id: UUID) -> UUID | None:
        """Look up the default office location for a workspace."""
        row = await conn.fetchrow(
            "SELECT id FROM ats.office_locations WHERE workspace_id = $1 AND is_default = true LIMIT 1",
            workspace_id,
        )
        return row["id"] if row else None

    async def _import_vacancies(
        self,
        http_client: httpx.AsyncClient,
        workspace_id: UUID,
        recruiter_map: dict[str, UUID],
        client_map: dict[str, UUID],
        result: ATSImportResult,
    ):
        """Import vacancies from ATS, linking to recruiters and clients."""
        try:
            raw_vacancies = await self._fetch_all_pages(http_client, "/api/v1/vacancies")
            logger.info(f"Fetched {len(raw_vacancies)} vacancies from ATS")

            async with self.pool.acquire() as conn:
                office_location_id = await self._get_default_office_location_id(conn, workspace_id)

                for vac_data in raw_vacancies:
                    vac = ATSVacancy(**vac_data)

                    # Skip if vacancy already imported (by source_id)
                    existing = await conn.fetchval(
                        "SELECT id FROM ats.vacancies WHERE source_id = $1 AND workspace_id = $2",
                        vac.external_id, workspace_id,
                    )
                    if existing:
                        continue

                    internal_status = self._map_vacancy_status(vac.status)

                    recruiter_id = recruiter_map.get(vac.recruiter_email) if vac.recruiter_email else None
                    client_id = client_map.get(vac.client_name) if vac.client_name else None

                    await conn.execute("""
                        INSERT INTO ats.vacancies
                        (title, company, location, description, status, source, source_id,
                         recruiter_id, client_id, workspace_id, office_location_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """, vac.title, vac.company_name, vac.work_location,
                        vac.description_html, internal_status,
                        "ats_import", vac.external_id,
                        recruiter_id, client_id, workspace_id, office_location_id)
                    result.vacancies_imported += 1

        except Exception as e:
            logger.error(f"Failed to import vacancies from ATS: {e}")
            result.errors.append(f"Vacancy import failed: {str(e)}")

    @staticmethod
    def _map_vacancy_status(ats_status: str) -> str:
        """Map ATS status values to internal status values."""
        mapping = {
            "active": "open",
            "inactive": "closed",
            "draft": "concept",
            "on_hold": "on_hold",
            "filled": "filled",
        }
        return mapping.get(ats_status, "open")
