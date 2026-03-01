from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from enum import Enum

if TYPE_CHECKING:
    from livekit import rtc
    from livekit.agents import BackgroundAudioPlayer

# After this many irrelevant answers (across all stages), the conversation ends.
MAX_IRRELEVANT = 3


def check_irrelevant(userdata, suffix: str = "om de vraag te beantwoorden") -> str | None:
    """Increment irrelevant counter. Returns warning message, or None if limit hit."""
    userdata.irrelevant_count += 1
    if userdata.irrelevant_count >= MAX_IRRELEVANT:
        return None
    remaining = MAX_IRRELEVANT - userdata.irrelevant_count
    return (
        f"[SYSTEEM] Irrelevant antwoord {userdata.irrelevant_count}/{MAX_IRRELEVANT}. "
        f"Nog {remaining} kans(en). Vraag de kandidaat beleefd maar duidelijk {suffix}."
    )


# --- Input config (provided by the system) ---

@dataclass
class KnockoutQuestion:
    id: str
    text: str
    internal_id: str = ""
    context: str = ""
    data_key: str = ""


@dataclass
class OpenQuestion:
    id: str
    text: str
    internal_id: str = ""
    description: str = ""


@dataclass
class CandidateRecord:
    """Pre-known candidate data from CRM. Used to skip knockout questions and scheduling."""
    known_answers: dict[str, str] = field(default_factory=dict)
    existing_booking_date: Optional[str] = None


@dataclass
class SessionInput:
    """All input configuration for a prescreening session, provided by the system."""
    call_id: str = ""

    # Candidate
    candidate_name: str = ""
    candidate_known: bool = False
    candidate_record: Optional[CandidateRecord] = None

    # Vacancy
    job_title: str = ""
    office_location: str = ""
    office_address: str = ""

    # Questions
    knockout_questions: list[KnockoutQuestion] = field(default_factory=list)
    open_questions: list[OpenQuestion] = field(default_factory=list)

    # Settings
    start_agent: str = ""
    allow_escalation: bool = True
    require_consent: bool = True
    is_playground: bool = False

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "candidate_name": self.candidate_name,
            "candidate_known": self.candidate_known,
            "candidate_record": {
                "known_answers": self.candidate_record.known_answers,
                "existing_booking_date": self.candidate_record.existing_booking_date,
            } if self.candidate_record else None,
            "job_title": self.job_title,
            "office_location": self.office_location,
            "office_address": self.office_address,
            "knockout_questions": [
                {"id": q.id, "text": q.text, "internal_id": q.internal_id, "context": q.context, "data_key": q.data_key}
                for q in self.knockout_questions
            ],
            "open_questions": [
                {"id": q.id, "text": q.text, "internal_id": q.internal_id, "description": q.description}
                for q in self.open_questions
            ],
            "allow_escalation": self.allow_escalation,
            "require_consent": self.require_consent,
            "is_playground": self.is_playground,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionInput:
        cr = data.get("candidate_record")
        return cls(
            call_id=data.get("call_id", ""),
            candidate_name=data.get("candidate_name", ""),
            candidate_known=data.get("candidate_known", False),
            candidate_record=CandidateRecord(
                known_answers=cr.get("known_answers", {}),
                existing_booking_date=cr.get("existing_booking_date"),
            ) if cr else None,
            job_title=data.get("job_title", ""),
            office_location=data.get("office_location", ""),
            office_address=data.get("office_address", ""),
            knockout_questions=[
                KnockoutQuestion(
                    id=q["id"], text=q["text"],
                    internal_id=q.get("internal_id", ""),
                    context=q.get("context", ""),
                    data_key=q.get("data_key", ""),
                ) for q in data.get("knockout_questions", [])
            ],
            open_questions=[
                OpenQuestion(
                    id=q["id"], text=q["text"],
                    internal_id=q.get("internal_id", ""),
                    description=q.get("description", ""),
                ) for q in data.get("open_questions", [])
            ],
            start_agent=data.get("start_agent", ""),
            allow_escalation=data.get("allow_escalation", True),
            require_consent=data.get("require_consent", True),
            is_playground=data.get("is_playground", False),
        )


