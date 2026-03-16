"""
Document Collection Agent — step-based conversation loop.

Follows the conversation_flow from the planner: each step has a type
and the agent dispatches to the appropriate handler. Simple loop:
"what's the next step?" → execute → advance.

Usage:
    agent = create_collection_agent(plan, type_cache)
    intro = await agent.get_initial_message()
    response = await agent.process_message("hier is mijn ID", has_image=True)
    agent = restore_collection_agent(state_json, type_cache)
"""

import json
import logging

from agents.document_collection.collection.handlers import STEP_HANDLERS
from agents.document_collection.collection.prompts import SYSTEM_INSTRUCTION
from agents.document_collection.collection.state import CollectionState

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


# ─── LLM Helpers ────────────────────────────────────────────────────────────

async def _generate(prompt: str) -> str:
    """Generate conversational text via LLM. No history — prompt is self-contained."""
    from src.utils.llm import generate

    return await generate(
        prompt=prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        model=DEFAULT_MODEL,
        temperature=0.7,
        max_output_tokens=1024,
    )


async def _extract_attribute_llm(
    slug: str, name: str, user_message: str,
    fields: list[dict] | None = None,
    partial: dict | None = None,
    ai_hint: str | None = None,
) -> dict:
    """Use LLM to extract a structured value from freetext answer."""
    from src.utils.llm import generate

    if fields:
        fields_spec = "\n".join(f'  "{f["key"]}": "{f["label"]} ({f.get("type", "text")})"' for f in fields)

        partial_context = ""
        missing_keys = []
        if partial and isinstance(partial, dict):
            known = ", ".join(f'{k}="{v}"' for k, v in partial.items() if v)
            missing_keys = [f["key"] for f in fields if not partial.get(f["key"])]
            missing_labels = [f["label"] for f in fields if f["key"] in missing_keys]
            if known and missing_keys:
                partial_context = f"\n\nEerder al verzameld: {known}\nOntbrekend: {', '.join(missing_labels)}\nHet antwoord van de kandidaat is specifiek voor de ontbrekende velden."

        hint_line = f"\n\nExtra instructie: {ai_hint}" if ai_hint else ""

        if missing_keys and len(missing_keys) == 1:
            missing_field = next(f for f in fields if f["key"] == missing_keys[0])
            known_items = ", ".join(f'{k}="{v}"' for k, v in partial.items() if v)
            prompt = f"""Extraheer de waarde voor het veld "{missing_field['label']}" ({missing_field['key']}) uit het antwoord.
Attribuut: {name} ({slug})
Eerder verzameld: {known_items}
Antwoord van kandidaat: "{user_message}"{hint_line}

Het antwoord is het ontbrekende veld "{missing_field['label']}" (type: {missing_field.get('type', 'text')}).
Neem het antwoord over als waarde voor "{missing_field['key']}". Combineer met eerder verzamelde data.

Antwoord ALLEEN met valid JSON (geen markdown):
{{"value": {{{", ".join(f'"{k}": "{v}"' for k, v in partial.items() if v)}, "{missing_field['key']}": "de waarde"}}, "valid": true, "missing_fields": []}}"""
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

Als het antwoord niet duidelijk is:
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
            lines = [line for line in text.split("\n") if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"Failed to parse attribute extraction: {response}")
        if fields:
            return {"value": None, "valid": False, "missing_fields": [f["key"] for f in fields]}
        return {"value": user_message.strip(), "valid": True}


# ─── Agent ───────────────────────────────────────────────────────────────────

