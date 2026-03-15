"""
Legacy Document Collection Conductor Agent.

FROZEN COPY — kept for backward compatibility with in-flight conversations
that were started with the old queue-based phase system.

Code-controlled conversation agent that executes a collection plan via WhatsApp.
Follows the same pattern as the pre-screening agent: Python controls all phase
transitions, LLM only generates conversational text.

The plan (from smart_collection_planner) is the single source of truth.

Conversation flow:
    INTRO → CONSENT → DOCUMENTS → CANDIDATE_INFO → SKIPPED_REVIEW → TASKS → ADDITIONAL_INFO → CLOSING → DONE

Usage:
    agent = create_collection_agent(
        collection_id="...",
        candidate_name="Pieter de Vries",
        vacancy_title="Productieoperator",
        company_name="Klant regio Diest",
        start_date="2026-03-16",
        days_remaining=3,
        summary="...",
        documents_to_collect=[...],
        attributes_to_collect=[...],
        agent_managed_tasks=[...],
        final_step={"action": "contract_signing"},
    )
    intro = await agent.get_initial_message()

    # Process incoming messages
    response = await agent.process_message("hier is mijn ID", has_image=True)

    # Restore from saved state
    agent = restore_collection_agent(state_json_from_db)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from agents.document_collection.collection.rules import (
    ADDRESS_GEOCODE_SLUGS,
    WORK_PERMIT_SLUGS,
    geocode_address,
    is_work_permit_item,
    schedule_task,
    validate_iban,
)
from agents.document_collection.collection.prompts import (
    SYSTEM_INSTRUCTION,
    build_ask_attribute_prompt,
    build_ask_back_prompt,
    build_ask_document_group_prompt,
    build_ask_document_prompt,
    build_attribute_unclear_prompt,
    build_closing_prompt,
    build_consent_prompt,
    build_consent_refused_prompt,
    build_intro_prompt,
    build_skip_prompt,
    build_skipped_review_prompt,
    build_stage_transition_prompt,
    build_task_ask_availability_prompt,
    build_task_contract_prompt,
    build_task_contract_signed_prompt,
    build_task_scheduled_prompt,
    build_tasks_blocked_prompt,
    build_verify_fail_prompt,
    build_verify_success_prompt,
    build_waiting_for_image_prompt,
)

logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_RETRIES_PER_DOC = 3



# ─── Phases ───────────────────────────────────────────────────────────────────

class Phase(str, Enum):
    INTRO = "intro"
    CONSENT = "consent"
    DOCUMENTS = "documents"
    WAITING_BACK = "waiting_back"       # sub-state of DOCUMENTS
    CANDIDATE_INFO = "candidate_info"
    SKIPPED_REVIEW = "skipped_review"
    TASKS = "tasks"
    ADDITIONAL_INFO = "additional_info"
    CLOSING = "closing"
    DONE = "done"


# ─── State ────────────────────────────────────────────────────────────────────

@dataclass
class CollectionState:
    """All conversation state — serializable to/from JSON for DB persistence."""

    phase: Phase = Phase.INTRO
    collection_id: str = ""

    # Context from plan
    candidate_name: str = ""
    vacancy_title: str = ""
    company_name: str = ""
    start_date: str = ""
    days_remaining: int = 0
    summary: str = ""

    # Recruiter info (from vacancy owner)
    recruiter_name: str = ""
    recruiter_email: str = ""
    recruiter_phone: str = ""

    # Consent
    consent_given: bool = False
    consent_refusal_count: int = 0

    # Stage-specific queues
    document_queue: list[dict] = field(default_factory=list)
    document_index: int = 0
    candidate_info_queue: list[dict] = field(default_factory=list)
    candidate_info_index: int = 0
    task_queue: list[dict] = field(default_factory=list)
    task_index: int = 0
    additional_info_queue: list[dict] = field(default_factory=list)
    additional_info_index: int = 0

    # Legacy: kept for backward compat with in-flight conversations
    item_queue: list[dict] = field(default_factory=list)
    current_item_index: int = 0

    # Results
    collected_documents: dict[str, dict] = field(default_factory=dict)  # slug -> {status, sides_collected, verification}
    collected_attributes: dict[str, dict] = field(default_factory=dict)  # slug -> {value: ...}

    # Skip tracking
    skipped_items: list[dict] = field(default_factory=list)
    skipped_review_index: int = 0

    # Per-document retry counts
    retry_counts: dict[str, int] = field(default_factory=dict)

    # Partial attribute extractions (for multi-field attrs answered across messages)
    partial_attributes: dict[str, dict] = field(default_factory=dict)  # slug -> {field_key: value, ...}

    # Candidate info derived from verified documents
    eu_citizen: bool | None = None  # None = unknown, True = EU/EER, False = non-EU

    # Silent recruiter review flags — not shown to candidate
    review_flags: list[dict] = field(default_factory=list)  # [{slug, flag, reason}]

    # Conversation history for LLM context
    conversation_history: list[dict] = field(default_factory=list)  # [{role: "agent"|"user", text: str}]

    # Task state tracking
    tasks_blocked: bool = False  # True if required items missing after skipped review

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "collection_id": self.collection_id,
            "candidate_name": self.candidate_name,
            "vacancy_title": self.vacancy_title,
            "company_name": self.company_name,
            "start_date": self.start_date,
            "days_remaining": self.days_remaining,
            "summary": self.summary,
            "recruiter_name": self.recruiter_name,
            "recruiter_email": self.recruiter_email,
            "recruiter_phone": self.recruiter_phone,
            "consent_given": self.consent_given,
            "consent_refusal_count": self.consent_refusal_count,
            "document_queue": self.document_queue,
            "document_index": self.document_index,
            "candidate_info_queue": self.candidate_info_queue,
            "candidate_info_index": self.candidate_info_index,
            "task_queue": self.task_queue,
            "task_index": self.task_index,
            "additional_info_queue": self.additional_info_queue,
            "additional_info_index": self.additional_info_index,
            "item_queue": self.item_queue,
            "current_item_index": self.current_item_index,
            "collected_documents": self.collected_documents,
            "collected_attributes": self.collected_attributes,
            "skipped_items": self.skipped_items,
            "skipped_review_index": self.skipped_review_index,
            "retry_counts": self.retry_counts,
            "partial_attributes": self.partial_attributes,
            "eu_citizen": self.eu_citizen,
            "review_flags": self.review_flags,
            "conversation_history": self.conversation_history,
            "tasks_blocked": self.tasks_blocked,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CollectionState":
        # Handle legacy phase values
        phase_val = d.get("phase", "intro")
        if phase_val == "collecting":
            phase_val = "documents"

        return cls(
            phase=Phase(phase_val),
            collection_id=d.get("collection_id", ""),
            candidate_name=d.get("candidate_name", ""),
            vacancy_title=d.get("vacancy_title", ""),
            company_name=d.get("company_name", ""),
            start_date=d.get("start_date", ""),
            days_remaining=d.get("days_remaining", 0),
            summary=d.get("summary", ""),
            recruiter_name=d.get("recruiter_name", ""),
            recruiter_email=d.get("recruiter_email", ""),
            recruiter_phone=d.get("recruiter_phone", ""),
            consent_given=d.get("consent_given", False),
            consent_refusal_count=d.get("consent_refusal_count", 0),
            document_queue=d.get("document_queue", []),
            document_index=d.get("document_index", 0),
            candidate_info_queue=d.get("candidate_info_queue", []),
            candidate_info_index=d.get("candidate_info_index", 0),
            task_queue=d.get("task_queue", []),
            task_index=d.get("task_index", 0),
            additional_info_queue=d.get("additional_info_queue", []),
            additional_info_index=d.get("additional_info_index", 0),
            item_queue=d.get("item_queue", []),
            current_item_index=d.get("current_item_index", 0),
            collected_documents=d.get("collected_documents", {}),
            collected_attributes=d.get("collected_attributes", {}),
            skipped_items=d.get("skipped_items", []),
            skipped_review_index=d.get("skipped_review_index", 0),
            retry_counts=d.get("retry_counts", {}),
            partial_attributes=d.get("partial_attributes", {}),
            eu_citizen=d.get("eu_citizen"),
            review_flags=d.get("review_flags", []),
            conversation_history=d.get("conversation_history", []),
            tasks_blocked=d.get("tasks_blocked", False),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "CollectionState":
        return cls.from_dict(json.loads(s))


# ─── Skip Detection ──────────────────────────────────────────────────────────

_SKIP_PATTERNS = re.compile(
    r"(?i)"
    r"(heb ik niet|heb ik nu niet|niet bij me|niet bij de hand"
    r"|kan ik later|stuur ik later|doe ik later"
    r"|overslaan|skip|sla over"
    r"|heb ik niet klaar|nog niet|niet beschikbaar"
    r"|kan niet nu|later sturen"
    r"|dat heb ik niet|heb ik helaas niet)",
    re.IGNORECASE,
)

# More lenient skip detection for recommended items (additional_info stage)
_SKIP_PATTERNS_LENIENT = re.compile(
    r"(?i)"
    r"(nee\b|neen\b|sorry|nee sorry|nee dank|niet nodig|hoeft niet)",
    re.IGNORECASE,
)

# ─── Consent Detection ──────────────────────────────────────────────────────

_CONSENT_YES = re.compile(
    r"(?i)(ja|akkoord|ok|oké|okay|goed|prima|geen probleem|dat is goed|mee eens|in orde|👍|yep|yes|sure)",
)

_CONSENT_NO = re.compile(
    r"(?i)(nee|niet akkoord|weiger|geen toestemming|niet mee eens|neen|no)",
)


def _check_skip_intent(message: str) -> bool:
    return bool(_SKIP_PATTERNS.search(message))


# ─── Simulated Verification ──────────────────────────────────────────────────

def _simulate_verification(message: str) -> dict | None:
    """Check for simulation markers in text.

    Identity markers (for document groups):
      --eu-id--       EU/EER ID card (front_back, no work permit needed)
      --eu-pass--     EU/EER passport (single, no work permit needed)
      --non-eu-pass-- Non-EU passport (single, work permit required)

    Generic markers (for other documents):
      --img-success-- Document OK
      --img-fail--    Document not readable
    """
    if "--eu-id--" in message:
        return {
            "passed": True,
            "category": "document",
            "quality": "good",
            "fraud_risk": "low",
            "summary": "EU/EER identiteitskaart geverifieerd (simulatie).",
            "resolved_slug": "id_card",
            "eu_citizen": True,
        }
    if "--eu-pass--" in message:
        return {
            "passed": True,
            "category": "document",
            "quality": "good",
            "fraud_risk": "low",
            "summary": "EU/EER paspoort geverifieerd (simulatie).",
            "resolved_slug": "passport",
            "eu_citizen": True,
        }
    if "--non-eu-pass--" in message:
        return {
            "passed": True,
            "category": "document",
            "quality": "good",
            "fraud_risk": "low",
            "summary": "Niet-EU paspoort geverifieerd (simulatie).",
            "resolved_slug": "passport",
            "eu_citizen": False,
        }
    if "--img-success--" in message:
        return {
            "passed": True,
            "category": "document",
            "quality": "good",
            "fraud_risk": "low",
            "summary": "Document geverifieerd (simulatie).",
        }
    if "--img-fail--" in message:
        return {
            "passed": False,
            "category": "unknown",
            "quality": "poor",
            "fraud_risk": "medium",
            "summary": "Document niet leesbaar (simulatie).",
        }
    return None


# ─── LLM Helper ──────────────────────────────────────────────────────────────

MAX_HISTORY_TURNS = 20  # Keep last N turns to avoid huge prompts


async def _generate_with_history(prompt: str, history: list[dict]) -> str:
    """Generate conversational text from a self-contained prompt.

    History is NOT passed to the LLM — prompts contain all necessary context.
    Passing history caused the model to follow conversation threads instead of
    the prompt instruction (e.g. continuing to ask about addresses when the
    prompt says to move to a new topic).
    """
    from src.utils.llm import generate

    return await generate(
        prompt=prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        model=DEFAULT_MODEL,
        temperature=0.7,
        max_output_tokens=1024,
    )


async def _extract_attribute(slug: str, name: str, user_message: str, fields: list[dict] | None = None, partial: dict | None = None, ai_hint: str | None = None) -> dict:
    """Use LLM to extract a structured value from freetext answer."""
    from src.utils.llm import generate

    if fields:
        # Structured extraction — extract multiple fields
        fields_spec = "\n".join(f'  "{f["key"]}": "{f["label"]} ({f.get("type", "text")})"' for f in fields)

        # If we have partial data from a previous message, include it as context
        partial_context = ""
        missing_keys = []
        if partial and isinstance(partial, dict):
            known = ", ".join(f'{k}="{v}"' for k, v in partial.items() if v)
            missing_keys = [f["key"] for f in fields if not partial.get(f["key"])]
            missing_labels = [f["label"] for f in fields if f["key"] in missing_keys]
            if known and missing_keys:
                partial_context = f"\n\nEerder al verzameld: {known}\nOntbrekend: {', '.join(missing_labels)}\nHet antwoord van de kandidaat is specifiek voor de ontbrekende velden. Wijs het antwoord toe aan het juiste ontbrekende veld."

        hint_line = f"\n\nExtra instructie: {ai_hint}" if ai_hint else ""

        # When only one field is missing, use a simpler targeted prompt
        if missing_keys and len(missing_keys) == 1:
            missing_field = next(f for f in fields if f["key"] == missing_keys[0])
            known_items = ", ".join(f'{k}="{v}"' for k, v in partial.items() if v)
            prompt = f"""Extraheer de waarde voor het veld "{missing_field['label']}" ({missing_field['key']}) uit het antwoord.
