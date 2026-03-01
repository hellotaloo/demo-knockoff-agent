"""
Shared post-call result processor for voice (LiveKit) and WhatsApp channels.

After a screening conversation ends, both channels store basic results (knockout pass/fail,
open answers) and transcript in the database. This processor then:
1. Reads the transcript + questions + existing answers from DB
2. Calls Gemini 3-Pro for scoring, ratings, motivations, and executive summary
3. Updates application_answers with scores and applications with AI summary
4. Triggers downstream: screening notes integration + workflow events

This replaces the old transcript_processor ADK agent with a single direct API call.
"""
import asyncio
import json
import logging
import os
import re
import uuid
from typing import Optional

from src.database import get_db_pool
from src.services.screening_notes_integration_service import trigger_screening_notes_integration
from src.workflows import get_orchestrator

logger = logging.getLogger(__name__)


# Rating labels mapped to score ranges (same as transcript_processor)
def score_to_rating(score: int) -> str:
    """Convert a numeric score (0-100) to a rating label."""
    if score <= 20:
        return "weak"
    elif score <= 40:
        return "below_average"
    elif score <= 60:
        return "average"
    elif score <= 80:
        return "good"
    else:
        return "excellent"


# Scoring instruction — adapted from transcript_processor/agent.py INSTRUCTION
SCORING_INSTRUCTION = """Je bent een expert in het analyseren van sollicitatiegesprekken.

Je taak is om een transcript van een screening te analyseren en de antwoorden van de kandidaat te evalueren.

## INPUT FORMAAT
Je ontvangt:
1. Een transcript van het gesprek (agent en user berichten)
2. Een lijst met KNOCKOUT vragen (ja/nee vragen, verplichte eisen) met het resultaat van de real-time agent
3. Een lijst met KWALIFICATIE vragen (met ideaal antwoord voor scoring)

## KNOCKOUT VRAGEN DOUBLE-CHECK
De real-time agent heeft de knockout vragen al beoordeeld (passed/failed).
Controleer of je het eens bent met de beoordeling op basis van het transcript.

Als je het NIET eens bent:
- Zet "override" op true en geef het juiste resultaat
- Leg uit waarom in "override_reason"

Als je het WEL eens bent:
- Zet "override" op false

## KWALIFICATIE VRAGEN EVALUATIE
Voor elke kwalificatie vraag:
- Zoek in het transcript waar deze vraag gesteld werd
- Identificeer het antwoord van de kandidaat
- Vergelijk het antwoord met het IDEAAL ANTWOORD
- Geef een score (0-100), rating EN motivatie:

RATINGS (van laag naar hoog):
- "weak" (score 0-20): Geen relevant antwoord of sterk afwijkend
- "below_average" (score 21-40): Minimaal relevant, mist belangrijke punten
- "average" (score 41-60): Gedeeltelijk relevant, mist enkele punten
- "good" (score 61-80): Goed antwoord, dekt meeste belangrijke punten
- "excellent" (score 81-100): Uitstekend antwoord, voldoet aan of overtreft ideaal

MOTIVATIE:
Schrijf een korte motivatie (2-3 zinnen) die uitlegt:
- Wat was goed aan het antwoord (positieve punten)
- Wat was minder goed of ontbrak (negatieve punten)
- Wat had de kandidaat moeten noemen voor een perfecte score van 100%

## OUTPUT FORMAAT
Antwoord ALLEEN met een JSON object in dit exacte formaat:

```json
{
  "knockout_checks": [
    {
      "question_id": "uuid-here",
      "override": false,
      "new_passed": null,
      "override_reason": ""
    }
  ],
  "qualification_scores": [
    {
      "question_id": "uuid-here",
      "score": 75,
      "rating": "good",
      "motivation": "Kandidaat toont relevante ervaring. Mist echter specifieke details over X. Voor 100% had de kandidaat ook Y moeten noemen."
    }
  ],
  "summary": "Eén zin executive summary voor de recruiter over deze kandidaat"
}
```

## BELANGRIJKE REGELS
1. De summary is een bondige, professionele zin voor recruiters die de essentie van de kandidaat samenvat
2. Citeer het antwoord zo letterlijk mogelijk uit het transcript in de motivatie
3. Wees eerlijk in je evaluatie
4. Antwoord ALLEEN met JSON, geen andere tekst
"""


