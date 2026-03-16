"""
Yousign webhook endpoint.

Yousign sends a POST to /webhook/yousign for signature events.
Signature verification: X-Yousign-Signature-256: sha256=<hmac-sha256(secret, body)>
"""
import hmac
import json
import logging
from datetime import datetime
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.config import YOUSIGN_WEBHOOK_SECRET
from src.database import get_db_pool
from src.routers.playground_chat import push_playground_message

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Webhooks"])


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not YOUSIGN_WEBHOOK_SECRET:
        logger.warning("[YOUSIGN] YOUSIGN_WEBHOOK_SECRET not set, skipping signature validation")
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("Missing or malformed Yousign signature header")
        return False

    expected = "sha256=" + hmac.new(
        key=YOUSIGN_WEBHOOK_SECRET.encode(),
        msg=body,
        digestmod=sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature_header, expected):
        logger.warning("Yousign HMAC signature mismatch")
        return False

    return True


async def _find_collection_by_yousign_request(request_id: str) -> dict | None:
    """Find the document collection that has this yousign_request_id in its agent_state."""
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """SELECT id, candidate_name, candidate_phone, agent_state, vacancy_id
        FROM agents.document_collections
        WHERE status = 'active'
          AND agent_state::jsonb -> 'context' ->> 'yousign_request_id' = $1
        LIMIT 1""",
        request_id,
    )
    return dict(row) if row else None


