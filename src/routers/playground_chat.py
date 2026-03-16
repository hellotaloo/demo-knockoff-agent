"""
Playground Chat Router — unified SSE chat endpoint for all agent types.

Supports pre-screening and document collection agents (and future agents)
via a single endpoint with agent_type dispatch.

Sessions are ephemeral (in-memory only) — no database persistence.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.database import get_db_pool
from src.models.playground import PlaygroundChatRequest
from src.utils.random_candidate import generate_random_candidate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Playground"])

# In-memory cache for ephemeral playground sessions
_chat_sessions: dict[str, "PlaygroundAgent"] = {}

# Reverse lookup: collection_id → session_id (for webhook → playground bridge)
_collection_to_session: dict[str, str] = {}

# Pending messages injected by external sources (e.g. Yousign webhook)
_pending_messages: dict[str, list[str]] = {}  # session_id → [messages]


# =============================================================================
# Agent wrapper — uniform interface across agent types
# =============================================================================

@dataclass
class PlaygroundAgent:
    agent: Any
    agent_type: str
    candidate_name: str
    context_id: str = ""
    candidate_id: str = ""
    candidacy_id: str = ""
    live_mode: bool = False

    async def process(self, message: str) -> str | list[str]:
        if self.agent_type == "document_collection":
            has_image = (
                self.agent.pending_image_data is not None
                or any(tag in message for tag in ("--img-success--", "--img-fail--", "--eu-id--", "--eu-pass--", "--non-eu-pass--"))
            )
            result = await self.agent.process_message(message, has_image=has_image)
            self.agent.pending_image_data = None  # Clear after processing
            return result
        return await self.agent.process_message(message)

    def is_complete(self) -> bool:
        if self.agent_type == "pre_screening":
            from agents.pre_screening.whatsapp import is_conversation_complete
            return is_conversation_complete(self.agent)
        elif self.agent_type == "document_collection":
            from agents.document_collection.collection import is_collection_complete
            return is_collection_complete(self.agent)
        return False

    def get_collection_progress(self) -> dict | None:
        """Return collection progress for document_collection agents."""
        if self.agent_type != "document_collection":
            return None
        state = self.agent.state
        skipped_map = {s.get("slug", ""): s.get("skip_reason", "skipped") for s in state.skipped_items}

        # Build steps overview from conversation_flow
        steps = []
        for i, step in enumerate(state.conversation_flow):
            step_type = step.get("type", "")
            completed = step_type in state.completed_steps
            is_current = i == state.current_step_index

            step_entry = {
                "step": step.get("step", i + 1),
                "type": step_type,
                "description": step.get("description", ""),
                "completed": completed,
                "current": is_current,
            }

            # Add item details for steps with items
            if step.get("items"):
                step_items = []
                for item in step["items"]:
                    slug = item.get("slug", "")
                    entry = {"slug": slug, "priority": item.get("priority", "required")}
                    if step_type == "collect_documents":
                        doc_info = state.collected_documents.get(slug)
                        entry["collected"] = bool(doc_info and doc_info.get("status") == "verified")
                    elif step_type == "collect_attributes":
                        entry["collected"] = slug in state.collected_attributes
                        if slug in state.collected_attributes:
                            entry["value"] = state.collected_attributes[slug].get("value")
                    if slug in skipped_map:
                        entry["skipped"] = True
                        entry["skip_reason"] = skipped_map[slug]
                    step_items.append(entry)
                step_entry["items"] = step_items

            steps.append(step_entry)

        current_step = state.conversation_flow[state.current_step_index] if state.current_step_index < len(state.conversation_flow) else None

        # Build flat items list for frontend compatibility (CollectionProgress.items)
        # Use TypeCache for display names when available
        type_cache = getattr(self.agent, "type_cache", None)
        def _name(slug: str) -> str:
            if type_cache:
                t = type_cache.get_attr_type(slug) or type_cache.get_doc_type(slug)
                if t:
                    return t.get("name", slug)
            return slug

        items = []
        for step in state.conversation_flow:
            step_type = step.get("type", "")

            if step_type == "greeting_and_consent":
                items.append({
                    "slug": "greeting_and_consent",
                    "name": "Consent gegevensverwerking",
                    "type": "attribute",
                    "collected": state.consent_given or "greeting_and_consent" in state.completed_steps,
                })

            elif step_type == "identity_verification":
                id_collected = state.identity_phase == "done" or "identity_verification" in state.completed_steps
                # Get extracted fields and detected document type from collected identity doc
                id_extracted = None
                detected_type = None
                _doc_type_labels = {"id_card": "Identiteitskaart", "passport": "Paspoort", "driver_license": "Rijbewijs"}
                for doc_slug, doc_info in state.collected_documents.items():
                    if doc_info.get("status") in ("verified", "front_verified"):
                        detected_type = _doc_type_labels.get(doc_slug, doc_slug)
                        if doc_info.get("extracted_fields"):
                            id_extracted = {k: v for k, v in doc_info["extracted_fields"].items() if v}
                        break
                id_name = "Identiteitsbewijs"
                if detected_type:
                    id_name = detected_type
                items.append({
                    "slug": "identity_verification",
                    "name": id_name,
                    "type": "document_group",
                    "collected": id_collected,
                    "value": id_extracted,
                })
                # Work eligibility sub-item (rendered as indented arrow by frontend)
                items.append({
                    "slug": "prato_5",
                    "name": _name("work_eligibility"),
                    "type": "document",
                    "collected": state.work_eligibility is True,
                    "value": "Ja" if state.work_eligibility is True else ("Nee" if state.work_eligibility is False else None),
                })
                # Attributes extracted from identity document
                for afd in state.attributes_from_documents:
                    afd_slug = afd.get("slug", "")
                    afd_info = state.collected_attributes.get(afd_slug)
                    items.append({
                        "slug": afd_slug,
                        "name": _name(afd_slug),
                        "type": "attribute",
                        "collected": afd_info is not None,
                        "value": afd_info.get("value") if afd_info else None,
                    })

            elif step_type == "address_collection":
                # Domicilie
                dom_info = state.collected_attributes.get("domicile_address")
                items.append({
                    "slug": "domicile_address",
                    "name": _name("domicile_address"),
                    "type": "attribute",
                    "collected": dom_info is not None,
                    "value": dom_info.get("value") if dom_info else None,
                })
                # Verblijfsadres gelijk aan domicilie
                same_flag = state.collected_attributes.get("adres_gelijk_aan_domicilie")
                items.append({
                    "slug": "adres_gelijk_aan_domicilie",
                    "name": _name("adres_gelijk_aan_domicilie"),
                    "type": "attribute",
                    "collected": same_flag is not None,
                    "value": same_flag.get("value") if same_flag else None,
                })
                # Verblijfsadres
                verb_info = state.collected_attributes.get("verblijfs_adres")
                same_as_dom = same_flag and str(same_flag.get("value", "")).lower() in ("ja", "yes", "true")
                verb_collected = verb_info is not None or same_as_dom
                items.append({
                    "slug": "verblijfs_adres",
                    "name": _name("verblijfs_adres"),
                    "type": "attribute",
                    "collected": verb_collected,
                    "value": verb_info.get("value") if verb_info else (dom_info.get("value") if same_as_dom and dom_info else None),
                })

            elif step_type in ("collect_documents", "collect_attributes"):
                for item in step.get("items", []):
                    slug = item.get("slug", "")
                    item_type = "document" if step_type == "collect_documents" else "attribute"
                    entry = {
                        "slug": slug,
                        "name": _name(slug),
                        "type": item_type,
                        "collected": False,
                    }
                    if item_type == "document":
                        doc_info = state.collected_documents.get(slug)
                        entry["collected"] = bool(doc_info and doc_info.get("status") == "verified")
                    elif item_type == "attribute":
                        entry["collected"] = slug in state.collected_attributes
                        if slug in state.collected_attributes:
                            entry["value"] = state.collected_attributes[slug].get("value")
                    if slug in skipped_map:
                        entry["skipped"] = True
                        entry["skip_reason"] = skipped_map[slug]
                    items.append(entry)

            elif step_type in ("medical_screening", "contract_signing"):
                task_labels = {"contract_signing": "Contract ondertekening", "medical_screening": "Medisch onderzoek"}
                items.append({
                    "slug": step_type,
                    "name": task_labels.get(step_type, step_type),
                    "type": "task",
                    "collected": step_type in state.completed_steps,
                })

        return {
            "items": items,
            "steps": steps,
            "current_step": current_step["type"] if current_step else "done",
            "current_step_index": state.current_step_index,
            "consent_given": state.consent_given,
            "identity_phase": state.identity_phase,
            "address_phase": state.address_phase,
            "collected_documents": list(state.collected_documents.keys()),
            "collected_attributes": {k: v.get("value") for k, v in state.collected_attributes.items()},
            "eu_citizen": state.eu_citizen,
            "work_eligibility": state.work_eligibility,
            "review_flags": state.review_flags,
        }


# =============================================================================
# Bootstrap functions — create agents from DB context
# =============================================================================

async def _bootstrap_pre_screening(pool, vacancy_id: str, candidate_name: str) -> PlaygroundAgent:
    """Create a pre-screening agent from vacancy data."""
    from agents.pre_screening.whatsapp import create_simple_agent, AgentConfig
    from src.services.livekit_service import fetch_scheduling_config

    vacancy_uuid = uuid.UUID(vacancy_id)

    vacancy = await pool.fetchrow(
        "SELECT id, title, workspace_id FROM ats.vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy:
        raise ValueError("Vacancy not found")

    ps_row = await pool.fetchrow(
        "SELECT id FROM agents.pre_screenings WHERE vacancy_id = $1",
        vacancy_uuid
    )
    if not ps_row:
        raise ValueError("No pre-screening found for this vacancy")

    questions = await pool.fetch(
        """
        SELECT question_type, question_text, ideal_answer
        FROM agents.pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        ps_row["id"]
    )

    knockout_questions = [
        {"question": q["question_text"], "requirement": q["ideal_answer"] or ""}
        for q in questions if q["question_type"] == "knockout"
    ]
    open_questions = [
        q["question_text"]
        for q in questions if q["question_type"] == "qualification"
    ]

    # Office location
    office_location = ""
    office_address = ""
    loc_row = await pool.fetchrow(
        """
        SELECT ol.name, ol.address
        FROM ats.vacancies v
        JOIN ats.office_locations ol ON ol.id = v.office_location_id
        WHERE v.id = $1
        """,
        vacancy_uuid
    )
    if loc_row:
        office_location = loc_row["name"] or ""
        office_address = loc_row["address"] or ""

    sched_cfg = await fetch_scheduling_config()
    config = AgentConfig(
        schedule_days_ahead=sched_cfg["schedule_days_ahead"],
        schedule_start_offset=sched_cfg["schedule_start_offset"],
    )

    agent = create_simple_agent(
        candidate_name=candidate_name,
        vacancy_title=vacancy["title"],
        company_name=office_location,
        knockout_questions=knockout_questions,
        open_questions=open_questions,
        is_test=True,
        office_location=office_location,
        office_address=office_address,
        config=config,
    )

    return PlaygroundAgent(agent=agent, agent_type="pre_screening", candidate_name=candidate_name)