Attribuut: {name} ({slug})
Eerder verzameld: {known_items}
Antwoord van kandidaat: "{user_message}"{hint_line}

Het antwoord van de kandidaat is het ontbrekende veld "{missing_field['label']}" (type: {missing_field.get('type', 'text')}).
Neem het antwoord over als waarde voor "{missing_field['key']}". Combineer met de eerder verzamelde data.

Antwoord ALLEEN met valid JSON (geen markdown):
{{"value": {{{", ".join(f'"{k}": "{v}"' for k, v in partial.items() if v)}, "{missing_field['key']}": "de geëxtraheerde waarde"}}, "valid": true, "missing_fields": []}}"""
        else:
            prompt = f"""Extraheer de waarden uit het antwoord van de kandidaat.
Attribuut: {name} ({slug})
Antwoord: "{user_message}"{partial_context}{hint_line}

De volgende velden moeten geëxtraheerd worden:
{fields_spec}

Antwoord ALLEEN met valid JSON (geen markdown):
{{"value": {{"veld_key": "waarde", ...}}, "valid": true, "missing_fields": []}}

Als een of meer velden ontbreken, zet ze in missing_fields:
{{"value": {{"veld_key": "waarde"}}, "valid": false, "missing_fields": ["ontbrekend_veld_key"]}}

Als het antwoord helemaal niet duidelijk is:
{{"value": null, "valid": false, "missing_fields": [{", ".join(f'"{f["key"]}"' for f in fields)}]}}"""
    else:
        prompt = f"""Extraheer de waarde uit het antwoord van de kandidaat.
Attribuut: {name} ({slug})
Antwoord: "{user_message}"

Antwoord ALLEEN met valid JSON (geen markdown):
{{"value": "de geëxtraheerde waarde", "valid": true}}

