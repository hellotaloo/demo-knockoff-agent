"""
Demo Data Management router.

Handles seeding and resetting demo data for development and testing.
Demo data is loaded from fixtures/ directory - edit JSON files there.
ATS-sourced data (recruiters, clients, vacancies) is imported via the ATS simulator.
"""
import asyncio
import uuid
import logging
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Query
from fixtures import load_candidates, load_applications, load_pre_screenings, load_activities, load_ontology
import json

from src.database import get_db_pool
from src.services import DemoService
from src.services.ats_import_service import ATSImportService, get_import_progress, clear_import_progress
from src.services.workflow_service import WorkflowService
from src.repositories import ConversationRepository

logger = logging.getLogger(__name__)

# Default workspace ID for demo data
DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

router = APIRouter(tags=["Demo Data"])


@router.post("/demo/seed")
async def seed_demo_data(activities: bool = Query(True, description="Include activities in seed")):
    """Seed base data (candidates, ontology). Vacancies are imported separately via POST /demo/import-ats."""
    pool = await get_db_pool()

    # Load fixtures from JSON files (non-ATS data only)
    candidates_data = load_candidates()
    applications_data = load_applications()
    pre_screenings_data = load_pre_screenings()
    activities_data = load_activities() if activities else []

    created_candidates = []
    created_vacancies = []
    created_applications = []
    created_pre_screenings = []
    created_skills = 0
    created_activities = 0

    # Query any existing vacancies/recruiters/clients (from a prior ATS import)
    async with pool.acquire() as conn:
        vacancy_rows = await conn.fetch(
            "SELECT id, title FROM ats.vacancies WHERE workspace_id = $1 ORDER BY created_at",
            DEFAULT_WORKSPACE_ID,
        )
        created_vacancies = [{"id": str(r["id"]), "title": r["title"]} for r in vacancy_rows]

        recruiter_rows = await conn.fetch("SELECT id, email FROM ats.recruiters")
        recruiter_email_to_id = {r["email"]: r["id"] for r in recruiter_rows if r["email"]}

        client_rows = await conn.fetch(
            "SELECT id, name FROM ats.clients WHERE workspace_id = $1",
            DEFAULT_WORKSPACE_ID,
        )
        client_name_to_id = {r["name"]: r["id"] for r in client_rows}

    # Seed non-ATS data (candidates, applications, pre-screenings, etc.)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert candidates (central registry)
            for cand in candidates_data:
                # Parse available_from date if present
                available_from = None
                if cand.get("available_from"):
                    available_from = date.fromisoformat(cand["available_from"])

                row = await conn.fetchrow("""
                    INSERT INTO ats.candidates
                    (phone, email, first_name, last_name, full_name, source,
                     status, availability, available_from, rating, workspace_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                """, cand["phone"], cand.get("email"), cand.get("first_name"),
                    cand.get("last_name"), cand["full_name"], cand.get("source", "application"),
                    cand.get("status", "new"), cand.get("availability", "unknown"),
                    available_from, cand.get("rating"), DEFAULT_WORKSPACE_ID)

                candidate_id = row["id"]
                created_candidates.append({
                    "id": str(candidate_id),
                    "full_name": cand["full_name"],
                    "phone": cand["phone"]
                })

                # Insert skills for this candidate
                for skill in cand.get("skills", []):
                    await conn.execute("""
                        INSERT INTO ats.candidate_skills
                        (candidate_id, skill_name, skill_category, score, source)
                        VALUES ($1, $2, $3, $4, $5)
                    """, candidate_id, skill["skill_name"],
                        skill.get("skill_category"), skill.get("score"), "import")
                    created_skills += 1

            # Insert applications (with candidate_id linked)
            for app_data in applications_data:
                vacancy_id = uuid.UUID(created_vacancies[app_data["vacancy_idx"]]["id"])
                candidate_id = uuid.UUID(created_candidates[app_data["candidate_idx"]]["id"])
                candidate_name = created_candidates[app_data["candidate_idx"]]["full_name"]
                candidate_phone = created_candidates[app_data["candidate_idx"]]["phone"]

                # Calculate completed_at if completed
                completed_at = None
                if app_data["completed"]:
                    # Use current time minus some offset for realism
                    completed_at = datetime.now() - timedelta(hours=len(created_applications) * 2)

                # Convert completed boolean to status
                status = "completed" if app_data["completed"] else "active"

                row = await conn.fetchrow("""
                    INSERT INTO ats.applications
                    (vacancy_id, candidate_id, candidate_name, candidate_phone, channel, qualified,
                     interaction_seconds, completed_at, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id, started_at
                """, vacancy_id, candidate_id, candidate_name, candidate_phone, app_data["channel"],
                    app_data["qualified"],
                    app_data["interaction_seconds"], completed_at, status)

                application_id = row["id"]

                # Insert answers
                for answer in app_data["answers"]:
                    await conn.execute("""
                        INSERT INTO ats.application_answers
                        (application_id, question_id, question_text, answer, passed)
                        VALUES ($1, $2, $3, $4, $5)
                    """, application_id, answer["question_id"], answer["question_text"],
                        answer["answer"], answer["passed"])

                created_applications.append({
                    "id": str(application_id),
                    "candidate": candidate_name,
                    "candidate_id": str(candidate_id)
                })

            # Insert pre-screenings
            for ps_data in pre_screenings_data:
                vacancy_id = uuid.UUID(created_vacancies[ps_data["vacancy_idx"]]["id"])

                # Use fixed ID if provided, otherwise auto-generate
                fixed_id = ps_data.get("id")
                if fixed_id:
                    pre_screening_id = uuid.UUID(fixed_id)
                    await conn.execute("""
                        INSERT INTO ats.pre_screenings (id, vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, pre_screening_id, vacancy_id, ps_data["intro"], ps_data["knockout_failed_action"],
                        ps_data["final_action"], ps_data["status"])
                else:
                    row = await conn.fetchrow("""
                        INSERT INTO ats.pre_screenings (vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                    """, vacancy_id, ps_data["intro"], ps_data["knockout_failed_action"],
                        ps_data["final_action"], ps_data["status"])
                    pre_screening_id = row["id"]

                # Insert knockout questions
                for position, q in enumerate(ps_data.get("knockout_questions", [])):
                    await conn.execute("""
                        INSERT INTO ats.pre_screening_questions
                        (pre_screening_id, question_type, position, question_text, is_approved)
                        VALUES ($1, $2, $3, $4, $5)
                    """, pre_screening_id, "knockout", position, q["question"], q.get("is_approved", False))

                # Insert qualification questions (with ideal_answer)
                for position, q in enumerate(ps_data.get("qualification_questions", [])):
                    await conn.execute("""
                        INSERT INTO ats.pre_screening_questions
                        (pre_screening_id, question_type, position, question_text, ideal_answer, is_approved)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, pre_screening_id, "qualification", position, q["question"], q.get("ideal_answer"), q.get("is_approved", False))

                created_pre_screenings.append({
                    "id": str(pre_screening_id),
                    "vacancy_id": str(vacancy_id),
                    "vacancy_title": created_vacancies[ps_data["vacancy_idx"]]["title"]
                })

            # Insert activities (for the global activity feed)
            for act_data in activities_data:
                # Get candidate_id if specified (some activities don't have a candidate)
                candidate_id = None
                if act_data.get("candidate_idx") is not None:
                    candidate_idx = act_data["candidate_idx"]
                    if candidate_idx < len(created_candidates):
                        candidate_id = uuid.UUID(created_candidates[candidate_idx]["id"])

                # Get vacancy_id
                vacancy_id = None
                if act_data.get("vacancy_idx") is not None:
                    vacancy_idx = act_data["vacancy_idx"]
                    if vacancy_idx < len(created_vacancies):
                        vacancy_id = uuid.UUID(created_vacancies[vacancy_idx]["id"])

                # Skip if we don't have the required candidate (activities need a candidate_id)
                if candidate_id is None and act_data.get("candidate_idx") is not None:
                    continue

                # Calculate created_at based on minutes_ago
                minutes_ago = act_data.get("minutes_ago", 0)
                created_at = datetime.now() - timedelta(minutes=minutes_ago)

                # Get metadata as JSON
                metadata = act_data.get("metadata", {})

                # For activities without a candidate, we need to pick a random one (FK constraint)
                if candidate_id is None and created_candidates:
                    candidate_id = uuid.UUID(created_candidates[0]["id"])

                await conn.execute("""
                    INSERT INTO ats.agent_activities
                    (candidate_id, vacancy_id, event_type, channel, actor_type, metadata, summary, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, candidate_id, vacancy_id, act_data["event_type"], act_data.get("channel"),
                    act_data["actor_type"], json.dumps(metadata), act_data.get("summary"), created_at)

                created_activities += 1

            # ---- Ontology demo data ----
            ontology_data = load_ontology()
            created_ontology_entities = 0
            created_ontology_relations = 0

            # Ensure ontology types are seeded for default workspace
            await conn.execute("SELECT ats.seed_ontology_defaults($1)", DEFAULT_WORKSPACE_ID)

            # Look up type IDs
            type_rows = await conn.fetch(
                "SELECT id, slug FROM ats.ontology_types WHERE workspace_id = $1",
                DEFAULT_WORKSPACE_ID,
            )
            type_map = {r["slug"]: r["id"] for r in type_rows}

            # Look up relation type IDs
            rel_type_rows = await conn.fetch(
                "SELECT id, slug FROM ats.ontology_relation_types WHERE workspace_id = $1",
                DEFAULT_WORKSPACE_ID,
            )
            rel_type_map = {r["slug"]: r["id"] for r in rel_type_rows}

            # Track entity name → id for building relations
            entity_name_to_id = {}

            # Insert categories
            for i, cat in enumerate(ontology_data.get("categories", [])):
                row = await conn.fetchrow("""
                    INSERT INTO ats.ontology_entities (workspace_id, type_id, name, description, icon, color, sort_order)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (workspace_id, type_id, name) DO UPDATE SET description = EXCLUDED.description
                    RETURNING id
                """, DEFAULT_WORKSPACE_ID, type_map["category"],
                    cat["name"], cat.get("description"), cat.get("icon"), cat.get("color"), i)
                entity_name_to_id[cat["name"]] = row["id"]
                created_ontology_entities += 1

            # Insert document types
            for i, doc in enumerate(ontology_data.get("document_types", [])):
                row = await conn.fetchrow("""
                    INSERT INTO ats.ontology_entities (workspace_id, type_id, name, description, icon, sort_order)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (workspace_id, type_id, name) DO UPDATE SET description = EXCLUDED.description
                    RETURNING id
                """, DEFAULT_WORKSPACE_ID, type_map["document_type"],
                    doc["name"], doc.get("description"), doc.get("icon"), i)
                entity_name_to_id[doc["name"]] = row["id"]
                created_ontology_entities += 1

            # Insert job functions
            for i, func in enumerate(ontology_data.get("job_functions", [])):
                row = await conn.fetchrow("""
                    INSERT INTO ats.ontology_entities (workspace_id, type_id, name, description, icon, sort_order)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (workspace_id, type_id, name) DO UPDATE SET description = EXCLUDED.description
                    RETURNING id
                """, DEFAULT_WORKSPACE_ID, type_map["job_function"],
                    func["name"], func.get("description"), func.get("icon"), i)
                entity_name_to_id[func["name"]] = row["id"]
                created_ontology_entities += 1

                # Create belongs_to relation (function → category)
                if func.get("category") and func["category"] in entity_name_to_id:
                    await conn.execute("""
                        INSERT INTO ats.ontology_relations
                            (workspace_id, source_entity_id, target_entity_id, relation_type_id, metadata)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (source_entity_id, target_entity_id, relation_type_id) DO NOTHING
                    """, DEFAULT_WORKSPACE_ID, row["id"],
                        entity_name_to_id[func["category"]], rel_type_map["belongs_to"], "{}")
                    created_ontology_relations += 1

            # Insert document requirements (function → document relations)
            for func_name, reqs in ontology_data.get("requirements", {}).items():
                func_id = entity_name_to_id.get(func_name)
                if not func_id:
                    continue
                for req in reqs:
                    doc_id = entity_name_to_id.get(req["document"])
                    if not doc_id:
                        continue
                    metadata = {
                        "requirement_type": req["requirement_type"],
                        "priority": req["priority"],
                    }
                    if req.get("condition"):
                        metadata["condition"] = req["condition"]
                    await conn.execute("""
                        INSERT INTO ats.ontology_relations
                            (workspace_id, source_entity_id, target_entity_id, relation_type_id, metadata)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (source_entity_id, target_entity_id, relation_type_id) DO NOTHING
                    """, DEFAULT_WORKSPACE_ID, func_id, doc_id, rel_type_map["requires"],
                        json.dumps(metadata))
                    created_ontology_relations += 1

    return {
        "status": "success",
        "message": f"Seed: {len(created_candidates)} candidates, {created_skills} skills, {len(created_applications)} applications, {len(created_pre_screenings)} pre-screenings, {created_activities} activities, {created_ontology_entities} ontology entities, {created_ontology_relations} ontology relations. Use POST /demo/import-ats to import vacancies from ATS.",
        "candidates_count": len(created_candidates),
        "skills_count": created_skills,
        "vacancies": created_vacancies,
        "applications_count": len(created_applications),
        "pre_screenings": created_pre_screenings,
        "activities_count": created_activities,
        "ontology_entities_count": created_ontology_entities,
        "ontology_relations_count": created_ontology_relations,
    }


@router.post("/demo/reset")
async def reset_demo_data(
    reseed: bool = Query(True, description="Reseed with demo data after reset"),
    activities: bool = Query(True, description="Include activities in reseed (only used if reseed=true)"),
    workflow_activities: bool = Query(True, description="Include workflow activities dashboard demo data")
):
    """Clear all vacancies, applications, candidates, and pre-screenings, optionally reseed with demo data."""
    clear_import_progress()
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete in correct order respecting foreign key constraints
            # First: conversation_messages (references screening_conversations)
            try:
                await conn.execute("DELETE FROM ats.conversation_messages")
            except Exception:
                pass  # Table may not exist yet

            # Then: tables that reference applications/candidates
            await conn.execute("DELETE FROM ats.screening_conversations")
            await conn.execute("DELETE FROM ats.application_answers")
            await conn.execute("DELETE FROM ats.scheduled_interviews")
            await conn.execute("DELETE FROM ats.document_collection_conversations")

            # Try to delete agent_activities and candidate_skills if tables exist
            try:
                await conn.execute("DELETE FROM ats.agent_activities")
            except Exception:
                pass  # Table may not exist yet

            try:
                await conn.execute("DELETE FROM ats.candidate_skills")
            except Exception:
                pass  # Table may not exist yet

            # Then: applications (references candidates and vacancies)
            await conn.execute("DELETE FROM ats.applications")

            # Then: candidates (now safe to delete)
            await conn.execute("DELETE FROM ats.candidates")

            # Then: pre-screening related
            await conn.execute("DELETE FROM ats.pre_screening_questions")
            await conn.execute("DELETE FROM ats.pre_screenings")

            # Finally: vacancies (clear recruiter_id and client_id first for FK safety)
            await conn.execute("DELETE FROM ats.vacancies")

            # Delete recruiters and clients
            await conn.execute("DELETE FROM ats.recruiters")
            await conn.execute("DELETE FROM ats.clients")

            # Delete workflows (activities dashboard)
            try:
                await conn.execute("DELETE FROM ats.workflows")
            except Exception:
                pass  # Table may not exist yet

            # Delete ontology data (relations first, then entities; keep types)
            try:
                await conn.execute("DELETE FROM ats.ontology_relations")
                await conn.execute("DELETE FROM ats.ontology_entities")
            except Exception:
                pass  # Tables may not exist yet

    result = {
        "status": "success",
        "message": "All demo data cleared",
    }

    # Optionally reseed
    if reseed:
        seed_result = await seed_demo_data(activities=activities)
        result["message"] = "Demo data reset and reseeded" + ("" if activities else " (without activities)")
        result["seed"] = seed_result

    # Optionally seed workflow activities (activities dashboard)
    if workflow_activities:
        workflow_service = WorkflowService(pool)
        await workflow_service.ensure_table()

        # Get created vacancies and candidates for context
        created_vacancies = result.get("seed", {}).get("vacancies", [])
        created_candidates = []
        if reseed:
            # Query just-created candidates for names
            rows = await pool.fetch("""
                SELECT id, full_name FROM ats.candidates
                ORDER BY created_at DESC LIMIT 10
            """)
            created_candidates = [{"id": str(r["id"]), "full_name": r["full_name"]} for r in rows]

        # Seed realistic workflow activities using actual candidate/vacancy data
        workflow_demo_data = []

        # Pre-screening workflows (use first 4 candidates if available)
        for i, step_info in enumerate([
            {"knockout_index": 2, "knockout_total": 3},
            {"knockout_index": 1, "knockout_total": 3},
            {"knockout_index": 3, "knockout_total": 3},
            {"open_index": 1, "open_total": 2},
        ]):
            if i < len(created_candidates) and i < len(created_vacancies):
                workflow_demo_data.append({
                    "workflow_type": "pre_screening",
                    "context": {
                        "candidate_name": created_candidates[i]["full_name"],
                        "candidate_id": created_candidates[i]["id"],
                        "vacancy_title": created_vacancies[i]["title"],
                        "vacancy_id": created_vacancies[i]["id"],
                        **step_info,
                    },
                    "timeout_seconds": 7200,
                })

        # Document collection workflows (use next 3 candidates)
        doc_types = ["ID kaart", "Rijbewijs", "Werkvergunning"]
        for i, doc_type in enumerate(doc_types):
            idx = i + 4  # Start after pre-screening candidates
            if idx < len(created_candidates) and i < len(created_vacancies):
                workflow_demo_data.append({
                    "workflow_type": "document_collection",
                    "context": {
                        "candidate_name": created_candidates[idx]["full_name"],
                        "candidate_id": created_candidates[idx]["id"],
                        "vacancy_title": created_vacancies[i]["title"],
                        "vacancy_id": created_vacancies[i]["id"],
                        "document_type": doc_type,
                    },
                    "timeout_seconds": 86400,
                })

        # Create the workflows
        created_workflows = 0
        for data in workflow_demo_data:
            await workflow_service.create(
                workflow_type=data["workflow_type"],
                context=data["context"],
                initial_step="waiting",  # Demo data starts in waiting step
                timeout_seconds=data["timeout_seconds"],
            )
            created_workflows += 1

        result["workflow_activities_count"] = created_workflows
        if "message" in result:
            result["message"] += f", {created_workflows} workflow activities"

    return result


@router.post("/demo/import-ats")
async def trigger_ats_import():
    """
    Start an ATS import as a background task.

    Imports recruiters, clients, and vacancies from the ATS simulator,
    then generates pre-screening questions for each vacancy.

    Poll GET /demo/import-ats/status for progress.
    """
    # Don't start a new import if one is already running
    progress = get_import_progress()
    if progress and progress.get("status") in ("importing", "generating"):
        return {"status": "already_running", "message": "Import is already in progress"}

    pool = await get_db_pool()
    import_service = ATSImportService(pool)

    # Fire and forget — runs in the background
    asyncio.create_task(import_service.import_and_generate(DEFAULT_WORKSPACE_ID))

    return {"status": "started", "message": "Import gestart. Poll GET /demo/import-ats/status voor voortgang."}


@router.get("/demo/import-ats/status")
async def get_ats_import_status():
    """
    Poll for ATS import progress.

    Returns the current state of the import, including per-vacancy generation status.
    Frontend should poll this every 3 seconds.
    """
    progress = get_import_progress()
    if progress is None:
        return {"status": "idle", "message": "Geen import actief"}
    return progress