async def _bootstrap_document_collection(pool, collection_id: str, candidate_name: Optional[str]) -> PlaygroundAgent:
    """Create a document collection agent from an existing collection record."""
    from agents.document_collection.collection import create_collection_agent

    collection_uuid = uuid.UUID(collection_id)

    row = await pool.fetchrow(
        """
        SELECT dc.id, dc.candidate_name, dc.candidate_phone, dc.collection_plan,
               dc.workspace_id, dc.candidate_id, dc.candidacy_id,
               v.title AS vacancy_title,
               ol.name AS office_name,
               p.start_date,
               r.name AS recruiter_name,
               r.email AS recruiter_email,
               r.phone AS recruiter_phone
        FROM agents.document_collections dc
        JOIN ats.vacancies v ON v.id = dc.vacancy_id
        LEFT JOIN ats.office_locations ol ON ol.id = v.office_location_id
        LEFT JOIN ats.placements p ON p.candidate_id = dc.candidate_id AND p.vacancy_id = dc.vacancy_id
        LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
        WHERE dc.id = $1
        """,
        collection_uuid
    )
    if not row:
        raise ValueError("Collection not found")

    plan = row["collection_plan"] if isinstance(row["collection_plan"], dict) else json.loads(row["collection_plan"])

    name = candidate_name or row["candidate_name"] or "Kandidaat"
    vacancy_title = row["vacancy_title"] or ""
    start_date_str = ""
    days_remaining = 30
    if row["start_date"]:
        start_date_str = str(row["start_date"])
        delta = row["start_date"] - date.today()
        days_remaining = max(0, delta.days)

    # Ensure plan has context block (new conversation_flow format)
    if "context" not in plan:
        plan["context"] = {
            "candidate": name,
            "vacancy": vacancy_title,
            "company": row["office_name"] or "",
            "start_date": start_date_str,
            "days_remaining": days_remaining,
        }

    # Inject candidate phone for Yousign integration
    candidate_phone = row["candidate_phone"] or ""
    if candidate_phone:
        phone = f"+{candidate_phone}" if not candidate_phone.startswith("+") else candidate_phone
        plan["context"]["candidate_phone"] = phone

    from agents.document_collection.collection.type_cache import TypeCache
    type_cache = TypeCache(pool, row["workspace_id"])
    await type_cache.ensure_loaded()

    agent = create_collection_agent(
        plan=plan,
        type_cache=type_cache,
        collection_id=collection_id,
        recruiter_name=row["recruiter_name"] or "",
        recruiter_email=row["recruiter_email"] or "",
        recruiter_phone=row["recruiter_phone"] or "",
    )

    return PlaygroundAgent(
        agent=agent,
        agent_type="document_collection",
        candidate_name=name,
        context_id=collection_id,
        candidate_id=str(row["candidate_id"]) if row["candidate_id"] else "",
        candidacy_id=str(row["candidacy_id"]) if row["candidacy_id"] else "",
    )