Als het antwoord niet duidelijk is of het gevraagde gegeven ontbreekt:
{{"value": null, "valid": false}}"""

    response = await generate(
        prompt=prompt,
        system_instruction="Je extraheert gestructureerde data uit Nederlandse tekst. Antwoord altijd in valid JSON.",
        model=DEFAULT_MODEL,
        temperature=0,
        max_output_tokens=1024,
    )

    try:
        text = response.strip()
        if text.startswith("```"):
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"Failed to parse attribute extraction: {response}")
        if fields:
            # Structured attribute — don't accept a flat fallback
            return {"value": None, "valid": False, "missing_fields": [f["key"] for f in fields]}
        return {"value": user_message.strip(), "valid": True}



# ─── Agent ────────────────────────────────────────────────────────────────────

class DocumentCollectionAgent:
    """
    Code-controlled document & data collection agent.

    Phase transitions are managed by Python code.
    LLM generates only conversational text (Dutch/Flemish, WhatsApp-style).
    """

    def __init__(self, state: CollectionState):
        self.state = state

    # ── Document Verification Helper ─────────────────────────────────────

    def _process_document_scan(
        self, slug: str, scan_mode: str, verification: dict, is_back_side: bool = False
    ) -> str:
        """Process a document verification result and update state.

        Returns a status string indicating what happened:
        - "front_verified": front side accepted, back side still needed
        - "verified": document fully verified (single or both sides done)
        - "retry": verification failed, retry allowed
        - "max_retries": verification failed, max retries reached
        """
        if verification["passed"]:
            existing = self.state.collected_documents.get(slug, {})
            sides = existing.get("sides_collected", [])

            if is_back_side:
                sides.append("back")
                self.state.collected_documents[slug] = {
                    "status": "verified",
                    "sides_collected": sides,
                    "verification": verification,
                }
                return "verified"

            if scan_mode == "front_back" and "front" not in sides:
                # Front received, need back
                self.state.collected_documents[slug] = {
                    "status": "front_verified",
                    "sides_collected": ["front"],
                    "verification": verification,
                }
                return "front_verified"

            # Fully verified (single scan or already had front)
            sides.append("front" if not sides else "back")
            self.state.collected_documents[slug] = {
                "status": "verified",
                "sides_collected": sides if sides else ["single"],
                "verification": verification,
            }
            return "verified"
        else:
            # Failed — check retries
            retries = self.state.retry_counts.get(slug, 0) + 1
            self.state.retry_counts[slug] = retries
            if retries >= MAX_RETRIES_PER_DOC:
                return "max_retries"
            return "retry"

    # ── LLM with conversation context ────────────────────────────────────

    async def _say(self, prompt: str) -> str:
        """Generate a response with full conversation history, and track it."""
        response = await _generate_with_history(prompt, self.state.conversation_history)
        self.state.conversation_history.append({"role": "agent", "text": response})
        return response

    def _hear(self, user_message: str, has_image: bool = False):
        """Record an incoming user message in conversation history."""
        text = user_message
        if has_image:
            text = f"[Foto gestuurd] {user_message}" if user_message.strip() else "[Foto gestuurd]"
        self.state.conversation_history.append({"role": "user", "text": text})

    # ── Queue helpers ────────────────────────────────────────────────────

    def _current_queue_item(self, queue: list[dict], index: int) -> dict | None:
        if index < len(queue):
            return queue[index]
        return None

    def _next_queue_item(self, queue: list[dict], index: int) -> dict | None:
        idx = index + 1
        if idx < len(queue):
            return queue[idx]
        return None

    # ── Public API ────────────────────────────────────────────────────────

    async def get_initial_message(self) -> list[str]:
        """Generate the intro message(s) and advance to CONSENT.

        Returns a list of messages — each becomes a separate WhatsApp bubble.
        """
        intro = await self._say(build_intro_prompt(self.state))

        # Move to CONSENT phase
        self.state.phase = Phase.CONSENT
        consent_msg = await self._say(build_consent_prompt(self.state))
        return [intro, consent_msg]

    async def process_message(self, user_message: str, has_image: bool = False) -> str:
        """Main entry point. Routes to the appropriate phase handler."""
        self._hear(user_message, has_image)
        phase = self.state.phase

        if phase == Phase.CONSENT:
            return await self._handle_consent(user_message)
        elif phase == Phase.DOCUMENTS:
            return await self._handle_documents(user_message, has_image)
        elif phase == Phase.WAITING_BACK:
            return await self._handle_waiting_back(user_message, has_image)
        elif phase == Phase.CANDIDATE_INFO:
            return await self._handle_candidate_info(user_message)
        elif phase == Phase.SKIPPED_REVIEW:
            return await self._handle_skipped_review(user_message, has_image)
        elif phase == Phase.TASKS:
            return await self._handle_tasks(user_message, has_image)
        elif phase == Phase.ADDITIONAL_INFO:
            return await self._handle_additional_info(user_message)
        elif phase == Phase.CLOSING:
            return await self._handle_closing(user_message)
        elif phase == Phase.DONE:
            return "Bedankt! Je dossier is volledig. Tot binnenkort! 👍"
        else:
            # INTRO phase shouldn't receive messages (get_initial_message handles it)
            messages = await self.get_initial_message()
            return "\n\n".join(messages)

    # ── Phase: CONSENT ───────────────────────────────────────────────────

    async def _handle_consent(self, msg: str) -> str:
        if _CONSENT_YES.search(msg):
            self.state.consent_given = True
            return await self._transition_to_next_stage("consent")

        if _CONSENT_NO.search(msg):
            self.state.consent_refusal_count += 1
            if self.state.consent_refusal_count >= 2:
                self.state.phase = Phase.CLOSING
                return await self._say(build_consent_refused_prompt(self.state))
            return await self._say(
                f"""De kandidaat twijfelt over de toestemming.
Leg nogmaals kort uit waarom het nodig is (dossier in orde brengen) en vraag opnieuw.
Max 2 zinnen. Geen druk."""
            )

        # Ambiguous — ask again
        return await self._say(
            f"""De kandidaat gaf een onduidelijk antwoord op de toestemmingsvraag.