# --- Runtime state & results ---

class QuestionResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCLEAR = "unclear"
    IRRELEVANT = "irrelevant"
    RECRUITER_REQUESTED = "recruiter_requested"


@dataclass
class KnockoutAnswer:
    question_id: str
    question_text: str
    result: QuestionResult
    raw_answer: str
    internal_id: str = ""
    candidate_note: str = ""


@dataclass
class OpenAnswer:
    question_id: str
    question_text: str
    answer_summary: str
    internal_id: str = ""
    candidate_note: str = ""


@dataclass
class CandidateData:
    input: SessionInput = field(default_factory=SessionInput)

    # Screening results
    knockout_answers: list[KnockoutAnswer] = field(default_factory=list)
    open_answers: list[OpenAnswer] = field(default_factory=list)

    # Consent
    consent_given: Optional[bool] = None

    # Voicemail
    voicemail_detected: bool = False

    # Screening outcome
    passed_knockout: bool = False
    interested_in_alternatives: bool = False

    # Scheduling
    chosen_timeslot: Optional[str] = None
    scheduling_preference: Optional[str] = None
    calendar_event_id: Optional[str] = None
    scheduled_date: Optional[str] = None   # YYYY-MM-DD
    scheduled_time: Optional[str] = None   # e.g. "10 uur"

    # Silence tracking
    silence_count: int = 0
    suppress_silence: bool = False

    # Irrelevant answer tracking (cross-stage counter, resets on valid answers)
    irrelevant_count: int = 0

    # Recruiter escalation flag (set by tasks inside TaskGroup to break early)
    recruiter_requested: bool = False

    # Language (ElevenLabs language code, e.g. "nl", "en", "fr")
    language: str = "nl"

    # Audio / room
    room: Optional[rtc.Room] = None
    thinking_audio: Optional[BackgroundAudioPlayer] = None

    def _resolve_status(self) -> str:
        if self.voicemail_detected:
            return "voicemail"
        if self.consent_given is False:
            return "not_interested"
        # Check if irrelevant limit was hit
        if self.irrelevant_count >= MAX_IRRELEVANT:
            return "irrelevant"
        # Check knockout results
        ko_results = [a.result for a in self.knockout_answers]
        if QuestionResult.UNCLEAR in ko_results:
            return "unclear"
        if QuestionResult.RECRUITER_REQUESTED in ko_results or self.recruiter_requested:
            return "escalated"
        if QuestionResult.FAIL in ko_results and not self.interested_in_alternatives:
            return "not_interested"
        if QuestionResult.FAIL in ko_results and self.interested_in_alternatives:
            return "knockout_failed"
        # Happy path
        if self.chosen_timeslot or self.scheduling_preference:
            return "completed"
        return "incomplete"

    def to_dict(self) -> dict:
        # Build internal_id lookup from input questions
        ko_ids = {q.id: q.internal_id for q in self.input.knockout_questions}
        oq_ids = {q.id: q.internal_id for q in self.input.open_questions}

        return {
            "call_id": self.input.call_id,
            "status": self._resolve_status(),
            "consent_given": self.consent_given,
            "voicemail_detected": self.voicemail_detected,
            "passed_knockout": self.passed_knockout,
            "interested_in_alternatives": self.interested_in_alternatives,
            "knockout_answers": [
                {
                    "question_id": a.question_id,
                    "internal_id": ko_ids.get(a.question_id, ""),
                    "question_text": a.question_text,
                    "result": a.result.value,
                    "raw_answer": a.raw_answer,
                    "candidate_note": a.candidate_note,
                } for a in self.knockout_answers
            ],
            "open_answers": [
                {
                    "question_id": a.question_id,
                    "internal_id": oq_ids.get(a.question_id, ""),
                    "question_text": a.question_text,
                    "answer_summary": a.answer_summary,
                    "candidate_note": a.candidate_note,
                } for a in self.open_answers
            ],
            "chosen_timeslot": self.chosen_timeslot,
            "scheduling_preference": self.scheduling_preference,
            "calendar_event_id": self.calendar_event_id,
            "scheduled_date": self.scheduled_date,
            "scheduled_time": self.scheduled_time,
        }