async def _handle_contract_signed(request_id: str, request_name: str, data: dict):
    """Handle signature_request.done: store confirmation message, update status."""
    collection = await _find_collection_by_yousign_request(request_id)
    if not collection:
        logger.warning("[YOUSIGN] No active collection found for request_id=%s", request_id)
        return

    pool = await get_db_pool()
    collection_id = collection["id"]
    candidate_name = collection["candidate_name"] or "Kandidaat"

    # Extract details from agent_state for the confirmation message
    agent_state = collection["agent_state"]
    if isinstance(agent_state, str):
        agent_state = json.loads(agent_state)

    context = agent_state.get("context", {})
    vacancy_title = context.get("vacancy", "")
    start_date = context.get("start_date", "")
    signing_url = context.get("yousign_signing_url", "")

    # Format start date to European style
    start_date_formatted = ""
    if start_date:
        try:
            _day_names = ["ma", "di", "woe", "do", "vr", "za", "zo"]
            dt = datetime.strptime(start_date, "%Y-%m-%d")
            start_date_formatted = f"{_day_names[dt.weekday()]} {dt.strftime('%d/%m/%y')}"
        except (ValueError, TypeError):
            start_date_formatted = start_date

    # Build confirmation message
    first_name = candidate_name.split()[0] if candidate_name else "Kandidaat"
    header = f"Proficiat {first_name}! 🎉 Je **contract** is volledig in orde"
    if vacancy_title:
        header += f" voor je opstart als **{vacancy_title}**"
    if start_date_formatted:
        header += f" op **{start_date_formatted}**"
    header += "."

    lines = [header, ""]
    if signing_url:
        lines.append(f"👉 [Bekijk je contract hier]({signing_url})")
        lines.append("")
    lines.append("👉 [Tips voor je opstart vind je hier](https://taloo.be/opstart)")
    lines.append("")
    lines.append("Heb je nog vragen of is er nog iets niet duidelijk? Stuur hier gerust een berichtje, dan helpen we je graag verder.")
    lines.append("")
    lines.append("Veel succes met je nieuwe job! 🍀")

    confirmation_msg = "\n".join(lines)

    # Store the confirmation message
    await pool.execute(
        """INSERT INTO agents.document_collection_session_turns
        (collection_id, role, message)
        VALUES ($1, 'agent', $2)""",
        collection_id,
        confirmation_msg,
    )

    # Update agent_state context to mark contract as signed
    context["contract_signed"] = True
    agent_state["context"] = context

    # Mark contract_signing step as completed so frontend progress updates
    completed = agent_state.get("completed_steps", [])
    if "contract_signing" not in completed:
        completed.append("contract_signing")
        agent_state["completed_steps"] = completed
    await pool.execute(
        """UPDATE agents.document_collections
        SET agent_state = $1::jsonb, updated_at = NOW()
        WHERE id = $2""",
        json.dumps(agent_state, ensure_ascii=False),
        collection_id,
    )

    # Push confirmation message to playground session (if active)
    push_playground_message(str(collection_id), confirmation_msg)

    # Mark collection as completed
    await pool.execute(
        "UPDATE agents.document_collections SET status = 'completed', completed_at = NOW() WHERE id = $1",
        collection_id,
    )

    # Advance workflow to complete
    try:
        from src.workflows import get_orchestrator
        orchestrator = await get_orchestrator()
        wf = await orchestrator.find_by_context("collection_id", str(collection_id))
        if wf:
            await orchestrator.service.update_step(wf["id"], "complete", new_status="completed")
            logger.info("[YOUSIGN] Workflow advanced to complete for collection=%s", collection_id)
    except Exception as e:
        logger.warning("[YOUSIGN] Workflow advancement failed: %s", e)

    # Transition candidacy
    candidacy_row = await pool.fetchrow(
        "SELECT candidacy_id FROM agents.document_collections WHERE id = $1", collection_id
    )
    if candidacy_row and candidacy_row["candidacy_id"]:
        try:
            from src.services.candidacy_transition_service import CandidacyStageTransitionService
            from src.models.candidacy import CandidacyStage
            service = CandidacyStageTransitionService(pool)
            await service.transition(
                candidacy_id=candidacy_row["candidacy_id"],
                to_stage=CandidacyStage.PLACED,
                triggered_by="yousign_webhook",
            )
            logger.info("[YOUSIGN] Candidacy transitioned to PLACED")
        except Exception as e:
            logger.warning("[YOUSIGN] Candidacy transition failed: %s", e)

        # Store contract URL on candidacy
        if signing_url:
            try:
                await pool.execute(
                    "UPDATE ats.candidacies SET contract_url = $1 WHERE id = $2",
                    signing_url, candidacy_row["candidacy_id"],
                )
            except Exception as e:
                logger.warning("[YOUSIGN] Contract URL update failed: %s", e)

    # Notify recruiter team
    try:
        from src.routers.document_collection import _notify_recruiter_team
        await _notify_recruiter_team(pool, collection_id)
    except Exception as e:
        logger.warning("[YOUSIGN] Teams notification failed: %s", e)

    # Persist review flags to candidacy record
    review_flags = agent_state.get("review_flags", [])
    if review_flags:
        candidacy_row = await pool.fetchrow(
            "SELECT candidacy_id FROM agents.document_collections WHERE id = $1", collection_id
        )
        if candidacy_row and candidacy_row["candidacy_id"]:
            try:
                reason = "; ".join(f["reason"] for f in review_flags)
                await pool.execute(
                    "UPDATE ats.candidacies SET recruiter_verification = true, recruiter_verification_reason = $1 WHERE id = $2",
                    reason, candidacy_row["candidacy_id"],
                )
            except Exception as e:
                logger.warning("[YOUSIGN] Recruiter verification flag update failed: %s", e)

    logger.info("[YOUSIGN] ✅ Contract signed for collection=%s, candidate=%s", collection_id, candidate_name)


@router.post("/webhook/yousign")
async def yousign_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Yousign-Signature-256")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event_name", "unknown")
    data = payload.get("data", {})
    # Yousign nests the signature request under data.signature_request
    sig_req = data.get("signature_request", data)
    request_id = sig_req.get("id", "unknown")
    request_name = sig_req.get("name", "")

    logger.info("[YOUSIGN] Event: %s | request_id=%s | name=%s", event, request_id, request_name)

    if event == "signature_request.done":
        await _handle_contract_signed(request_id, request_name, data)

    elif event == "signature_request.declined":
        logger.info("[YOUSIGN] ❌ Contract declined: %s (%s)", request_name, request_id)

    elif event == "signature_request.expired":
        logger.info("[YOUSIGN] ⏰ Contract expired: %s (%s)", request_name, request_id)

    elif event == "signature_request.canceled":
        logger.info("[YOUSIGN] 🚫 Contract canceled: %s (%s)", request_name, request_id)

    else:
        logger.info("[YOUSIGN] Unhandled event: %s", event)

    return JSONResponse({"status": "ok"})