Vraag opnieuw of de kandidaat akkoord gaat. Geef een kort voorbeeld: "ja" of "nee".
Max 1-2 zinnen."""
        )

    # ── Phase: DOCUMENTS ─────────────────────────────────────────────────

    async def _handle_documents(self, msg: str, has_image: bool) -> str:
        item = self._current_queue_item(self.state.document_queue, self.state.document_index)
        if not item:
            return await self._transition_to_next_stage("documents")

        if item["type"] == "document_group":
            return await self._handle_document_group_item(msg, has_image, item)
        else:
            return await self._handle_document_item(msg, has_image, item)

    async def _handle_document_item(self, msg: str, has_image: bool, item: dict) -> str:
        slug = item["slug"]

        # Check skip intent
        if _check_skip_intent(msg):
            return await self._skip_and_advance_in_stage(item, "document")

        # Check for verification (simulated or real image)
        verification = _simulate_verification(msg)
        if verification or has_image:
            if not verification:
                verification = {"passed": True, "category": "document", "quality": "good", "summary": "Document ontvangen."}

            result = self._process_document_scan(slug, item.get("scan_mode", "single"), verification)

            if result == "front_verified":
                self.state.phase = Phase.WAITING_BACK
                return await self._say(build_ask_back_prompt(item))
            elif result == "verified":
                return await self._advance_in_stage(item, "document")
            elif result == "max_retries":
                return await self._skip_and_advance_in_stage(item, "document", reason="max_retries")
            else:  # retry
                return await self._say(build_verify_fail_prompt(item, self.state.retry_counts.get(slug, 0)))

        # No image, no skip — remind to upload
        return await self._say(build_waiting_for_image_prompt(item))

    async def _handle_document_group_item(self, msg: str, has_image: bool, item: dict) -> str:
        """Handle a group of alternative documents (e.g. ID card OR passport)."""
        alternatives = item.get("alternatives", [])

        # Check skip intent
        if _check_skip_intent(msg):
            return await self._skip_and_advance_in_stage(item, "document")

        verification = _simulate_verification(msg)
        if verification or has_image:
            if not verification:
                verification = {"passed": True, "category": "document", "quality": "good", "summary": "Document ontvangen."}

            if not verification["passed"]:
                # For groups, use group name for the retry prompt
                group_name = " / ".join(a["name"] for a in alternatives)
                result = self._process_document_scan(item["slug"], "single", verification)
                if result == "max_retries":
                    return await self._skip_and_advance_in_stage(item, "document", reason="max_retries")
                return await self._say(build_verify_fail_prompt({"name": group_name}, self.state.retry_counts.get(item["slug"], 0)))

            # Resolve which alternative was sent
            target_slug = verification.get("resolved_slug")
            resolved = next((a for a in alternatives if a["slug"] == target_slug), alternatives[0])
            resolved_slug = resolved["slug"]

            # Store EU citizenship status if available
            if "eu_citizen" in verification:
                self.state.eu_citizen = verification["eu_citizen"]

            result = self._process_document_scan(resolved_slug, resolved.get("scan_mode", "single"), verification)

            if result == "front_verified":
                self.state.document_queue[self.state.document_index]["resolved"] = resolved
                self.state.phase = Phase.WAITING_BACK
                return await self._say(build_ask_back_prompt(resolved))
            elif result == "verified":
                return await self._advance_in_stage(item, "document")
            elif result == "max_retries":
                return await self._skip_and_advance_in_stage(item, "document", reason="max_retries")
            else:  # retry
                return await self._say(build_verify_fail_prompt(resolved, self.state.retry_counts.get(resolved_slug, 0)))

        # No image — remind
        names = " of ".join(a["name"].lower() for a in alternatives)
        return await self._say(build_waiting_for_image_prompt({"name": names}))

    # ── Phase: WAITING_BACK ──────────────────────────────────────────────

    async def _handle_waiting_back(self, msg: str, has_image: bool) -> str:
        item = self._current_queue_item(self.state.document_queue, self.state.document_index)
        if not item:
            self.state.phase = Phase.DOCUMENTS
            return await self._transition_to_next_stage("documents")

        # For document groups, the resolved alternative has the actual slug
        resolved = item.get("resolved", item)
        slug = resolved["slug"]

        # Check skip intent
        if _check_skip_intent(msg):
            return await self._skip_and_advance_in_stage(item, "document", reason="back_skipped")

        verification = _simulate_verification(msg)
        if verification or has_image:
            if not verification:
                verification = {"passed": True, "category": "document", "quality": "good", "summary": "Achterkant ontvangen."}

            result = self._process_document_scan(slug, "front_back", verification, is_back_side=True)

            if result == "verified":
                self.state.phase = Phase.DOCUMENTS
                return await self._advance_in_stage(item, "document")
            elif result == "max_retries":
                self.state.phase = Phase.DOCUMENTS
                return await self._skip_and_advance_in_stage(item, "document", reason="max_retries")
            else:  # retry
                return await self._say(build_verify_fail_prompt(item, self.state.retry_counts.get(slug, 0)))

        # No image — remind
        return await self._say(build_waiting_for_image_prompt(item))

    # ── Phase: CANDIDATE_INFO ────────────────────────────────────────────

    async def _handle_candidate_info(self, msg: str) -> str:
        item = self._current_queue_item(self.state.candidate_info_queue, self.state.candidate_info_index)
        if not item:
            return await self._transition_to_next_stage("candidate_info")
        return await self._handle_attribute_item(msg, item, "candidate_info")

    # ── Phase: TASKS ─────────────────────────────────────────────────────

    async def _handle_tasks(self, msg: str, has_image: bool) -> str:
        task = self._current_queue_item(self.state.task_queue, self.state.task_index)
        if not task:
            return await self._transition_to_next_stage("tasks")

        task_slug = task.get("slug", task.get("action", ""))

        # Contract signing
        if task_slug == "contract_signing" or task.get("action") == "contract_signing":
            if "--signed--" in msg:
                self.state.task_index += 1
                congrats = await self._say(build_task_contract_signed_prompt(task, self.state))
                # Check if more tasks remain, otherwise transition
                next_task = self._current_queue_item(self.state.task_queue, self.state.task_index)
                if next_task:
                    next_req = await self._generate_task_request(next_task)
                    return congrats + "\n\n" + next_req
                return congrats + "\n\n" + await self._transition_to_next_stage("tasks")
            if not task.get("_link_sent"):
                task["_link_sent"] = True
                return await self._say(build_task_contract_prompt(task, self.state))
            # Waiting for signature
            return await self._say(
                f"""De kandidaat heeft gereageerd maar het contract is nog niet ondertekend.
Herinner vriendelijk dat het contract ondertekend moet worden via de link.
Max 1-2 zinnen."""
            )

        # Medical screening / interactive tasks
        if task.get("_availability_collected"):
            # Already collected, shouldn't be here — advance
            self.state.task_index += 1
            next_task = self._current_queue_item(self.state.task_queue, self.state.task_index)
            if next_task:
                return await self._generate_task_request(next_task)
            return await self._transition_to_next_stage("tasks")

        if task.get("_asked"):
            # We asked for availability, now collect the response
            task["_availability_collected"] = True
            await schedule_task(
                task_slug=task_slug,
                task_name=task.get("name", task_slug),
                availability=msg,
                collection_id=self.state.collection_id,
            )
            self.state.task_index += 1
            scheduled_msg = await self._say(build_task_scheduled_prompt(task))

            # Check if there are more tasks
            next_task = self._current_queue_item(self.state.task_queue, self.state.task_index)
            if next_task:
                next_request = await self._generate_task_request(next_task)
                return scheduled_msg + "\n\n" + next_request
            return scheduled_msg + "\n\n" + await self._transition_to_next_stage("tasks")

        # First time seeing this task — ask for availability
        task["_asked"] = True
        return await self._say(build_task_ask_availability_prompt(task, self.state))

    async def _generate_task_request(self, task: dict) -> str:
        """Generate the initial request for a task."""
        task_slug = task.get("slug", task.get("action", ""))
        if task_slug == "contract_signing" or task.get("action") == "contract_signing":
            task["_link_sent"] = True
            return await self._say(build_task_contract_prompt(task, self.state))
        task["_asked"] = True
        return await self._say(build_task_ask_availability_prompt(task, self.state))

    # ── Phase: ADDITIONAL_INFO ───────────────────────────────────────────

    async def _handle_additional_info(self, msg: str) -> str:
        item = self._current_queue_item(self.state.additional_info_queue, self.state.additional_info_index)
        if not item:
            return await self._transition_to_next_stage("additional_info")

        if item["type"] in ("document", "document_group"):
            # For recommended docs in additional_info, handle like document phase
            if item["type"] == "document_group":
                return await self._handle_document_group_item_additional(msg, item)
            return await self._handle_document_item_additional(msg, item)
        return await self._handle_attribute_item(msg, item, "additional_info")

    async def _handle_document_item_additional(self, msg: str, item: dict) -> str:
        """Handle document items in additional_info queue (recommended docs)."""
        slug = item["slug"]
        has_image = any(tag in msg for tag in ("--img-success--", "--img-fail--", "--eu-id--", "--eu-pass--", "--non-eu-pass--"))

        if _check_skip_intent(msg) or _SKIP_PATTERNS_LENIENT.search(msg):
            return await self._skip_and_advance_in_stage(item, "additional_info")

        verification = _simulate_verification(msg)
        if verification or has_image:
            if not verification:
                verification = {"passed": True, "category": "document", "quality": "good", "summary": "Document ontvangen."}
            result = self._process_document_scan(slug, item.get("scan_mode", "single"), verification)
            if result == "verified":
                return await self._advance_in_stage(item, "additional_info")
            elif result == "max_retries":
                return await self._skip_and_advance_in_stage(item, "additional_info", reason="max_retries")
            else:
                return await self._say(build_verify_fail_prompt(item, self.state.retry_counts.get(slug, 0)))

        return await self._say(build_waiting_for_image_prompt(item))

    async def _handle_document_group_item_additional(self, msg: str, item: dict) -> str:
        """Handle document group items in additional_info queue."""
        has_image = any(tag in msg for tag in ("--img-success--", "--img-fail--", "--eu-id--", "--eu-pass--", "--non-eu-pass--"))

        if _check_skip_intent(msg) or _SKIP_PATTERNS_LENIENT.search(msg):
            return await self._skip_and_advance_in_stage(item, "additional_info")

        verification = _simulate_verification(msg)
        if verification or has_image:
            if not verification:
                verification = {"passed": True, "category": "document", "quality": "good", "summary": "Document ontvangen."}
            alternatives = item.get("alternatives", [])
            target_slug = verification.get("resolved_slug")
            resolved = next((a for a in alternatives if a["slug"] == target_slug), alternatives[0]) if alternatives else item
            result = self._process_document_scan(resolved["slug"], resolved.get("scan_mode", "single"), verification)
            if result == "verified":
                return await self._advance_in_stage(item, "additional_info")
            elif result == "max_retries":
                return await self._skip_and_advance_in_stage(item, "additional_info", reason="max_retries")
            else:
                return await self._say(build_verify_fail_prompt(resolved, self.state.retry_counts.get(resolved["slug"], 0)))

        names = " of ".join(a["name"].lower() for a in item.get("alternatives", []))
        return await self._say(build_waiting_for_image_prompt({"name": names}))

    # ── Phase: SKIPPED_REVIEW ────────────────────────────────────────────

    async def _handle_skipped_review(self, msg: str, has_image: bool) -> str:
        if self.state.skipped_review_index >= len(self.state.skipped_items):
            return await self._after_skipped_review()

        item = self.state.skipped_items[self.state.skipped_review_index]

        # Check if they want to skip again
        if _check_skip_intent(msg):
            item["permanently_skipped"] = True
            self.state.skipped_review_index += 1
            return await self._next_skipped_or_after_review()

        if item["type"] in ("document", "document_group"):
            verification = _simulate_verification(msg)
            if verification or has_image:
                if not verification:
                    verification = {"passed": True, "category": "document", "quality": "good", "summary": "OK"}

                slug = item["slug"]
                existing = self.state.collected_documents.get(slug, {})
                is_back = "front" in existing.get("sides_collected", [])
                result = self._process_document_scan(
                    slug, item.get("scan_mode", "single"), verification, is_back_side=is_back
                )

                if result == "front_verified":
                    # Ask for back — stay on same skipped index
                    return await self._say(build_ask_back_prompt(item))
                elif result == "verified":
                    self.state.skipped_review_index += 1
                    return await self._next_skipped_or_after_review()
                else:  # retry or max_retries — permanently skip in review phase
                    item["permanently_skipped"] = True
                    self.state.skipped_review_index += 1
                    return await self._next_skipped_or_after_review()

            # No image — remind
            return await self._say(build_waiting_for_image_prompt(item))

        else:
            # Attribute
            result = await _extract_attribute(item["slug"], item["name"], msg, fields=item.get("fields"), ai_hint=item.get("ai_hint"))
            if result.get("valid") and result.get("value"):
                self.state.collected_attributes[item["slug"]] = {"value": result["value"]}
                self.state.skipped_review_index += 1
                return await self._next_skipped_or_after_review()
            else:
                return await self._say(build_attribute_unclear_prompt(item))

    # ── Phase: CLOSING ───────────────────────────────────────────────────

    async def _handle_closing(self, msg: str) -> str:
        # Already in closing — generate closing and mark done
        closing = await self._say(build_closing_prompt(self.state))
        self.state.phase = Phase.DONE
        return closing

    # ── Shared Attribute Handling ────────────────────────────────────────

    def _merge_partial_attribute(self, slug: str, new_value: dict) -> dict:
        """Merge new extraction with any existing partial values for a structured attribute."""
        existing = self.state.partial_attributes.get(slug)
        if existing and isinstance(existing, dict):
            return {**existing, **{k: v for k, v in new_value.items() if v}}
        return new_value

    def _get_missing_required_fields(self, fields: list[dict], value: dict) -> list[str]:
        """Return keys of required fields that are still empty."""
        return [f["key"] for f in fields if not value.get(f["key"]) and f.get("required", True)]

    async def _ask_missing_fields(self, item: dict, fields: list[dict], missing_keys: list[str]) -> str:
        """Store partial and ask for missing fields."""
        missing_labels = [f["label"] for f in fields if f["key"] in missing_keys]
        missing_text = " en ".join(missing_labels)
        return await self._say(
            f"""Bedankt! Maar voor *{item['name']}* mis ik nog: *{missing_text}*.
