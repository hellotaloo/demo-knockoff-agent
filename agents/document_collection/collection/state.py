"""
CollectionState — conversation state for the document collection agent.

Clean dataclass with JSON serialization. Tracks progress through
the conversation_flow steps from the planner.
"""

import json
from dataclasses import dataclass, field


@dataclass
class CollectionState:
    """All conversation state — serializable to/from JSON for DB persistence."""

    # ── Context from plan ────────────────────────────────────────────────
    collection_id: str = ""
    conversation_flow: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    attributes_from_documents: list[dict] = field(default_factory=list)
    summary: str = ""

    # ── Recruiter info (loaded separately) ───────────────────────────────
    recruiter_name: str = ""
    recruiter_email: str = ""
    recruiter_phone: str = ""

    # ── Progress ─────────────────────────────────────────────────────────
    current_step_index: int = 0
    step_item_index: int = 0
    completed_steps: list[str] = field(default_factory=list)

    # ── Consent ──────────────────────────────────────────────────────────
    consent_given: bool = False
    consent_refusal_count: int = 0

    # ── Results ──────────────────────────────────────────────────────────
    collected_documents: dict[str, dict] = field(default_factory=dict)
    collected_attributes: dict[str, dict] = field(default_factory=dict)
    skipped_items: list[dict] = field(default_factory=list)

    # ── Identity ─────────────────────────────────────────────────────────
    eu_citizen: bool | None = None       # None=unknown, True=EU, False=non-EU
    work_eligibility: bool | None = None

    # ── In-progress tracking ─────────────────────────────────────────────
    partial_attributes: dict[str, dict] = field(default_factory=dict)
    retry_counts: dict[str, int] = field(default_factory=dict)
    waiting_for_back: str | None = None  # slug of doc waiting for back side

    # ── Sub-state: identity handler ──────────────────────────────────────
    # ask_id → waiting_id → ask_work_permit → waiting_work_permit → done
    identity_phase: str = "ask_id"

    # ── Sub-state: address handler ───────────────────────────────────────
    # ask_domicile → ask_same → ask_verblijf → done
    address_phase: str = "ask_domicile"

    # ── Conversation context (compact) ───────────────────────────────────
    last_agent_message: str = ""
    message_count: int = 0

    # ── Review flags (silent, for recruiter) ─────────────────────────────
    review_flags: list[dict] = field(default_factory=list)

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "collection_id": self.collection_id,
            "conversation_flow": self.conversation_flow,
            "context": self.context,
            "attributes_from_documents": self.attributes_from_documents,
            "summary": self.summary,
            "recruiter_name": self.recruiter_name,
            "recruiter_email": self.recruiter_email,
            "recruiter_phone": self.recruiter_phone,
            "current_step_index": self.current_step_index,
            "step_item_index": self.step_item_index,
            "completed_steps": self.completed_steps,
            "consent_given": self.consent_given,
            "consent_refusal_count": self.consent_refusal_count,
            "collected_documents": self.collected_documents,
            "collected_attributes": self.collected_attributes,
            "skipped_items": self.skipped_items,
            "eu_citizen": self.eu_citizen,
            "work_eligibility": self.work_eligibility,
            "partial_attributes": self.partial_attributes,
            "retry_counts": self.retry_counts,
            "waiting_for_back": self.waiting_for_back,
            "identity_phase": self.identity_phase,
            "address_phase": self.address_phase,
            "last_agent_message": self.last_agent_message,
            "message_count": self.message_count,
            "review_flags": self.review_flags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CollectionState":
        return cls(
            collection_id=d.get("collection_id", ""),
            conversation_flow=d.get("conversation_flow", []),
            context=d.get("context", {}),
            attributes_from_documents=d.get("attributes_from_documents", []),
            summary=d.get("summary", ""),
            recruiter_name=d.get("recruiter_name", ""),
            recruiter_email=d.get("recruiter_email", ""),
            recruiter_phone=d.get("recruiter_phone", ""),
            current_step_index=d.get("current_step_index", 0),
            step_item_index=d.get("step_item_index", 0),
            completed_steps=d.get("completed_steps", []),
            consent_given=d.get("consent_given", False),
            consent_refusal_count=d.get("consent_refusal_count", 0),
            collected_documents=d.get("collected_documents", {}),
            collected_attributes=d.get("collected_attributes", {}),
            skipped_items=d.get("skipped_items", []),
            eu_citizen=d.get("eu_citizen"),
            work_eligibility=d.get("work_eligibility"),
            partial_attributes=d.get("partial_attributes", {}),
            retry_counts=d.get("retry_counts", {}),
            waiting_for_back=d.get("waiting_for_back"),
            identity_phase=d.get("identity_phase", "ask_id"),
            address_phase=d.get("address_phase", "ask_domicile"),
            last_agent_message=d.get("last_agent_message", ""),
            message_count=d.get("message_count", 0),
            review_flags=d.get("review_flags", []),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "CollectionState":
        return cls.from_dict(json.loads(s))

    # ── Convenience ──────────────────────────────────────────────────────

    @property
    def candidate_name(self) -> str:
        return self.context.get("candidate", "")

    @property
    def vacancy_title(self) -> str:
        return self.context.get("vacancy", "")

    @property
    def company_name(self) -> str:
        return self.context.get("company", "")

    @property
    def start_date(self) -> str:
        return self.context.get("start_date", "")

    @property
    def days_remaining(self) -> int:
        return self.context.get("days_remaining", 0)