def _build_prompt(
    transcript: list[dict],
    knockout_questions: list[dict],
    qualification_questions: list[dict],
    existing_answers: list[dict],
) -> tuple[str, dict[str, str]]:
    """Build the full prompt for Gemini 3-Pro.

    Returns (prompt, id_map) where id_map maps simple IDs (ko_1, oq_1) to DB UUIDs.
    Simple IDs are used in the prompt so the LLM can reliably echo them back.
    """
    # Format transcript
    transcript_lines = []
    for msg in transcript:
        role = msg.get("role", "unknown").upper()
        message = msg.get("message", "")
        transcript_lines.append(f"{role}: {message}")
    transcript_text = "\n".join(transcript_lines)

    # Map simple IDs to application_answers.question_id for the UPDATE.
    # We join by question_text (stable across re-publishes) to find the correct answer row.
    id_map: dict[str, str] = {}  # simple_id -> application_answers.question_id
    answer_by_id = {str(a["question_id"]): a for a in existing_answers}
    answer_by_text = {a.get("question_text", ""): a for a in existing_answers}

    # Build knockout section with agent's existing evaluation
    ko_lines = []
    for i, q in enumerate(knockout_questions, 1):
        simple_id = f"ko_{i}"
        q_text = q["question_text"]
        # Prefer matching by pre_screening_questions.id, fall back to question_text
        answer = answer_by_id.get(str(q["id"])) or answer_by_text.get(q_text) or {}
        # Map to the answer's actual question_id (used for UPDATE)
        answer_qid = str(answer["question_id"]) if answer.get("question_id") else str(q["id"])
        id_map[simple_id] = answer_qid
        passed = answer.get("passed")
        passed_str = "passed" if passed is True else "failed" if passed is False else "unclear"
        raw_answer = answer.get("answer", "[niet beantwoord]")
        ko_lines.append(f"- {simple_id}: {q_text}")
        ko_lines.append(f"  Agent beoordeling: {passed_str}")
        ko_lines.append(f"  Antwoord kandidaat: {raw_answer}")

    # Build qualification section with ideal answers
    qual_lines = []
    for i, q in enumerate(qualification_questions, 1):
        simple_id = f"oq_{i}"
        q_text = q["question_text"]
        answer = answer_by_id.get(str(q["id"])) or answer_by_text.get(q_text) or {}
        answer_qid = str(answer["question_id"]) if answer.get("question_id") else str(q["id"])
        id_map[simple_id] = answer_qid
        raw_answer = answer.get("answer", "[niet beantwoord]")
        ideal = q.get("ideal_answer", "")
        qual_lines.append(f"- {simple_id}: {q_text}")
        if ideal:
            qual_lines.append(f"  IDEAAL ANTWOORD: {ideal}")
        qual_lines.append(f"  Antwoord kandidaat: {raw_answer}")

    ko_section = "\n".join(ko_lines) if ko_lines else "(geen knockout vragen)"
    qual_section = "\n".join(qual_lines) if qual_lines else "(geen kwalificatie vragen)"

    prompt = f"""Analyseer het volgende transcript en evalueer de antwoorden.

## TRANSCRIPT
{transcript_text}

## KNOCKOUT VRAGEN
{ko_section}

## KWALIFICATIE VRAGEN
{qual_section}

Geef je evaluatie als JSON."""

    return prompt, id_map


def _parse_json_response(response_text: str) -> dict:
    """Extract JSON from the model response (handles markdown code blocks)."""
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.error(f"Could not find JSON in response: {response_text[:500]}")
            return {}

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}\nJSON string: {json_str[:500]}")
        return {}