# =============================================================================
# Live mode — persist collected data to real candidate records
# =============================================================================

async def _sync_live_mode(wrapper: PlaygroundAgent, pool):
    """Persist collected attributes to ats.candidate_attributes (idempotent via upsert)."""
    from src.repositories.candidate_attribute_repo import CandidateAttributeRepository

    state = wrapper.agent.state
    type_cache = wrapper.agent.type_cache
    candidate_uuid = uuid.UUID(wrapper.candidate_id)
    attr_repo = CandidateAttributeRepository(pool)

    for slug, attr_data in state.collected_attributes.items():
        attr_type = type_cache.get_attr_type(slug)
        if not attr_type or "id" not in attr_type:
            logger.debug(f"[LIVE] Skipping attribute '{slug}' — no type definition in TypeCache")
            continue

        value = attr_data.get("value")
        if isinstance(value, dict):
            value = json.dumps(value)
        elif value is not None:
            value = str(value)

        try:
            await attr_repo.upsert(
                candidate_id=candidate_uuid,
                attribute_type_id=attr_type["id"],
                value=value,
                source="document_collection_agent",
                verified=False,
            )
        except Exception as e:
            logger.warning(f"[LIVE] Failed to upsert attribute '{slug}': {e}")


async def _sync_live_mode_completion(wrapper: PlaygroundAgent, pool):
    """Transition candidacy to PLACED on collection completion."""
    if not wrapper.candidacy_id:
        return

    try:
        from src.services.candidacy_transition_service import CandidacyStageTransitionService
        from src.models.candidacy import CandidacyStage

        service = CandidacyStageTransitionService(pool)
        await service.transition(
            candidacy_id=uuid.UUID(wrapper.candidacy_id),
            to_stage=CandidacyStage.PLACED,
            triggered_by="document_collection_playground",
        )
        logger.info(f"[LIVE] Transitioned candidacy {wrapper.candidacy_id[:8]}... to PLACED")
    except Exception as e:
        logger.warning(f"[LIVE] Candidacy transition failed: {e}")

    # Notify recruiter team via Teams
    if wrapper.context_id:
        try:
            from src.routers.document_collection import _notify_recruiter_team
            await _notify_recruiter_team(pool, uuid.UUID(wrapper.context_id))
        except Exception as e:
            logger.warning(f"[LIVE] Teams notification failed: {e}")

    # Update collection status to completed
    if wrapper.context_id:
        try:
            await pool.execute(
                "UPDATE agents.document_collections SET status = 'completed', completed_at = NOW() WHERE id = $1",
                uuid.UUID(wrapper.context_id),
            )
            logger.info(f"[LIVE] Collection {wrapper.context_id[:8]}... marked as completed")
        except Exception as e:
            logger.warning(f"[LIVE] Collection status update failed: {e}")

    # Advance workflow
    if wrapper.context_id:
        try:
            from src.workflows import get_orchestrator
            orchestrator = await get_orchestrator()
            wf = await orchestrator.find_by_context("collection_id", wrapper.context_id)
            if wf:
                await orchestrator.service.update_step(wf["id"], "complete", new_status="completed")
                logger.info(f"[LIVE] Workflow advanced to collection_complete")
        except Exception as e:
            logger.warning(f"[LIVE] Workflow advancement failed: {e}")

    # Persist review flags (e.g. non-Belgian IBAN) to candidacy record
    if wrapper.candidacy_id and wrapper.agent_type == "document_collection":
        review_flags = wrapper.agent.state.review_flags
        if review_flags:
            try:
                reason = "; ".join(f["reason"] for f in review_flags)
                await pool.execute(
                    "UPDATE ats.candidacies SET recruiter_verification = true, recruiter_verification_reason = $1 WHERE id = $2",
                    reason,
                    uuid.UUID(wrapper.candidacy_id),
                )
                logger.info(f"[LIVE] Set recruiter_verification for candidacy {wrapper.candidacy_id[:8]}... ({len(review_flags)} flags)")
            except Exception as e:
                logger.warning(f"[LIVE] Recruiter verification flag update failed: {e}")