Vraag specifiek naar de ontbrekende info. Benoem waarvoor het is (bv. "het telefoonnummer van je noodcontact").
Max 1-2 zinnen. Vriendelijk."""
        )

    async def _validate_iban(self, value: str) -> tuple[str | None, str | None]:
        """Validate IBAN and return (formatted_value, error_prompt).

        Returns (formatted_iban, None) on success, or (None, prompt) on failure.
        """
        iban = validate_iban(value)
        if not iban.valid:
            prompt = await self._say(
                f"""De kandidaat gaf "{value}" als IBAN maar dit is geen geldig IBAN-nummer.
Vraag vriendelijk om het opnieuw te controleren en nog eens te sturen.
Kort en direct, max 1-2 zinnen."""
            )
            return None, prompt
        if not iban.is_sepa:
            prompt = await self._say(
                f"""De kandidaat gaf een geldig IBAN ({iban.formatted}) maar dit is geen SEPA-rekeningnummer.
Voor de verloning is een SEPA-bankrekening vereist (bv. Belgisch, Nederlands, Duits, Frans, ...).
Leg dit vriendelijk uit en vraag om een ander rekeningnummer.
Kort en direct, max 2 zinnen."""
            )
            return None, prompt
        if not iban.is_belgian:
            self.state.review_flags.append({
                "slug": "iban",
                "flag": "non_belgian_iban",
                "reason": f"Bankrekening is SEPA-conform maar niet Belgisch ({iban.country_code}): {iban.formatted}",
            })
        return iban.formatted, None

    async def _handle_attribute_item(self, msg: str, item: dict, stage: str) -> str:
        """Handle an attribute item from any stage (candidate_info or additional_info)."""
        slug = item["slug"]
        fields = item.get("fields")

        # Check skip intent (lenient for recommended items in additional_info)
        if _check_skip_intent(msg) or (stage == "additional_info" and _SKIP_PATTERNS_LENIENT.search(msg)):
            self.state.partial_attributes.pop(slug, None)
            return await self._skip_and_advance_in_stage(item, stage)

        # Special case: user provides an address when asked "Is verblijfsadres gelijk aan domicilie?"
        # This means "no, here's my different address" — save "neen" and auto-collect verblijfs_adres
        if slug == "adres_gelijk_aan_domicilie" and not fields:
            geocoded = await geocode_address(msg)
            if geocoded:
                logger.info(f"[ATTR] {slug}: user gave an address instead of yes/no → interpreting as 'neen'")
                self.state.collected_attributes[slug] = {"value": "neen"}

                # Try to also auto-collect verblijfs_adres from the geocoded result
                verblijf_item = next(
                    (i for i in self.state.candidate_info_queue if i.get("slug") == "verblijfs_adres"), None
                )
                if verblijf_item and verblijf_item.get("fields"):
                    field_keys = {f["key"] for f in verblijf_item["fields"]}
                    verblijf_value = {k: v for k, v in geocoded.items() if k in field_keys and v}
                    missing = self._get_missing_required_fields(verblijf_item["fields"], verblijf_value)
                    if not missing:
                        self.state.collected_attributes["verblijfs_adres"] = {"value": verblijf_value}
                        logger.info(f"[ATTR] verblijfs_adres: auto-collected from geocoded address → {verblijf_value}")
                    else:
                        self.state.partial_attributes["verblijfs_adres"] = verblijf_value

                return await self._advance_in_stage(item, stage)

        # Address attributes: try Google Maps geocoding first
        if fields and slug in ADDRESS_GEOCODE_SLUGS:
            geocoded = await geocode_address(msg)
            if geocoded:
                # Filter to only keys that match field spec
                field_keys = {f["key"] for f in fields}
                value = {k: v for k, v in geocoded.items() if k in field_keys and v}
                logger.info(f"[ATTR] {slug}: geocoded → {value}")

                missing = self._get_missing_required_fields(fields, value)
                if not missing:
                    self.state.partial_attributes.pop(slug, None)
                    self.state.collected_attributes[slug] = {"value": value}
                    return await self._advance_in_stage(item, stage)
                else:
                    # Geocode got partial result — store and ask for rest
                    self.state.partial_attributes[slug] = value
                    return await self._ask_missing_fields(item, fields, missing)

        # Extract value from message (LLM fallback)
        existing_partial = self.state.partial_attributes.get(slug)
        logger.info(f"[ATTR] Extracting {slug}: fields={bool(fields)}, partial={bool(existing_partial)}, msg={msg[:60]}")
        result = await _extract_attribute(slug, item["name"], msg, fields=fields, partial=existing_partial, ai_hint=item.get("ai_hint"))
        logger.info(f"[ATTR] Result for {slug}: {result}")

        if result.get("valid") and result.get("value"):
            value = result["value"]

            if fields:
                # Structured attribute — value MUST be a dict with field keys
                if not isinstance(value, dict):
                    logger.warning(f"[ATTR] {slug}: got flat string instead of dict, re-extracting as structured")
                    retry_result = await _extract_attribute(
                        slug, item["name"], str(value),
                        fields=fields, partial=existing_partial, ai_hint=item.get("ai_hint"),
                    )
                    if retry_result.get("value") and isinstance(retry_result["value"], dict):
                        value = retry_result["value"]
                    else:
                        all_keys = [f["key"] for f in fields if f.get("required", True)]
                        return await self._ask_missing_fields(item, fields, all_keys)

                value = self._merge_partial_attribute(slug, value)

                # Check required fields are filled
                missing = self._get_missing_required_fields(fields, value)
                if missing:
                    self.state.partial_attributes[slug] = value
                    return await self._ask_missing_fields(item, fields, missing)

            self.state.partial_attributes.pop(slug, None)

            # IBAN-specific validation
            if slug == "iban" and isinstance(value, str):
                validated, error = await self._validate_iban(value)
                if error:
                    return error
                value = validated

            self.state.collected_attributes[slug] = {"value": value}
            return await self._advance_in_stage(item, stage)

        # Structured attribute with missing fields — store partial and ask for the rest
        if fields and result.get("missing_fields") and result.get("value"):
            value = result["value"]
            if isinstance(value, dict):
                value = self._merge_partial_attribute(slug, value)
            self.state.partial_attributes[slug] = value

            # Determine which fields are still truly missing
            still_missing = [k for k in result["missing_fields"] if not value.get(k)]
            if not still_missing:
                self.state.partial_attributes.pop(slug, None)
                self.state.collected_attributes[slug] = {"value": value}
                return await self._advance_in_stage(item, stage)

            return await self._ask_missing_fields(item, fields, still_missing)

        # Unclear answer — ask again
        return await self._say(build_attribute_unclear_prompt(item))

    # ── Auto-Skip Logic ──────────────────────────────────────────────────

    def _should_auto_skip(self, item: dict) -> bool:
        """Check if an item should be auto-skipped based on collected info."""
        slug = item.get("slug", "")

        # Already collected (e.g. auto-filled from another step)
        if item["type"] == "attribute" and slug in self.state.collected_attributes:
            return True

        if is_work_permit_item(item):
            if self.state.eu_citizen is True:
                return True  # EU citizen — not needed
            if self.state.eu_citizen is None:
                return True  # Unknown nationality — defer until identity is resolved

        # Verblijfs adres: skip if domicilie = verblijf
        if slug == "verblijfs_adres":
            agd = self.state.collected_attributes.get("adres_gelijk_aan_domicilie", {})
            value = agd.get("value", "")
            if isinstance(value, str) and value.strip().lower() in ("ja", "yes", "true"):
                return True

        return False

    def _auto_skip_details(self, item: dict) -> tuple[str, bool]:
        """Return (skip_reason, permanently_skipped) for an auto-skipped item."""
        slug = item.get("slug", "")

        # Already collected from a previous step
        if item["type"] == "attribute" and slug in self.state.collected_attributes:
            return "already_collected", True

        if slug == "verblijfs_adres":
            # Copy domicilie address value to verblijfs_adres
            domicilie = (
                self.state.collected_attributes.get("domicile_address")
                or self.state.collected_attributes.get("domicilie_adres")
            )
            if domicilie:
                self.state.collected_attributes["verblijfs_adres"] = {"value": domicilie["value"]}
                logger.info("Copied domicilie address to verblijfs_adres (same address)")
            return "same_as_domicile", True

        if self.state.eu_citizen is True:
            return "not_applicable", True  # EU citizen — permanently skip
        # eu_citizen is None — defer for skipped review
        return "pending_identity", False

    # ── Stage Navigation ─────────────────────────────────────────────────

    def _get_stage_queue_and_index(self, stage: str) -> tuple[list[dict], int, str, str]:
        """Return (queue, index, index_attr_name, queue_attr_name) for a stage."""
        if stage == "document":
            return self.state.document_queue, self.state.document_index, "document_index", "document_queue"
        elif stage == "candidate_info":
            return self.state.candidate_info_queue, self.state.candidate_info_index, "candidate_info_index", "candidate_info_queue"
        elif stage == "additional_info":
            return self.state.additional_info_queue, self.state.additional_info_index, "additional_info_index", "additional_info_queue"
        raise ValueError(f"Unknown stage: {stage}")

    def _increment_stage_index(self, stage: str):
        """Increment the index for a stage."""
        if stage == "document":
            self.state.document_index += 1
        elif stage == "candidate_info":
            self.state.candidate_info_index += 1
        elif stage == "additional_info":
            self.state.additional_info_index += 1

    def _get_current_stage_item(self, stage: str) -> dict | None:
        queue, index, _, _ = self._get_stage_queue_and_index(stage)
        return self._current_queue_item(queue, index)

    async def _advance_in_stage(self, completed_item: dict, stage: str) -> str:
        """Move to next item in the current stage queue."""
        self._increment_stage_index(stage)

        # Auto-skip items that are no longer needed
        queue, _, index_attr, _ = self._get_stage_queue_and_index(stage)
        while True:
            index = getattr(self.state, index_attr)
            next_item = self._current_queue_item(queue, index)
            if not next_item or not self._should_auto_skip(next_item):
                break
            skip_reason, permanently = self._auto_skip_details(next_item)
            logger.info(f"Auto-skipping {next_item['slug']} ({skip_reason})")
            self.state.skipped_items.append({
                **next_item,
                "skip_reason": skip_reason,
                "permanently_skipped": permanently,
            })
            self._increment_stage_index(stage)

        index = getattr(self.state, index_attr)
        next_item = self._current_queue_item(queue, index)

        # Deterministic success confirmation — no LLM needed
        confirm = f"Oké, {completed_item['name'].lower()} is genoteerd! ✅"

        if next_item:
            # Generate ONLY the next item request via LLM (fresh prompt, no history pollution)
            next_request = await self._generate_item_request(next_item)
            return confirm + "\n\n" + next_request
        else:
            # Stage complete — transition
            transition_msg = await self._transition_to_next_stage(stage)
            return confirm + "\n\n" + transition_msg

    async def _skip_and_advance_in_stage(self, item: dict, stage: str, reason: str = "candidate_skipped") -> str:
        """Skip current item and advance to next in the stage queue."""
        self.state.skipped_items.append({
            **item,
            "skip_reason": reason,
            "permanently_skipped": False,
        })
        self._increment_stage_index(stage)

        # Auto-skip items that are no longer needed
        queue, _, index_attr, _ = self._get_stage_queue_and_index(stage)
        while True:
            index = getattr(self.state, index_attr)
            next_item = self._current_queue_item(queue, index)
            if not next_item or not self._should_auto_skip(next_item):
                break
            skip_reason, permanently = self._auto_skip_details(next_item)
            logger.info(f"Auto-skipping {next_item['slug']} ({skip_reason})")
            self.state.skipped_items.append({
                **next_item,
                "skip_reason": skip_reason,
                "permanently_skipped": permanently,
            })
            self._increment_stage_index(stage)

        index = getattr(self.state, index_attr)
        next_item = self._current_queue_item(queue, index)

        # Deterministic skip confirmation
        skip_confirm = f"Geen probleem, we slaan {item['name'].lower()} even over. 👍"

        if next_item:
            next_request = await self._generate_item_request(next_item)
            return skip_confirm + "\n\n" + next_request
        else:
            return skip_confirm + "\n\n" + await self._transition_to_next_stage(stage)

    async def _transition_to_next_stage(self, completed_stage: str) -> str:
        """Transition to the next stage in the flow."""
        # Normalize: internal stage names use singular "document", but flow uses "documents"
        if completed_stage == "document":
            completed_stage = "documents"

        if completed_stage == "consent":
            if self.state.document_queue:
                self.state.phase = Phase.DOCUMENTS
                first_item = self.state.document_queue[0]
                transition = await self._say(build_stage_transition_prompt("consent", "documents"))
                first_request = await self._generate_item_request(first_item)
                return transition + "\n\n" + first_request
            # No documents — go to candidate_info
            completed_stage = "documents"  # fall through

        if completed_stage == "documents":
            if self.state.candidate_info_queue:
                self.state.phase = Phase.CANDIDATE_INFO
                first_item = self.state.candidate_info_queue[0]
                transition = await self._say(build_stage_transition_prompt("documents", "candidate_info"))
                first_request = await self._generate_item_request(first_item)
                return transition + "\n\n" + first_request
            completed_stage = "candidate_info"  # fall through

        if completed_stage == "candidate_info":
            # Go to skipped review
            return await self._enter_skipped_review()

        if completed_stage == "skipped_review":
            # Check blocking rule: all required docs + info collected?
            if self._all_required_collected():
                if self.state.task_queue:
                    self.state.phase = Phase.TASKS
                    first_task = self.state.task_queue[0]
                    return await self._generate_task_request(first_task)
                completed_stage = "tasks"  # fall through
            else:
                # Required items still missing — block tasks
                self.state.tasks_blocked = True
                blocked_msg = await self._say(build_tasks_blocked_prompt(self.state))
                if self.state.additional_info_queue:
                    self.state.phase = Phase.ADDITIONAL_INFO
                    first_item = self.state.additional_info_queue[0]
                    first_request = await self._generate_item_request(first_item)
                    return blocked_msg + "\n\n" + first_request
                return blocked_msg + "\n\n" + await self._transition_to_closing()

        if completed_stage == "tasks":
            if self.state.additional_info_queue:
                self.state.phase = Phase.ADDITIONAL_INFO
                first_item = self.state.additional_info_queue[0]
                transition = await self._say(build_stage_transition_prompt("tasks", "additional_info"))
                first_request = await self._generate_item_request(first_item)
                return transition + "\n\n" + first_request
            completed_stage = "additional_info"  # fall through

        if completed_stage == "additional_info":
            return await self._transition_to_closing()

        return await self._transition_to_closing()

    def _all_required_collected(self) -> bool:
        """Check if all required documents and candidate info have been collected."""
        # Check all document queue items (required/conditional docs)
        for item in self.state.document_queue:
            slug = item.get("slug", "")
            if item["type"] == "document_group":
                # At least one alternative must be verified
                alternatives = item.get("alternatives", [])
                if not any(
                    self.state.collected_documents.get(a["slug"], {}).get("status") == "verified"
                    for a in alternatives
                ):
                    # Check if it was auto-skipped permanently (e.g. work permit for EU citizen)
                    if not any(
                        s.get("slug") == slug and s.get("permanently_skipped") and s.get("skip_reason") in ("not_applicable", "same_as_domicile")
                        for s in self.state.skipped_items
                    ):
                        return False
            elif item["type"] == "document":
                if self.state.collected_documents.get(slug, {}).get("status") != "verified":
                    if not any(
                        s.get("slug") == slug and s.get("permanently_skipped") and s.get("skip_reason") in ("not_applicable", "same_as_domicile")
                        for s in self.state.skipped_items
                    ):
                        return False

        # Check all candidate_info queue items
        for item in self.state.candidate_info_queue:
            slug = item.get("slug", "")
            if slug not in self.state.collected_attributes:
                if not any(
                    s.get("slug") == slug and s.get("permanently_skipped") and s.get("skip_reason") in ("not_applicable", "same_as_domicile")
                    for s in self.state.skipped_items
                ):
                    return False

        return True

    async def _enter_skipped_review(self) -> str:
        """Re-evaluate skipped items and enter SKIPPED_REVIEW if needed."""
        # Re-evaluate deferred items now that we have more info
        for item in self.state.skipped_items:
            if item.get("permanently_skipped"):
                continue
            slug = item.get("slug", "")
            # Already collected? Mark as permanently skipped.
            if item["type"] in ("document", "document_group") and slug in self.state.collected_documents:
                item["permanently_skipped"] = True
                item["skip_reason"] = "already_collected"
                continue
            if item["type"] == "attribute" and slug in self.state.collected_attributes:
                item["permanently_skipped"] = True
                item["skip_reason"] = "already_collected"
                continue
            # Re-check auto-skip
            if self._should_auto_skip(item):
                skip_reason, _ = self._auto_skip_details(item)
                item["permanently_skipped"] = True
                item["skip_reason"] = skip_reason

        reviewable = [i for i in self.state.skipped_items if not i.get("permanently_skipped")]
        if reviewable:
            self.state.phase = Phase.SKIPPED_REVIEW
            self.state.skipped_review_index = 0
            return await self._next_skipped_or_after_review()
        else:
            return await self._transition_to_next_stage("skipped_review")

    async def _next_skipped_or_after_review(self) -> str:
        """Move to next skipped item or transition after review."""
        while self.state.skipped_review_index < len(self.state.skipped_items):
            item = self.state.skipped_items[self.state.skipped_review_index]
            slug = item.get("slug", "")
            if not item.get("permanently_skipped"):
                already_collected = (
                    (item["type"] in ("document", "document_group") and slug in self.state.collected_documents) or
                    (item["type"] == "attribute" and slug in self.state.collected_attributes)
                )
                if already_collected or self._should_auto_skip(item):
                    item["permanently_skipped"] = True
                    self.state.skipped_review_index += 1
                    continue
                return await self._say(build_skipped_review_prompt(item))
            self.state.skipped_review_index += 1

        return await self._after_skipped_review()

    async def _after_skipped_review(self) -> str:
        """Called when skipped review is complete. Determine next stage."""
        return await self._transition_to_next_stage("skipped_review")

    async def _transition_to_closing(self) -> str:
        self.state.phase = Phase.CLOSING
        closing = await self._say(build_closing_prompt(self.state))
        self.state.phase = Phase.DONE
        return closing

    async def _generate_item_request(self, item: dict) -> str:
        """Generate the request message for an item."""
        if item["type"] == "document_group":
            return await self._say(build_ask_document_group_prompt(item, self.state))
        elif item["type"] == "document":
            return await self._say(build_ask_document_prompt(item, self.state))
        else:
            return await self._say(build_ask_attribute_prompt(item, self.state))


# ─── Factory Functions ────────────────────────────────────────────────────────

def create_collection_agent(
    collection_id: str,
    candidate_name: str,
    vacancy_title: str,
    company_name: str,
    start_date: str,
    days_remaining: int,
    summary: str,
    documents_to_collect: list[dict],
    attributes_to_collect: list[dict],
    agent_managed_tasks: list[dict] | None = None,
    final_step: dict | None = None,
    recruiter_name: str = "",
    recruiter_email: str = "",
    recruiter_phone: str = "",
) -> "DocumentCollectionAgent":
    """Create a new agent from a collection plan."""

    agent_managed_tasks = agent_managed_tasks or []

    # ── Hardcoded identity/work permit workflow ───────────────────────────
    # These are always handled by the agent, never by the planner.
    # The agent determines EU vs non-EU from the identity document and
    # auto-skips work permits for EU citizens.

    HARDCODED_DOC_SLUGS = {"id_card", "passport"} | WORK_PERMIT_SLUGS

    identity_group = {
        "type": "document_group",
        "slug": "identity",
        "name": "ID-kaart / Paspoort",
        "alternatives": [
            {
                "type": "document",
                "slug": "id_card",
                "name": "ID-kaart",
                "scan_mode": "front_back",
                "priority": "required",
                "reason": "Identiteitsbewijs EU/EER-burgers",
                "is_verifiable": True,
                "category": "identity",
            },
            {
                "type": "document",
                "slug": "passport",
                "name": "Paspoort",
                "scan_mode": "single",
                "priority": "required",
                "reason": "Identiteitsbewijs (vereist voor niet-EU/EER)",
                "is_verifiable": True,
                "category": "identity",
            },
        ],
    }

    work_permit_group = {
        "type": "document_group",
        "slug": "work_permit",
        "name": "Werkvergunning / Verblijfsdocument",
        "alternatives": [
            {"type": "document", "slug": "prato_5", "name": "Werkvergunning", "scan_mode": "single", "priority": "conditional", "reason": "Bewijs arbeidstoegang niet-EU/EER", "is_verifiable": True, "category": "certificate"},
            {"type": "document", "slug": "prato_101", "name": "Verblijfsdocument - vrijstelling", "scan_mode": "single", "priority": "conditional", "reason": "Onbeperkte arbeidsmarkttoegang niet-EU/EER", "is_verifiable": True, "category": "identity"},
            {"type": "document", "slug": "prato_102", "name": "Verblijfsdocument - bijkomstig", "scan_mode": "single", "priority": "conditional", "reason": "Beperkte arbeidsmarkttoegang niet-EU/EER", "is_verifiable": True, "category": "identity"},
            {"type": "document", "slug": "prato_9", "name": "Vrijstelling arbeidskaart", "scan_mode": "single", "priority": "conditional", "reason": "Vrijgesteld van arbeidsvergunning", "is_verifiable": True, "category": "certificate"},
            {"type": "document", "slug": "prato_20", "name": "Arbeidskaart", "scan_mode": "single", "priority": "conditional", "reason": "Oud systeem, nog geldig", "is_verifiable": True, "category": "certificate"},
        ],
    }

    document_queue = [identity_group, work_permit_group]

    # ── Planner-provided documents (VCA, diploma, CV, etc.) ───────────────

    def _make_doc_item(doc: dict) -> dict:
        return {
            "type": "document",
            "slug": doc["slug"],
            "name": doc["name"],
            "scan_mode": doc.get("scan_mode", "single"),
            "priority": doc.get("priority", "required"),
            "reason": doc.get("reason", ""),
            "is_verifiable": doc.get("is_verifiable", False),
            "verification_config": doc.get("verification_config"),
            "ai_hint": doc.get("ai_hint"),
            "category": doc.get("category"),
        }

    required_docs = []
    recommended_docs = []

    for doc in documents_to_collect:
        if doc["slug"] in HARDCODED_DOC_SLUGS:
            continue  # Handled by hardcoded identity/work permit workflow
        doc_item = _make_doc_item(doc)
        if doc.get("priority") == "recommended":
            recommended_docs.append(doc_item)
        else:
            required_docs.append(doc_item)

    document_queue.extend(required_docs)

    # ── Hardcoded address workflow ────────────────────────────────────────
    # Always collected: domicilie → same as domicilie? → verblijfs (if different)

    HARDCODED_ATTR_SLUGS = {"domicile_address", "domicilie_adres", "adres_gelijk_aan_domicilie", "verblijfs_adres"}

    hardcoded_address_attrs = [
        {
            "type": "attribute", "slug": "domicile_address", "name": "Domicilie adres",
            "reason": "Administratie",
            "ai_hint": "Als stad en/of postcode opgegeven zijn, mag je het land automatisch invullen.",
            "fields": [
                {"key": "street", "label": "Straat", "type": "text", "required": True},
                {"key": "number", "label": "Nummer", "type": "text", "required": True},
                {"key": "stad", "label": "Stad", "type": "text", "required": True},
                {"key": "postcode", "label": "Postcode", "type": "text", "required": True},
                {"key": "country", "label": "Land", "type": "text", "required": False},
            ],
        },
        {
            "type": "attribute", "slug": "adres_gelijk_aan_domicilie",
            "name": "Verblijfsadres gelijk aan domicilie", "reason": "Administratie",
            "ai_hint": 'Vraag direct na het domicilieadres: "Is je verblijfsadres hetzelfde als je domicilieadres?"',
        },
        {
            "type": "attribute", "slug": "verblijfs_adres", "name": "Verblijfsadres",
            "reason": "Administratie",
            "ai_hint": "Als stad en postcode gekend zijn, vul dan automatisch het land in.",
            "fields": [
                {"key": "street", "label": "Straat", "type": "text", "required": True},
                {"key": "number", "label": "Nummer", "type": "text", "required": True},
                {"key": "stad", "label": "Stad", "type": "text", "required": True},
                {"key": "postcode", "label": "Postcode", "type": "text", "required": True},
                {"key": "country", "label": "Land", "type": "text", "required": False},
            ],
        },
    ]

    # ── Planner-provided attributes ───────────────────────────────────────

    def _make_attr_item(attr: dict) -> dict:
        item = {
            "type": "attribute",
            "slug": attr["slug"],
            "name": attr["name"],
            "reason": attr.get("reason", ""),
        }
        if attr.get("fields"):
            item["fields"] = attr["fields"]
        if attr.get("ai_hint"):
            item["ai_hint"] = attr["ai_hint"]
        return item

    required_attrs = []
    recommended_attrs = []

    for attr in attributes_to_collect:
        if attr.get("collection_method") == "document":
            continue  # Auto-extracted from doc verification
        if attr["slug"] in HARDCODED_ATTR_SLUGS:
            continue  # Handled by hardcoded address workflow

        item = _make_attr_item(attr)
        if attr.get("priority") == "recommended":
            recommended_attrs.append(item)
        else:
            required_attrs.append(item)

    # Address first, then planner-provided attrs
    candidate_info_queue = hardcoded_address_attrs + required_attrs

    # ── Build task queue ─────────────────────────────────────────────────

    task_queue = []
    for task in agent_managed_tasks:
        task_queue.append({
            "slug": task.get("slug", ""),
            "name": task.get("slug", "").replace("_", " ").title(),
            "action": task.get("action", ""),
            "task_type": "interactive",
        })

    # Append contract signing as final task
    if final_step and final_step.get("action") == "contract_signing":
        task_queue.append({
            "slug": "contract_signing",
            "name": "Contract ondertekening",
            "action": "contract_signing",
            "task_type": "interactive",
        })

    # ── Build additional_info queue ──────────────────────────────────────

    additional_info_queue = []
    additional_info_queue.extend(recommended_docs)
    additional_info_queue.extend(recommended_attrs)

    # ── Legacy item_queue for backward compat ────────────────────────────

    item_queue = document_queue + candidate_info_queue + additional_info_queue

    state = CollectionState(
        phase=Phase.INTRO,
        collection_id=collection_id,
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        company_name=company_name,
        start_date=start_date,
        days_remaining=days_remaining,
        summary=summary,
        recruiter_name=recruiter_name,
        recruiter_email=recruiter_email,
        recruiter_phone=recruiter_phone,
        document_queue=document_queue,
        candidate_info_queue=candidate_info_queue,
        task_queue=task_queue,
        additional_info_queue=additional_info_queue,
        item_queue=item_queue,
    )

    logger.info(
        f"Created collection agent: {candidate_name} × {vacancy_title}, "
        f"docs={len(document_queue)}, info={len(candidate_info_queue)}, "
        f"tasks={len(task_queue)}, additional={len(additional_info_queue)}"
    )

    return DocumentCollectionAgent(state=state)


def restore_collection_agent(state_json: str) -> DocumentCollectionAgent:
    """Restore agent from saved state JSON."""
    state = CollectionState.from_json(state_json)

    # Backward compat: if old state has item_queue but no stage queues, migrate
    if state.item_queue and not state.document_queue and not state.candidate_info_queue:
        logger.info("Migrating legacy item_queue to stage-specific queues")
        for item in state.item_queue:
            if item["type"] in ("document", "document_group"):
                state.document_queue.append(item)
            else:
                state.candidate_info_queue.append(item)
        # Adjust indices based on current_item_index
        doc_count = len(state.document_queue)
        if state.current_item_index < doc_count:
            state.document_index = state.current_item_index
            state.candidate_info_index = 0
        else:
            state.document_index = doc_count
            state.candidate_info_index = state.current_item_index - doc_count

    return DocumentCollectionAgent(state=state)


def is_collection_complete(agent: DocumentCollectionAgent) -> bool:
    return agent.state.phase == Phase.DONE