class DocumentCollectionAgent:
    """
    Step-based document & data collection agent.

    Follows the conversation_flow from the planner. Each step has a type
    that maps to a handler. The agent loop: get step → dispatch → advance.
    """

    def __init__(self, state: CollectionState, type_cache=None):
        self.state = state
        self.type_cache = type_cache
        self.pending_image_data: bytes | None = None  # Set by router before process_message()

    # ── LLM interface (used by handlers) ──────────────────────────────

    async def _say(self, prompt: str) -> str:
        """Generate a conversational response via LLM."""
        response = await _generate(prompt)
        self.state.last_agent_message = response
        return response

    async def _extract_attribute(
        self, slug: str, name: str, message: str,
        fields: list[dict] | None = None,
        partial: dict | None = None,
        ai_hint: str | None = None,
    ) -> dict:
        """Extract structured attribute from user message."""
        return await _extract_attribute_llm(slug, name, message, fields, partial, ai_hint)

    def _merge_partial(self, slug: str, new_value: dict) -> dict:
        """Merge new extraction with existing partial values."""
        existing = self.state.partial_attributes.get(slug)
        if existing and isinstance(existing, dict):
            return {**existing, **{k: v for k, v in new_value.items() if v}}
        return new_value

    # ── Step navigation ───────────────────────────────────────────────

    def _current_step(self) -> dict | None:
        """Get the current step from conversation_flow."""
        idx = self.state.current_step_index
        flow = self.state.conversation_flow
        if idx < len(flow):
            return flow[idx]
        return None

    async def _jump_to_step(self, tag: str) -> str:
        """Testing shortcut: jump to a step by tag like --sign-contract-- or --medical--."""
        # Map tags to step types
        tag_map = {
            "--sign-contract--": "contract_signing",
            "--contract--": "contract_signing",
            "--medical--": "medical_screening",
            "--identity--": "identity_verification",
            "--address--": "address_collection",
            "--documents--": "collect_documents",
            "--attributes--": "collect_attributes",
        }
        target_type = tag_map.get(tag)
        if not target_type:
            return f"Onbekende test-tag: {tag}\nBeschikbaar: {', '.join(tag_map.keys())}"

        # Find the step in conversation_flow
        for i, step in enumerate(self.state.conversation_flow):
            if step.get("type") == target_type:
                # Mark all previous steps as completed
                for j in range(i):
                    prev_type = self.state.conversation_flow[j].get("type", "")
                    if prev_type not in self.state.completed_steps:
                        self.state.completed_steps.append(prev_type)
                self.state.current_step_index = i
                self.state.step_item_index = 0
                logger.info(f"[TEST] Jumped to step {i}: {target_type}")
                return await self._enter_step(step)

        return f"Stap '{target_type}' niet gevonden in conversation_flow."

    async def _advance_step(self) -> str:
        """Mark current step complete, find and enter next eligible step."""
        step = self._current_step()
        if step:
            self.state.completed_steps.append(step["type"])

        self.state.current_step_index += 1
        self.state.step_item_index = 0

        # Find next step with met requirements
        while self.state.current_step_index < len(self.state.conversation_flow):
            next_step = self.state.conversation_flow[self.state.current_step_index]
            requires = next_step.get("requires", [])

            if all(r in self.state.completed_steps for r in requires):
                # Requirements met — enter this step
                return await self._enter_step(next_step)
            else:
                # Requirements not met — skip for now
                logger.info(
                    f"Skipping step {next_step['type']}: requires {requires}, "
                    f"completed: {self.state.completed_steps}"
                )
                self.state.current_step_index += 1

        # All steps done
        return await self._handle_done()

    async def _enter_step(self, step: dict) -> str:
        """Generate the opening message for a new step."""
        step_type = step.get("type", "")
        handler_pair = STEP_HANDLERS.get(step_type)

        if handler_pair:
            enter_fn, _ = handler_pair
            return await enter_fn(self, step)

        logger.warning(f"No handler for step type: {step_type}")
        return await self._advance_step()

    async def _handle_done(self) -> str:
        """Called when all steps are complete. Generates a warm closing with summary."""
        state = self.state

        collected_docs = [slug for slug, v in state.collected_documents.items() if v.get("status") == "verified"]
        collected_attrs = list(state.collected_attributes.keys())
        skipped = [i.get("name", i.get("slug", "")) for i in state.skipped_items]

        parts = []
        if collected_docs:
            parts.append(f"Documenten ontvangen: {', '.join(collected_docs)}")
        if collected_attrs:
            parts.append(f"Gegevens ontvangen: {', '.join(collected_attrs)}")

        skipped_note = ""
        if skipped:
            skipped_note = f"\nEr zijn nog items die niet verzameld konden worden: {', '.join(skipped)}. Een medewerker zal hiervoor contact opnemen."

        recruiter_info = ""
        if state.recruiter_name:
            recruiter_info = f"\nNoem **{state.recruiter_name}** als contactpersoon voor verdere vragen"
            if state.recruiter_email:
                recruiter_info += f" ({state.recruiter_email})"
            elif state.recruiter_phone:
                recruiter_info += f" ({state.recruiter_phone})"
            recruiter_info += "."

        closing_msg = await self._say(
            f"""Sluit het gesprek af. Bedank {state.candidate_name} hartelijk.
Samenvatting: {'; '.join(parts) if parts else 'Alle items verwerkt.'}{skipped_note}{recruiter_info}
Max 3 zinnen. Warme afsluiting."""
        )

        state.current_step_index = len(state.conversation_flow)
        return closing_msg

    # ── Public API ────────────────────────────────────────────────────

    async def get_initial_message(self) -> list[str]:
        """Generate intro message(s) and enter the first step.

        Returns a list of messages — each becomes a separate WhatsApp bubble.
        """
        step = self._current_step()
        if not step:
            return ["Er is geen verzamelplan beschikbaar."]

        step_type = step.get("type", "")
        handler_pair = STEP_HANDLERS.get(step_type)

        if handler_pair:
            enter_fn, _ = handler_pair
            result = await enter_fn(self, step)
            # enter_fn may return a list (e.g. consent: 2 bubbles) or a single string
            return result if isinstance(result, list) else [result]

        # Unknown step — advance
        advance_msg = await self._advance_step()
        return [advance_msg]

    async def _handle_question(self, question: str) -> str | None:
        """Detect and answer candidate questions. Returns answer or None if not a question."""
        from src.utils.llm import generate as llm_generate

        detection = await llm_generate(
            prompt=f"""De kandidaat stuurt het volgende bericht tijdens een onboarding-gesprek:
"{question}"

Is dit een VRAAG die de kandidaat stelt (over het proces, de job, het bedrijf, documenten, etc.)?
Antwoord ALLEEN "JA" of "NEE".""",
            temperature=0,
            max_output_tokens=5,
        )

        if "JA" not in detection.strip().upper():
            return None

        step = self._current_step()
        step_context = step.get("description", "") if step else ""

        answer = await self._say(
            f"""De kandidaat stelt een vraag: "{question}"
Context: we zijn bezig met een onboarding-gesprek voor de functie {self.state.vacancy_title} bij {self.state.company_name}.
Huidige stap: {step_context}

Beantwoord de vraag kort en vriendelijk. Als je het antwoord niet weet, zeg dat de recruiter hierover meer info kan geven.
Stuur daarna het gesprek terug naar de huidige stap.
GEEN begroeting. Max 2-3 zinnen."""
        )
        return answer

    async def process_message(self, user_message: str, has_image: bool = False) -> str:
        """Main entry point — route to the appropriate step handler."""
        self.state.message_count += 1

        # Testing shortcut: jump directly to a step by type
        if user_message.strip().startswith("--") and user_message.strip().endswith("--"):
            return await self._jump_to_step(user_message.strip())

        step = self._current_step()

        if not step:
            return await self._handle_done()

        # Handle candidate questions before routing to step handler
        if not has_image and len(user_message.strip()) > 5:
            question_answer = await self._handle_question(user_message)
            if question_answer:
                return question_answer

        step_type = step.get("type", "")
        handler_pair = STEP_HANDLERS.get(step_type)

        if handler_pair:
            _, handle_fn = handler_pair
            return await handle_fn(self, user_message, has_image, step)

        logger.warning(f"No handler for step type: {step_type}, advancing")
        return await self._advance_step()

    # ── Compact context (for debugging / logging) ─────────────────────

    def get_context_summary(self) -> str:
        """Build a compact summary of current state for debugging."""
        step = self._current_step()
        ctx = self.state.context
        lines = [
            f"Kandidaat: {ctx.get('candidate', '?')}",
            f"Vacature: {ctx.get('vacancy', '?')} @ {ctx.get('company', '?')}",
            f"Stap {self.state.current_step_index + 1}/{len(self.state.conversation_flow)}: {step['type'] if step else 'done'}",
        ]
        if self.state.collected_attributes:
            lines.append(f"Attributen: {', '.join(self.state.collected_attributes.keys())}")
        if self.state.collected_documents:
            lines.append(f"Documenten: {', '.join(self.state.collected_documents.keys())}")
        return "\n".join(lines)