# =============================================================================
# SSE streaming
# =============================================================================

async def stream_playground_chat(
    agent_type: str,
    message: str,
    session_id: Optional[str],
    vacancy_id: Optional[str],
    collection_id: Optional[str],
    candidate_name: Optional[str],
    image_base64: Optional[str] = None,
    live_mode: bool = False,
) -> AsyncGenerator[str, None]:
    """Stream SSE events for a playground chat turn."""
    global _chat_sessions

    pool = await get_db_pool()
    is_new = session_id is None or message.upper() == "START"

    if is_new:
        # Generate random candidate name if not provided
        if not candidate_name:
            random_candidate = generate_random_candidate()
            candidate_name = random_candidate.first_name

        session_id = str(uuid.uuid4())

        try:
            if agent_type == "pre_screening":
                if not vacancy_id:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'vacancy_id is required for pre_screening'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                wrapper = await _bootstrap_pre_screening(pool, vacancy_id, candidate_name)

            elif agent_type == "document_collection":
                if not collection_id:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'collection_id is required for document_collection'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                wrapper = await _bootstrap_document_collection(pool, collection_id, candidate_name)

            else:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Unknown agent_type: {agent_type}'})}\n\n"
                yield "data: [DONE]\n\n"
                return

        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
            return

        wrapper.live_mode = live_mode
        _chat_sessions[session_id] = wrapper
        if wrapper.context_id:
            _collection_to_session[wrapper.context_id] = session_id
        candidate_name = wrapper.candidate_name

        logger.info("=" * 60)
        logger.info(f"🎬 NEW PLAYGROUND CHAT — {agent_type}")
        logger.info(f"👤 Candidate: {candidate_name} | Session: {session_id[:8]}...")
        logger.info("=" * 60)

        # Advance workflow to 'collecting' when conversation starts
        if wrapper.live_mode and wrapper.context_id and agent_type == "document_collection":
            try:
                from src.workflows import get_orchestrator
                orchestrator = await get_orchestrator()
                wf = await orchestrator.find_by_context("collection_id", wrapper.context_id)
                if wf:
                    await orchestrator.service.update_step(wf["id"], "collecting")
                    logger.info(f"[LIVE] Workflow advanced to collecting")
            except Exception as e:
                logger.warning(f"[LIVE] Workflow advance to collecting failed: {e}")

    else:
        wrapper = _chat_sessions.get(session_id)
        if wrapper:
            wrapper.live_mode = live_mode
        if not wrapper:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found. Please start a new conversation.'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        candidate_name = wrapper.candidate_name

    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Antwoord genereren...'})}\n\n"

    try:
        # Decode and attach image data for document collection
        if image_base64 and wrapper.agent_type == "document_collection":
            import base64 as b64
            wrapper.agent.pending_image_data = b64.b64decode(image_base64)

        if is_new:
            result = await wrapper.agent.get_initial_message()
        else:
            result = await wrapper.process(message)

        # Handlers may return str, list[str], or nested lists — flatten to list[str]
        def _flatten(val):
            if isinstance(val, str):
                return [val]
            out = []
            for item in val:
                out.extend(_flatten(item))
            return out
        messages_list = _flatten(result)

        # Persist agent state to DB for document_collection (needed for Yousign webhook lookup)
        if wrapper.agent_type == "document_collection" and wrapper.context_id:
            try:
                pool = await get_db_pool()
                await pool.execute(
                    """UPDATE agents.document_collections
                    SET agent_state = $1::jsonb, updated_at = NOW()
                    WHERE id = $2""",
                    wrapper.agent.state.to_json(),
                    uuid.UUID(wrapper.context_id),
                )
            except Exception as e:
                logger.warning(f"Failed to persist playground agent state: {e}")

        # Live mode: persist collected attributes to candidate records
        if wrapper.live_mode and wrapper.candidate_id and wrapper.agent_type == "document_collection":
            logger.info(f"[LIVE] Syncing {len(wrapper.agent.state.collected_attributes)} attributes for candidate {wrapper.candidate_id}")
            try:
                await _sync_live_mode(wrapper, pool)
            except Exception as e:
                logger.warning(f"[LIVE] Sync failed: {e}")

        is_complete = wrapper.is_complete()
        collection_progress = wrapper.get_collection_progress()

        if is_complete:
            # Live mode: transition candidacy to PLACED on completion
            if wrapper.live_mode and wrapper.candidate_id:
                try:
                    await _sync_live_mode_completion(wrapper, pool)
                except Exception as e:
                    logger.warning(f"[LIVE] Completion sync failed: {e}")
            if session_id in _chat_sessions:
                del _chat_sessions[session_id]

        for i, msg_text in enumerate(messages_list):
            # Add delay between multiple messages for natural UX
            if i > 0:
                await asyncio.sleep(1.5)
            payload = {
                'type': 'complete',
                'message': msg_text,
                'session_id': session_id,
                'candidate_name': candidate_name,
                'is_complete': is_complete,
            }
            if collection_progress is not None:
                payload['collection_progress'] = collection_progress
            yield f"data: {json.dumps(payload)}\n\n"

    except Exception as e:
        logger.error(f"Error in playground chat ({agent_type}): {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    yield "data: [DONE]\n\n"


# =============================================================================
# Endpoint
# =============================================================================

def push_playground_message(collection_id: str, message: str):
    """Push a message into the playground session for a given collection_id.

    Called by the Yousign webhook to inject confirmation messages.
    Also marks contract_signing as completed in the in-memory agent state.
    """
    session_id = _collection_to_session.get(collection_id)
    if not session_id:
        logger.warning(f"[PLAYGROUND] No active session for collection_id={collection_id}")
        return False
    _pending_messages.setdefault(session_id, []).append(message)

    # Update in-memory agent state so collection_progress reflects the change
    wrapper = _chat_sessions.get(session_id)
    if wrapper and wrapper.agent_type == "document_collection":
        state = wrapper.agent.state
        if "contract_signing" not in state.completed_steps:
            state.completed_steps.append("contract_signing")

    logger.info(f"[PLAYGROUND] Pushed message to session {session_id[:8]}... for collection {collection_id[:8]}...")
    return True


@router.get("/playground/chat/{session_id}/pending")
async def playground_chat_pending(session_id: str):
    """Return and clear any pending messages for this session (e.g. from webhooks)."""
    messages = _pending_messages.pop(session_id, [])
    result = {"messages": messages}

    # Include collection_progress if available so frontend updates the checklist
    if messages:
        wrapper = _chat_sessions.get(session_id)
        if wrapper:
            progress = wrapper.get_collection_progress()
            if progress is not None:
                result["collection_progress"] = progress

    return result


@router.delete("/playground/chat/{session_id}")
async def playground_chat_reset(session_id: str):
    """Delete a playground session so the next START creates a fresh agent."""
    deleted = _chat_sessions.pop(session_id, None)
    return {"deleted": deleted is not None, "session_id": session_id}


@router.post("/playground/chat")
async def playground_chat(request: PlaygroundChatRequest):
    """
    Unified playground chat for all agent types.

    Supported agent_type values:
    - "pre_screening": WhatsApp pre-screening agent (requires vacancy_id)
    - "document_collection": Document collection conductor (requires collection_id)

    For new conversations: send message="START" with agent-specific context.
    For continuing: include session_id from previous response.
    """
    return StreamingResponse(
        stream_playground_chat(
            agent_type=request.agent_type,
            message=request.message,
            session_id=request.session_id,
            vacancy_id=request.vacancy_id,
            collection_id=request.collection_id,
            candidate_name=request.candidate_name,
            image_base64=request.image_base64,
            live_mode=request.live_mode,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
