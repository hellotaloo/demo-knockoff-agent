"""
LiveKit Agent Models - Webhook payload models for pre-screening v2 voice agent.

These models match the CandidateData.to_dict() output from pre_screening_v2/models.py.
"""
from typing import Optional
from pydantic import BaseModel


class LiveKitKnockoutAnswerPayload(BaseModel):
    """A single knockout question answer from the voice agent."""
    question_id: str
    internal_id: str = ""
    question_text: str
    result: str  # "pass", "fail", "unclear", "irrelevant", "recruiter_requested"
    raw_answer: str
    candidate_note: str = ""


class LiveKitOpenAnswerPayload(BaseModel):
    """A single open question answer from the voice agent."""
    question_id: str
    internal_id: str = ""
    question_text: str
    answer_summary: str
    candidate_note: str = ""


class LiveKitTranscriptMessage(BaseModel):
    """A single transcript message from the voice agent session."""
    role: str  # "user" or "assistant"
    message: str


class LiveKitCallResultPayload(BaseModel):
    """
    Full call result payload from the pre-screening v2 LiveKit agent.

    Posted to POST /webhook/livekit/call-result by the agent's _on_session_complete callback.

    Status values:
    - completed: Full flow done, timeslot chosen or preference recorded
    - voicemail: Hit voicemail, left a message
    - not_interested: Candidate declined or failed knockout + not interested in alternatives
    - knockout_failed: Failed a knockout question but interested in other vacancies
    - escalated: Candidate requested human recruiter
    - unclear: Couldn't get a clear answer after retries
    - irrelevant: Too many off-topic answers (3 max)
    - incomplete: Session ended unexpectedly (silence timeout, disconnect)
    """
    call_id: str
    status: str
    consent_given: Optional[bool] = None
    voicemail_detected: bool = False
    passed_knockout: bool = False
    interested_in_alternatives: bool = False
    knockout_answers: list[LiveKitKnockoutAnswerPayload] = []
    open_answers: list[LiveKitOpenAnswerPayload] = []
    chosen_timeslot: Optional[str] = None
    scheduling_preference: Optional[str] = None
    calendar_event_id: Optional[str] = None
    scheduled_date: Optional[str] = None   # YYYY-MM-DD
    scheduled_time: Optional[str] = None   # e.g. "10 uur"
    transcript: list[LiveKitTranscriptMessage] = []
