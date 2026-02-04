"""
Demo Data Management router.

Handles seeding and resetting demo data for development and testing.
Demo data is loaded from fixtures/ directory - edit JSON files there.
"""
import uuid
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from voice_agent import list_voice_agents, delete_voice_agent
from fixtures import load_vacancies, load_applications, load_pre_screenings

from src.database import get_db_pool
from src.services import DemoService
from src.repositories import ConversationRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Demo Data"])


@router.post("/demo/seed")
async def seed_demo_data():
    """Populate the database with demo vacancies, applications, and pre-screenings."""
    pool = await get_db_pool()

    # Load fixtures from JSON files
    vacancies_data = load_vacancies()
    applications_data = load_applications()
    pre_screenings_data = load_pre_screenings()

    created_vacancies = []
    created_applications = []
    created_pre_screenings = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert vacancies
            for vac in vacancies_data:
                row = await conn.fetchrow("""
                    INSERT INTO vacancies (title, company, location, description, status, source, source_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                """, vac["title"], vac["company"], vac["location"], vac["description"],
                    vac["status"], vac["source"], vac["source_id"])
                created_vacancies.append({"id": str(row["id"]), "title": vac["title"]})

            # Insert applications
            for app_data in applications_data:
                vacancy_id = uuid.UUID(created_vacancies[app_data["vacancy_idx"]]["id"])

                # Calculate completed_at if completed
                completed_at = None
                if app_data["completed"]:
                    # Use current time minus some offset for realism
                    completed_at = datetime.now() - timedelta(hours=len(created_applications) * 2)

                # Convert completed boolean to status
                status = 'completed' if app_data["completed"] else 'active'

                row = await conn.fetchrow("""
                    INSERT INTO applications
                    (vacancy_id, candidate_name, channel, qualified,
                     interaction_seconds, completed_at, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, started_at
                """, vacancy_id, app_data["candidate_name"], app_data["channel"],
                    app_data["qualified"],
                    app_data["interaction_seconds"], completed_at, status)

                application_id = row["id"]

                # Insert answers
                for answer in app_data["answers"]:
                    await conn.execute("""
                        INSERT INTO application_answers
                        (application_id, question_id, question_text, answer, passed)
                        VALUES ($1, $2, $3, $4, $5)
                    """, application_id, answer["question_id"], answer["question_text"],
                        answer["answer"], answer["passed"])

                created_applications.append({
                    "id": str(application_id),
                    "candidate": app_data["candidate_name"]
                })

            # Insert pre-screenings
            for ps_data in pre_screenings_data:
                vacancy_id = uuid.UUID(created_vacancies[ps_data["vacancy_idx"]]["id"])

                # Update vacancy status to match pre-screening status
                vacancy_status = "draft" if ps_data["status"] == "draft" else "screening_active"
                await conn.execute("""
                    UPDATE vacancies SET status = $1 WHERE id = $2
                """, vacancy_status, vacancy_id)

                # Use fixed ID if provided, otherwise auto-generate
                fixed_id = ps_data.get("id")
                if fixed_id:
                    pre_screening_id = uuid.UUID(fixed_id)
                    await conn.execute("""
                        INSERT INTO pre_screenings (id, vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, pre_screening_id, vacancy_id, ps_data["intro"], ps_data["knockout_failed_action"],
                        ps_data["final_action"], ps_data["status"])
                else:
                    row = await conn.fetchrow("""
                        INSERT INTO pre_screenings (vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                    """, vacancy_id, ps_data["intro"], ps_data["knockout_failed_action"],
                        ps_data["final_action"], ps_data["status"])
                    pre_screening_id = row["id"]

                # Insert knockout questions
                for position, q in enumerate(ps_data.get("knockout_questions", [])):
                    await conn.execute("""
                        INSERT INTO pre_screening_questions
                        (pre_screening_id, question_type, position, question_text, is_approved)
                        VALUES ($1, $2, $3, $4, $5)
                    """, pre_screening_id, "knockout", position, q["question"], q.get("is_approved", False))

                # Insert qualification questions (with ideal_answer)
                for position, q in enumerate(ps_data.get("qualification_questions", [])):
                    await conn.execute("""
                        INSERT INTO pre_screening_questions
                        (pre_screening_id, question_type, position, question_text, ideal_answer, is_approved)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, pre_screening_id, "qualification", position, q["question"], q.get("ideal_answer"), q.get("is_approved", False))

                created_pre_screenings.append({
                    "id": str(pre_screening_id),
                    "vacancy_id": str(vacancy_id),
                    "vacancy_title": created_vacancies[ps_data["vacancy_idx"]]["title"]
                })

    return {
        "status": "success",
        "message": f"Created {len(created_vacancies)} vacancies, {len(created_applications)} applications, {len(created_pre_screenings)} pre-screenings",
        "vacancies": created_vacancies,
        "applications_count": len(created_applications),
        "pre_screenings": created_pre_screenings
    }


@router.post("/demo/reset")
async def reset_demo_data(reseed: bool = Query(True, description="Reseed with demo data after reset")):
    """Clear all vacancies, applications, and pre-screenings, optionally reseed with demo data."""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete in correct order respecting foreign key constraints
            await conn.execute("DELETE FROM screening_conversations")
            await conn.execute("DELETE FROM application_answers")
            await conn.execute("DELETE FROM applications")
            await conn.execute("DELETE FROM pre_screening_questions")
            await conn.execute("DELETE FROM pre_screenings")
            await conn.execute("DELETE FROM vacancies")

    # Clean up ElevenLabs voice agents (keep only the base agent)
    KEEP_AGENT_ID = "agent_2101kg9wn4xbefbrbet9p5fqnncn"
    deleted_agents = []
    failed_agents = []

    try:
        agents = list_voice_agents()
        for agent in agents:
            if agent["agent_id"] != KEEP_AGENT_ID:
                if delete_voice_agent(agent["agent_id"]):
                    deleted_agents.append(agent["agent_id"])
                else:
                    failed_agents.append(agent["agent_id"])
    except Exception as e:
        logger.warning(f"Failed to clean up ElevenLabs agents: {e}")

    result = {
        "status": "success",
        "message": "All demo data cleared",
        "elevenlabs_cleanup": {
            "deleted": len(deleted_agents),
            "failed": len(failed_agents),
            "kept": KEEP_AGENT_ID
        }
    }

    # Optionally reseed
    if reseed:
        seed_result = await seed_demo_data()
        result["message"] = "Demo data reset and reseeded"
        result["seed"] = seed_result

    return result