async def process_call_results(
    application_id: uuid.UUID,
    pre_screening_id: uuid.UUID,
    conversation_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    candidate_name: str,
    channel: str,
) -> None:
    """
    Post-process a completed screening call/conversation.

    Reads transcript + questions + existing answers from DB, calls Gemini 3-Pro
    for scoring, updates DB, and triggers downstream integrations.

    Args:
        application_id: The application to score
        pre_screening_id: Pre-screening config (for fetching questions + ideal answers)
        conversation_id: Screening conversation (for fetching transcript)
        vacancy_id: Vacancy ID (for workflow context)
        candidate_name: Candidate name (for workflow context)
        channel: "voice" or "whatsapp"
    """
    pool = await get_db_pool()
    logger.info(f"Post-processing {channel} call: application={application_id}, conversation={conversation_id}")

    try:
        # 1. Fetch transcript
        messages = await pool.fetch(
            """
            SELECT role, message
            FROM ats.conversation_messages
            WHERE conversation_id = $1
            ORDER BY created_at
            """,
            conversation_id,
        )
        transcript = [{"role": m["role"], "message": m["message"]} for m in messages]

        if not transcript:
            logger.warning(f"No transcript found for conversation {conversation_id}, skipping scoring")
            # Still trigger downstream with whatever summary exists
            await _trigger_downstream(pool, application_id, vacancy_id, conversation_id, candidate_name, channel)
            return

        # 2. Fetch questions + ideal answers
        questions = await pool.fetch(
            """
            SELECT id, question_type, question_text, ideal_answer
            FROM ats.pre_screening_questions
            WHERE pre_screening_id = $1
            ORDER BY question_type, position
            """,
            pre_screening_id,
        )
        knockout_questions = [dict(q) for q in questions if q["question_type"] == "knockout"]
        qualification_questions = [dict(q) for q in questions if q["question_type"] == "qualification"]

        # 3. Fetch existing answers (stored by the real-time agent/webhook)
        existing_answers = await pool.fetch(
            """
            SELECT question_id, question_text, answer, passed
            FROM ats.application_answers
            WHERE application_id = $1
            """,
            application_id,
        )
        existing_answers_list = [dict(a) for a in existing_answers]

        # 4. Build prompt and call Gemini 3-Pro
        prompt, id_map = _build_prompt(transcript, knockout_questions, qualification_questions, existing_answers_list)
        logger.info(f"Prompt built: {len(id_map)} question IDs mapped ({', '.join(id_map.keys())})")

        from google import genai
        from google.genai import types

        client = genai.Client()
        response = await client.aio.models.generate_content(
            model="gemini-3-pro-preview",
            contents=[
                types.Content(role="user", parts=[types.Part(text=SCORING_INSTRUCTION)]),
                types.Content(role="user", parts=[types.Part(text=prompt)]),
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
                thinking_config=types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=1024,
                ),
            ),
        )

        response_text = ""
        thinking_text = ""
        if response and response.candidates:
            for part in response.candidates[0].content.parts:
                # Skip thinking parts — they have thought=True and would corrupt JSON parsing
                if getattr(part, "thought", False):
                    if hasattr(part, "text") and part.text:
                        thinking_text += part.text
                    continue
                if hasattr(part, "text") and part.text:
                    response_text += part.text

        logger.info(f"Gemini response: {len(response_text)} chars output, {len(thinking_text)} chars thinking")

        # 5. Parse response
        if not response_text:
            logger.error(f"Empty response from Gemini for application {application_id}")
            await _trigger_downstream(pool, application_id, vacancy_id, conversation_id, candidate_name, channel)
            return

        logger.debug(f"Raw Gemini response: {response_text[:1000]}")
        parsed = _parse_json_response(response_text)
        if not parsed:
            logger.error(f"Failed to parse Gemini response for application {application_id}. Response: {response_text[:500]}")
            await _trigger_downstream(pool, application_id, vacancy_id, conversation_id, candidate_name, channel)
            return

        # 6. Update DB — translate simple IDs (ko_1, oq_1) back to DB UUIDs
        summary = parsed.get("summary", "")
        qualification_scores = parsed.get("qualification_scores", [])
        knockout_checks = parsed.get("knockout_checks", [])

        logger.info(f"Parsed: {len(qualification_scores)} qualification scores, {len(knockout_checks)} knockout checks, summary={bool(summary)}")

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Update qualification scores
                for scores in qualification_scores:
                    simple_id = scores.get("question_id", "")
                    db_id = id_map.get(simple_id)
                    if not db_id:
                        logger.warning(f"Unknown question ID from Gemini: {simple_id}")
                        continue
                    score = scores.get("score", 0)
                    rating = scores.get("rating") or score_to_rating(score)
                    motivation = scores.get("motivation", "")
                    result = await conn.execute(
                        """
                        UPDATE ats.application_answers
                        SET score = $1, rating = $2, motivation = $3
                        WHERE application_id = $4 AND question_id = $5
                        """,
                        score, rating, motivation, application_id, db_id,
                    )
                    logger.info(f"  Score update {simple_id} -> {db_id[:8]}...: score={score}, rating={rating}, rows={result}")

                # Handle knockout overrides
                for check in knockout_checks:
                    simple_id = check.get("question_id", "")
                    db_id = id_map.get(simple_id)
                    if not db_id:
                        logger.warning(f"Unknown question ID from Gemini: {simple_id}")
                        continue
                    if check.get("override"):
                        new_passed = check.get("new_passed")
                        override_reason = check.get("override_reason", "")
                        logger.warning(
                            f"Knockout override {simple_id} -> {db_id[:8]}...: passed={new_passed}, reason={override_reason}"
                        )
                        await conn.execute(
                            """
                            UPDATE ats.application_answers
                            SET passed = $1, motivation = $2
                            WHERE application_id = $3 AND question_id = $4
                            """,
                            new_passed, f"[Override] {override_reason}", application_id, db_id,
                        )

                # Update application summary + mark as completed
                if summary:
                    await conn.execute(
                        "UPDATE ats.applications SET summary = $1, status = 'completed' WHERE id = $2",
                        summary, application_id,
                    )
                else:
                    await conn.execute(
                        "UPDATE ats.applications SET status = 'completed' WHERE id = $1",
                        application_id,
                    )

        logger.info(f"Post-processing complete for application {application_id}: {len(qualification_scores)} scores updated")

    except Exception as e:
        logger.error(f"Post-processing failed for application {application_id}: {e}", exc_info=True)
        # Still mark as completed so the app doesn't get stuck in 'processing'
        try:
            await pool.execute(
                "UPDATE ats.applications SET status = 'completed' WHERE id = $1",
                application_id,
            )
        except Exception:
            pass

    # 7. Trigger downstream (always, even on error — raw results are already stored)
    await _trigger_downstream(pool, application_id, vacancy_id, conversation_id, candidate_name, channel)