# ─── Factory Functions ───────────────────────────────────────────────────────

def create_collection_agent(
    plan: dict,
    type_cache=None,
    collection_id: str = "",
    recruiter_name: str = "",
    recruiter_email: str = "",
    recruiter_phone: str = "",
) -> DocumentCollectionAgent:
    """Create a new agent from a conversation_flow plan.

    Args:
        plan: The full plan dict from the planner, containing:
            - context: {candidate, vacancy, company, start_date, days_remaining, ...}
            - conversation_flow: [{step, type, description, items, requires}, ...]
            - attributes_from_documents: [{slug, reason}, ...]
            - summary: str
        type_cache: TypeCache or MockTypeCache for loading type definitions
        collection_id: DB collection ID
        recruiter_name/email/phone: Recruiter contact info
    """
    context = plan.get("context", {})
    # Inject goal into context so handlers can access it
    if "goal" not in context and plan.get("goal"):
        context["goal"] = plan["goal"]

    state = CollectionState(
        collection_id=collection_id,
        conversation_flow=plan.get("conversation_flow", []),
        context=context,
        attributes_from_documents=plan.get("attributes_from_documents", []),
        summary=plan.get("summary", ""),
        recruiter_name=recruiter_name,
        recruiter_email=recruiter_email,
        recruiter_phone=recruiter_phone,
    )

    logger.info(
        f"Created collection agent: {state.candidate_name} × {state.vacancy_title}, "
        f"steps={len(state.conversation_flow)}"
    )

    return DocumentCollectionAgent(state=state, type_cache=type_cache)


def restore_collection_agent(state_json: str, type_cache=None) -> DocumentCollectionAgent:
    """Restore agent from saved state JSON."""
    state = CollectionState.from_json(state_json)
    return DocumentCollectionAgent(state=state, type_cache=type_cache)


def is_collection_complete(agent: DocumentCollectionAgent) -> bool:
    """Check if the agent has completed all steps."""
    return agent._current_step() is None