async def _trigger_downstream(
    pool,
    application_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    conversation_id: uuid.UUID,
    candidate_name: str,
    channel: str,
) -> None:
    """Trigger screening notes integration and workflow events."""
    # Fetch current application state (may have been updated by scoring)
    app = await pool.fetchrow(
        "SELECT qualified, summary FROM ats.applications WHERE id = $1",
        application_id,
    )
    if not app:
        logger.error(f"Application {application_id} not found for downstream triggers")
        return

    qualified = app["qualified"]
    summary = app["summary"] or ""

    # Trigger screening notes for qualified candidates
    if qualified:
        asyncio.create_task(trigger_screening_notes_integration(
            pool=pool,
            application_id=application_id,
            recruiter_email=os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL"),
        ))
        logger.info(f"Triggered screening notes integration for application {application_id}")

    # Notify workflow orchestrator
    try:
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", str(conversation_id))

        if workflow:
            # Look up interview slot
            interview_slot = None
            scheduled = await pool.fetchrow(
                "SELECT selected_date, selected_time FROM ats.scheduled_interviews WHERE conversation_id = $1",
                str(conversation_id),
            )
            if scheduled:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                try:
                    hour = int(scheduled["selected_time"].replace("u", "").replace("h", ""))
                    tz = ZoneInfo("Europe/Brussels")
                    dt = datetime.combine(scheduled["selected_date"], datetime.min.time(), tzinfo=tz).replace(hour=hour)
                    interview_slot = dt.isoformat()
                except Exception as e:
                    logger.warning(f"Could not parse interview slot: {e}")
                    interview_slot = f"{scheduled['selected_date']} {scheduled['selected_time']}"

            await orchestrator.handle_event(
                workflow_id=workflow["id"],
                event="screening_completed",
                payload={
                    "qualified": qualified,
                    "interview_slot": interview_slot,
                    "application_id": str(application_id),
                    "candidate_name": candidate_name,
                    "summary": summary,
                },
            )
            logger.info(f"Workflow {workflow['id']}: screening_completed event handled")
        else:
            logger.debug(f"No workflow found for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Failed to notify workflow orchestrator: {e}")
